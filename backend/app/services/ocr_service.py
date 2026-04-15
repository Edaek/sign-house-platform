import cv2
import numpy as np
import pytesseract
from PIL import Image


class OCRService:
    """Service for OCR text extraction."""
    
    def __init__(self, tesseract_cmd=None):
        """Initialize OCR service.
        
        Args:
            tesseract_cmd: Path to tesseract executable (optional)
        """
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        
        # Default OCR configuration
        # PSM 7 = single line of text (better for labels)
        # PSM 6 = uniform block of text
        self.config = '--oem 3 --psm 7'  # LSTM OCR Engine, single line
    
    def preprocess_for_ocr(self, image, label_mode=False):
        """Preprocess image for better OCR results.
        
        Args:
            image: Input image (numpy array)
            label_mode: If True, use specialized preprocessing for label boxes
            
        Returns:
            Preprocessed image
        """
        if label_mode:
            return self._preprocess_label(image)
        
        # Convert to grayscale if needed
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()
        
        # Apply thresholding to get black text on white background
        # Use adaptive thresholding for varying lighting conditions
        thresh = cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            11, 2
        )
        
        # Denoise
        denoised = cv2.fastNlMeansDenoising(thresh)
        
        # Optional: Scale up small images for better OCR
        height, width = denoised.shape[:2]
        if height < 50 or width < 50:
            scale = max(50 / height, 50 / width, 2)
            denoised = cv2.resize(denoised, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        
        return denoised
    
    def _preprocess_label(self, image):
        """Specialized preprocessing for label boxes with red borders.
        
        Args:
            image: Input image (numpy array)
            
        Returns:
            Preprocessed image optimized for label OCR
        """
        # Make a copy
        img = image.copy()
        
        # Get dimensions
        h, w = img.shape[:2]
        
        # Remove red borders by cropping inward (borders are ~2-4px thick)
        margin = max(3, min(w, h) // 15)  # Crop 3px or ~7% of smallest dimension
        if h > margin * 2 and w > margin * 2:
            img = img[margin:h-margin, margin:w-margin]
            h, w = img.shape[:2]
        
        # Convert to HSV for better color handling
        if len(img.shape) == 3:
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            
            # Mask out red text/lines (convert to black)
            lower_red1 = np.array([0, 40, 40])
            upper_red1 = np.array([10, 255, 255])
            lower_red2 = np.array([170, 40, 40])
            upper_red2 = np.array([180, 255, 255])
            
            red_mask1 = cv2.inRange(hsv, lower_red1, upper_red1)
            red_mask2 = cv2.inRange(hsv, lower_red2, upper_red2)
            red_mask = cv2.bitwise_or(red_mask1, red_mask2)
            
            # Convert to grayscale
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            
            # Make red areas black (so they'll be seen as text)
            gray[red_mask > 0] = 0
        else:
            gray = img.copy()
        
        # Scale up significantly for better OCR (labels are small ~30px height)
        scale_factor = max(4, 100 / h)  # Scale to at least 100px height
        scaled = cv2.resize(gray, None, fx=scale_factor, fy=scale_factor, 
                           interpolation=cv2.INTER_CUBIC)
        
        # Apply slight Gaussian blur to reduce noise
        blurred = cv2.GaussianBlur(scaled, (3, 3), 0)
        
        # Use Otsu's thresholding for clean binary image
        _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        # Morphological operations to clean up text
        kernel = np.ones((2, 2), np.uint8)
        # Close small gaps in characters
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)
        
        return binary
    
    def extract_text(self, image, preprocess=True, label_mode=False):
        """Extract text from an image.
        
        Args:
            image: Input image (numpy array or PIL Image)
            preprocess: Whether to preprocess the image
            label_mode: Use specialized preprocessing for label boxes
            
        Returns:
            Tuple of (extracted text, confidence)
        """
        # Convert PIL Image to numpy array if needed
        if isinstance(image, Image.Image):
            image = np.array(image)
        
        if preprocess:
            image = self.preprocess_for_ocr(image, label_mode=label_mode)
        
        # Get detailed OCR data
        data = pytesseract.image_to_data(image, config=self.config, output_type=pytesseract.Output.DICT)
        
        # Extract text and calculate average confidence
        texts = []
        confidences = []
        
        for i, conf in enumerate(data['conf']):
            if conf > 0:  # Valid detection
                text = data['text'][i].strip()
                if text:
                    texts.append(text)
                    confidences.append(conf)
        
        extracted_text = ' '.join(texts)
        avg_confidence = sum(confidences) / len(confidences) / 100 if confidences else 0
        
        # Post-process: clean up common OCR errors in labels
        if label_mode:
            extracted_text = self._clean_label_text(extracted_text)
        
        return extracted_text, avg_confidence
    
    def _clean_label_text(self, text):
        """Clean up common OCR errors in label text.
        
        Args:
            text: Raw OCR text
            
        Returns:
            Cleaned text
        """
        import re
        
        # Remove common artifacts from borders
        text = text.strip('|])[}')
        
        # Remove extra spaces first
        text = ' '.join(text.split())
        
        # STEP 1: Common single character OCR mistakes (do this first)
        replacements = {
            '$': 'S',  # Dollar sign -> S
            'i': '1',  # lowercase i -> 1
            'l': '1',  # lowercase L -> 1
            'I': '1',  # uppercase I -> 1 (in number context)
            'O': '0',  # Letter O -> zero
            '|': '',   # Remove pipes
            ']': '',   # Remove brackets
            ')': '',   # Remove parentheses
            '(': '',   # Remove parentheses
        }
        
        for old, new in replacements.items():
            text = text.replace(old, new)
        
        # Clean up spaces after character removal
        text = ' '.join(text.split())
        
        # STEP 2: Pattern-based fixes for common label formats
        
        # Fix "510-XXX" -> "S10-XXX" (5 at start -> S)
        text = re.sub(r'^5(\d)', r'S\1', text)
        
        # Fix "9X-X" -> "SX-X" (9 at start -> S)
        text = re.sub(r'^9(\d)', r'S\1', text)
        
        # Fix missing S at start of label pattern like "X-X" or "XX-XXX"
        if re.match(r'^\d+-\d+', text):
            text = 'S' + text
        
        # Fix "S0 1-1" -> "S1-1" (space between 0 and 1)
        text = re.sub(r'S0\s+1', 'S1', text)
        
        # Fix "S 1-1" -> "S1-1" (space after S before number)
        text = re.sub(r'S\s+(\d)', r'S\1', text)
        
        # Final cleanup: remove extra spaces
        text = ' '.join(text.split())
        
        return text
    
    def parse_quantity(self, text):
        """Parse quantity multiplier from text (e.g., "S10-84 x2" -> ("S10-84", 2)).
        
        Args:
            text: Text that may contain a quantity multiplier
            
        Returns:
            Tuple of (cleaned_text, quantity)
            - cleaned_text: Text with multiplier removed
            - quantity: Integer quantity (defaults to 1 if no multiplier found)
        """
        import re
        
        if not text:
            return text, 1
        
        # Look for patterns like "x2", "x3", "x10" (case insensitive)
        # Try multiple patterns:
        # 1. At the end: "S10-84 x2" or "S10-84x2"
        # 2. Anywhere in string: "x2 S10-84" (less common but possible)
        
        # Pattern 1: x followed by digits at the end
        match = re.search(r'\s*[xX](\d+)\s*$', text)
        if match:
            quantity = int(match.group(1))
            cleaned_text = text[:match.start()].strip()
            return cleaned_text, quantity
        
        # Pattern 2: x followed by digits anywhere (with word boundaries)
        match = re.search(r'\b[xX](\d+)\b', text)
        if match:
            quantity = int(match.group(1))
            # Remove the multiplier from the text
            cleaned_text = text[:match.start()] + text[match.end():]
            cleaned_text = cleaned_text.strip()
            return cleaned_text, quantity
        
        # No multiplier found, return original text with quantity of 1
        return text.strip(), 1
    
    def extract_text_from_region(self, image_path, x, y, width, height, padding=5, label_mode=False, capture_adjacent=True):
        """Extract text from a specific region of an image.
        
        Args:
            image_path: Path to the image file
            x, y, width, height: Region coordinates
            padding: Extra padding around the region
            label_mode: Use specialized preprocessing for label boxes
            capture_adjacent: If True, search for multipliers around the rectangle (not used anymore)
            
        Returns:
            Tuple of (extracted text, confidence)
        """
        # Load image
        img = cv2.imread(image_path)
        if img is None:
            raise FileNotFoundError(f"Could not load image: {image_path}")
        
        # Apply padding and bounds checking (no expansion)
        x1 = max(0, x - padding)
        y1 = max(0, y - padding)
        x2 = min(img.shape[1], x + width + padding)
        y2 = min(img.shape[0], y + height + padding)
        
        # Extract region
        region = img[y1:y2, x1:x2]
        
        if region.size == 0:
            return '', 0.0
        
        return self.extract_text(region, label_mode=label_mode)
    
    def find_multiplier_near_region(self, image_path, x, y, width, height, search_distance=None):
        """Search for multiplier text (x2, x3, etc.) near a rectangular region.
        
        Args:
            image_path: Path to the image file
            x, y, width, height: Region coordinates of the main rectangle
            search_distance: How far to search (defaults to max(width, height))
            
        Returns:
            Integer quantity (1 if no multiplier found)
        """
        import re
        
        # Load image
        img = cv2.imread(image_path)
        if img is None:
            return 1
        
        # Default search distance
        if search_distance is None:
            search_distance = max(width, height)
        
        # Define search regions around the rectangle
        # Search in 4 directions: right, left, top, bottom
        search_regions = [
            # Right side
            {
                'x': x + width,
                'y': y,
                'width': search_distance,
                'height': height,
                'name': 'right'
            },
            # Left side
            {
                'x': max(0, x - search_distance),
                'y': y,
                'width': min(search_distance, x),
                'height': height,
                'name': 'left'
            },
            # Top
            {
                'x': x,
                'y': max(0, y - search_distance),
                'width': width,
                'height': min(search_distance, y),
                'name': 'top'
            },
            # Bottom
            {
                'x': x,
                'y': y + height,
                'width': width,
                'height': search_distance,
                'name': 'bottom'
            }
        ]
        
        multiplier_pattern = re.compile(r'\b[xX](\d+)\b')
        
        for region_def in search_regions:
            # Extract the search region
            rx, ry, rw, rh = region_def['x'], region_def['y'], region_def['width'], region_def['height']
            
            # Bounds check
            x1 = max(0, rx)
            y1 = max(0, ry)
            x2 = min(img.shape[1], rx + rw)
            y2 = min(img.shape[0], ry + rh)
            
            if x2 <= x1 or y2 <= y1:
                continue
            
            # Extract region
            search_img = img[y1:y2, x1:x2]
            
            if search_img.size == 0:
                continue
            
            # Run OCR on this small region
            try:
                # Use simple preprocessing for small text regions
                text, confidence = self.extract_text(search_img, preprocess=True, label_mode=False)
                
                # Look for multiplier pattern
                match = multiplier_pattern.search(text)
                if match:
                    quantity = int(match.group(1))
                    return quantity
                    
            except Exception:
                continue
        
        # No multiplier found
        return 1
    
    def _preprocess_circle(self, image, radius):
        """Specialized preprocessing for text inside circle markers.
        
        Masks out the circle outline (keeping 90% of interior), scales up,
        and uses adaptive thresholding optimized for thin architectural fonts.
        
        Args:
            image: Input image (numpy array, BGR) cropped to circle bounding box
            radius: Detected circle radius
            
        Returns:
            Preprocessed binary image ready for OCR
        """
        h, w = image.shape[:2]
        cx, cy = w // 2, h // 2
        
        inner_radius = max(5, int(radius * 0.90))
        circle_mask = np.zeros((h, w), dtype=np.uint8)
        cv2.circle(circle_mask, (cx, cy), inner_radius, 255, -1)
        
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()
        
        result = np.full((h, w), 255, dtype=np.uint8)
        result[circle_mask > 0] = gray[circle_mask > 0]
        
        scale = max(5.0, 250.0 / max(h, 1))
        scaled = cv2.resize(result, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        
        binary = cv2.adaptiveThreshold(
            scaled, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 31, 8
        )
        
        inv = cv2.bitwise_not(binary)
        inv = cv2.dilate(inv, np.ones((2, 2), np.uint8), iterations=1)
        binary = cv2.bitwise_not(inv)
        
        pad = 20
        binary = cv2.copyMakeBorder(binary, pad, pad, pad, pad,
                                     cv2.BORDER_CONSTANT, value=255)
        
        return binary
    
    def extract_text_from_circle(self, image_path, center_x, center_y, radius, padding=5):
        """Extract text from a circular region with circle-aware preprocessing.
        
        Args:
            image_path: Path to the image file
            center_x, center_y: Center coordinates
            radius: Circle radius
            padding: Extra padding
            
        Returns:
            Tuple of (extracted text, confidence)
        """
        img = cv2.imread(image_path)
        if img is None:
            raise FileNotFoundError(f"Could not load image: {image_path}")
        
        # Crop bounding box around circle with padding
        x1 = max(0, center_x - radius - padding)
        y1 = max(0, center_y - radius - padding)
        x2 = min(img.shape[1], center_x + radius + padding)
        y2 = min(img.shape[0], center_y + radius + padding)
        
        roi = img[y1:y2, x1:x2]
        if roi.size == 0:
            return '', 0.0
        
        preprocessed = self._preprocess_circle(roi, radius)
        
        # PSM 7 (single text line) works best for signage codes like SA-15, SC-2
        config = '--oem 3 --psm 7'
        data = pytesseract.image_to_data(
            preprocessed, config=config,
            output_type=pytesseract.Output.DICT
        )
        
        texts = []
        confidences = []
        for i, conf in enumerate(data['conf']):
            if conf > 0:
                text = data['text'][i].strip()
                if text:
                    texts.append(text)
                    confidences.append(conf)
        
        extracted_text = ' '.join(texts)
        avg_confidence = sum(confidences) / len(confidences) / 100 if confidences else 0
        
        # Fallback to PSM 8 (single word) if PSM 7 got nothing
        if not extracted_text:
            data = pytesseract.image_to_data(
                preprocessed, config='--oem 3 --psm 8',
                output_type=pytesseract.Output.DICT
            )
            texts = []
            confidences = []
            for i, conf in enumerate(data['conf']):
                if conf > 0:
                    text = data['text'][i].strip()
                    if text:
                        texts.append(text)
                        confidences.append(conf)
            extracted_text = ' '.join(texts)
            avg_confidence = sum(confidences) / len(confidences) / 100 if confidences else 0
        
        return extracted_text, avg_confidence
    
    def batch_extract(self, image_path, regions, label_mode=False):
        """Extract text from multiple regions.
        
        Args:
            image_path: Path to the image file
            regions: List of region dictionaries with x, y, width, height
            label_mode: Use specialized preprocessing for label boxes
            
        Returns:
            List of tuples (extracted text, confidence)
        """
        # Load image once
        img = cv2.imread(image_path)
        if img is None:
            raise FileNotFoundError(f"Could not load image: {image_path}")
        
        results = []
        
        for region in regions:
            x, y, w, h = region['x'], region['y'], region['width'], region['height']
            padding = region.get('padding', 0)  # Default 0 for labels (borders already removed)
            
            # Apply padding and bounds checking
            x1 = max(0, x - padding)
            y1 = max(0, y - padding)
            x2 = min(img.shape[1], x + w + padding)
            y2 = min(img.shape[0], y + h + padding)
            
            # Extract region
            roi = img[y1:y2, x1:x2]
            
            if roi.size == 0:
                results.append(('', 0.0))
            else:
                results.append(self.extract_text(roi, label_mode=label_mode))
        
        return results
    
    def get_text_locations(self, image_path):
        """Get locations of all text in an image.
        
        Args:
            image_path: Path to the image file
            
        Returns:
            List of dictionaries with text and bounding box info
        """
        img = cv2.imread(image_path)
        if img is None:
            raise FileNotFoundError(f"Could not load image: {image_path}")
        
        processed = self.preprocess_for_ocr(img)
        
        # Get detailed OCR data with bounding boxes
        data = pytesseract.image_to_data(processed, config=self.config, output_type=pytesseract.Output.DICT)
        
        locations = []
        
        for i in range(len(data['text'])):
            if data['conf'][i] > 0 and data['text'][i].strip():
                locations.append({
                    'text': data['text'][i],
                    'x': data['left'][i],
                    'y': data['top'][i],
                    'width': data['width'][i],
                    'height': data['height'][i],
                    'confidence': data['conf'][i] / 100
                })
        
        return locations
    
    def extract_title_from_floorplan(self, image_path, x_start_pct=60, y_start_pct=85, 
                                     width_pct=40, height_pct=15):
        """Extract title/sheet information from lower right corner of a floor plan.
        
        This method targets the title block typically found in the lower-right corner
        of architectural drawings containing information like "Sheet Title & Sign No."
        
        It tries multiple strategies to find the best title:
        1. Look for "Sheet Title & Sign No:" field and extract the value
        2. Look for "Dwg. No." or "Drawing No." field
        3. Extract from specified region and clean up
        
        Args:
            image_path: Path to the floor plan image file
            x_start_pct: Percentage from left where title region starts (default 60%)
            y_start_pct: Percentage from top where title region starts (default 85%)
            width_pct: Width of title region as percentage of image (default 40%)
            height_pct: Height of title region as percentage of image (default 15%)
            
        Returns:
            Cleaned title text string, or None if extraction fails
        """
        import re
        
        # Load image
        img = cv2.imread(image_path)
        if img is None:
            return None
        
        img_height, img_width = img.shape[:2]
        
        # Try multiple regions to find the best extraction
        # These regions are optimized for standard architectural title blocks
        regions_to_try = [
            # Region 1: Target the Sheet Title & Sign No field specifically
            {
                'x_pct': 84, 'y_pct': 78, 'w_pct': 15, 'h_pct': 6,
                'name': 'sheet_title_primary', 'ocr_mode': 6
            },
            # Region 2: Slightly larger to catch multi-line titles
            {
                'x_pct': 83, 'y_pct': 77, 'w_pct': 16, 'h_pct': 7,
                'name': 'sheet_title_extended', 'ocr_mode': 6
            },
            # Region 3: Include the label + value
            {
                'x_pct': 84, 'y_pct': 76, 'w_pct': 15, 'h_pct': 8,
                'name': 'sheet_title_with_label', 'ocr_mode': 6
            },
            # Region 4: User-specified default region (fallback)
            {
                'x_pct': x_start_pct, 'y_pct': y_start_pct, 
                'w_pct': width_pct, 'h_pct': height_pct,
                'name': 'user_default', 'ocr_mode': 6
            },
        ]
        
        best_title = None
        best_score = 0  # Score based on match quality
        
        for region_config in regions_to_try:
            x_start = int(img_width * (region_config['x_pct'] / 100))
            y_start = int(img_height * (region_config['y_pct'] / 100))
            region_width = int(img_width * (region_config['w_pct'] / 100))
            region_height = int(img_height * (region_config['h_pct'] / 100))
            
            # Ensure we don't go out of bounds
            x_end = min(x_start + region_width, img_width)
            y_end = min(y_start + region_height, img_height)
            
            if x_end <= x_start or y_end <= y_start:
                continue
            
            # Extract the region
            title_region = img[y_start:y_end, x_start:x_end]
            
            if title_region.size == 0:
                continue
            
            try:
                # Set OCR mode
                original_config = self.config
                self.config = f'--oem 3 --psm {region_config["ocr_mode"]}'
                
                # Extract text from this region
                text, confidence = self.extract_text(title_region, preprocess=True, label_mode=False)
                
                # Restore original config
                self.config = original_config
                
                if not text:
                    continue
                
                # Strategy 1: Look for "Sheet Title & Sign No:" pattern (HIGHEST PRIORITY)
                # This is the most specific and preferred pattern
                sheet_patterns = [
                    r'Sheet\s+Title\s*[&\+]?\s*Sign\s*No\.?\s*[:=\-]?\s*(.+?)(?:\n|Dwg|T\s*-\s*Dwg|Checked|$)',
                    r'Sheet\s+Title\s*[:=\-]?\s*(.+?)(?:\n|Dwg|T\s*-\s*Dwg|Checked|$)',
                    r'Title\s*[&\+]?\s*Sign\s*No\.?\s*[:=\-]?\s*(.+?)(?:\n|Dwg|T\s*-\s*Dwg|Checked|$)',
                ]
                
                for pattern in sheet_patterns:
                    match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
                    if match:
                        title = match.group(1).strip()
                        # Replace newlines with spaces for multi-line titles
                        title = re.sub(r'\s+', ' ', title)
                        # Clean and validate
                        cleaned = self._clean_title_text(title)
                        if cleaned and self._validate_title_text(cleaned):
                            # Found the sheet title field - this is the best match
                            # Give it a high score (100)
                            if 100 > best_score:
                                best_title = cleaned
                                best_score = 100
                
                # Strategy 2: Look for "Dwg. No." pattern (MEDIUM PRIORITY)
                if best_score < 50:  # Only if we haven't found sheet title
                    dwg_match = re.search(r'(?:Dwg\.?\s*No\.?|Drawing\s*No\.?)\s*[:.]?\s*([A-Za-z0-9\-_]+)', text, re.IGNORECASE)
                    if dwg_match:
                        title = dwg_match.group(1).strip()
                        cleaned = self._clean_title_text(title)
                        if cleaned and self._validate_title_text(cleaned):
                            if 50 > best_score:
                                best_title = cleaned
                                best_score = 50
                
                # Strategy 3: If this region has good text, save as potential fallback (LOW PRIORITY)
                if best_score < 10:
                    cleaned_text = self._clean_title_text(text)
                    if cleaned_text and self._validate_title_text(cleaned_text) and len(cleaned_text) < 80:
                        if 10 > best_score:
                            best_title = cleaned_text
                            best_score = 10
                        
            except Exception:
                continue
        
        return best_title
    
    def _clean_title_text(self, text):
        """Clean extracted title text by removing artifacts and normalizing.
        
        Args:
            text: Raw OCR text from title block
            
        Returns:
            Cleaned text string
        """
        import re
        
        if not text:
            return ''
        
        # Remove extra whitespace
        text = ' '.join(text.split())
        
        # Remove common border artifacts
        text = text.strip('|[](){}/_\\-=+*#')
        
        # Remove multiple consecutive dashes/underscores (common OCR artifacts)
        text = re.sub(r'[-_]{3,}', '', text)
        text = re.sub(r'[.]{3,}', '', text)
        
        # Replace problematic filename characters with safe alternatives
        unsafe_chars = {
            '/': '-',
            '\\': '-',
            ':': '-',
            '*': '',
            '?': '',
            '"': '',
            '<': '',
            '>': '',
            '|': '-'
        }
        
        for unsafe, safe in unsafe_chars.items():
            text = text.replace(unsafe, safe)
        
        # Clean up any resulting double spaces or dashes
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'-+', '-', text)
        
        # Final trim
        text = text.strip('- _')
        
        return text
    
    def _validate_title_text(self, text):
        """Validate that extracted title text is usable.
        
        Args:
            text: Cleaned text to validate
            
        Returns:
            True if text is valid, False otherwise
        """
        import re
        
        if not text:
            return False
        
        # Minimum length check (at least 3 characters)
        if len(text) < 3:
            return False
        
        # Maximum length check (reasonable filename length)
        if len(text) > 100:
            return False
        
        # Check if text is mostly artifacts (more than 50% special chars)
        special_char_count = len(re.findall(r'[^a-zA-Z0-9\s-]', text))
        if len(text) > 0 and (special_char_count / len(text)) > 0.5:
            return False
        
        # Reject if text is only numbers (likely page number, not title)
        if text.replace(' ', '').replace('-', '').isdigit():
            return False
        
        # Reject common OCR garbage patterns
        garbage_patterns = [
            r'^[.\-_|]+$',  # Only dots, dashes, underscores, pipes
            r'^\s*$',       # Only whitespace
        ]
        
        for pattern in garbage_patterns:
            if re.match(pattern, text):
                return False
        
        return True
    
    def group_ocr_results(self, results):
        """Group OCR results by identical text, summing quantities.
        
        Args:
            results: List of extracted data dictionaries with keys:
                     - _id: Database ID
                     - extracted_text: OCR text
                     - manual_text: Manual override text (optional)
                     - quantity: Current quantity
                     - confidence: OCR confidence
                     - Other fields preserved from first occurrence
        
        Returns:
            Dictionary with:
                - grouped: List of grouped results (keeping first occurrence)
                - deleted_ids: List of IDs that should be deleted (duplicates)
                - merge_info: Dictionary mapping kept ID to number of items merged
        """
        from collections import defaultdict
        
        # Dictionary to track groups by text (case-insensitive)
        groups = defaultdict(list)
        
        # Group results by their display text
        for result in results:
            # Use manual_text if available, otherwise extracted_text
            display_text = result.get('manual_text') or result.get('extracted_text') or ''
            # Normalize: strip whitespace and convert to lowercase for grouping
            normalized_text = display_text.strip().lower()
            
            # Skip empty texts
            if not normalized_text:
                groups['__empty__'].append(result)
            else:
                groups[normalized_text].append(result)
        
        grouped_results = []
        deleted_ids = []
        merge_info = {}
        
        # Process each group
        for normalized_text, group_items in groups.items():
            if len(group_items) == 1:
                # No duplicates, keep as is
                grouped_results.append(group_items[0])
            else:
                # Multiple items with same text - merge them
                # Keep the first occurrence
                primary = group_items[0]
                duplicates = group_items[1:]
                
                # Sum all quantities
                total_quantity = primary.get('quantity', 1)
                for dup in duplicates:
                    total_quantity += dup.get('quantity', 1)
                
                # Collect all bounding boxes for canvas display
                all_boxes = []
                for item in group_items:
                    box = {
                        'x': item.get('x'),
                        'y': item.get('y'),
                        'width': item.get('width'),
                        'height': item.get('height'),
                        'shape_type': item.get('shape_type')
                    }
                    # Add shape_data if it exists (for circles)
                    if item.get('shape_data'):
                        box['shape_data'] = item.get('shape_data')
                    all_boxes.append(box)
                
                # Update primary with merged quantity
                primary['quantity'] = total_quantity
                
                # Track merge metadata
                merge_info[str(primary['_id'])] = {
                    'merged_count': len(group_items),
                    'total_quantity': total_quantity,
                    'original_indices': [item.get('shape_index', 0) for item in group_items],
                    'all_bounding_boxes': all_boxes
                }
                
                # Mark duplicates for deletion
                for dup in duplicates:
                    deleted_ids.append(dup['_id'])
                
                grouped_results.append(primary)
        
        return {
            'grouped': grouped_results,
            'deleted_ids': deleted_ids,
            'merge_info': merge_info
        }

