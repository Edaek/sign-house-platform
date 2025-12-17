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
    
    def extract_text_from_region(self, image_path, x, y, width, height, padding=5, label_mode=False):
        """Extract text from a specific region of an image.
        
        Args:
            image_path: Path to the image file
            x, y, width, height: Region coordinates
            padding: Extra padding around the region
            label_mode: Use specialized preprocessing for label boxes
            
        Returns:
            Tuple of (extracted text, confidence)
        """
        # Load image
        img = cv2.imread(image_path)
        if img is None:
            raise FileNotFoundError(f"Could not load image: {image_path}")
        
        # Apply padding and bounds checking
        x1 = max(0, x - padding)
        y1 = max(0, y - padding)
        x2 = min(img.shape[1], x + width + padding)
        y2 = min(img.shape[0], y + height + padding)
        
        # Extract region
        region = img[y1:y2, x1:x2]
        
        if region.size == 0:
            return '', 0.0
        
        return self.extract_text(region, label_mode=label_mode)
    
    def extract_text_from_circle(self, image_path, center_x, center_y, radius, padding=5):
        """Extract text from a circular region.
        
        Args:
            image_path: Path to the image file
            center_x, center_y: Center coordinates
            radius: Circle radius
            padding: Extra padding
            
        Returns:
            Tuple of (extracted text, confidence)
        """
        # Convert circle to bounding box
        x = center_x - radius
        y = center_y - radius
        width = radius * 2
        height = radius * 2
        
        return self.extract_text_from_region(image_path, x, y, width, height, padding)
    
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

