import os
import re
import cv2
import numpy as np
import logging
from PIL import Image

logger = logging.getLogger(__name__)

# Suppress noisy PaddleOCR/PaddleX logs
for _name in ('paddleocr', 'paddlex', 'ppocr', 'paddle'):
    logging.getLogger(_name).setLevel(logging.WARNING)

os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')

SIGN_CODE_PATTERN = re.compile(
    r'^[A-Z][a-zA-Z]{0,3}[.\-]?\d+[a-zA-Z]?([.\-]\d+[a-zA-Z]?)*(\s*[xX]\d+)?$'
)

# Standalone x2 / ×3 only — do not match the X2 inside sign codes like EX2, EX4.
MULTIPLIER_PATTERN = re.compile(r'(?<![A-Za-z])[xX\u00d7*]\s*(\d+)')

_REJECT_WORDS = frozenset({
    'flat', 'type', 'room', 'living', 'bedroom', 'kitchen',
    'toilet', 'bath', 'hall', 'lobby', 'corridor', 'stair',
    'lift', 'block', 'floor', 'roof', 'balcony', 'store',
    'utility', 'master', 'common', 'typical', 'plan',
    'elevation', 'section', 'detail', 'note', 'ref',
    'ac', 'db', 'dp', 'up', 'dn', 'fl', 'rm',
    'no', 'nr', 'wc', 'tv', 'tel', 'rev',
    'li', 'jc', 'le', 'hf', 'lf', 'lft',
    'fo', 'cf', 'ab', '1c', 'in', 'its', 'for', 'at', 'pa', 'ci',
    'vl', '2n', 'fof', 'jn', 'on', 'un', 'is', 'pl', 'vc', 'or',
    'poi', '10h',
})


def _normalize_unicode_punctuation(text):
    """Normalize full-width and Unicode punctuation to ASCII equivalents."""
    replacements = {
        '\uff0c': ',', '\u3001': ',', '\uff0e': '.', '\u3002': '.',
        '\uff01': '!', '\uff1f': '?', '\uff1a': ':', '\uff1b': ';',
        '\uff08': '(', '\uff09': ')', '\uff3b': '[', '\uff3d': ']',
        '\uff5b': '{', '\uff5d': '}', '\uff0d': '-', '\u2013': '-',
        '\u2014': '-', '\u2018': "'", '\u2019': "'", '\u201c': '"',
        '\u201d': '"', '\uff02': '"', '\uff07': "'", '\uff5c': '|',
        '\uff0f': '/', '\uff3c': '\\', '\uff04': 'S', '\u00b7': '.',
        '\u2022': '.', '\u00a0': ' ',
        '\u00d7': 'x',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def clean_ocr_text(text):
    """Strip common OCR artifacts from sign code text.

    Normalizes Unicode punctuation, removes brackets, pipes, trailing dots,
    and strips all characters not valid in sign codes.
    """
    if not text:
        return ''
    text = _normalize_unicode_punctuation(text)
    text = text.replace('$', 'S')
    text = text.replace('*', 'x')
    text = text.strip(' |])[}{(.!@#%^&+=:;"\'<>,?/~`')
    text = re.sub(r'[^A-Za-z0-9\s.\-xX]', '', text)
    return text.strip()


def is_valid_sign_code(text, strict=False):
    """Determine whether *text* looks like a valid sign code.

    Returns True  -> keep the shape
    Returns False -> discard the shape

    When *strict* is True (used by the CV-level gate), only the regex
    pattern and the letter+digit heuristic are accepted; the looser
    fallback rules are skipped and a minimum length of 2 is enforced.

    Decision logic (in order):
      1. Empty / whitespace-only  -> False  (nothing readable)
      2. Matches SIGN_CODE_PATTERN -> True
      -- strict mode stops here (+ letter+digit heuristic) --
      3. 3+ words                 -> False
      4. Contains a known non-sign word -> False
      5. 2 words AND >12 chars    -> False
      6. Has letter+digit AND <=8 chars -> True
      7. Everything else          -> False
    """
    if not text or not text.strip():
        return False

    stripped = text.strip()
    if len(stripped) > 2 and re.search(r'[(){}\[\]]', stripped[1:-1]):
        return False

    cleaned = clean_ocr_text(text)
    if not cleaned:
        return False

    if cleaned.lower() in _REJECT_WORDS:
        return False

    # Gray lift labels OCR as "NO.1" / "NO-2", which match SIGN_CODE_PATTERN.
    # Only reject that pattern — do not treat every reject word as a prefix,
    # or real codes like WC1 / IN2 / FO3 get dropped.
    if re.fullmatch(r'NO[.\-]?\d+', cleaned, flags=re.IGNORECASE):
        return False

    # Quantity marks (x2 / ×2) are not sign codes. The 'x' is often read as Y.
    if re.fullmatch(r'[xXyY]\d+', cleaned):
        return False

    if strict and len(cleaned) < 2:
        return False

    if not strict and re.match(r'^[A-Z]{1,4}$', cleaned):
        if cleaned.lower() not in _REJECT_WORDS and len(cleaned) >= 2:
            return True

    if SIGN_CODE_PATTERN.match(cleaned):
        return True

    code_part = re.sub(r'\s*[xX]\d+$', '', cleaned)
    if not code_part:
        return False
    if any(c.islower() for c in code_part):
        return False

    has_digit = any(c.isdigit() for c in cleaned)
    has_alpha = any(c.isalpha() for c in cleaned)

    if strict:
        if not has_alpha:
            return False
        if ' ' in cleaned:
            return False
        return has_digit and has_alpha and len(cleaned) <= 8

    words = cleaned.split()

    if len(words) >= 3:
        return False

    if any(w.lower() in _REJECT_WORDS for w in words):
        return False

    if len(words) == 2 and len(cleaned) > 12:
        return False

    if has_digit and has_alpha and len(cleaned) <= 8:
        return True

    return False


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

        inner_radius = max(5, int(radius * 0.98))
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

    def extract_text_from_circle(self, image_path, center_x, center_y, radius, padding=5, img=None):
        """Extract text from a circular region with circle-aware preprocessing.

        Args:
            image_path: Path to the image file
            center_x, center_y: Center coordinates
            radius: Circle radius
            padding: Extra padding
            img: Optional pre-loaded BGR image (avoids redundant imread)

        Returns:
            Tuple of (extracted text, confidence)
        """
        if img is None:
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
        extracted_text = clean_ocr_text(extracted_text)
        avg_confidence = sum(scores) / len(scores) if scores else 0.0

        return extracted_text, avg_confidence

    def extract_text_from_region(self, image_path, x, y, width, height, padding=5,
                                  label_mode=False, capture_adjacent=True, img=None):
        """Extract text from a specific region of an image.

        Args:
            image_path: Path to the image file
            x, y, width, height: Region coordinates
            padding: Extra padding around the region
            label_mode: Use specialized preprocessing for label boxes
            capture_adjacent: (unused, kept for API compat)
            img: Optional pre-loaded BGR image (avoids redundant imread)

        Returns:
            Tuple of (extracted text, confidence)
        """
        if img is None:
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

    @staticmethod
    def _multiplier_search_regions(x, y, width, height, d):
        """Halo first so a clipped diagonal 'x2' is not read as '2', then
        cardinal strips and four diagonal squares around the sign box."""
        return [
            (x - d, y - d, width + 2 * d, height + 2 * d),
            (x + width, y, d, height),
            (x - d, y, d, height),
            (x, y - d, width, d),
            (x, y + height, width, d),
            (x + width, y - d, d, d),
            (x + width, y + height, d, d),
            (x - d, y - d, d, d),
            (x - d, y + height, d, d),
        ]

    @staticmethod
    def _point_to_sign_box(cx, cy, sign):
        x, y, w, h = sign['x'], sign['y'], sign['width'], sign['height']
        nearest_x = min(max(cx, x), x + w)
        nearest_y = min(max(cy, y), y + h)
        return float(np.hypot(cx - nearest_x, cy - nearest_y))

    @staticmethod
    def _point_inside_sign(cx, cy, sign, inset=0.15):
        x, y, w, h = sign['x'], sign['y'], sign['width'], sign['height']
        pad_x = w * inset
        pad_y = h * inset
        return (x + pad_x) <= cx <= (x + w - pad_x) and (y + pad_y) <= cy <= (y + h - pad_y)

    def _multiplier_hits_from_crop(self, crop, origin_x, origin_y, pattern):
        """OCR a crop and return x2 hits in image coordinates."""
        hits = []
        try:
            texts, _scores, boxes = self._run_ocr_with_boxes(crop)
        except Exception:
            texts, boxes = [], []

        for text, box in zip(texts, boxes):
            match = pattern.search(text or '')
            if not match:
                continue
            hits.append({
                'cx': origin_x + box['x'] + box['width'] / 2.0,
                'cy': origin_y + box['y'] + box['height'] / 2.0,
                'qty': int(match.group(1)),
            })

        if not hits:
            try:
                text, _ = self.extract_text(crop, preprocess=True, label_mode=False)
                match = pattern.search(text or '')
                if match:
                    hits.append({
                        'cx': origin_x + crop.shape[1] / 2.0,
                        'cy': origin_y + crop.shape[0] / 2.0,
                        'qty': int(match.group(1)),
                    })
            except Exception:
                pass
        return hits

    def _collect_multiplier_hits(self, img, x, y, width, height, pattern,
                                 search_distance=None):
        """OCR the 8 neighbor windows and return x2 locations."""
        d = max(width, height) if search_distance is None else search_distance
        hits = []
        for rx, ry, rw, rh in self._multiplier_search_regions(x, y, width, height, d):
            x1 = max(0, int(rx))
            y1 = max(0, int(ry))
            x2 = min(img.shape[1], int(rx + rw))
            y2 = min(img.shape[0], int(ry + rh))
            if x2 <= x1 or y2 <= y1:
                continue
            crop = img[y1:y2, x1:x2]
            if crop.size == 0:
                continue
            hits.extend(self._multiplier_hits_from_crop(crop, x1, y1, pattern))
        return hits

    @staticmethod
    def _cluster_multiplier_hits(hits, merge_dist):
        clusters = []
        for hit in hits:
            placed = False
            for cluster in clusters:
                if np.hypot(hit['cx'] - cluster['cx'], hit['cy'] - cluster['cy']) <= merge_dist:
                    n = cluster['n'] + 1
                    cluster['cx'] = (cluster['cx'] * cluster['n'] + hit['cx']) / n
                    cluster['cy'] = (cluster['cy'] * cluster['n'] + hit['cy']) / n
                    cluster['n'] = n
                    if hit.get('si') is not None:
                        cluster['sources'].add(hit['si'])
                    placed = True
                    break
            if not placed:
                sources = set()
                if hit.get('si') is not None:
                    sources.add(hit['si'])
                clusters.append({
                    'cx': hit['cx'], 'cy': hit['cy'], 'qty': hit['qty'],
                    'n': 1, 'sources': sources,
                })
        return clusters

    def assign_quantities(self, img, signs):
        """Assign multipliers found in each sign's neighbor windows.

        A sign may only claim an x2 it actually OCR'd. Uncontested hits are
        assigned first; remaining overlaps use distance to the sign box.
        Search reach is capped at the page-median sign size so a larger
        neighbor cannot reach into the next row. Leftovers farther than
        twice the nearest original claimant are left unassigned.
        """
        if img is None or not signs:
            return [1] * len(signs or [])

        sizes = [max(s['width'], s['height']) for s in signs]
        median_d = float(np.median(sizes))

        pattern = MULTIPLIER_PATTERN
        hits = []
        for si, sign in enumerate(signs):
            reach = min(float(max(sign['width'], sign['height'])), median_d)
            for hit in self._collect_multiplier_hits(
                    img, sign['x'], sign['y'], sign['width'], sign['height'],
                    pattern, search_distance=reach):
                hit['si'] = si
                hits.append(hit)

        hits = [h for h in hits
                if not any(self._point_inside_sign(h['cx'], h['cy'], s) for s in signs)]

        if not hits:
            return [1] * len(signs)

        typical = max(sizes)
        clusters = self._cluster_multiplier_hits(hits, merge_dist=typical * 0.6)

        claimants = [[] for _ in clusters]
        for ci, cluster in enumerate(clusters):
            if cluster['qty'] < 1:
                continue
            for si in cluster.get('sources') or ():
                dist = self._point_to_sign_box(
                    cluster['cx'], cluster['cy'], signs[si])
                claimants[ci].append((dist, si))

        quantities = [1] * len(signs)
        used_clusters = set()
        used_signs = set()

        def remaining(ci):
            return [(d, si) for d, si in claimants[ci] if si not in used_signs]

        def too_far(ci, dist):
            nearest = min((d for d, _si in claimants[ci]), default=0.0)
            return nearest > 0 and dist > 2.0 * nearest

        changed = True
        while changed:
            changed = False
            unique = []
            for ci, cluster in enumerate(clusters):
                if ci in used_clusters:
                    continue
                cands = remaining(ci)
                if len(cands) != 1:
                    continue
                dist, si = cands[0]
                if too_far(ci, dist):
                    continue
                unique.append((dist, ci, si, cluster['qty']))
            unique.sort()
            for _dist, ci, si, qty in unique:
                if ci in used_clusters or si in used_signs:
                    continue
                quantities[si] = qty
                used_clusters.add(ci)
                used_signs.add(si)
                changed = True

        pairs = []
        for ci, cluster in enumerate(clusters):
            if ci in used_clusters:
                continue
            for dist, si in remaining(ci):
                if too_far(ci, dist):
                    continue
                pairs.append((dist, ci, si, cluster['qty']))
        pairs.sort()
        for _dist, ci, si, qty in pairs:
            if ci in used_clusters or si in used_signs:
                continue
            quantities[si] = qty
            used_clusters.add(ci)
            used_signs.add(si)
        return quantities

    def find_multiplier_near_region(self, image_path, x, y, width, height,
                                    search_distance=None, img=None):
        """Search for multiplier text (x2, x3, etc.) near a rectangular region.

        Args:
            image_path: Path to the image file
            x, y, width, height: Region coordinates of the main rectangle
            search_distance: How far to search (defaults to max(width, height))
            img: Optional pre-loaded BGR image (avoids redundant imread)

        Returns:
            Integer quantity (1 if no multiplier found)
        """
        if img is None:
            img = cv2.imread(image_path)
            if img is None:
                return 1

        return self.assign_quantities(img, [{
            'x': x, 'y': y, 'width': width, 'height': height,
        }])[0]

    def extract_title_from_floorplan(self, image_path, x_start_pct=60, y_start_pct=85,
                                     width_pct=40, height_pct=15):
        """Extract title/sheet information from a floor plan image.

        Landscape: searches the lower-right corner.
        Portrait: extracts the bottom strip (title block), rotates 90 deg CCW
        to make its text readable, then searches within the rotated crop.

        Returns:
            Cleaned title text string, or None if extraction fails
        """
        import re

        img = cv2.imread(image_path)
        if img is None:
            return None

        img_height, img_width = img.shape[:2]

        # Portrait handling: title block is at the bottom, text rotated 90 deg CW.
        # Crop the bottom strip and rotate it so downstream region logic applies.
        is_portrait = img_height > img_width
        if is_portrait:
            bottom_crop = img[int(img_height * 0.85):img_height, 0:img_width]
            rotated = cv2.rotate(bottom_crop, cv2.ROTATE_90_COUNTERCLOCKWISE)
            img = rotated
            img_height, img_width = img.shape[:2]
            logger.info(f"Portrait title extraction: rotated bottom strip to {img_width}x{img_height}")

        regions_to_try = [
            {'x_pct': 84, 'y_pct': 76, 'w_pct': 15, 'h_pct': 12, 'name': 'sheet_title_primary'},
            {'x_pct': 83, 'y_pct': 75, 'w_pct': 16, 'h_pct': 14, 'name': 'sheet_title_extended'},
            {'x_pct': 84, 'y_pct': 74, 'w_pct': 15, 'h_pct': 15, 'name': 'sheet_title_with_label'},
            {'x_pct': x_start_pct, 'y_pct': y_start_pct, 'w_pct': width_pct, 'h_pct': height_pct, 'name': 'user_default'},
        ]
        if is_portrait:
            regions_to_try.append(
                {'x_pct': 0, 'y_pct': 0, 'w_pct': 100, 'h_pct': 100, 'name': 'full_region_fallback'}
            )

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
                    r'Sheet\s+Title\s*[&\+]?\s*Sign\s*No\.?\s*[:=\-]?\s*(.+?)(?=Dwg|T\s*-\s*Dwg|Checked|\Z)',
                    r'Sheet\s+Title\s*[:=\-]?\s*(.+?)(?=Dwg|T\s*-\s*Dwg|Checked|\Z)',
                    r'Title\s*[&\+]?\s*Sign\s*No\.?\s*[:=\-]?\s*(.+?)(?=Dwg|T\s*-\s*Dwg|Checked|\Z)',
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

        text = _normalize_unicode_punctuation(text)
        text = text.strip('|])[}{(.!@#%^&*+=:;"\'<>,?/~`')
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

        text = re.sub(r'^[^A-Za-z0-9]+', '', text)
        text = re.sub(r'[^A-Za-z0-9xX]+$', '', text)

        text = ' '.join(text.split())
        return text

    def parse_quantity(self, text):
        """Parse quantity multiplier from text (e.g., "S10-84 x2" -> ("S10-84", 2))."""
        import re

        if not text:
            return text, 1

        match = re.search(r'(?<![A-Za-z])[xX](\d+)\s*$', text)
        if match:
            quantity = int(match.group(1))
            cleaned_text = text[:match.start()].strip()
            return cleaned_text, quantity

        match = re.search(r'(?<![A-Za-z])[xX](\d+)\b', text)
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
        text = text.strip('|[]{}/_\\=+*#')

        text = re.sub(r'[-_]{3,}', '', text)
        text = re.sub(r'[.]{3,}', '', text)

        unsafe_chars = {
            '\\': '-', '*': '', '?': '',
            '"': '', '<': '', '>': '', '|': '-'
        }
        for unsafe, safe in unsafe_chars.items():
            text = text.replace(unsafe, safe)

        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'-+', '-', text)
        text = text.strip('- _')

        text = re.sub(r'\)\s*\S{1,4}$', ')', text)

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
