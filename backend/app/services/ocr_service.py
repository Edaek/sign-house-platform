import os
import cv2
import numpy as np
import logging
from PIL import Image

logger = logging.getLogger(__name__)

# Suppress noisy PaddleOCR/PaddleX logs
for _name in ('paddleocr', 'paddlex', 'ppocr', 'paddle'):
    logging.getLogger(_name).setLevel(logging.WARNING)

os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')


class OCRService:
    """Service for OCR text extraction using PaddleOCR."""

    _shared_ocr = None
    _shared_ocr_fast = None

    def __init__(self):
        """Initialize OCR service with lazy-loaded PaddleOCR models."""
        self._ocr = None
        self._ocr_fast = None

    @classmethod
    def _get_shared_ocr(cls):
        if cls._shared_ocr is None:
            from paddleocr import PaddleOCR
            cls._shared_ocr = PaddleOCR(
                lang='en',
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        return cls._shared_ocr

    @classmethod
    def _get_shared_ocr_fast(cls):
        """Lightweight instance for quick recognition on small crops."""
        if cls._shared_ocr_fast is None:
            from paddleocr import PaddleOCR
            cls._shared_ocr_fast = PaddleOCR(
                lang='en',
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        return cls._shared_ocr_fast

    @property
    def ocr(self):
        if self._ocr is None:
            self._ocr = self._get_shared_ocr()
        return self._ocr

    @property
    def ocr_fast(self):
        if self._ocr_fast is None:
            self._ocr_fast = self._get_shared_ocr_fast()
        return self._ocr_fast

    def _run_ocr(self, image, fast=False):
        """Run PaddleOCR on an image and return (texts, scores) lists.

        Args:
            image: numpy array (BGR or grayscale) or file path
            fast: if True use the lightweight recognizer

        Returns:
            Tuple of (texts list, scores list)
        """
        engine = self.ocr_fast if fast else self.ocr

        if isinstance(image, np.ndarray) and len(image.shape) == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)

        try:
            for result in engine.predict(image):
                texts = result.get('rec_texts', [])
                scores = result.get('rec_scores', [])
                return texts, scores
        except Exception as e:
            logger.warning(f"PaddleOCR prediction failed: {e}")
        return [], []

    def _run_ocr_with_boxes(self, image):
        """Run PaddleOCR and return (texts, scores, boxes) with bounding box info.

        Args:
            image: numpy array (BGR) or file path

        Returns:
            Tuple of (texts, scores, boxes) where boxes are [x,y,w,h] per detection
        """
        if isinstance(image, np.ndarray) and len(image.shape) == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)

        try:
            for result in self.ocr.predict(image):
                texts = result.get('rec_texts', [])
                scores = result.get('rec_scores', [])
                dt_polys = result.get('dt_polys', [])

                boxes = []
                for poly in dt_polys:
                    poly = np.array(poly)
                    x_min, y_min = poly.min(axis=0)
                    x_max, y_max = poly.max(axis=0)
                    boxes.append({
                        'x': int(x_min),
                        'y': int(y_min),
                        'width': int(x_max - x_min),
                        'height': int(y_max - y_min)
                    })
                return texts, scores, boxes
        except Exception as e:
            logger.warning(f"PaddleOCR prediction with boxes failed: {e}")
        return [], [], []

    # ----------------------------------------------------------------
    # Preprocessing (kept from original – PaddleOCR also benefits)
    # ----------------------------------------------------------------

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

        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()

        thresh = cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            11, 2
        )

        denoised = cv2.fastNlMeansDenoising(thresh)

        height, width = denoised.shape[:2]
        if height < 50 or width < 50:
            scale = max(50 / height, 50 / width, 2)
            denoised = cv2.resize(denoised, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

        return denoised

    def _preprocess_label(self, image):
        """Specialized preprocessing for label boxes with red borders."""
        img = image.copy()
        h, w = img.shape[:2]

        margin = max(3, min(w, h) // 15)
        if h > margin * 2 and w > margin * 2:
            img = img[margin:h - margin, margin:w - margin]
            h, w = img.shape[:2]

        if len(img.shape) == 3:
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

            lower_red1 = np.array([0, 40, 40])
            upper_red1 = np.array([10, 255, 255])
            lower_red2 = np.array([170, 40, 40])
            upper_red2 = np.array([180, 255, 255])

            red_mask1 = cv2.inRange(hsv, lower_red1, upper_red1)
            red_mask2 = cv2.inRange(hsv, lower_red2, upper_red2)
            red_mask = cv2.bitwise_or(red_mask1, red_mask2)

            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            gray[red_mask > 0] = 0
        else:
            gray = img.copy()

        scale_factor = max(4, 100 / h)
        scaled = cv2.resize(gray, None, fx=scale_factor, fy=scale_factor,
                            interpolation=cv2.INTER_CUBIC)

        blurred = cv2.GaussianBlur(scaled, (3, 3), 0)
        _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        kernel = np.ones((2, 2), np.uint8)
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)

        return binary

    def _preprocess_circle(self, image, radius):
        """Specialized preprocessing for text inside circle markers."""
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

    # ----------------------------------------------------------------
    # Public extraction methods
    # ----------------------------------------------------------------

    def extract_text(self, image, preprocess=True, label_mode=False):
        """Extract text from an image.

        Args:
            image: Input image (numpy array or PIL Image)
            preprocess: Whether to preprocess the image
            label_mode: Use specialized preprocessing for label boxes

        Returns:
            Tuple of (extracted text, confidence)
        """
        if isinstance(image, Image.Image):
            image = np.array(image)

        if preprocess:
            processed = self.preprocess_for_ocr(image, label_mode=label_mode)
        else:
            processed = image

        texts, scores = self._run_ocr(processed)

        if not texts:
            return '', 0.0

        extracted_text = ' '.join(t for t in texts if t.strip())
        avg_confidence = sum(scores) / len(scores) if scores else 0.0

        if label_mode:
            extracted_text = self._clean_label_text(extracted_text)

        return extracted_text, avg_confidence

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

        x1 = max(0, center_x - radius - padding)
        y1 = max(0, center_y - radius - padding)
        x2 = min(img.shape[1], center_x + radius + padding)
        y2 = min(img.shape[0], center_y + radius + padding)

        roi = img[y1:y2, x1:x2]
        if roi.size == 0:
            return '', 0.0

        preprocessed = self._preprocess_circle(roi, radius)
        texts, scores = self._run_ocr(preprocessed)

        extracted_text = ' '.join(t for t in texts if t.strip())
        avg_confidence = sum(scores) / len(scores) if scores else 0.0

        return extracted_text, avg_confidence

    def extract_text_from_region(self, image_path, x, y, width, height, padding=5,
                                  label_mode=False, capture_adjacent=True):
        """Extract text from a specific region of an image.

        Args:
            image_path: Path to the image file
            x, y, width, height: Region coordinates
            padding: Extra padding around the region
            label_mode: Use specialized preprocessing for label boxes
            capture_adjacent: (unused, kept for API compat)

        Returns:
            Tuple of (extracted text, confidence)
        """
        img = cv2.imread(image_path)
        if img is None:
            raise FileNotFoundError(f"Could not load image: {image_path}")

        x1 = max(0, x - padding)
        y1 = max(0, y - padding)
        x2 = min(img.shape[1], x + width + padding)
        y2 = min(img.shape[0], y + height + padding)

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

        img = cv2.imread(image_path)
        if img is None:
            return 1

        if search_distance is None:
            search_distance = max(width, height)

        search_regions = [
            {'x': x + width, 'y': y, 'width': search_distance, 'height': height, 'name': 'right'},
            {'x': max(0, x - search_distance), 'y': y, 'width': min(search_distance, x), 'height': height, 'name': 'left'},
            {'x': x, 'y': max(0, y - search_distance), 'width': width, 'height': min(search_distance, y), 'name': 'top'},
            {'x': x, 'y': y + height, 'width': width, 'height': search_distance, 'name': 'bottom'},
        ]

        multiplier_pattern = re.compile(r'\b[xX](\d+)\b')

        for region_def in search_regions:
            rx, ry, rw, rh = region_def['x'], region_def['y'], region_def['width'], region_def['height']

            x1 = max(0, rx)
            y1 = max(0, ry)
            x2 = min(img.shape[1], rx + rw)
            y2 = min(img.shape[0], ry + rh)

            if x2 <= x1 or y2 <= y1:
                continue

            search_img = img[y1:y2, x1:x2]
            if search_img.size == 0:
                continue

            try:
                text, confidence = self.extract_text(search_img, preprocess=True, label_mode=False)
                match = multiplier_pattern.search(text)
                if match:
                    return int(match.group(1))
            except Exception:
                continue

        return 1

    def extract_title_from_floorplan(self, image_path, x_start_pct=60, y_start_pct=85,
                                     width_pct=40, height_pct=15):
        """Extract title/sheet information from lower right corner of a floor plan.

        Tries multiple strategies:
        1. Look for "Sheet Title & Sign No:" field
        2. Look for "Dwg. No." field
        3. Fall back to region text

        Args:
            image_path: Path to the floor plan image file
            x_start_pct: Percentage from left where title region starts
            y_start_pct: Percentage from top where title region starts
            width_pct: Width of title region as percentage
            height_pct: Height of title region as percentage

        Returns:
            Cleaned title text string, or None if extraction fails
        """
        import re

        img = cv2.imread(image_path)
        if img is None:
            return None

        img_height, img_width = img.shape[:2]

        regions_to_try = [
            {'x_pct': 84, 'y_pct': 78, 'w_pct': 15, 'h_pct': 6, 'name': 'sheet_title_primary'},
            {'x_pct': 83, 'y_pct': 77, 'w_pct': 16, 'h_pct': 7, 'name': 'sheet_title_extended'},
            {'x_pct': 84, 'y_pct': 76, 'w_pct': 15, 'h_pct': 8, 'name': 'sheet_title_with_label'},
            {'x_pct': x_start_pct, 'y_pct': y_start_pct, 'w_pct': width_pct, 'h_pct': height_pct, 'name': 'user_default'},
        ]

        best_title = None
        best_score = 0

        for region_config in regions_to_try:
            x_start = int(img_width * (region_config['x_pct'] / 100))
            y_start = int(img_height * (region_config['y_pct'] / 100))
            region_width = int(img_width * (region_config['w_pct'] / 100))
            region_height = int(img_height * (region_config['h_pct'] / 100))

            x_end = min(x_start + region_width, img_width)
            y_end = min(y_start + region_height, img_height)

            if x_end <= x_start or y_end <= y_start:
                continue

            title_region = img[y_start:y_end, x_start:x_end]
            if title_region.size == 0:
                continue

            try:
                text, confidence = self.extract_text(title_region, preprocess=True, label_mode=False)

                if not text:
                    continue

                sheet_patterns = [
                    r'Sheet\s+Title\s*[&\+]?\s*Sign\s*No\.?\s*[:=\-]?\s*(.+?)(?:\n|Dwg|T\s*-\s*Dwg|Checked|$)',
                    r'Sheet\s+Title\s*[:=\-]?\s*(.+?)(?:\n|Dwg|T\s*-\s*Dwg|Checked|$)',
                    r'Title\s*[&\+]?\s*Sign\s*No\.?\s*[:=\-]?\s*(.+?)(?:\n|Dwg|T\s*-\s*Dwg|Checked|$)',
                ]

                for pattern in sheet_patterns:
                    match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
                    if match:
                        title = match.group(1).strip()
                        title = re.sub(r'\s+', ' ', title)
                        cleaned = self._clean_title_text(title)
                        if cleaned and self._validate_title_text(cleaned):
                            if 100 > best_score:
                                best_title = cleaned
                                best_score = 100

                if best_score < 50:
                    dwg_match = re.search(
                        r'(?:Dwg\.?\s*No\.?|Drawing\s*No\.?)\s*[:.]?\s*([A-Za-z0-9\-_]+)',
                        text, re.IGNORECASE
                    )
                    if dwg_match:
                        title = dwg_match.group(1).strip()
                        cleaned = self._clean_title_text(title)
                        if cleaned and self._validate_title_text(cleaned):
                            if 50 > best_score:
                                best_title = cleaned
                                best_score = 50

                if best_score < 10:
                    cleaned_text = self._clean_title_text(text)
                    if cleaned_text and self._validate_title_text(cleaned_text) and len(cleaned_text) < 80:
                        if 10 > best_score:
                            best_title = cleaned_text
                            best_score = 10

            except Exception:
                continue

        return best_title

    # ----------------------------------------------------------------
    # Text cleaning / validation helpers
    # ----------------------------------------------------------------

    def _clean_label_text(self, text):
        """Clean up common OCR errors in label text."""
        import re

        text = text.strip('|])[}')
        text = ' '.join(text.split())

        replacements = {
            '$': 'S',
            'i': '1',
            'l': '1',
            'I': '1',
            'O': '0',
            '|': '',
            ']': '',
            ')': '',
            '(': '',
        }

        for old, new in replacements.items():
            text = text.replace(old, new)

        text = ' '.join(text.split())

        text = re.sub(r'^5(\d)', r'S\1', text)
        text = re.sub(r'^9(\d)', r'S\1', text)

        if re.match(r'^\d+-\d+', text):
            text = 'S' + text

        text = re.sub(r'S0\s+1', 'S1', text)
        text = re.sub(r'S\s+(\d)', r'S\1', text)

        text = ' '.join(text.split())
        return text

    def parse_quantity(self, text):
        """Parse quantity multiplier from text (e.g., "S10-84 x2" -> ("S10-84", 2))."""
        import re

        if not text:
            return text, 1

        match = re.search(r'\s*[xX](\d+)\s*$', text)
        if match:
            quantity = int(match.group(1))
            cleaned_text = text[:match.start()].strip()
            return cleaned_text, quantity

        match = re.search(r'\b[xX](\d+)\b', text)
        if match:
            quantity = int(match.group(1))
            cleaned_text = text[:match.start()] + text[match.end():]
            return cleaned_text.strip(), quantity

        return text.strip(), 1

    def _clean_title_text(self, text):
        """Clean extracted title text."""
        import re

        if not text:
            return ''

        text = ' '.join(text.split())
        text = text.strip('|[](){}/_\\-=+*#')

        text = re.sub(r'[-_]{3,}', '', text)
        text = re.sub(r'[.]{3,}', '', text)

        unsafe_chars = {
            '/': '-', '\\': '-', ':': '-', '*': '', '?': '',
            '"': '', '<': '', '>': '', '|': '-'
        }
        for unsafe, safe in unsafe_chars.items():
            text = text.replace(unsafe, safe)

        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'-+', '-', text)
        text = text.strip('- _')

        return text

    def _validate_title_text(self, text):
        """Validate that extracted title text is usable."""
        import re

        if not text or len(text) < 3 or len(text) > 100:
            return False

        special_char_count = len(re.findall(r'[^a-zA-Z0-9\s-]', text))
        if len(text) > 0 and (special_char_count / len(text)) > 0.5:
            return False

        if text.replace(' ', '').replace('-', '').isdigit():
            return False

        garbage_patterns = [r'^[.\-_|]+$', r'^\s*$']
        for pattern in garbage_patterns:
            if re.match(pattern, text):
                return False

        return True

    # ----------------------------------------------------------------
    # Batch / location methods
    # ----------------------------------------------------------------

    def batch_extract(self, image_path, regions, label_mode=False):
        """Extract text from multiple regions.

        Args:
            image_path: Path to the image file
            regions: List of region dictionaries with x, y, width, height
            label_mode: Use specialized preprocessing for label boxes

        Returns:
            List of tuples (extracted text, confidence)
        """
        img = cv2.imread(image_path)
        if img is None:
            raise FileNotFoundError(f"Could not load image: {image_path}")

        results = []

        for region in regions:
            x, y, w, h = region['x'], region['y'], region['width'], region['height']
            padding = region.get('padding', 0)

            x1 = max(0, x - padding)
            y1 = max(0, y - padding)
            x2 = min(img.shape[1], x + w + padding)
            y2 = min(img.shape[0], y + h + padding)

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

        texts, scores, boxes = self._run_ocr_with_boxes(img)

        locations = []
        for i, text in enumerate(texts):
            if text.strip() and i < len(scores) and scores[i] > 0:
                loc = {
                    'text': text,
                    'confidence': scores[i],
                }
                if i < len(boxes):
                    loc.update(boxes[i])
                locations.append(loc)

        return locations

    def group_ocr_results(self, results):
        """Group OCR results by identical text, summing quantities.

        Args:
            results: List of extracted data dictionaries

        Returns:
            Dictionary with grouped, deleted_ids, merge_info
        """
        from collections import defaultdict

        groups = defaultdict(list)

        for result in results:
            display_text = result.get('manual_text') or result.get('extracted_text') or ''
            normalized_text = display_text.strip().lower()

            if not normalized_text:
                groups['__empty__'].append(result)
            else:
                groups[normalized_text].append(result)

        grouped_results = []
        deleted_ids = []
        merge_info = {}

        for normalized_text, group_items in groups.items():
            if len(group_items) == 1:
                grouped_results.append(group_items[0])
            else:
                primary = group_items[0]
                duplicates = group_items[1:]

                total_quantity = primary.get('quantity', 1)
                for dup in duplicates:
                    total_quantity += dup.get('quantity', 1)

                all_boxes = []
                for item in group_items:
                    box = {
                        'x': item.get('x'),
                        'y': item.get('y'),
                        'width': item.get('width'),
                        'height': item.get('height'),
                        'shape_type': item.get('shape_type')
                    }
                    if item.get('shape_data'):
                        box['shape_data'] = item.get('shape_data')
                    all_boxes.append(box)

                primary['quantity'] = total_quantity

                merge_info[str(primary['_id'])] = {
                    'merged_count': len(group_items),
                    'total_quantity': total_quantity,
                    'original_indices': [item.get('shape_index', 0) for item in group_items],
                    'all_bounding_boxes': all_boxes
                }

                for dup in duplicates:
                    deleted_ids.append(dup['_id'])

                grouped_results.append(primary)

        return {
            'grouped': grouped_results,
            'deleted_ids': deleted_ids,
            'merge_info': merge_info
        }
