import os
import re
import cv2
import numpy as np
import logging
from contextlib import contextmanager

from app.services.ocr_service import clean_ocr_text, is_valid_sign_code
from app.services.job_cancel import JobCancelledError, raise_if_cancelled

logger = logging.getLogger(__name__)


class CVService:
    """Service for computer vision shape detection."""

    FAST_MODE = 'fast'
    ACCURATE_MODE = 'accurate'
    MARKER_COLORS = ('red', 'blue', 'yellow')
    # Accurate mode searches every supported color except the sample color.
    # Fast mode stays sample-color-only. Calibrated on LP-BLK1-GF.pdf (E01 blue).
    SUPPORTED_COLORS = ('blue', 'red', 'yellow')
    MIN_CIRCULARITY = 0.75

    @staticmethod
    def _is_portrait(img):
        h, w = img.shape[:2]
        return h > w
    
    def __init__(self, mode='accurate'):
        """Initialize CV service with default parameters.
        
        Args:
            mode: 'fast' for speed-optimized detection (fewer passes, no OCR gating),
                  'accurate' for full detection (all passes, OCR verification).
        """
        self._ocr_engine = None
        self.mode = mode
        # Circle detection parameters
        self.circle_params = {
            'dp': 1.2,
            'min_dist': 30,
            'param1': 50,
            'param2': 30,
            'min_radius': 15,
            'max_radius': 100
        }
        
        # Rectangle detection parameters
        self.rect_params = {
            'min_area': 500,
            'max_area': 50000,
            'min_aspect_ratio': 0.3,
            'max_aspect_ratio': 3.0,
            'approx_epsilon': 0.02
        }
        
        # Template-based circle detection parameters
        self.template_circle_params = {
            'search_region_ratio': 0.15,  # Upper-right 15% of image
            'scale_range': (0.8, 1.2),    # 80% to 120% of template size
            'scale_steps': 10,            # Number of scale variations
            'match_threshold': 0.5,       # Minimum correlation score (lower for edge matching)
            'nms_iou_threshold': 0.3,     # NMS overlap threshold (tighter to avoid duplicates)
            # Blue HSV calibrated on the saturated E01 marker (H=120, S≈255,
            # V≈245, BGR≈(245,0,0)). S≥70 / V≥100 drops gray-blue CAD ink;
            # H 105–135 keeps true blue without cyan-leaning greys.
            'lower_blue': np.array([105, 70, 100]),
            'upper_blue': np.array([135, 255, 255]),
            'template_padding': 5,        # Padding around extracted template
            'min_circularity': 0.75,      # Minimum circularity score for template detection
        }
        
        # Red rectangle detection parameters
        self.red_rect_params = {
            'min_area': 400,  # Lowered to catch small labels on coloured backgrounds (~28x18)
            'max_area': 30000,  # Raised for large labels like D.C.L0.148.D (~269x97)
            'min_width': 20,  # Lowered for small labels on coloured backgrounds (~27px)
            'max_width': 280,  # Raised for long labels like D.C.L0.148.D (~269px)
            'min_height': 14,  # Lowered for short labels with thin borders
            'max_height': 100,  # Raised for tall labels (~57-97px in DS-BC plans)
            'min_aspect_ratio': 1.0,  # Lowered for near-square labels like L0 (86x57)
            'max_aspect_ratio': 7.0,  # Raised for very wide labels
            'approx_epsilon': 0.03,
            # Red color ranges in HSV (red wraps around at 0/180)
            'lower_red1': np.array([0, 50, 50]),
            'upper_red1': np.array([10, 255, 255]),
            'lower_red2': np.array([170, 50, 50]),
            'upper_red2': np.array([180, 255, 255]),
            # White interior threshold (grayscale value)
            'white_threshold': 200,  # Stricter white threshold
            'white_ratio_min': 0.55  # At least 55% of interior must be white/light
        }

    @contextmanager
    def defer_shape_ocr(self):
        """Skip per-candidate OCR during CV detection; run once in batch OCR."""
        prev = getattr(self, '_defer_shape_ocr', False)
        self._defer_shape_ocr = True
        try:
            yield
        finally:
            self._defer_shape_ocr = prev

    @staticmethod
    def _pop_should_cancel(params):
        if not params:
            return None
        return params.pop('should_cancel', None)
    
    def load_image(self, image_path, img=None):
        """Load an image from file, or reuse a pre-loaded array."""
        if img is None:
            img = cv2.imread(image_path)
            if img is None:
                raise FileNotFoundError(f"Could not load image: {image_path}")

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return img, gray
    
    def preprocess_for_detection(self, gray_image):
        """Preprocess image for shape detection.
        
        Args:
            gray_image: Grayscale image
            
        Returns:
            Preprocessed image
        """
        # Apply Gaussian blur to reduce noise
        blurred = cv2.GaussianBlur(gray_image, (9, 9), 2)
        
        return blurred
    
    def detect_circles(self, image_path, params=None):
        """Detect circles in an image.
        
        Args:
            image_path: Path to the image file
            params: Optional dictionary of detection parameters
            
        Returns:
            List of detected circles with bounding box info
        """
        if params:
            self.circle_params.update(params)
        
        img, gray = self.load_image(image_path)
        processed = self.preprocess_for_detection(gray)
        
        # Detect circles using Hough Circle Transform
        circles = cv2.HoughCircles(
            processed,
            cv2.HOUGH_GRADIENT,
            dp=self.circle_params['dp'],
            minDist=self.circle_params['min_dist'],
            param1=self.circle_params['param1'],
            param2=self.circle_params['param2'],
            minRadius=self.circle_params['min_radius'],
            maxRadius=self.circle_params['max_radius']
        )
        
        detected = []
        
        if circles is not None:
            circles = np.round(circles[0, :]).astype("int")
            
            for (center_x, center_y, radius) in circles:
                # Calculate bounding box
                x = max(0, center_x - radius)
                y = max(0, center_y - radius)
                width = min(radius * 2, img.shape[1] - x)
                height = min(radius * 2, img.shape[0] - y)
                
                detected.append({
                    'type': 'circle',
                    'center_x': int(center_x),
                    'center_y': int(center_y),
                    'radius': int(radius),
                    'x': int(x),
                    'y': int(y),
                    'width': int(width),
                    'height': int(height)
                })
        
        return detected
    
    def _extract_template_from_corner(self, img):
        """Extract a circle template from the upper-right corner of the image.
        
        Looks for a colored circle (blue or red) in the upper-right region.
        
        Args:
            img: BGR image (numpy array)
            
        Returns:
            Tuple of (template_image, template_center, template_radius) or (None, None, None) if not found
        """
        h, w = img.shape[:2]
        ratio = self.template_circle_params['search_region_ratio']
        
        search_w = int(w * ratio)
        search_h = int(h * ratio)
        search_region = img[0:search_h, w - search_w:w]
        
        best_contour = None
        best_circularity = 0
        
        for color_type in self.SUPPORTED_COLORS:
            color_mask = self._build_color_mask(search_region, color_type)
            contours, _ = cv2.findContours(color_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            for contour in contours:
                area = cv2.contourArea(contour)
                if area < 100:
                    continue
                
                perimeter = cv2.arcLength(contour, True)
                if perimeter == 0:
                    continue
                
                circularity = 4 * np.pi * area / (perimeter * perimeter)
                
                if circularity > best_circularity and circularity >= self.template_circle_params['min_circularity']:
                    best_circularity = circularity
                    best_contour = contour
        
        if best_contour is None:
            return None, None, None
        
        (cx, cy), radius = cv2.minEnclosingCircle(best_contour)
        cx, cy, radius = int(cx), int(cy), int(radius)
        
        padding = self.template_circle_params['template_padding']
        x1 = max(0, cx - radius - padding)
        y1 = max(0, cy - radius - padding)
        x2 = min(search_region.shape[1], cx + radius + padding)
        y2 = min(search_region.shape[0], cy + radius + padding)
        
        template = search_region[y1:y2, x1:x2].copy()
        template_center = (cx - x1, cy - y1)
        
        return template, template_center, radius
    
    def _multi_scale_template_match(self, img, template, scale_range, scale_steps, threshold):
        """Perform multi-scale template matching using edge detection.
        
        Uses Canny edge detection on both template and image to match
        the circle outline pattern rather than pixel colors (which vary
        due to different text labels inside each circle).
        
        Args:
            img: Source image (BGR)
            template: Template image (BGR)
            scale_range: Tuple of (min_scale, max_scale)
            scale_steps: Number of scale steps
            threshold: Minimum correlation threshold
            
        Returns:
            List of (x, y, w, h, score, scale) tuples for all matches
        """
        matches = []
        template_h, template_w = template.shape[:2]
        
        # Convert to grayscale and apply edge detection for matching
        img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        img_edges = cv2.Canny(img_gray, 50, 150)
        
        template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        template_edges = cv2.Canny(template_gray, 50, 150)
        
        # Generate scale factors
        min_scale, max_scale = scale_range
        scales = np.linspace(min_scale, max_scale, scale_steps)
        
        for scale in scales:
            # Resize template edges
            new_w = int(template_w * scale)
            new_h = int(template_h * scale)
            
            if new_w < 10 or new_h < 10:
                continue
            
            scaled_template = cv2.resize(template_edges, (new_w, new_h), interpolation=cv2.INTER_AREA)
            
            # Skip if template is larger than image
            if new_w > img_edges.shape[1] or new_h > img_edges.shape[0]:
                continue
            
            # Template matching on edge images
            result = cv2.matchTemplate(img_edges, scaled_template, cv2.TM_CCOEFF_NORMED)
            
            # Find all locations above threshold
            locations = np.where(result >= threshold)
            
            for pt in zip(*locations[::-1]):  # Switch x and y
                x, y = pt
                score = result[y, x]
                matches.append((x, y, new_w, new_h, score, scale))
        
        return matches
    
    def _non_maximum_suppression(self, matches, iou_threshold):
        """Apply non-maximum suppression to remove overlapping detections.
        
        Args:
            matches: List of (x, y, w, h, score, scale) tuples
            iou_threshold: IoU threshold for suppression
            
        Returns:
            Filtered list of matches
        """
        if not matches:
            return []
        
        # Sort by score (descending)
        matches = sorted(matches, key=lambda m: m[4], reverse=True)
        
        kept = []
        
        for match in matches:
            x1, y1, w1, h1, score1, scale1 = match
            
            # Check if this match overlaps with any kept match
            is_suppressed = False
            
            for kept_match in kept:
                x2, y2, w2, h2, _, _ = kept_match
                
                # Calculate IoU
                iou = self._calculate_iou(x1, y1, w1, h1, x2, y2, w2, h2)
                
                if iou > iou_threshold:
                    is_suppressed = True
                    break
            
            if not is_suppressed:
                kept.append(match)
        
        return kept
    
    def _calculate_iou(self, x1, y1, w1, h1, x2, y2, w2, h2):
        """Calculate Intersection over Union for two rectangles.
        
        Args:
            x1, y1, w1, h1: First rectangle
            x2, y2, w2, h2: Second rectangle
            
        Returns:
            IoU value (0.0 to 1.0)
        """
        # Calculate intersection
        xi1 = max(x1, x2)
        yi1 = max(y1, y2)
        xi2 = min(x1 + w1, x2 + w2)
        yi2 = min(y1 + h1, y2 + h2)
        
        if xi2 <= xi1 or yi2 <= yi1:
            return 0.0
        
        intersection = (xi2 - xi1) * (yi2 - yi1)
        
        # Calculate union
        area1 = w1 * h1
        area2 = w2 * h2
        union = area1 + area2 - intersection
        
        if union == 0:
            return 0.0
        
        return intersection / union
    
    def _verify_colored_circle(self, img, x, y, w, h, color_type='blue'):
        """Verify that a detected region contains a colored circle outline.
        
        Args:
            img: BGR image
            x, y, w, h: Bounding box of detected region
            color_type: 'blue' or 'red'
            
        Returns:
            True if the region contains significant colored pixels
        """
        y1 = max(0, y)
        y2 = min(img.shape[0], y + h)
        x1 = max(0, x)
        x2 = min(img.shape[1], x + w)
        
        if y2 <= y1 or x2 <= x1:
            return False
        
        region = img[y1:y2, x1:x2]
        color_mask = self._build_color_mask(region, color_type)
        color_ratio = np.sum(color_mask > 0) / color_mask.size
        
        return color_ratio >= 0.05
    
    def detect_circles_by_template(self, image_path, params=None, img=None):
        """Detect circles matching the sample from upper-right corner.
        
        Uses the sample circle to learn radius/size, then finds circles of the
        requested marker colors across the floorplan.
        
        Args:
            image_path: Path to the image file
            params: Optional dictionary of detection parameters. Supports
                marker_colors: list of 'red' | 'blue' | 'yellow' (default ['red'])
            
        Returns:
            List of detected circles with bounding box info
        """
        params = dict(params or {})
        should_cancel = self._pop_should_cancel(params)
        marker_colors = params.pop('marker_colors', None)
        color_samples = params.pop('color_samples', None) or []
        normalized_samples = []
        for sample in color_samples:
            if isinstance(sample, dict) and all(k in sample for k in ('b', 'g', 'r')):
                normalized_samples.append({
                    'b': int(sample['b']),
                    'g': int(sample['g']),
                    'r': int(sample['r']),
                    'label': sample.get('label'),
                })

        if marker_colors is None:
            marker_colors = [] if normalized_samples else ['red']
        else:
            marker_colors = [c for c in marker_colors if c in self.MARKER_COLORS]

        if not marker_colors and not normalized_samples:
            marker_colors = ['red']

        raise_if_cancelled(should_cancel)

        if params:
            self.template_circle_params.update(params)
        
        img, gray = self.load_image(image_path, img=img)
        h, w = img.shape[:2]
        
        sample_info = self._analyze_sample_circle(img)
        
        if sample_info is None:
            return []
        
        target_radius = sample_info['radius']
        sample_location = sample_info.get('location')

        # Detect legend box in upper-left corner to exclude from detection
        legend_bbox = self._detect_legend_region(img)

        sample_color = sample_info.get('color_type', 'red')
        if not marker_colors and normalized_samples:
            detected = []
            for sample_idx, sample in enumerate(normalized_samples):
                raise_if_cancelled(should_cancel, sample_idx, every=1)
                bgr = (sample['b'], sample['g'], sample['r'])
                preset = self._match_bgr_to_preset(*bgr)
                label = sample.get('label') or (preset or self._bgr_to_hex(*bgr))
                if preset:
                    batch = self._detect_secondary_color_circles(
                        img, gray, target_radius, preset, detected, sample_location,
                        marker_color_label=label, should_cancel=should_cancel)
                else:
                    batch = self._detect_secondary_color_circles(
                        img, gray, target_radius, 'red', detected, sample_location,
                        bgr_sample=bgr, marker_color_label=label, should_cancel=should_cancel)
                detected.extend(batch)
                detected = self._remove_duplicate_circles(
                    detected, min_distance=int(target_radius * 0.8))
            return self._finalize_detected_circles(detected, img, legend_bbox)

        color_type = marker_colors[0]
        secondary_colors = marker_colors[1:]
        secondary_colors = self._expand_secondary_colors(color_type, secondary_colors)

        if len(marker_colors) == 1 and marker_colors[0] != sample_color and not normalized_samples:
            detected = self._detect_secondary_color_circles(
                img, gray, target_radius, marker_colors[0], [], sample_location,
                should_cancel=should_cancel)
            return self._finalize_detected_circles(detected, img, legend_bbox)
        
        # Build color mask using detected color type (HSV-based)
        color_mask = self._build_color_mask(img, color_type)
        
        raw_color_mask = color_mask.copy()
        
        grad_data = None
        if target_radius <= 20:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            gx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
            gy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
            grad_mag = np.sqrt(gx ** 2 + gy ** 2)
            grad_data = (gx, gy, grad_mag)
        
        # Dilate to connect outline pixels (symmetric kernel to avoid directional bias)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        color_mask = cv2.dilate(color_mask, kernel, iterations=2)
        
        color_mask_blurred = cv2.GaussianBlur(color_mask, (5, 5), 1)
        
        size_tolerance = 0.50
        min_radius = max(5, int(target_radius * (1 - size_tolerance)))
        max_radius = int(target_radius * (1 + size_tolerance))
        
        circles = cv2.HoughCircles(
            color_mask_blurred,
            cv2.HOUGH_GRADIENT,
            dp=1.0,
            minDist=int(target_radius * 0.8),
            param1=50,
            param2=12,
            minRadius=min_radius,
            maxRadius=max_radius
        )
        
        detected = []
        
        if circles is not None:
            circles = np.round(circles[0, :]).astype("int")
            
            for hough_idx, (cx, cy, radius) in enumerate(circles):
                raise_if_cancelled(should_cancel, hough_idx, every=1)
                if sample_location:
                    sample_cx, sample_cy = sample_location
                    dist_to_sample = np.sqrt((cx - sample_cx) ** 2 + (cy - sample_cy) ** 2)
                    if dist_to_sample < target_radius * 2:
                        continue
                
                if not self._verify_circle_has_color(color_mask, cx, cy, radius):
                    continue
                
                if target_radius > 20 and not self._verify_circle_contour(
                        color_mask, cx, cy, radius, target_radius):
                    continue
                
                if target_radius <= 20 and grad_data and not self._verify_circle_gradient(
                        grad_data, cx, cy, radius, raw_color_mask):
                    continue
                
                # Refine center using raw (undilated) color mask on the ring region
                r_pad = int(radius * 1.3)
                y1c = max(0, cy - r_pad)
                y2c = min(h, cy + r_pad)
                x1c = max(0, cx - r_pad)
                x2c = min(w, cx + r_pad)
                roi_raw = raw_color_mask[y1c:y2c, x1c:x2c]
                roi_h, roi_w = roi_raw.shape[:2]
                local_cx_r = cx - x1c
                local_cy_r = cy - y1c
                outer_mask = np.zeros((roi_h, roi_w), dtype=np.uint8)
                inner_mask = np.zeros((roi_h, roi_w), dtype=np.uint8)
                cv2.circle(outer_mask, (local_cx_r, local_cy_r), int(radius * 1.2), 255, -1)
                cv2.circle(inner_mask, (local_cx_r, local_cy_r), int(radius * 0.7), 255, -1)
                ring_mask = cv2.bitwise_and(roi_raw, outer_mask)
                ring_mask = cv2.bitwise_and(ring_mask, cv2.bitwise_not(inner_mask))
                
                # Try fitEllipse for sub-pixel precision
                ring_points = np.column_stack(np.where(ring_mask > 0))
                if len(ring_points) >= 5:
                    try:
                        ellipse = cv2.fitEllipse(ring_points[:, ::-1])  # fitEllipse expects (x,y)
                        ecx, ecy = ellipse[0]
                        refined_cx = int(round(x1c + ecx))
                        refined_cy = int(round(y1c + ecy))
                        if abs(refined_cx - cx) < radius * 0.3 and abs(refined_cy - cy) < radius * 0.3:
                            cx, cy = refined_cx, refined_cy
                    except cv2.error:
                        # Fallback to moments if fitEllipse fails
                        M = cv2.moments(ring_mask)
                        if M['m00'] > 0:
                            refined_cx = int(round(x1c + M['m10'] / M['m00']))
                            refined_cy = int(round(y1c + M['m01'] / M['m00']))
                            if abs(refined_cx - cx) < radius * 0.3 and abs(refined_cy - cy) < radius * 0.3:
                                cx, cy = refined_cx, refined_cy
                else:
                    M = cv2.moments(ring_mask)
                    if M['m00'] > 0:
                        refined_cx = int(round(x1c + M['m10'] / M['m00']))
                        refined_cy = int(round(y1c + M['m01'] / M['m00']))
                        if abs(refined_cx - cx) < radius * 0.3 and abs(refined_cy - cy) < radius * 0.3:
                            cx, cy = refined_cx, refined_cy
                
                # Tight fit: reduce by 1px to align with circle ring midline
                adj_radius = radius - 1
                x = max(0, cx - adj_radius)
                y = max(0, cy - adj_radius)
                width = min(adj_radius * 2, w - x)
                height = min(adj_radius * 2, h - y)
                
                candidate = {
                    'type': 'circle',
                    'center_x': int(cx),
                    'center_y': int(cy),
                    'radius': int(adj_radius),
                    'x': int(x),
                    'y': int(y),
                    'width': int(width),
                    'height': int(height),
                    'confidence': 1.0,
                    'marker_color': color_type,
                }
                
                keep, text, conf = self._verify_shape_content(
                    img, candidate, color_type=color_type, should_cancel=should_cancel)
                if not keep:
                    continue
                
                if text:
                    candidate['extracted_text'] = text
                    candidate['ocr_confidence'] = conf
                
                detected.append(candidate)
        
        # --- Contour-based detection pass (catches circles Hough misses) ---
        # Skipped in fast mode — Hough-only is sufficient for speed
        if self.mode != self.FAST_MODE:
            kern_size = max(3, int(target_radius * 0.15))
            open_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kern_size, kern_size))
            contour_mask = cv2.morphologyEx(raw_color_mask, cv2.MORPH_OPEN, open_kernel)
            contours, _ = cv2.findContours(contour_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            radius_lo = target_radius * 0.55
            radius_hi = target_radius * 1.45

            for contour_idx, contour in enumerate(contours):
                raise_if_cancelled(should_cancel, contour_idx, every=4)
                area = cv2.contourArea(contour)
                if area < 200:
                    continue
                perimeter = cv2.arcLength(contour, True)
                if perimeter == 0:
                    continue
                circularity = 4 * np.pi * area / (perimeter * perimeter)
                if circularity < self.MIN_CIRCULARITY:
                    continue
                (ccx, ccy), cradius = cv2.minEnclosingCircle(contour)
                if not (radius_lo <= cradius <= radius_hi):
                    continue

                equiv_radius = np.sqrt(area / np.pi)
                cradius = equiv_radius * 0.7 + cradius * 0.3

                if len(contour) >= 5:
                    try:
                        ellipse = cv2.fitEllipse(contour)
                        ccx, ccy = ellipse[0]
                    except cv2.error:
                        M = cv2.moments(contour)
                        if M['m00'] > 0:
                            ccx = M['m10'] / M['m00']
                            ccy = M['m01'] / M['m00']
                else:
                    M = cv2.moments(contour)
                    if M['m00'] > 0:
                        ccx = M['m10'] / M['m00']
                        ccy = M['m01'] / M['m00']

                ccx, ccy = int(round(ccx)), int(round(ccy))

                if sample_location:
                    dist_to_sample = np.sqrt(
                        (ccx - sample_location[0]) ** 2 + (ccy - sample_location[1]) ** 2
                    )
                    if dist_to_sample < target_radius * 2:
                        continue

                already_found = any(
                    np.sqrt((ccx - d['center_x']) ** 2 + (ccy - d['center_y']) ** 2) < target_radius
                    for d in detected
                )
                if already_found:
                    continue

                adj_r = int(round(cradius)) - 1
                candidate = {
                    'type': 'circle',
                    'center_x': ccx,
                    'center_y': ccy,
                    'radius': adj_r,
                    'x': max(0, ccx - adj_r),
                    'y': max(0, ccy - adj_r),
                    'width': min(adj_r * 2, w - max(0, ccx - adj_r)),
                    'height': min(adj_r * 2, h - max(0, ccy - adj_r)),
                    'confidence': float(circularity),
                    'marker_color': color_type,
                }

                keep, text, conf = self._verify_shape_content(
                    img, candidate, color_type=color_type, should_cancel=should_cancel)
                if not keep:
                    continue
                if text:
                    candidate['extracted_text'] = text
                    candidate['ocr_confidence'] = conf
                detected.append(candidate)

        detected = self._remove_duplicate_circles(detected, min_distance=int(target_radius * 0.8))
        
        for sec_idx, sec_color_name in enumerate(secondary_colors):
            raise_if_cancelled(should_cancel, sec_idx, every=1)
            sec_detected = self._detect_secondary_color_circles(
                img, gray, target_radius, sec_color_name, detected, sample_location,
                should_cancel=should_cancel)
            detected.extend(sec_detected)
            detected = self._remove_duplicate_circles(detected, min_distance=int(target_radius * 0.8))

        for sample_idx, sample in enumerate(normalized_samples):
            raise_if_cancelled(should_cancel, sample_idx, every=1)
            bgr = (sample['b'], sample['g'], sample['r'])
            preset = self._match_bgr_to_preset(*bgr)
            label = sample.get('label') or (preset or self._bgr_to_hex(*bgr))
            if preset:
                custom_detected = self._detect_secondary_color_circles(
                    img, gray, target_radius, preset, detected, sample_location,
                    marker_color_label=label, should_cancel=should_cancel)
            else:
                custom_detected = self._detect_secondary_color_circles(
                    img, gray, target_radius, 'red', detected, sample_location,
                    bgr_sample=bgr, marker_color_label=label, should_cancel=should_cancel)
            detected.extend(custom_detected)
            detected = self._remove_duplicate_circles(
                detected, min_distance=int(target_radius * 0.8))
        
        return self._finalize_detected_circles(detected, img, legend_bbox)
    
    def _expand_secondary_colors(self, primary_color, user_secondary):
        """Merge user-selected colors with legacy secondary passes."""
        merged = list(user_secondary)
        if self.mode == self.FAST_MODE:
            return merged
        for legacy_color in ('yellow', 'red'):
            if legacy_color != primary_color and legacy_color not in merged:
                merged.append(legacy_color)
        return merged
    
    def _is_too_close_to_existing(self, cx, cy, radius, existing, min_dist, color=None):
        """Return True if a candidate overlaps a same-color detection nearby."""
        for d in existing:
            if color is not None and d.get('marker_color') != color:
                continue
            dist = np.sqrt((cx - d['center_x']) ** 2 + (cy - d['center_y']) ** 2)
            d_radius = d.get('radius', 0)
            if radius > d_radius * 1.5:
                continue
            if dist < max(min_dist, d_radius):
                return True
        return False

    def _has_yellow_fill(self, img, cx, cy, radius):
        """True when the circle interior is predominantly yellow fill."""
        h, w = img.shape[:2]
        inner_r = max(3, int(radius * 0.55))
        y1, y2 = max(0, cy - inner_r), min(h, cy + inner_r + 1)
        x1, x2 = max(0, cx - inner_r), min(w, cx + inner_r + 1)
        roi = img[y1:y2, x1:x2]
        if roi.size == 0:
            return False

        yellow_mask = self._build_color_mask(roi, 'yellow')
        lh, lw = yellow_mask.shape[:2]
        local_cx, local_cy = cx - x1, cy - y1
        circle = np.zeros((lh, lw), dtype=np.uint8)
        cv2.circle(circle, (local_cx, local_cy), inner_r, 255, -1)
        circle_area = max(1, cv2.countNonZero(circle))
        fill_hits = cv2.countNonZero(cv2.bitwise_and(yellow_mask, circle))
        return (fill_hits / circle_area) >= 0.35

    def _infer_marker_color(self, img, candidate):
        """Re-label red/blue ring detections that sit on yellow-filled markers."""
        color = candidate.get('marker_color')
        if color not in ('red', 'blue'):
            return color
        cx = candidate.get('center_x')
        cy = candidate.get('center_y')
        radius = candidate.get('radius')
        if cx is None or cy is None or radius is None:
            return color
        if self._has_yellow_fill(img, cx, cy, radius):
            return 'yellow'
        return color

    def _detect_secondary_color_circles(
        self, img, gray, target_radius, sec_color, existing, sample_location,
        bgr_sample=None, marker_color_label=None, should_cancel=None,
    ):
        """Run a secondary detection pass for circles of a different color.
        
        For filled circles (like yellow), independently estimates the actual
        radius from contour analysis rather than relying on the primary sample's
        target_radius.
        """
        h, w = img.shape[:2]
        result_color = marker_color_label or sec_color
        
        color_mask = self._build_color_mask(img, sec_color, bgr_sample=bgr_sample)
        
        if cv2.countNonZero(color_mask) < 100:
            return []
        
        is_thin_blue_ring = sec_color == 'blue' and bgr_sample is None
        min_contour_area = 80 if is_thin_blue_ring else 300
        ring_color_ratio = 0.28 if is_thin_blue_ring else 0.5
        
        kernel = np.ones((3, 3), np.uint8)
        if sec_color == 'blue' and bgr_sample is None:
            ellipse = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
            color_mask_clean = cv2.dilate(color_mask, ellipse, iterations=2)
        elif bgr_sample is not None:
            color_mask_clean = cv2.morphologyEx(color_mask, cv2.MORPH_CLOSE, kernel)
            color_mask_clean = cv2.morphologyEx(color_mask_clean, cv2.MORPH_OPEN, kernel)
            dilate_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            color_mask_clean = cv2.dilate(color_mask_clean, dilate_kernel, iterations=1)
        else:
            color_mask_clean = cv2.morphologyEx(color_mask, cv2.MORPH_CLOSE, kernel)
            color_mask_clean = cv2.morphologyEx(color_mask_clean, cv2.MORPH_OPEN, kernel)
        
        # --- Step 1: Estimate actual circle radius from contours ---
        radius_source = color_mask if is_thin_blue_ring else color_mask_clean
        est_contours, _ = cv2.findContours(
            radius_source, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        radii = []
        for c in est_contours:
            area = cv2.contourArea(c)
            if area < min_contour_area:
                continue
            if is_thin_blue_ring and area > 1200:
                continue
            peri = cv2.arcLength(c, True)
            if peri == 0:
                continue
            circ = 4 * np.pi * area / (peri * peri)
            min_circ = 0.55 if is_thin_blue_ring else 0.85
            if circ > min_circ:
                _, r = cv2.minEnclosingCircle(c)
                if is_thin_blue_ring and r > target_radius * 1.3:
                    continue
                radii.append(r)
        
        # Size caps: tighter bounds to reduce false positives and speed up detection.
        _size_cap = 2.0
        _target_cap = 1.8

        if radii:
            yellow_target = int(np.median(radii))
            yellow_target = max(int(target_radius * 0.5), min(yellow_target, int(target_radius * _target_cap)))
            min_radius = max(5, int(min(radii) * 0.7))
            max_radius = int(max(radii) * 1.3)
            max_radius = min(max_radius, int(target_radius * _size_cap))
            if is_thin_blue_ring:
                yellow_target = min(yellow_target, int(target_radius * 1.05))
                max_radius = min(max_radius, int(target_radius * 1.2))
        else:
            yellow_target = target_radius
            min_radius = max(5, int(target_radius * 0.5))
            max_radius = int(target_radius * _size_cap)
            if is_thin_blue_ring:
                yellow_target = int(target_radius * 0.95)
                max_radius = int(target_radius * 1.15)
        
        # --- Step 2: Hough. Blue uses the dilated mask (same as primary);
        # filled yellow/red still use Canny on the opened mask. ---
        if sec_color == 'blue':
            hough_input = cv2.GaussianBlur(color_mask_clean, (5, 5), 1)
        else:
            hough_input = cv2.Canny(color_mask_clean, 50, 150)
        
        # Pre-compute connected component labels for shape validation
        num_labels, labels, cc_stats, _ = cv2.connectedComponentsWithStats(color_mask_clean)
        
        hough_param2 = 14 if sec_color == 'red' else (8 if is_thin_blue_ring else 10)
        circles = cv2.HoughCircles(
            hough_input,
            cv2.HOUGH_GRADIENT,
            dp=1.0,
            minDist=int(yellow_target * 0.8),
            param1=50,
            param2=hough_param2,
            minRadius=min_radius,
            maxRadius=max_radius
        )
        
        detected = []
        
        if circles is not None:
            circles = np.round(circles[0, :]).astype("int")
            
            for sec_hough_idx, (cx, cy, radius) in enumerate(circles):
                raise_if_cancelled(should_cancel, sec_hough_idx, every=1)
                if sample_location:
                    dist_to_sample = np.sqrt(
                        (cx - sample_location[0]) ** 2 + (cy - sample_location[1]) ** 2)
                    if dist_to_sample < yellow_target * 2:
                        continue
                
                if not self._verify_circle_has_color(
                        color_mask if is_thin_blue_ring else color_mask_clean,
                        cx, cy, radius, min_ratio=ring_color_ratio):
                    continue
                
                # For red circles: skip contour verification (red text inside
                # makes the interior non-empty, causing false rejections)
                
                # Verify the connected component at this point is roughly circular
                if 0 <= cy < h and 0 <= cx < w and not is_thin_blue_ring:
                    label_id = labels[cy, cx]
                    if label_id > 0:
                        cc_w = cc_stats[label_id, cv2.CC_STAT_WIDTH]
                        cc_h = cc_stats[label_id, cv2.CC_STAT_HEIGHT]
                        cc_area = cc_stats[label_id, cv2.CC_STAT_AREA]
                        cc_aspect = min(cc_w, cc_h) / max(cc_w, cc_h) if max(cc_w, cc_h) > 0 else 0
                        expected_area = np.pi * radius * radius
                        area_limit = 8 if sec_color == 'red' else 4
                        if cc_aspect < 0.4 or cc_area > expected_area * area_limit:
                            continue
                
                too_close = self._is_too_close_to_existing(
                    cx, cy, radius, existing, max(yellow_target * 0.7, 0),
                    color=result_color)
                if too_close:
                    continue
                
                refine_seed_r = (
                    max(14, int(round(target_radius * 1.05))) if is_thin_blue_ring else radius)
                cx, cy, radius = self._refine_circle_from_ring_mask(
                    color_mask if is_thin_blue_ring else color_mask_clean,
                    cx, cy, refine_seed_r, is_thin_ring=is_thin_blue_ring)
                
                if is_thin_blue_ring:
                    min_r = max(12, int(target_radius * 0.8))
                    max_r = max(min_r + 2, int(round(target_radius * 1.15)))
                    radius = max(min_r, min(max_r, int(radius)))
                    cx, cy, radius = self._refine_circle_from_ring_mask(
                        color_mask, cx, cy, radius, is_thin_ring=True)
                    radius = max(min_r, min(max_r, int(radius)))
                
                adj_radius = max(5, int(radius))
                x = max(0, cx - adj_radius)
                y = max(0, cy - adj_radius)
                bw = min(adj_radius * 2, w - x)
                bh = min(adj_radius * 2, h - y)
                
                candidate = {
                    'type': 'circle',
                    'center_x': int(cx),
                    'center_y': int(cy),
                    'radius': int(adj_radius),
                    'x': int(x),
                    'y': int(y),
                    'width': int(bw),
                    'height': int(bh),
                    'confidence': 1.0,
                    'marker_color': result_color,
                }
                
                keep, text, conf = self._verify_shape_content(
                    img, candidate,
                    color_type=None if sec_color == 'red' else sec_color,
                    should_cancel=should_cancel)
                if is_thin_blue_ring:
                    if keep and text:
                        candidate['extracted_text'] = text
                        candidate['ocr_confidence'] = conf
                    detected.append(candidate)
                elif keep:
                    if text:
                        candidate['extracted_text'] = text
                        candidate['ocr_confidence'] = conf
                    detected.append(candidate)
                elif not text or not text.strip():
                    detected.append(candidate)
        
        # --- Step 3: Contour-based pass with independent radius range ---
        contours, _ = cv2.findContours(
            color_mask_clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        radius_lo = min_radius * 0.85
        radius_hi = max_radius * 1.1
        circ_threshold = self.MIN_CIRCULARITY
        
        for sec_contour_idx, contour in enumerate(contours):
            raise_if_cancelled(should_cancel, sec_contour_idx, every=4)
            area = cv2.contourArea(contour)
            if area < min_contour_area:
                continue
            perimeter = cv2.arcLength(contour, True)
            if perimeter == 0:
                continue
            circularity = 4 * np.pi * area / (perimeter * perimeter)
            if circularity < circ_threshold:
                continue
            (ccx, ccy), cradius = cv2.minEnclosingCircle(contour)
            if not (radius_lo <= cradius <= radius_hi):
                continue
            
            # Use equivalent radius for more robust estimate
            equiv_radius = np.sqrt(area / np.pi)
            cradius = equiv_radius * 0.7 + cradius * 0.3
            
            # Use fitEllipse for sub-pixel center
            if len(contour) >= 5:
                try:
                    ellipse = cv2.fitEllipse(contour)
                    ccx, ccy = ellipse[0]
                except cv2.error:
                    M = cv2.moments(contour)
                    if M['m00'] > 0:
                        ccx = M['m10'] / M['m00']
                        ccy = M['m01'] / M['m00']
            else:
                M = cv2.moments(contour)
                if M['m00'] > 0:
                    ccx = M['m10'] / M['m00']
                    ccy = M['m01'] / M['m00']
            ccx, ccy = int(round(ccx)), int(round(ccy))
            
            if is_thin_blue_ring:
                seed_r = max(14, int(round(target_radius * 1.05)))
                ccx, ccy, cradius = self._refine_circle_from_ring_mask(
                    color_mask, ccx, ccy, seed_r, is_thin_ring=True)
                min_r = max(12, int(target_radius * 0.8))
                max_r = max(min_r + 2, int(round(target_radius * 1.15)))
                cradius = max(min_r, min(max_r, int(cradius)))
                ccx, ccy, cradius = self._refine_circle_from_ring_mask(
                    color_mask, ccx, ccy, cradius, is_thin_ring=True)
                cradius = max(min_r, min(max_r, int(cradius)))
            
            too_close = self._is_too_close_to_existing(
                ccx, ccy, cradius, existing + detected, max(yellow_target * 0.7, 0),
                color=result_color)
            if too_close:
                continue
            
            adj_r = int(round(cradius))
            candidate = {
                'type': 'circle',
                'center_x': ccx,
                'center_y': ccy,
                'radius': adj_r,
                'x': max(0, ccx - adj_r),
                'y': max(0, ccy - adj_r),
                'width': min(adj_r * 2, w - max(0, ccx - adj_r)),
                'height': min(adj_r * 2, h - max(0, ccy - adj_r)),
                'confidence': float(circularity),
                'marker_color': result_color,
            }
            
            keep, text, conf = self._verify_shape_content(
                img, candidate,
                color_type=None if sec_color == 'red' else sec_color,
                should_cancel=should_cancel)
            if is_thin_blue_ring:
                if keep and text:
                    candidate['extracted_text'] = text
                    candidate['ocr_confidence'] = conf
                detected.append(candidate)
            elif keep:
                if text:
                    candidate['extracted_text'] = text
                    candidate['ocr_confidence'] = conf
                detected.append(candidate)
            elif not text or not text.strip():
                detected.append(candidate)
        
        if is_thin_blue_ring and detected:
            detected = self._merge_nearby_circles(detected, max_dist=35)
        elif sec_color == 'yellow' and detected:
            merge_dist = max(22, int(target_radius * 1.15))
            detected = self._merge_nearby_circles(detected, max_dist=merge_dist)
        
        return detected
    
    def _merge_nearby_circles(self, circles, max_dist=50):
        """Keep the best circle when several detections cluster together."""
        if not circles:
            return circles
        
        def priority(c):
            text = c.get('extracted_text') or ''
            valid = bool(text and is_valid_sign_code(text, strict=True))
            return (1 if valid else 0, c.get('radius', 0), c.get('confidence', 0))
        
        ranked = sorted(circles, key=priority, reverse=True)
        kept = []
        for circle in ranked:
            too_close = False
            for existing in kept:
                dist = np.hypot(
                    circle['center_x'] - existing['center_x'],
                    circle['center_y'] - existing['center_y'],
                )
                if dist < max_dist:
                    too_close = True
                    break
            if not too_close:
                kept.append(circle)
        return kept
    
    def _measure_mask_circularity(self, mask, cx, cy, radius):
        """Measure how circular the mask fill is within a given circle region.
        
        Returns the ratio of filled pixels to total circle area.
        A solid circular region gives ~0.9+, a rectangular bar gives <<0.5.
        """
        h, w = mask.shape[:2]
        x1 = max(0, cx - radius)
        y1 = max(0, cy - radius)
        x2 = min(w, cx + radius)
        y2 = min(h, cy + radius)
        
        region = mask[y1:y2, x1:x2]
        if region.size == 0:
            return 0.0
        
        rh, rw = region.shape
        local_cx = cx - x1
        local_cy = cy - y1
        
        Y, X = np.ogrid[:rh, :rw]
        dist = np.sqrt((X - local_cx) ** 2 + (Y - local_cy) ** 2)
        circle_mask = dist <= radius
        
        circle_area = np.count_nonzero(circle_mask)
        if circle_area == 0:
            return 0.0
        
        filled = np.count_nonzero(region[circle_mask])
        return filled / circle_area

    def _verify_circle_circularity(self, color_mask, cx, cy, radius, min_circularity=None):
        """Verify that a detected circle region contains a sufficiently circular contour.

        Crops the color mask around the circle, finds contours, and checks
        if the best contour has circularity above the threshold.
        """
        if min_circularity is None:
            min_circularity = self.MIN_CIRCULARITY
        h, w = color_mask.shape[:2]
        pad = int(radius * 0.3)
        x1 = max(0, cx - radius - pad)
        y1 = max(0, cy - radius - pad)
        x2 = min(w, cx + radius + pad)
        y2 = min(h, cy + radius + pad)

        region = color_mask[y1:y2, x1:x2]
        if region.size == 0:
            return False

        contours, _ = cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return False

        best_circularity = 0.0
        min_area = np.pi * (radius * 0.4) ** 2
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < min_area:
                continue
            perimeter = cv2.arcLength(contour, True)
            if perimeter == 0:
                continue
            circularity = 4 * np.pi * area / (perimeter * perimeter)
            best_circularity = max(best_circularity, circularity)

        return best_circularity >= min_circularity

    def _detect_legend_region(self, img):
        """Detect a legend/key box in the upper-left corner of the image.

        Three-layer fallback strategy:
        1. Border contour detection (fast, works when legend has a clear border)
        2. OCR keyword detection (searches for "scope", "legend", etc.)
        3. Edge-density evidence check (only excludes if the corner is
           significantly denser than average, suggesting a bordered box)

        Returns:
            Tuple (x, y, w, h) of the legend bounding box, or None.
        """
        cache_key = (img.shape[1], img.shape[0], id(img))
        if getattr(self, '_legend_cache', (None, None))[0] == cache_key:
            return self._legend_cache[1]

        box = self._detect_legend_by_contour(img)
        if box:
            logger.info(f"Legend detected via contour: x={box[0]} y={box[1]} w={box[2]} h={box[3]} "
                        f"(image {img.shape[1]}x{img.shape[0]}, "
                        f"covers {box[2]*100/img.shape[1]:.1f}%w x {box[3]*100/img.shape[0]:.1f}%h)")
            self._legend_cache = (cache_key, box)
            return box

        box = self._detect_legend_by_keywords(img)
        if box:
            logger.info(f"Legend detected via keywords: x={box[0]} y={box[1]} w={box[2]} h={box[3]} "
                        f"(image {img.shape[1]}x{img.shape[0]}, "
                        f"covers {box[2]*100/img.shape[1]:.1f}%w x {box[3]*100/img.shape[0]:.1f}%h)")
            self._legend_cache = (cache_key, box)
            return box

        h, w = img.shape[:2]
        corner_w, corner_h = int(w * 0.12), int(h * 0.10)
        if corner_w < 10 or corner_h < 10:
            return None

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        corner_edges = cv2.Canny(gray[0:corner_h, 0:corner_w], 50, 150)
        corner_density = np.sum(corner_edges > 0) / max(corner_edges.size, 1)

        full_edges = cv2.Canny(gray, 50, 150)
        full_density = np.sum(full_edges > 0) / max(full_edges.size, 1)

        if full_density > 0 and corner_density > full_density * 1.5:
            logger.info(f"Legend fallback: edge density {corner_density:.3f} vs avg {full_density:.3f}, "
                        f"excluding {corner_w}x{corner_h}")
            box = (0, 0, corner_w, corner_h)
            self._legend_cache = (cache_key, box)
            return box

        self._legend_cache = (cache_key, None)
        return None

    def _detect_legend_by_contour(self, img):
        """Detect legend region by finding a bordered rectangle in the upper-left."""
        h, w = img.shape[:2]

        search_w = int(w * 0.25)
        search_h = int(h * 0.30)
        region = img[0:search_h, 0:search_w]

        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)

        edges = cv2.Canny(gray, 50, 150)
        kernel = np.ones((3, 3), np.uint8)
        edges = cv2.dilate(edges, kernel, iterations=1)

        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        min_legend_area = search_w * search_h * 0.05
        max_legend_area = w * h * 0.05

        best_box = None
        best_area = 0

        for contour in contours:
            area = cv2.contourArea(contour)
            if area < min_legend_area or area > max_legend_area:
                continue

            peri = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.02 * peri, True)

            if len(approx) >= 4:
                x, y, bw, bh = cv2.boundingRect(contour)
                aspect = bw / bh if bh > 0 else 0
                if bw > w * 0.20 or bh > h * 0.20:
                    continue
                if 0.3 < aspect < 4.0 and area > best_area:
                    best_area = area
                    best_box = (x, y, bw, bh)

        if best_box:
            pad = 10
            bx, by, bw, bh = best_box
            return (max(0, bx - pad), max(0, by - pad), bw + pad * 2, bh + pad * 2)

        return None

    def _detect_legend_by_keywords(self, img):
        """Detect legend region by running OCR on the upper-left and searching
        for keywords like 'scope', 'legend', 'note', 'not under', etc.
        """
        h, w = img.shape[:2]

        search_w = int(w * 0.30)
        search_h = int(h * 0.35)
        region = img[0:search_h, 0:search_w]

        keywords = ['scope', 'legend', 'note', 'not under', 'following signage',
                    'signage not', 'not in our', 'not included']

        try:
            ocr = self._get_ocr_engine()
            for result in ocr.predict(region):
                texts = result.get('rec_texts', [])
                boxes = result.get('dt_polys', [])

                if not texts or not boxes:
                    continue

                min_x, min_y = search_w, search_h
                max_x, max_y = 0, 0
                found = False

                for text, box in zip(texts, boxes):
                    text_lower = text.lower().strip()
                    if any(kw in text_lower for kw in keywords):
                        found = True
                        box_arr = np.array(box)
                        bx_min = int(box_arr[:, 0].min())
                        by_min = int(box_arr[:, 1].min())
                        bx_max = int(box_arr[:, 0].max())
                        by_max = int(box_arr[:, 1].max())
                        min_x = min(min_x, bx_min)
                        min_y = min(min_y, by_min)
                        max_x = max(max_x, bx_max)
                        max_y = max(max_y, by_max)

                if found:
                    pad_x = int(search_w * 0.05)
                    pad_y = int(search_h * 0.15)
                    rx = max(0, min_x - pad_x)
                    ry = max(0, min_y - pad_x)
                    rw = min(search_w, max_x + pad_x) - rx
                    rh = min(search_h, max_y + pad_y) - ry
                    return (rx, ry, rw, rh)

        except Exception:
            pass

        return None
    
    def _detect_right_strip(self, img):
        """Detect a full-height title block strip on the right side of the image.

        Architectural drawings typically have a vertical dividing line separating
        the drawing area from the title block column on the right.  This method
        finds that line using Hough line detection, with a column-projection
        fallback.

        Returns:
            Tuple (x, 0, w-x, h) covering the right strip, or None.
        """
        h, w = img.shape[:2]

        search_ratio = 0.25
        search_x = int(w * (1 - search_ratio))
        region = img[0:h, search_x:w]

        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)

        # --- Strategy 1: HoughLinesP for near-vertical lines ---
        min_line_len = int(h * 0.75)
        lines = cv2.HoughLinesP(
            edges, rho=1, theta=np.pi / 180, threshold=100,
            minLineLength=min_line_len, maxLineGap=int(h * 0.05)
        )

        candidates = []
        if lines is not None:
            for line in lines:
                x1, y1, x2, y2 = line[0]
                dx = abs(x2 - x1)
                dy = abs(y2 - y1)
                if dy == 0:
                    continue
                angle_deg = np.degrees(np.arctan(dx / dy))
                if angle_deg > 5:
                    continue
                line_x = min(x1, x2)
                abs_x = search_x + line_x
                if abs_x < w * 0.75:
                    continue
                candidates.append(line_x)

        if candidates:
            candidates.sort()
            for cand_x in candidates:
                abs_x = max(0, search_x + cand_x - 5)
                strip_ratio = (w - abs_x) / w
                if 0.08 <= strip_ratio <= 0.25:
                    logger.debug(f"Right strip detected via Hough at x={abs_x} ({strip_ratio:.1%} width, image {w}x{h})")
                    return (abs_x, 0, w - abs_x, h)

        # --- Strategy 2: Column edge-density projection ---
        col_sum = np.sum(edges > 0, axis=0).astype(float)
        kernel_size = max(3, int(region.shape[1] * 0.02)) | 1
        col_smooth = np.convolve(col_sum, np.ones(kernel_size) / kernel_size, mode='same')

        if col_smooth.max() > 0:
            threshold = col_smooth.mean() + col_smooth.std() * 1.5
            for cx in range(len(col_smooth)):
                if col_smooth[cx] >= threshold:
                    abs_x = max(0, search_x + cx - 5)
                    strip_ratio = (w - abs_x) / w
                    if abs_x >= w * 0.75 and 0.08 <= strip_ratio <= 0.25:
                        logger.debug(f"Right strip detected via projection at x={abs_x} ({strip_ratio:.1%} width, image {w}x{h})")
                        return (abs_x, 0, w - abs_x, h)

        return None

    def _detect_bottom_strip(self, img):
        """Detect a full-width title block strip at the bottom (portrait PDFs).

        Portrait drawings have a horizontal dividing line separating the drawing
        area from the title block row at the bottom.  This mirrors
        _detect_right_strip but searches for horizontal lines instead.

        Returns:
            Tuple (0, y, w, h-y) covering the bottom strip, or None.
        """
        h, w = img.shape[:2]

        search_ratio = 0.25
        search_y = int(h * (1 - search_ratio))
        region = img[search_y:h, 0:w]

        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)

        # Strategy 1: HoughLinesP for near-horizontal lines spanning most of width
        min_line_len = int(w * 0.75)
        lines = cv2.HoughLinesP(
            edges, rho=1, theta=np.pi / 180, threshold=100,
            minLineLength=min_line_len, maxLineGap=int(w * 0.05)
        )

        candidates = []
        if lines is not None:
            for line in lines:
                seg = line[0] if line.ndim == 2 else line
                if seg.shape[0] != 4:
                    continue
                x1, y1, x2, y2 = seg
                dx = abs(x2 - x1)
                dy = abs(y2 - y1)
                if dx == 0:
                    continue
                angle_deg = np.degrees(np.arctan(dy / dx))
                if angle_deg > 5:
                    continue
                line_y = min(y1, y2)
                abs_y = search_y + line_y
                if abs_y < h * 0.75:
                    continue
                candidates.append(abs_y)

        if candidates:
            candidates.sort()
            for cand_y in candidates:
                abs_y = max(0, cand_y - 5)
                strip_ratio = (h - abs_y) / h
                if 0.08 <= strip_ratio <= 0.25:
                    logger.debug(f"Bottom strip detected via Hough at y={abs_y} "
                                 f"({strip_ratio:.1%} height, image {w}x{h})")
                    return (0, abs_y, w, h - abs_y)

        # Strategy 2: Row edge-density projection
        row_sum = np.sum(edges > 0, axis=1).astype(float)
        kernel_size = max(3, int(region.shape[0] * 0.02)) | 1
        row_smooth = np.convolve(row_sum, np.ones(kernel_size) / kernel_size, mode='same')

        if row_smooth.max() > 0:
            threshold = row_smooth.mean() + row_smooth.std() * 1.5
            for ry in range(len(row_smooth)):
                if row_smooth[ry] >= threshold:
                    abs_y = max(0, search_y + ry - 5)
                    strip_ratio = (h - abs_y) / h
                    if abs_y >= h * 0.75 and 0.08 <= strip_ratio <= 0.25:
                        logger.debug(f"Bottom strip detected via projection at y={abs_y} "
                                     f"({strip_ratio:.1%} height, image {w}x{h})")
                        return (0, abs_y, w, h - abs_y)

        return None

    def _detect_drawing_frame(self, img):
        """Detect the drawing frame borders (top and bottom horizontal lines).

        Architectural drawings have a rectangular frame around the content.
        Shapes outside this frame (in margins/notes areas) should be excluded.

        Returns:
            Tuple (top_y, bottom_y) — the y coordinates of the top and bottom
            frame borders.  Either may be None if not detected.
        """
        h, w = img.shape[:2]
        cache_key = (w, h, id(img))
        if hasattr(self, '_frame_cache') and self._frame_cache[0] == cache_key:
            return self._frame_cache[1]

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)

        min_line_len = int(w * 0.7)
        top_y = None
        bottom_y = None

        # Portrait: frame bottom border is above the title block (~80-90% of height),
        # so search a wider band; landscape: border is near the page edge (bottom 5%).
        bottom_pct = 0.80 if self._is_portrait(img) else 0.95
        bottom_start = int(h * bottom_pct)
        bottom_search = edges[bottom_start:h, :]
        lines = cv2.HoughLinesP(bottom_search, 1, np.pi / 180, 100,
                                minLineLength=min_line_len, maxLineGap=30)
        if lines is not None:
            for line in lines:
                x1, y1, x2, y2 = line[0]
                dx, dy = abs(x2 - x1), abs(y2 - y1)
                if dx == 0:
                    continue
                if np.degrees(np.arctan(dy / dx)) < 3:
                    abs_y = bottom_start + min(y1, y2)
                    if bottom_y is None or abs_y < bottom_y:
                        bottom_y = abs_y

        # Detect top frame border (search top 5% of image)
        top_search = edges[0:int(h * 0.05), :]
        lines = cv2.HoughLinesP(top_search, 1, np.pi / 180, 100,
                                minLineLength=min_line_len, maxLineGap=30)
        if lines is not None:
            for line in lines:
                x1, y1, x2, y2 = line[0]
                dx, dy = abs(x2 - x1), abs(y2 - y1)
                if dx == 0:
                    continue
                if np.degrees(np.arctan(dy / dx)) < 3:
                    abs_y = max(y1, y2)
                    if top_y is None or abs_y > top_y:
                        top_y = abs_y

        if top_y is not None:
            logger.debug(f"Drawing frame top border at y={top_y} ({top_y/h:.1%})")
        if bottom_y is not None:
            logger.debug(f"Drawing frame bottom border at y={bottom_y} ({bottom_y/h:.1%})")

        result = (top_y, bottom_y)
        self._frame_cache = (cache_key, result)
        return result

    def _detect_title_block(self, img):
        """Detect the title block region.

        Landscape: right-side strip or bottom-right corner rectangle.
        Portrait: full-width bottom strip (title block is at the bottom,
        rotated 90 deg relative to the drawing content).

        Returns:
            Tuple (x, y, w, h) in full image coordinates.
        """
        h, w = img.shape[:2]
        cache_key = (w, h, id(img))
        if hasattr(self, '_title_block_cache') and self._title_block_cache[0] == cache_key:
            return self._title_block_cache[1]

        if self._is_portrait(img):
            result = self._detect_bottom_strip(img)
            if result is None:
                fallback_y = int(h * 0.85)
                result = (0, fallback_y, w, h - fallback_y)
                logger.info(f"Title block fallback (portrait): fixed bottom strip at y={fallback_y} "
                            f"(image {w}x{h})")
        else:
            result = self._detect_right_strip(img)
            if result is None:
                result = self._detect_title_block_corner(img)
            if result is None:
                fallback_x = int(w * 0.85)
                result = (fallback_x, 0, w - fallback_x, h)
                logger.info(f"Title block fallback: fixed 20% strip at x={fallback_x} (image {w}x{h})")

        self._title_block_cache = (cache_key, result)
        return result

    def _detect_title_block_corner(self, img):
        """Original title block detection: bottom-right corner rectangle.

        Returns:
            Tuple (x, y, w, h) in full image coordinates, or None.
        """
        h, w = img.shape[:2]

        search_w = int(w * 0.35)
        search_h = int(h * 0.45)
        offset_x = w - search_w
        offset_y = h - search_h
        region = img[offset_y:h, offset_x:w]

        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        kern = np.ones((3, 3), np.uint8)
        edges = cv2.dilate(edges, kern, iterations=1)

        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        min_title_area = search_w * search_h * 0.08
        max_title_area = w * h * 0.15

        best_box = None
        best_area = 0

        for contour in contours:
            area = cv2.contourArea(contour)
            if area < min_title_area or area > max_title_area:
                continue

            peri = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.02 * peri, True)

            if len(approx) >= 4:
                x, y, bw, bh = cv2.boundingRect(contour)
                aspect = bw / bh if bh > 0 else 0
                if 0.5 < aspect < 5.0 and area > best_area:
                    right_edge = x + bw
                    bottom_edge = y + bh
                    margin = 30
                    if right_edge >= search_w - margin and bottom_edge >= search_h - margin:
                        best_area = area
                        best_box = (x, y, bw, bh)

        if best_box:
            pad = 10
            bx, by, bw, bh = best_box
            return (
                max(0, offset_x + bx - pad),
                max(0, offset_y + by - pad),
                bw + pad * 2,
                bh + pad * 2
            )

        return None
    
    def _verify_circle_has_color(self, color_mask, cx, cy, radius, min_ratio=0.5):
        """Verify that a detected circle location actually has colored pixels.
        
        Checks that there are colored pixels along the circle perimeter.
        
        Args:
            color_mask: Binary mask of colored pixels
            cx, cy: Circle center
            radius: Circle radius
            min_ratio: Minimum fraction of perimeter samples that must hit color
            
        Returns:
            True if the circle perimeter has enough colored pixels
        """
        h, w = color_mask.shape
        
        relaxed = min_ratio < 0.5
        num_samples = 24 if relaxed else 16
        colored_count = 0
        pad = 3 if relaxed else 2
        
        for i in range(num_samples):
            angle = 2 * np.pi * i / num_samples
            px = int(cx + radius * np.cos(angle))
            py = int(cy + radius * np.sin(angle))
            
            if 0 <= px < w and 0 <= py < h:
                y1, y2 = max(0, py - pad), min(h, py + pad + 1)
                x1, x2 = max(0, px - pad), min(w, px + pad + 1)
                region = color_mask[y1:y2, x1:x2]
                if np.any(region > 0):
                    colored_count += 1
        
        return colored_count >= num_samples * min_ratio
    
    def _verify_circle_contour(self, color_mask, cx, cy, radius, target_radius):
        """Verify a candidate has a ring of colored pixels at the expected radius
        and a relatively empty interior (to reject text blocks).
        
        Real circle outlines have high ring density but low interior density.
        Red text blocks have high density everywhere.
        
        Args:
            color_mask: Binary mask of colored pixels
            cx, cy: Candidate circle center
            radius: Candidate circle radius
            target_radius: Expected radius from the sample circle
            
        Returns:
            True if the candidate looks like a circle outline, not text
        """
        h, w = color_mask.shape
        thickness = max(3, int(target_radius * 0.08))
        
        y1 = max(0, cy - radius - thickness)
        y2 = min(h, cy + radius + thickness + 1)
        x1 = max(0, cx - radius - thickness)
        x2 = min(w, cx + radius + thickness + 1)
        
        roi = color_mask[y1:y2, x1:x2]
        if roi.size == 0:
            return False
        
        local_cx = cx - x1
        local_cy = cy - y1
        Y, X = np.ogrid[:roi.shape[0], :roi.shape[1]]
        dist = np.sqrt((X - local_cx) ** 2 + (Y - local_cy) ** 2)
        
        ring = (dist >= radius - thickness) & (dist <= radius + thickness)
        ring_pixels = roi[ring]
        if len(ring_pixels) == 0:
            return False
        
        ring_density = np.count_nonzero(ring_pixels) / len(ring_pixels)
        if ring_density < 0.15:
            return False
        
        # A strong ring is enough — OCR will reject non-sign content.
        # Only block extreme interior fill (solid colored blobs with no
        # discernible ring/interior contrast).
        if ring_density < 0.20:
            inner = dist <= radius * 0.6
            inner_pixels = roi[inner]
            if len(inner_pixels) > 0:
                inner_density = np.count_nonzero(inner_pixels) / len(inner_pixels)
                if ring_density > 0 and inner_density / ring_density > 0.95:
                    return False
        
        return True
    
    def _verify_circle_gradient(self, grad_data, cx, cy, radius, raw_color_mask):
        """Reject text false positives for small circles using gradient analysis.
        
        Uses two signals:
        1. Radial gradient alignment: real circle outlines produce gradients
           that point radially (toward/away from center). Text characters
           produce randomly-oriented gradients.
        2. Outer density: text extends beyond the circle boundary while
           real circle markers are isolated.
        
        Only applied for small circles (target_radius <= 20) where the
        ring density check is unreliable due to dilation effects.
        
        Args:
            grad_data: Tuple of (gx, gy, mag) pre-computed Sobel gradients
        """
        gx, gy, mag = grad_data
        h, w = mag.shape
        n_samples = 24

        aligned = 0
        total = 0
        for i in range(n_samples):
            angle = 2 * np.pi * i / n_samples
            for dr in range(-1, 2):
                px = int(cx + (radius + dr) * np.cos(angle))
                py = int(cy + (radius + dr) * np.sin(angle))
                if 0 <= py < h and 0 <= px < w and mag[py, px] > 20:
                    grad_angle = np.arctan2(gy[py, px], gx[py, px])
                    radial_angle = np.arctan2(py - cy, px - cx)
                    diff = abs(grad_angle - radial_angle)
                    diff = min(diff, 2 * np.pi - diff)
                    diff = min(diff, abs(diff - np.pi))
                    total += 1
                    if diff < np.pi / 4:
                        aligned += 1
                    break

        if total == 0:
            return True
        align_score = aligned / total

        thickness = max(2, int(radius * 0.15))
        pad = int(radius * 2)
        y1 = max(0, cy - radius - pad)
        y2 = min(raw_color_mask.shape[0], cy + radius + pad + 1)
        x1 = max(0, cx - radius - pad)
        x2 = min(raw_color_mask.shape[1], cx + radius + pad + 1)
        roi = raw_color_mask[y1:y2, x1:x2]
        if roi.size == 0:
            return True

        local_cx = cx - x1
        local_cy = cy - y1
        Y, X = np.ogrid[:roi.shape[0], :roi.shape[1]]
        dist = np.sqrt((X - local_cx) ** 2 + (Y - local_cy) ** 2)
        outer = (dist > radius + thickness) & (dist <= radius * 2)
        outer_pixels = roi[outer]
        outer_density = (np.count_nonzero(outer_pixels) / len(outer_pixels)
                         if len(outer_pixels) > 0 else 0)

        if align_score < 0.45 and outer_density > 0.10:
            return False
        if align_score <= 0.40 and outer_density > 0.08:
            return False

        return True

    def _get_ocr_engine(self):
        """Reuse the shared PaddleOCR instance from OCRService."""
        if self._ocr_engine is None:
            from app.services.ocr_service import OCRService
            self._ocr_engine = OCRService._get_shared_ocr()
        return self._ocr_engine

    def run_shape_ocr(self, img, shape, should_cancel=None):
        """Run CV-quality OCR on a detected shape (strict sign-code validation)."""
        color_type = shape.get('marker_color')
        prev = getattr(self, '_defer_shape_ocr', False)
        self._defer_shape_ocr = False
        try:
            keep, text, conf = self._verify_shape_content(
                img, shape, color_type=color_type, should_cancel=should_cancel,
            )
            if color_type == 'yellow' and (not keep or not (text or '').strip()):
                keep, text, conf = self._verify_shape_content(
                    img, shape, color_type=None, should_cancel=should_cancel,
                )
            return keep, text, conf
        finally:
            self._defer_shape_ocr = prev

    def _verify_shape_content(self, img, shape, color_type=None, should_cancel=None):
        """Validate a detected shape by running OCR and checking if the text
        matches a sign code pattern.

        In fast mode, skip OCR entirely and keep all geometric candidates.

        Args:
            img: Full BGR image (numpy array)
            shape: Dict with at least 'type', 'x', 'y', 'width', 'height'.
                   Circles also need 'center_x', 'center_y', 'radius'.
            color_type: 'blue' or 'red' — the circle outline color, used to
                        filter out foreign-colored text from the crop.
            should_cancel: Optional callable returning True when job is cancelled.

        Returns:
            Tuple of (keep: bool, text: str, confidence: float)
        """
        raise_if_cancelled(should_cancel)
        if getattr(self, '_defer_shape_ocr', False):
            return (True, '', 0.0)
        is_circle = shape.get('type') == 'circle'

        if is_circle:
            cx = shape['center_x']
            cy = shape['center_y']
            radius = shape['radius']
            cropped_bgr = self._crop_circle_for_ocr(img, cx, cy, radius, color_type=color_type)
        else:
            x, y, w, h = shape['x'], shape['y'], shape['width'], shape['height']
            cropped_bgr = self._crop_rect_for_ocr(img, x, y, w, h)

        if cropped_bgr is None or cropped_bgr.size == 0:
            return (False, '', 0.0)

        try:
            ocr = self._get_ocr_engine()
            import re
            multiplier_only = re.compile(r'^[xX\u00d7*]\s*\d+$')
            for result in ocr.predict(cropped_bgr):
                texts = result.get('rec_texts', [])
                scores = result.get('rec_scores', [])

                filtered_pairs = [
                    (t.strip(), scores[i] if i < len(scores) else 0.0)
                    for i, t in enumerate(texts)
                    if t.strip() and not multiplier_only.match(t.strip())
                ]
                combined = ' '.join(t for t, _ in filtered_pairs)

                if not combined.strip():
                    return (False, '', 0.0)

                cleaned = clean_ocr_text(combined)
                avg_conf = (
                    sum(s for _, s in filtered_pairs) / len(filtered_pairs)
                    if filtered_pairs else 0.0
                )

                if not cleaned:
                    return (False, '', avg_conf)

                keep = is_valid_sign_code(cleaned, strict=True)
                if not keep and not is_circle:
                    # Retry: strip ALL internal spaces (multi-line small rects)
                    no_space = cleaned.replace(' ', '')
                    if no_space and is_valid_sign_code(no_space, strict=True):
                        cleaned = no_space
                        keep = True
                if not keep:
                    logger.debug(
                        f"Shape {shape.get('type')} at ({shape.get('x')},{shape.get('y')}) "
                        f"rejected: OCR='{cleaned}'"
                    )
                return (keep, cleaned, avg_conf)

        except Exception as e:
            logger.warning(f"OCR cross-check failed for shape at ({shape.get('x')},{shape.get('y')}): {e}")
            return (False, '', 0.0)

        return (False, '', 0.0)

    def _crop_circle_for_ocr(self, img, cx, cy, radius, color_type=None):
        """Crop and preprocess a circle region for OCR verification.

        When *color_type* is provided, pixels belonging to the **opposite**
        color are erased (set to white) before OCR so that overlapping
        foreign-colored text does not contaminate the reading.
        """
        h, w = img.shape[:2]
        pad = max(5, int(radius * (0.25 if color_type == 'yellow' else 0.15)))
        x1 = max(0, cx - radius - pad)
        y1 = max(0, cy - radius - pad)
        x2 = min(w, cx + radius + pad)
        y2 = min(h, cy + radius + pad)

        roi = img[y1:y2, x1:x2].copy()
        if roi.size == 0:
            return None

        if color_type and color_type != 'yellow' and len(roi.shape) == 3:
            foreign_types = [ct for ct in ('blue', 'red', 'yellow') if ct != color_type]
            for ft in foreign_types:
                foreign_mask = self._build_color_mask(roi, ft)
                foreign_mask = cv2.dilate(foreign_mask, np.ones((3, 3), np.uint8), iterations=1)
                roi[foreign_mask > 0] = (255, 255, 255)
            # Blue ink is mid-gray in BGR→gray (~107 on LP-BLK1-GF E01) and
            # OCR misses it. Paint blue pixels black before the gray convert.
            if color_type == 'blue':
                blue_ink = self._build_color_mask(roi, 'blue')
                blue_ink = cv2.dilate(blue_ink, np.ones((2, 2), np.uint8), iterations=1)
                roi[blue_ink > 0] = (0, 0, 0)
        elif color_type == 'yellow' and len(roi.shape) == 3:
            yellow_mask = self._build_color_mask(roi, 'yellow')
            yellow_mask = cv2.dilate(yellow_mask, np.ones((3, 3), np.uint8), iterations=1)
            roi[yellow_mask > 0] = (255, 255, 255)
            gray_tmp = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            text_pixels = gray_tmp < 200
            roi[text_pixels] = (0, 0, 0)

        roi_h, roi_w = roi.shape[:2]
        local_cx = cx - x1
        local_cy = cy - y1
        inner_scale = 0.98 if color_type == 'yellow' else 0.92
        inner_r = max(3, int(radius * inner_scale))

        mask = np.zeros((roi_h, roi_w), dtype=np.uint8)
        cv2.circle(mask, (local_cx, local_cy), inner_r, 255, -1)

        if len(roi.shape) == 3:
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        else:
            gray = roi.copy()

        masked = np.full((roi_h, roi_w), 255, dtype=np.uint8)
        masked[mask > 0] = gray[mask > 0]

        min_scale = 4.0 if color_type == 'yellow' else 3.0
        scale = max(min_scale, 120.0 / max(roi_h, 1))
        scaled = cv2.resize(masked, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        return cv2.cvtColor(scaled, cv2.COLOR_GRAY2BGR)

    @staticmethod
    def _crop_rect_for_ocr(img, x, y, w, h):
        """Crop and preprocess a rectangle region for OCR verification."""
        img_h, img_w = img.shape[:2]
        pad = max(2, min(w, h) // 8)
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(img_w, x + w + pad)
        y2 = min(img_h, y + h + pad)

        roi = img[y1:y2, x1:x2]
        if roi.size == 0:
            return None

        roi_h, roi_w = roi.shape[:2]
        scale = max(3.0, 120.0 / max(roi_h, 1))
        scaled = cv2.resize(roi, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

        if len(scaled.shape) == 2:
            scaled = cv2.cvtColor(scaled, cv2.COLOR_GRAY2BGR)
        return scaled

    def _bgr_to_hex(self, b, g, r):
        return f'#{int(r):02x}{int(g):02x}{int(b):02x}'

    def _match_bgr_to_preset(self, b, g, r):
        """Map a sampled BGR pixel to a known marker preset when possible."""
        b, g, r = int(b), int(g), int(r)
        max_c = max(r, g, b)
        min_c = min(r, g, b)
        if max_c - min_c < 30:
            return None
        if r >= max_c * 0.8 and r >= g + 35 and r >= b + 35:
            return 'red'
        if b >= max_c * 0.75 and b >= r + 25 and b >= g + 10:
            return 'blue'
        if g >= max_c * 0.75 and g >= r + 25 and g >= b + 10:
            return 'yellow'
        return None

    def _build_color_mask_from_bgr(self, img_region, b, g, r):
        """Build a binary mask for pixels similar to a sampled BGR color."""
        preset = self._match_bgr_to_preset(b, g, r)
        if preset:
            return self._build_color_mask(img_region, preset)

        hsv = cv2.cvtColor(img_region, cv2.COLOR_BGR2HSV)
        sample_hsv = cv2.cvtColor(
            np.uint8([[[int(b), int(g), int(r)]]]), cv2.COLOR_BGR2HSV
        )[0][0]
        h, s, v = int(sample_hsv[0]), int(sample_hsv[1]), int(sample_hsv[2])

        h_tol = 22
        s_tol = max(50, min(110, int(s * 0.65) if s > 0 else 70))
        v_tol = max(50, min(110, int(v * 0.55) if v > 0 else 70))
        s_min = max(20, s - s_tol)
        v_min = max(25, v - v_tol)

        if h <= 10 or h >= 170:
            lower1 = np.array([0, s_min, v_min])
            upper1 = np.array([min(180, h + h_tol), 255, 255])
            lower2 = np.array([max(0, h - h_tol), s_min, v_min])
            upper2 = np.array([180, 255, 255])
            mask = cv2.bitwise_or(
                cv2.inRange(hsv, lower1, upper1),
                cv2.inRange(hsv, lower2, upper2),
            )
        else:
            lower = np.array([max(0, h - h_tol), s_min, v_min])
            upper = np.array([min(180, h + h_tol), 255, 255])
            mask = cv2.inRange(hsv, lower, upper)

        b_ch, g_ch, r_ch = cv2.split(img_region)
        if b >= max(r, g) + 15:
            ratio_mask = ((b_ch.astype(int) > r_ch + 15) &
                          (b_ch.astype(int) > g_ch + 8)).astype(np.uint8) * 255
            mask = cv2.bitwise_or(mask, ratio_mask)
        elif r >= max(g, b) + 15:
            ratio_mask = ((r_ch.astype(int) > g_ch + 15) &
                          (r_ch.astype(int) > b_ch + 15)).astype(np.uint8) * 255
            mask = cv2.bitwise_or(mask, ratio_mask)

        return mask

    def _build_color_mask(self, img_region, color_type, bgr_sample=None):
        """Build a binary mask for pixels of a given color type."""
        if bgr_sample is not None:
            b, g, r = bgr_sample
            return self._build_color_mask_from_bgr(img_region, b, g, r)
        b, g, r = cv2.split(img_region)
        threshold = 30
        
        if color_type == 'blue':
            hsv = cv2.cvtColor(img_region, cv2.COLOR_BGR2HSV)
            hsv_mask = cv2.inRange(hsv, np.array([90, 50, 35]), np.array([135, 255, 255]))
            template_mask = cv2.inRange(
                hsv,
                self.template_circle_params['lower_blue'],
                self.template_circle_params['upper_blue'],
            )
            ratio_mask = ((b.astype(int) > r.astype(int) + threshold) &
                            (b.astype(int) > g.astype(int) + threshold) &
                            (b > 80)).astype(np.uint8) * 255
            mask = cv2.bitwise_or(
                hsv_mask,
                cv2.bitwise_or(template_mask, ratio_mask),
            )
        elif color_type == 'red':
            hsv = cv2.cvtColor(img_region, cv2.COLOR_BGR2HSV)
            h_ch, s_ch, v_ch = cv2.split(hsv)
            mask_low = cv2.inRange(hsv, np.array([0, 35, 60]), np.array([10, 255, 255]))
            mask_high = cv2.inRange(hsv, np.array([165, 35, 60]), np.array([180, 255, 255]))
            mask = cv2.bitwise_or(mask_low, mask_high)
        elif color_type == 'yellow':
            hsv = cv2.cvtColor(img_region, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, np.array([10, 40, 60]), np.array([50, 255, 255]))
            b, g, r = cv2.split(img_region)
            bright_fill = ((g.astype(int) > 175) & (r.astype(int) > 175) &
                           (b.astype(int) < 100)).astype(np.uint8) * 255
            mask = cv2.bitwise_or(mask, bright_fill)
        else:
            mask = np.zeros(img_region.shape[:2], dtype=np.uint8)
        
        return mask
    
    def _search_ring_on_mask(self, roi, local_cx, local_cy, radius, shift, rad_span, step=1):
        """Grid-search the best (cx, cy, r) ring alignment on a local ROI."""
        best = (local_cx, local_cy, float(radius))
        best_score = -1.0
        for dx in range(-shift, shift + 1, step):
            for dy in range(-shift, shift + 1, step):
                for dr in range(-rad_span, rad_span + 1, step):
                    trial_r = radius + dr
                    if trial_r < 6:
                        continue
                    score = self._score_ring_on_mask(
                        roi, local_cx + dx, local_cy + dy, trial_r)
                    if score > best_score:
                        best_score = score
                        best = (local_cx + dx, local_cy + dy, float(trial_r))
        return best, best_score

    def _refine_circle_from_ring_mask(self, color_mask, cx, cy, radius, is_thin_ring=False):
        """Refine circle center and radius using ring pixels on an undilated mask."""
        h, w = color_mask.shape[:2]
        search_pad = max(int(radius * 1.8), 14)
        y1 = max(0, cy - search_pad)
        y2 = min(h, cy + search_pad)
        x1 = max(0, cx - search_pad)
        x2 = min(w, cx + search_pad)
        roi = color_mask[y1:y2, x1:x2]
        if roi.size == 0:
            return int(cx), int(cy), int(radius)

        local_cx = cx - x1
        local_cy = cy - y1

        if is_thin_ring:
            # Thin blue rings need a wider search, but a full 41×41×15 grid
            # (~25k trials) costs ~1.8s per call. Coarse-to-fine keeps accuracy
            # while cutting blue secondary pass from minutes to seconds.
            best, best_score = self._search_ring_on_mask(
                roi, local_cx, local_cy, radius, shift=10, rad_span=4, step=2)
            rcx, rcy, rr = best
            best, best_score = self._search_ring_on_mask(
                roi, rcx, rcy, rr, shift=2, rad_span=2, step=1)
        else:
            best, best_score = self._search_ring_on_mask(
                roi, local_cx, local_cy, radius, shift=4, rad_span=3, step=1)

        rcx, rcy, rr = best
        if best_score >= (0.22 if is_thin_ring else 0.35):
            return int(round(x1 + rcx)), int(round(y1 + rcy)), max(6, int(round(rr)))

        # Fallback: fit ellipse to ring band on the raw mask
        roi_h, roi_w = roi.shape[:2]
        outer_m = np.zeros((roi_h, roi_w), dtype=np.uint8)
        inner_m = np.zeros((roi_h, roi_w), dtype=np.uint8)
        cv2.circle(outer_m, (local_cx, local_cy), int(radius * 1.15), 255, -1)
        cv2.circle(inner_m, (local_cx, local_cy), int(radius * 0.65), 255, -1)
        ring = cv2.bitwise_and(roi, outer_m)
        ring = cv2.bitwise_and(ring, cv2.bitwise_not(inner_m))
        ring_pts = np.column_stack(np.where(ring > 0))
        if len(ring_pts) >= 5:
            try:
                ell = cv2.fitEllipse(ring_pts[:, ::-1])
                ecx, ecy = ell[0]
                rr = (ell[1][0] + ell[1][1]) / 4.0
                return int(round(x1 + ecx)), int(round(y1 + ecy)), max(6, int(round(rr)))
            except cv2.error:
                pass

        return int(cx), int(cy), int(radius)

    def _score_ring_on_mask(self, mask, cx, cy, radius):
        """Count how many sample points on a ring hit the mask."""
        hits = 0
        total = 24
        pad = 2
        mh, mw = mask.shape[:2]
        for i in range(total):
            angle = 2 * np.pi * i / total
            px = int(cx + radius * np.cos(angle))
            py = int(cy + radius * np.sin(angle))
            if 0 <= px < mw and 0 <= py < mh:
                y0, y1 = max(0, py - pad), min(mh, py + pad + 1)
                x0, x1 = max(0, px - pad), min(mw, px + pad + 1)
                if np.any(mask[y0:y1, x0:x1] > 0):
                    hits += 1
        return hits / total
    
    def _finalize_detected_circles(self, detected, img, legend_bbox):
        """Apply post-filters and sort detected circles."""
        for circle in detected:
            inferred = self._infer_marker_color(img, circle)
            if inferred != circle.get('marker_color'):
                circle['marker_color'] = inferred

        if detected:
            radii = [c.get('radius', 18) for c in detected if c.get('radius')]
            min_dist = int(max(12, np.median(radii) * 0.85)) if radii else 14
            detected = self._remove_duplicate_circles(detected, min_distance=min_dist)

        detected = self._remove_contained_circles(detected)

        if legend_bbox:
            lx, ly, lw, lh = legend_bbox
            detected = [d for d in detected
                        if not (lx <= d['center_x'] <= lx + lw and ly <= d['center_y'] <= ly + lh)]

        title_bbox = self._detect_title_block(img)
        if title_bbox:
            tx, ty, tw, th = title_bbox
            detected = [d for d in detected
                        if not (tx <= d['center_x'] <= tx + tw and ty <= d['center_y'] <= ty + th)]

        frame_top, frame_bottom = self._detect_drawing_frame(img)
        if frame_top is not None or frame_bottom is not None:
            detected = [d for d in detected
                        if (frame_top is None or d['center_y'] > frame_top)
                        and (frame_bottom is None or d['center_y'] < frame_bottom)]

        # Drop non-red detections in the right-hand sheet margin (revision block noise)
        margin_x = int(img.shape[1] * 0.82)
        detected = [d for d in detected
                    if d['center_x'] < margin_x or d.get('marker_color') == 'red']

        detected.sort(key=lambda c: (c['y'], c['x']))
        return detected

    def _find_best_circle_in_mask(self, color_mask, min_area=50, min_radius=5):
        """Find the most circular contour in a binary mask.
        
        Args:
            color_mask: Binary mask (uint8)
            min_area: Minimum contour area
            min_radius: Minimum enclosing circle radius
            
        Returns:
            Tuple of (best_contour, best_circularity, best_radius) or (None, 0, 0)
        """
        contours, _ = cv2.findContours(color_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if not contours:
            return None, 0, 0
        
        best_contour = None
        best_circularity = 0
        best_radius = 0
        
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < min_area:
                continue
            
            perimeter = cv2.arcLength(contour, True)
            if perimeter == 0:
                continue
            
            circularity = 4 * np.pi * area / (perimeter * perimeter)
            (cx, cy), radius = cv2.minEnclosingCircle(contour)
            
            if circularity > best_circularity and radius > min_radius:
                best_circularity = circularity
                best_contour = contour
                # Adjust inward by ~2px to get ring midline instead of outer boundary
                best_radius = max(min_radius, int(radius) - 2)
        
        return best_contour, best_circularity, best_radius
    
    def _analyze_sample_circle(self, img):
        """Analyze the sample circle to extract its properties.

        Landscape: searches the upper-right 15% corner.
        Portrait: searches the bottom-right 15% corner (title block is at the
        bottom in portrait drawings, and the sample circle lives there).
        
        Args:
            img: BGR image
            
        Returns:
            Dict with 'radius', 'bgr_color', 'color_type' or None if not found
        """
        h, w = img.shape[:2]
        ratio = self.template_circle_params['search_region_ratio']
        
        search_w = int(w * ratio)
        search_h = int(h * ratio)

        if self._is_portrait(img):
            search_region = img[h - search_h:h, w - search_w:w]
            offset_x = w - search_w
            offset_y = h - search_h
            logger.debug(f"Sample circle search: portrait bottom-right "
                         f"({offset_x},{offset_y})-({w},{h})")
        else:
            search_region = img[0:search_h, w - search_w:w]
            offset_x = w - search_w
            offset_y = 0
        
        # Try each color in priority order
        candidates = []
        for color_type in self.SUPPORTED_COLORS:
            color_mask = self._build_color_mask(search_region, color_type)
            contour, circularity, radius = self._find_best_circle_in_mask(color_mask)
            
            if contour is not None and circularity >= self.MIN_CIRCULARITY:
                # Reject filled circles (e.g. revision markers A/B/C/D).
                # A real sample circle is an empty ring with a white interior.
                (check_cx, check_cy), check_r = cv2.minEnclosingCircle(contour)
                inner_r = max(3, int(check_r * 0.55))
                cy_i, cx_i = int(round(check_cy)), int(round(check_cx))
                rh, rw = search_region.shape[:2]
                y1 = max(0, cy_i - inner_r)
                y2 = min(rh, cy_i + inner_r + 1)
                x1 = max(0, cx_i - inner_r)
                x2 = min(rw, cx_i + inner_r + 1)
                inner_roi = search_region[y1:y2, x1:x2]
                if inner_roi.size > 0:
                    inner_gray = cv2.cvtColor(inner_roi, cv2.COLOR_BGR2GRAY)
                    dark_ratio = np.count_nonzero(inner_gray < 180) / max(1, inner_gray.size)
                    color_fill = cv2.countNonZero(color_mask[y1:y2, x1:x2]) / max(1, inner_gray.size)
                    if dark_ratio > 0.25 or color_fill > 0.40:
                        logger.debug(
                            f"Sample circle candidate rejected (filled): "
                            f"color={color_type} dark={dark_ratio:.2f} fill={color_fill:.2f}")
                        continue

                candidates.append({
                    'contour': contour,
                    'circularity': circularity,
                    'radius': radius,
                    'color_type': color_type,
                    'color_mask': color_mask,
                })
        
        if not candidates:
            return None
        
        # Sample marker lives in the outer corner of the search region.
        # Prefer that location so a nearby yellow/red sign does not steal
        # the template (seen on LP-BLK1-GF.pdf).
        if self._is_portrait(img):
            corner_local = (search_w, search_h)
        else:
            corner_local = (search_w, 0)
        for cand in candidates:
            (cx_c, cy_c), _ = cv2.minEnclosingCircle(cand['contour'])
            cand['corner_dist'] = float(np.hypot(cx_c - corner_local[0], cy_c - corner_local[1]))
        best = min(candidates, key=lambda c: (c['corner_dist'], -c['circularity']))
        best_contour = best['contour']
        color_mask = best['color_mask']
        
        (cx_local, cy_local), _ = cv2.minEnclosingCircle(best_contour)
        M = cv2.moments(best_contour)
        if M['m00'] > 0:
            cx_local = M['m10'] / M['m00']
            cy_local = M['m01'] / M['m00']
        cx_full = int(round(cx_local)) + offset_x
        cy_full = int(round(cy_local)) + offset_y
        
        # Sample BGR from the colored pixels only (outline), not the filled interior
        # This avoids averaging with white background inside thin-outline circles
        outline_mask = np.zeros(color_mask.shape, dtype=np.uint8)
        cv2.drawContours(outline_mask, [best_contour], -1, 255, 3)
        combined_mask = cv2.bitwise_and(outline_mask, color_mask)
        
        colored_pixels = search_region[combined_mask > 0]
        if len(colored_pixels) == 0:
            # Fallback: use all color mask pixels from the contour area
            filled_mask = np.zeros(color_mask.shape, dtype=np.uint8)
            cv2.drawContours(filled_mask, [best_contour], -1, 255, -1)
            combined_mask = cv2.bitwise_and(filled_mask, color_mask)
            colored_pixels = search_region[combined_mask > 0]
        
        if len(colored_pixels) == 0:
            return None
        
        avg_bgr = np.mean(colored_pixels, axis=0).astype(int)
        
        return {
            'radius': best['radius'],
            'bgr_color': avg_bgr,
            'circularity': best['circularity'],
            'color_type': best['color_type'],
            'location': (cx_full, cy_full),
        }
    
    def has_sample_circle(self, image_path, img=None):
        """Check if the image has a sample circle (upper-right for landscape,
        bottom-right for portrait).
        """
        img, _ = self.load_image(image_path, img=img)
        sample_info = self._analyze_sample_circle(img)
        return sample_info is not None
    
    def _remove_duplicate_circles(self, circles, min_distance=20):
        """Remove duplicate circle detections that are too close together.
        
        Uses both center distance and overlap checks to eliminate redundant
        detections (e.g., phantom circles formed at intersection of two outlines).
        
        Args:
            circles: List of detected circles
            min_distance: Minimum distance between circle centers
            
        Returns:
            Filtered list of circles
        """
        if not circles:
            return circles
        
        circles = sorted(circles, key=lambda c: c.get('confidence', 0), reverse=True)
        
        kept = []
        for circle in circles:
            is_duplicate = False
            cr = circle.get('radius', 0)
            for kept_circle in kept:
                kr = kept_circle.get('radius', 0)
                dist = np.sqrt(
                    (circle['center_x'] - kept_circle['center_x']) ** 2 +
                    (circle['center_y'] - kept_circle['center_y']) ** 2
                )
                if dist < min_distance:
                    is_duplicate = True
                    break
                if dist < (cr + kr) * 0.7:
                    is_duplicate = True
                    break
                if dist + min(cr, kr) < max(cr, kr) * 0.9:
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                kept.append(circle)
        
        return kept

    def _remove_contained_circles(self, circles):
        """Remove circles that are fully contained within a larger circle.

        Uses two strategies:
        1. OCR text comparison: if the smaller circle's text is a substring of
           the larger circle's text (or identical), and its center is inside the
           larger circle, remove the smaller one.
        2. Geometric containment: if the smaller circle is mostly inside the
           larger one (dist + small_r < large_r * 0.85), remove it.
        """
        if len(circles) < 2:
            return circles

        circles = sorted(circles, key=lambda c: c.get('radius', 0), reverse=True)
        kept = []

        for circle in circles:
            cr = circle.get('radius', 0)
            c_text = circle.get('extracted_text', '').strip()
            is_contained = False

            for larger in kept:
                if circle.get('marker_color') != larger.get('marker_color'):
                    continue
                lr = larger.get('radius', 0)
                if lr <= cr * 1.2:
                    continue
                dist = np.sqrt(
                    (circle['center_x'] - larger['center_x']) ** 2 +
                    (circle['center_y'] - larger['center_y']) ** 2
                )

                l_text = larger.get('extracted_text', '').strip()
                text_is_subset = (
                    c_text and l_text and
                    (c_text in l_text or l_text in c_text or c_text == l_text)
                )

                if text_is_subset and dist < lr:
                    is_contained = True
                    break
                elif dist + cr < lr * 0.85:
                    is_contained = True
                    break

            if not is_contained:
                kept.append(circle)

        return kept

    def _extract_template_fallback(self, img):
        """Fallback template extraction: scan the entire top row of the image.
        
        Args:
            img: BGR image (numpy array)
            
        Returns:
            Tuple of (template_image, template_center, template_radius) or (None, None, None) if not found
        """
        h, w = img.shape[:2]
        
        search_h = int(h * 0.2)
        search_region = img[0:search_h, :]
        
        best_contour = None
        best_circularity = 0
        
        for color_type in self.SUPPORTED_COLORS:
            color_mask = self._build_color_mask(search_region, color_type)
            contours, _ = cv2.findContours(color_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            for contour in contours:
                area = cv2.contourArea(contour)
                if area < 100:
                    continue
                
                perimeter = cv2.arcLength(contour, True)
                if perimeter == 0:
                    continue
                
                circularity = 4 * np.pi * area / (perimeter * perimeter)
                
                if circularity > best_circularity and circularity >= self.template_circle_params['min_circularity']:
                    best_circularity = circularity
                    best_contour = contour
        
        if best_contour is None:
            return None, None, None
        
        (cx, cy), radius = cv2.minEnclosingCircle(best_contour)
        cx, cy, radius = int(cx), int(cy), int(radius)
        
        padding = self.template_circle_params['template_padding']
        x1 = max(0, cx - radius - padding)
        y1 = max(0, cy - radius - padding)
        x2 = min(search_region.shape[1], cx + radius + padding)
        y2 = min(search_region.shape[0], cy + radius + padding)
        
        template = search_region[y1:y2, x1:x2].copy()
        template_center = (cx - x1, cy - y1)
        
        return template, template_center, radius
    
    def detect_rectangles(self, image_path, params=None):
        """Detect rectangles in an image.
        
        Args:
            image_path: Path to the image file
            params: Optional dictionary of detection parameters
            
        Returns:
            List of detected rectangles with bounding box info
        """
        if params:
            self.rect_params.update(params)
        
        img, gray = self.load_image(image_path)
        
        # Apply edge detection
        edges = cv2.Canny(gray, 50, 150)
        
        # Dilate to close gaps
        kernel = np.ones((3, 3), np.uint8)
        dilated = cv2.dilate(edges, kernel, iterations=1)
        
        # Find contours
        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        detected = []
        
        for contour in contours:
            # Calculate area
            area = cv2.contourArea(contour)
            
            if area < self.rect_params['min_area'] or area > self.rect_params['max_area']:
                continue
            
            # Approximate the contour
            peri = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, self.rect_params['approx_epsilon'] * peri, True)
            
            # Check if it's a rectangle (4 vertices)
            if len(approx) == 4:
                x, y, w, h = cv2.boundingRect(approx)
                
                # Check aspect ratio
                aspect_ratio = float(w) / h if h > 0 else 0
                if (aspect_ratio < self.rect_params['min_aspect_ratio'] or 
                    aspect_ratio > self.rect_params['max_aspect_ratio']):
                    continue
                
                detected.append({
                    'type': 'rectangle',
                    'x': int(x),
                    'y': int(y),
                    'width': int(w),
                    'height': int(h)
                })
        
        # Sort by position (top-left to bottom-right)
        detected.sort(key=lambda r: (r['y'], r['x']))
        
        return detected
    
    def detect_red_rectangles(self, image_path, params=None, img=None):
        """Detect rectangles with red borders and white backgrounds.
        
        Two-pass approach:
        1. Find rectangles via edge detection on grayscale
        2. Find rectangles via contours in the red mask
        Then filter both for red border + white interior.
        
        Args:
            image_path: Path to the image file
            params: Optional dictionary of detection parameters
            
        Returns:
            List of detected rectangles with bounding box info
        """
        if params:
            params = dict(params)
            should_cancel = self._pop_should_cancel(params)
            self.red_rect_params.update(params)
        else:
            should_cancel = None
        
        img, gray = self.load_image(image_path, img=img)
        
        # Convert to HSV for red detection
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        
        # Create mask for red color
        lower_red1 = np.array([0, 50, 50])
        upper_red1 = np.array([10, 255, 255])
        lower_red2 = np.array([170, 50, 50])
        upper_red2 = np.array([180, 255, 255])
        
        mask1 = cv2.inRange(hsv, lower_red1, upper_red1)
        mask2 = cv2.inRange(hsv, lower_red2, upper_red2)
        red_mask = cv2.bitwise_or(mask1, mask2)
        
        detected = []
        seen_rects = set()
        
        # PASS 1: Edge detection on grayscale image
        edges = cv2.Canny(gray, 50, 150)
        kernel = np.ones((2, 2), np.uint8)
        edges = cv2.dilate(edges, kernel, iterations=1)
        
        contours1, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        
        # PASS 2: Find enclosed regions in dilated red mask
        red_dilated = cv2.dilate(red_mask, np.ones((3, 3), np.uint8), iterations=2)
        # Flood fill from corners
        red_filled = red_dilated.copy()
        h_img, w_img = red_filled.shape
        flood_mask = np.zeros((h_img + 2, w_img + 2), np.uint8)
        cv2.floodFill(red_filled, flood_mask, (0, 0), 255)
        # Invert to get enclosed regions
        enclosed = cv2.bitwise_not(red_filled)
        contours2, _ = cv2.findContours(enclosed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # PASS 3: Find thin red borders with minimal processing
        # Only close small gaps within individual borders, don't connect separate labels
        kernel_tiny = np.ones((2, 2), np.uint8)
        red_connected = cv2.morphologyEx(red_mask, cv2.MORPH_CLOSE, kernel_tiny, iterations=1)
        
        # Find contours of the connected red borders
        contours_red3, _ = cv2.findContours(red_connected, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        
        contours3 = []
        for contour in contours_red3:
            peri = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.03 * peri, True)
            
            # Accept 4-12 vertices (rectangles with noise from thin borders)
            if len(approx) >= 4 and len(approx) <= 12:
                x, y, w, h = cv2.boundingRect(approx)
                area = cv2.contourArea(approx)
                bounding_area = w * h
                
                # Label size filter
                if w >= 20 and w <= 280 and h >= 14 and h <= 100 and bounding_area >= 400:
                    if bounding_area > 0 and area > 0:
                        rect_ratio = area / bounding_area
                        if rect_ratio >= 0.15:  # Very low threshold for thin border contours
                            rect_contour = np.array([
                                [[x, y]], [[x+w, y]], [[x+w, y+h]], [[x, y+h]]
                            ], dtype=np.int32)
                            contours3.append(rect_contour)
        
        # PASS 4: White-region detection for signs on coloured backgrounds.
        # On tinted floor-plan zones the edge / red-mask passes often produce
        # contours whose bounding boxes are too small or irregularly shaped.
        # Here we look for small white rectangular blobs (the sign interior),
        # expand them slightly to include the red border, and add synthetic
        # rectangle contours so they enter the shared validation pipeline.
        white_mask = cv2.inRange(hsv, np.array([0, 0, 195]), np.array([180, 55, 255]))
        white_mask = cv2.morphologyEx(white_mask, cv2.MORPH_OPEN,
                                      np.ones((2, 2), np.uint8))
        white_contours, _ = cv2.findContours(white_mask, cv2.RETR_EXTERNAL,
                                             cv2.CHAIN_APPROX_SIMPLE)
        contours4 = []
        for wc in white_contours:
            wx, wy, ww, wh = cv2.boundingRect(wc)
            warea = ww * wh
            if warea < 250 or warea > 6000:
                continue
            if ww < 15 or ww > 120 or wh < 10 or wh > 70:
                continue
            w_aspect = ww / wh if wh > 0 else 0
            if w_aspect < 0.6 or w_aspect > 5.0:
                continue
            # Expand bounding box by 3px to include the red border
            ex, ey = max(0, wx - 3), max(0, wy - 3)
            ew = min(w_img, wx + ww + 3) - ex
            eh = min(h_img, wy + wh + 3) - ey
            rect_contour = np.array([
                [[ex, ey]], [[ex + ew, ey]],
                [[ex + ew, ey + eh]], [[ex, ey + eh]]
            ], dtype=np.int32)
            contours4.append(rect_contour)

        # Process all sets of contours
        all_contours = list(contours1) + list(contours2) + list(contours3) + list(contours4)
        
        for contour_idx, contour in enumerate(all_contours):
            raise_if_cancelled(should_cancel, contour_idx, every=1)
            # Get bounding rectangle
            x, y, w, h = cv2.boundingRect(contour)
            bounding_area = w * h
            
            # Size filters
            if bounding_area < self.red_rect_params['min_area'] or bounding_area > self.red_rect_params['max_area']:
                continue
            if w < self.red_rect_params['min_width'] or w > self.red_rect_params['max_width']:
                continue
            if h < self.red_rect_params['min_height'] or h > self.red_rect_params['max_height']:
                continue
            
            # Aspect ratio check
            aspect_ratio = float(w) / h if h > 0 else 0
            if aspect_ratio < self.red_rect_params['min_aspect_ratio'] or aspect_ratio > self.red_rect_params['max_aspect_ratio']:
                continue
            
            # Check if it approximates to a 4-sided polygon
            peri = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.04 * peri, True)
            
            # Accept 4-6 vertices (some tolerance for imperfect rectangles)
            if len(approx) < 4 or len(approx) > 6:
                continue
            
            # Rectangularity check
            contour_area = cv2.contourArea(contour)
            if bounding_area > 0 and contour_area > 0:
                rectangularity = contour_area / bounding_area
                if rectangularity < 0.6:  # At least 60% fill
                    continue
            
            # Duplicate check (finer grid to avoid merging small nearby labels)
            rect_key = (x // 15, y // 15)
            if rect_key in seen_rects:
                continue
            
            # KEY FILTER: must have red border on all 4 sides AND valid interior
            has_red = self._has_complete_red_border(red_mask, x, y, w, h)
            has_white = self._has_white_interior(gray, x, y, w, h, bgr_image=img)
            
            if has_red and has_white:
                candidate = {
                    'type': 'rectangle',
                    'x': int(x),
                    'y': int(y),
                    'width': int(w),
                    'height': int(h),
                }

                keep, text, conf = self._verify_shape_content(
                    img, candidate, should_cancel=should_cancel)
                if not keep:
                    continue

                if text:
                    candidate['extracted_text'] = text
                    candidate['ocr_confidence'] = conf

                seen_rects.add(rect_key)
                detected.append(candidate)
        
        # Sort by position (top-left to bottom-right)
        detected.sort(key=lambda r: (r['y'], r['x']))
        
        # Post-process: remove overlapping/close duplicates
        detected = self._remove_duplicate_boxes(detected)
        
        # Exclude rectangles inside the title block region
        title_bbox = self._detect_title_block(img)
        if title_bbox:
            tx, ty, tw, th = title_bbox
            detected = [d for d in detected
                        if not (tx <= d['x'] + d['width'] // 2 <= tx + tw
                                and ty <= d['y'] + d['height'] // 2 <= ty + th)]

        # Exclude rectangles outside the drawing frame
        frame_top, frame_bottom = self._detect_drawing_frame(img)
        if frame_top is not None or frame_bottom is not None:
            detected = [d for d in detected
                        if (frame_top is None or d['y'] + d['height'] // 2 > frame_top)
                        and (frame_bottom is None or d['y'] + d['height'] // 2 < frame_bottom)]

        return detected
    
    def _remove_duplicate_boxes(self, boxes, threshold=20):
        """Remove boxes that overlap or are very close to each other.
        
        Keeps the first box encountered when duplicates are found.
        
        Args:
            boxes: List of detected boxes
            threshold: Distance threshold in pixels
            
        Returns:
            Filtered list with duplicates removed
        """
        if not boxes:
            return boxes
        
        filtered = []
        for box in boxes:
            is_duplicate = False
            for kept in filtered:
                # Check if centers are close
                cx1 = box['x'] + box['width'] / 2
                cy1 = box['y'] + box['height'] / 2
                cx2 = kept['x'] + kept['width'] / 2
                cy2 = kept['y'] + kept['height'] / 2
                
                dist = ((cx1 - cx2) ** 2 + (cy1 - cy2) ** 2) ** 0.5
                if dist < threshold:
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                filtered.append(box)
        
        return filtered
    
    def _has_right_angles(self, approx):
        """Check if a 4-point polygon has approximately 90-degree corners.
        
        Args:
            approx: Approximated contour with 4 points
            
        Returns:
            True if all corners are close to 90 degrees
        """
        if len(approx) != 4:
            return False
        
        # Get the 4 corner points
        pts = approx.reshape(4, 2)
        
        # Check each angle
        for i in range(4):
            p1 = pts[i]
            p2 = pts[(i + 1) % 4]
            p3 = pts[(i + 2) % 4]
            
            # Vectors from p2 to p1 and p2 to p3
            v1 = p1 - p2
            v2 = p3 - p2
            
            # Calculate angle using dot product
            dot = np.dot(v1, v2)
            mag1 = np.linalg.norm(v1)
            mag2 = np.linalg.norm(v2)
            
            if mag1 == 0 or mag2 == 0:
                return False
            
            cos_angle = dot / (mag1 * mag2)
            cos_angle = np.clip(cos_angle, -1, 1)  # Handle floating point errors
            angle = np.degrees(np.arccos(cos_angle))
            
            # Allow 20 degree tolerance from 90 degrees
            if abs(angle - 90) > 20:
                return False
        
        return True
    
    def _has_red_border(self, red_mask, x, y, w, h, border_width=3):
        """Check if the rectangle has red pixels around its border.
        
        Args:
            red_mask: Binary mask of red pixels
            x, y, w, h: Rectangle bounding box
            border_width: Width of border to check
            
        Returns:
            True if there are significant red pixels around the border
        """
        # Check top edge
        top_edge = red_mask[max(0, y-border_width):y+border_width, x:x+w]
        # Check bottom edge
        bottom_edge = red_mask[y+h-border_width:min(red_mask.shape[0], y+h+border_width), x:x+w]
        # Check left edge
        left_edge = red_mask[y:y+h, max(0, x-border_width):x+border_width]
        # Check right edge
        right_edge = red_mask[y:y+h, x+w-border_width:min(red_mask.shape[1], x+w+border_width)]
        
        # Count red pixels in each edge
        total_red = 0
        total_pixels = 0
        
        for edge in [top_edge, bottom_edge, left_edge, right_edge]:
            if edge.size > 0:
                total_red += np.sum(edge > 0)
                total_pixels += edge.size
        
        # At least 20% of border pixels should be red
        if total_pixels > 0:
            return (total_red / total_pixels) > 0.15
        return False
    
    def _has_complete_red_border(self, red_mask, x, y, w, h, border_width=4):
        """Check if the rectangle has red pixels on ALL four sides.
        
        Strictly requires red on all 4 edges of the rectangle.
        
        Args:
            red_mask: Binary mask of red pixels
            x, y, w, h: Rectangle bounding box
            border_width: Width of border to check
            
        Returns:
            True if all four sides have significant red pixels
        """
        min_coverage = 0.05  # At least 5% of each edge strip should have red
        
        # Check top edge (horizontal strip along top)
        top_y1 = max(0, y - border_width)
        top_y2 = min(red_mask.shape[0], y + border_width)
        top_edge = red_mask[top_y1:top_y2, x:x+w]
        
        # Check bottom edge (horizontal strip along bottom)
        bot_y1 = max(0, y + h - border_width)
        bot_y2 = min(red_mask.shape[0], y + h + border_width)
        bottom_edge = red_mask[bot_y1:bot_y2, x:x+w]
        
        # Check left edge (vertical strip along left)
        left_x1 = max(0, x - border_width)
        left_x2 = min(red_mask.shape[1], x + border_width)
        left_edge = red_mask[y:y+h, left_x1:left_x2]
        
        # Check right edge (vertical strip along right)
        right_x1 = max(0, x + w - border_width)
        right_x2 = min(red_mask.shape[1], x + w + border_width)
        right_edge = red_mask[y:y+h, right_x1:right_x2]
        
        # Count edges with red pixels
        edges = [('top', top_edge), ('bottom', bottom_edge), 
                 ('left', left_edge), ('right', right_edge)]
        edges_with_red = 0
        
        for name, edge in edges:
            if edge.size > 0:
                coverage = np.sum(edge > 0) / edge.size
                if coverage >= min_coverage:
                    edges_with_red += 1
        
        # Require at least 2 out of 4 edges to have red (tolerance for bounding box misalignment)
        return edges_with_red >= 2
    
    def _has_white_interior(self, gray_image, x, y, w, h, bgr_image=None):
        """Check if the interior of a rectangle has a valid background.

        Accepts either a mostly-white interior (original check) or a
        uniformly-coloured interior (e.g. orange/yellow filled signs).

        Args:
            gray_image: Grayscale image
            x, y, w, h: Rectangle bounding box
            bgr_image: Optional BGR image for colour-fill check

        Returns:
            True if the interior looks like a sign background
        """
        # Shrink the region slightly to avoid the border
        margin = max(2, min(w, h) // 10)
        x1 = x + margin
        y1 = y + margin
        x2 = x + w - margin
        y2 = y + h - margin
        
        # Make sure we have a valid region
        if x2 <= x1 or y2 <= y1:
            return True  # Too small to check, assume valid
        
        # Clip to image bounds
        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = min(gray_image.shape[1], x2)
        y2 = min(gray_image.shape[0], y2)
        
        # Extract interior region
        interior = gray_image[y1:y2, x1:x2]
        
        if interior.size == 0:
            return True  # Empty region, assume valid
        
        # --- Path 1: mostly white (original logic) ---
        white_pixels = np.sum(interior > self.red_rect_params['white_threshold'])
        total_pixels = interior.size
        white_ratio = white_pixels / total_pixels
        
        area = w * h
        if area < 1500:
            min_white = 0.40
        else:
            min_white = self.red_rect_params['white_ratio_min']
        max_white = 0.92
        
        if min_white <= white_ratio <= max_white:
            return True

        # --- Path 2: uniformly coloured interior (orange / yellow fills) ---
        if bgr_image is not None:
            roi_bgr = bgr_image[y1:y2, x1:x2]
            if roi_bgr.size > 0:
                roi_hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
                sat = roi_hsv[:, :, 1]
                val = roi_hsv[:, :, 2]
                # "Bright & colourful" pixels: S > 40 and V > 120
                bright_colored = (sat > 40) & (val > 120)
                bright_ratio = np.count_nonzero(bright_colored) / max(1, total_pixels)
                # Accept if ≥ 35 % of interior is bright & colourful
                # (catches orange / yellow fills while rejecting dark areas)
                if bright_ratio >= 0.35:
                    return True

        return False
    
    def detect_all_shapes(self, image_path):
        """Detect both circles and rectangles in an image.
        
        Args:
            image_path: Path to the image file
            
        Returns:
            Dictionary with 'circles' and 'rectangles' lists
        """
        circles = self.detect_circles(image_path)
        rectangles = self.detect_rectangles(image_path)
        
        return {
            'circles': circles,
            'rectangles': rectangles
        }
    
    def get_shape_region(self, image_path, x, y, width, height, padding=5):
        """Extract a region from an image.
        
        Args:
            image_path: Path to the image file
            x, y, width, height: Region coordinates
            padding: Extra padding around the region
            
        Returns:
            Extracted region as numpy array
        """
        img, _ = self.load_image(image_path)
        
        # Apply padding
        x1 = max(0, x - padding)
        y1 = max(0, y - padding)
        x2 = min(img.shape[1], x + width + padding)
        y2 = min(img.shape[0], y + height + padding)
        
        return img[y1:y2, x1:x2]
    
    def draw_shapes_on_image(self, image_path, shapes, output_path):
        """Draw detected shapes on an image and save.
        
        Args:
            image_path: Path to the input image
            shapes: List of shape dictionaries
            output_path: Path for the output image
            
        Returns:
            Path to the output image
        """
        img, _ = self.load_image(image_path)
        
        for shape in shapes:
            color = (0, 255, 0)  # Green
            thickness = 2
            
            if shape.get('type') == 'circle' or 'radius' in shape:
                center = (shape.get('center_x', shape['x'] + shape['width'] // 2),
                         shape.get('center_y', shape['y'] + shape['height'] // 2))
                radius = shape.get('radius', shape['width'] // 2)
                cv2.circle(img, center, radius, color, thickness)
            else:
                x, y, w, h = shape['x'], shape['y'], shape['width'], shape['height']
                cv2.rectangle(img, (x, y), (x + w, y + h), color, thickness)
        
        cv2.imwrite(output_path, img)
        return output_path
    
    def crop_image(self, image_path, regions, output_dir):
        """Crop an image into multiple regions and save each as a separate file.
        
        Args:
            image_path: Path to the source image file
            regions: List of crop region dictionaries with x, y, width, height, and optional name
            output_dir: Directory to save cropped images
            
        Returns:
            List of dictionaries with cropped image info: {path, name, x, y, width, height}
        """
        img, _ = self.load_image(image_path)
        img_height, img_width = img.shape[:2]
        
        cropped_images = []
        
        for idx, region in enumerate(regions):
            # Get region coordinates with bounds checking
            x = max(0, int(region['x']))
            y = max(0, int(region['y']))
            width = int(region['width'])
            height = int(region['height'])
            
            # Ensure we don't go out of bounds
            x2 = min(img_width, x + width)
            y2 = min(img_height, y + height)
            
            # Skip invalid regions
            if x2 <= x or y2 <= y:
                continue
            
            # Crop the region
            cropped = img[y:y2, x:x2]
            
            # Generate output filename
            region_name = region.get('name', f'crop_{idx + 1}')
            # Sanitize the name for use as a filename
            safe_name = "".join(c for c in region_name if c.isalnum() or c in (' ', '-', '_')).strip()
            safe_name = safe_name.replace(' ', '_')
            if not safe_name:
                safe_name = f'crop_{idx + 1}'
            
            output_filename = f"{safe_name}.png"
            output_path = os.path.join(output_dir, output_filename)
            
            # Handle duplicate filenames
            counter = 1
            while os.path.exists(output_path):
                output_filename = f"{safe_name}_{counter}.png"
                output_path = os.path.join(output_dir, output_filename)
                counter += 1
            
            # Save the cropped image
            cv2.imwrite(output_path, cropped)
            
            cropped_images.append({
                'path': output_path,
                'name': region_name,
                'x': x,
                'y': y,
                'width': x2 - x,
                'height': y2 - y
            })
        
        return cropped_images
    
    def get_image_dimensions(self, image_path):
        """Get the dimensions of an image.
        
        Args:
            image_path: Path to the image file
            
        Returns:
            Tuple of (width, height)
        """
        img, _ = self.load_image(image_path)
        height, width = img.shape[:2]
        return width, height

    def extract_color_profile(self, image):
        """Extract a compact HSV color profile from an image region.

        Returns a dict with dominant hue/sat ranges suitable for
        pre-filtering templates against target images.
        """
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        h, s, v = cv2.split(hsv)

        h_hist = cv2.calcHist([h], [0], None, [180], [0, 180]).flatten()
        s_hist = cv2.calcHist([s], [0], None, [256], [0, 256]).flatten()

        dominant_hue = int(np.argmax(h_hist))
        dominant_sat = int(np.argmax(s_hist))

        h_nonzero = np.where(h_hist > h_hist.max() * 0.1)[0]
        s_nonzero = np.where(s_hist > s_hist.max() * 0.1)[0]

        return {
            'dominant_hue': dominant_hue,
            'dominant_sat': dominant_sat,
            'hue_range': [int(h_nonzero.min()), int(h_nonzero.max())] if len(h_nonzero) else [0, 180],
            'sat_range': [int(s_nonzero.min()), int(s_nonzero.max())] if len(s_nonzero) else [0, 256],
        }

    def _get_learned_scales(self):
        """Build a scale set that always includes 1.0 and clusters steps nearby.

        Covers 0.65x–2.0x which handles DPI ratios up to ~3:1.
        Extreme scales (0.5, 2.5) removed as they almost never produce
        useful matches; 2.0 kept for cross-DPI template reuse.
        """
        near = [0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15, 1.2]
        wide = [0.65, 0.8, 1.4, 1.7, 2.0]
        return sorted(set(near + wide))

    def _multi_scale_match_on_prepared(self, img_prepared, tmpl_prepared,
                                        scales, threshold, max_per_scale=50):
        """Run matchTemplate at multiple scales on already-prepared images.

        Both img_prepared and tmpl_prepared must be single-channel uint8.
        Keeps only the top max_per_scale matches per scale to bound runtime.
        Returns list of (x, y, w, h, score, scale) tuples.
        """
        matches = []
        tmpl_h, tmpl_w = tmpl_prepared.shape[:2]

        for scale in scales:
            new_w = int(tmpl_w * scale)
            new_h = int(tmpl_h * scale)
            if new_w < 10 or new_h < 10:
                continue
            if new_w > img_prepared.shape[1] or new_h > img_prepared.shape[0]:
                continue

            scaled = cv2.resize(tmpl_prepared, (new_w, new_h), interpolation=cv2.INTER_AREA)
            result = cv2.matchTemplate(img_prepared, scaled, cv2.TM_CCOEFF_NORMED)
            locations = np.where(result >= threshold)

            scale_matches = []
            for pt in zip(*locations[::-1]):
                x, y = pt
                score = result[y, x]
                scale_matches.append((x, y, new_w, new_h, float(score), scale))

            if len(scale_matches) > max_per_scale:
                scale_matches.sort(key=lambda m: m[4], reverse=True)
                scale_matches = scale_matches[:max_per_scale]

            matches.extend(scale_matches)

        return matches

    def _build_hsv_color_mask(self, bgr_image, color_profile):
        """Build a binary mask isolating the dominant color from a color profile."""
        if not color_profile or color_profile.get('dominant_sat', 0) < 50:
            return None

        hsv = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2HSV)
        hue_range = color_profile.get('hue_range', [0, 180])
        sat_range = color_profile.get('sat_range', [0, 256])

        h_lo = max(0, hue_range[0] - 10)
        h_hi = min(180, hue_range[1] + 10)
        s_lo = max(30, sat_range[0] - 20)
        s_hi = min(255, sat_range[1] + 20)

        if h_lo > h_hi:
            mask1 = cv2.inRange(hsv, np.array([0, s_lo, 50]), np.array([h_hi, s_hi, 255]))
            mask2 = cv2.inRange(hsv, np.array([h_lo, s_lo, 50]), np.array([180, s_hi, 255]))
            return cv2.bitwise_or(mask1, mask2)

        return cv2.inRange(hsv, np.array([h_lo, s_lo, 50]), np.array([h_hi, s_hi, 255]))

    def detect_from_learned_templates(self, image_path, templates, shape_type=None, img=None,
                                    should_cancel=None):
        """Run learned templates against an image using multiple matching strategies.

        Strategies:
          1. Raw grayscale matching — best for same-DPI / same-floorplan
          2. Dilated edge matching — tolerant to minor shifts, cross-DPI
          3. Color-mask matching — for shapes with distinctive color borders

        Candidates are filtered against the legend's color rules so only
        shapes matching the floorplan's color scheme are kept.

        Args:
            image_path: Path to the floorplan image
            templates: List of dicts from shape_templates collection
            shape_type: Optional filter — only use templates of this type
            img: Optional pre-loaded BGR image (avoids redundant imread)

        Returns:
            List of shape dicts in the standard detection output format.
        """
        if not templates:
            return []

        if img is None:
            img, gray = self.load_image(image_path, img=img)
            if img is None:
                logger.error(f"Could not load image: {image_path}")
                return []

        img_h, img_w = img.shape[:2]
        scales = self._get_learned_scales()

        img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        img_edges = cv2.Canny(img_gray, 50, 150)
        kernel = np.ones((3, 3), np.uint8)
        img_edges_dilated = cv2.dilate(img_edges, kernel, iterations=1)
        img_edges_smooth = cv2.GaussianBlur(img_edges_dilated, (3, 3), 0)

        all_matches = []

        import time as _time

        # --- Template fingerprint deduplication ---
        # Group templates that are visually similar AND have similar
        # physical size AND similar color. This avoids running nearly
        # identical templates while preserving templates that differ
        # in size or color (which match different shapes).
        THUMB_SIZE = 32
        DEDUP_THRESHOLD = 0.92
        SIZE_TOLERANCE = 0.30     # max 30% size difference
        HUE_TOLERANCE = 25        # max hue difference (0-180 scale)

        loadable = []
        for tmpl_info in templates:
            if shape_type and tmpl_info.get('shape_type') != shape_type:
                continue
            tmpl_path = tmpl_info.get('image_path', '')
            if not os.path.exists(tmpl_path):
                logger.warning(f"Template image not found: {tmpl_path}")
                continue
            t_img = cv2.imread(tmpl_path)
            if t_img is None:
                continue
            th, tw = t_img.shape[:2]
            if th < 10 or tw < 10:
                continue

            thumb = cv2.resize(
                cv2.cvtColor(t_img, cv2.COLOR_BGR2GRAY),
                (THUMB_SIZE, THUMB_SIZE)
            ).flatten().astype(np.float32)
            norm = np.linalg.norm(thumb)
            if norm > 0:
                thumb /= norm

            t_area = th * tw
            cp = tmpl_info.get('color_profile')
            t_hue = cp.get('dominant_hue', -1) if cp else -1
            t_sat = cp.get('dominant_sat', 0) if cp else 0

            loadable.append((tmpl_info, t_img, thumb, t_area, t_hue, t_sat))

        used = [False] * len(loadable)
        representative_indices = []
        group_sizes = []

        for i in range(len(loadable)):
            if used[i]:
                continue
            used[i] = True
            representative_indices.append(i)
            group_count = 1
            _, _, thumb_i, area_i, hue_i, sat_i = loadable[i]

            for j in range(i + 1, len(loadable)):
                if used[j]:
                    continue
                _, _, thumb_j, area_j, hue_j, sat_j = loadable[j]

                size_ratio = min(area_i, area_j) / max(area_i, area_j) if max(area_i, area_j) > 0 else 0
                if size_ratio < (1.0 - SIZE_TOLERANCE):
                    continue

                both_colored = sat_i >= 50 and sat_j >= 50
                if both_colored:
                    hue_diff = min(abs(hue_i - hue_j), 180 - abs(hue_i - hue_j))
                    if hue_diff > HUE_TOLERANCE:
                        continue

                corr = float(np.dot(thumb_i, thumb_j))
                if corr >= DEDUP_THRESHOLD:
                    used[j] = True
                    group_count += 1
            group_sizes.append(group_count)

        total_loadable = len(loadable)
        total_reps = len(representative_indices)
        logger.info(
            f"Template dedup: {total_loadable} loadable → {total_reps} groups "
            f"(skipping {total_loadable - total_reps} duplicates)"
        )

        for rep_loop_idx, (rep_idx, grp_size) in enumerate(zip(representative_indices, group_sizes)):
            raise_if_cancelled(should_cancel, rep_loop_idx, every=1)
            tmpl_info, template_img, _, _, _, _ = loadable[rep_idx]

            _t0 = _time.time()

            tmpl_id = str(tmpl_info.get('_id', ''))
            tmpl_shape_type = tmpl_info.get('shape_type', 'rectangle')
            color_profile = tmpl_info.get('color_profile')

            tmpl_gray = cv2.cvtColor(template_img, cv2.COLOR_BGR2GRAY)
            tmpl_edges = cv2.Canny(tmpl_gray, 50, 150)
            tmpl_edges_dilated = cv2.dilate(tmpl_edges, kernel, iterations=1)
            tmpl_edges_smooth = cv2.GaussianBlur(tmpl_edges_dilated, (3, 3), 0)

            raw_matches = []
            edge_matches = []
            color_matches = []

            # Strategy 1: Raw grayscale (high threshold — pixel-exact match)
            raw_matches = self._multi_scale_match_on_prepared(
                img_gray, tmpl_gray, scales, threshold=0.7
            )

            raw_best = max((m[4] for m in raw_matches), default=0)

            # Strategy 2: Dilated + blurred edges
            # Skip if raw already found high-confidence matches — edge would
            # find the same locations plus noise.
            if raw_best < 0.85:
                edge_matches = self._multi_scale_match_on_prepared(
                    img_edges_smooth, tmpl_edges_smooth, scales, threshold=0.65
                )

            # Strategy 3: Color mask (only if template has a colored border)
            if color_profile and color_profile.get('dominant_sat', 0) >= 50:
                tmpl_color_mask = self._build_hsv_color_mask(template_img, color_profile)
                img_color_mask = self._build_hsv_color_mask(img, color_profile)
                if tmpl_color_mask is not None and img_color_mask is not None:
                    color_matches = self._multi_scale_match_on_prepared(
                        img_color_mask, tmpl_color_mask, scales, threshold=0.5
                    )

            _elapsed = _time.time() - _t0
            edge_best = max((m[4] for m in edge_matches), default=0)
            color_best = max((m[4] for m in color_matches), default=0)
            hit_scales = set(m[5] for m in raw_matches + edge_matches + color_matches)
            edge_skipped = " [edge skipped]" if raw_best >= 0.85 else ""
            logger.info(
                f"Template {tmpl_id[:8]} (grp={grp_size}): elapsed={_elapsed:.3f}s "
                f"raw={len(raw_matches)}(best:{raw_best:.2f}) "
                f"edge={len(edge_matches)}(best:{edge_best:.2f}) "
                f"color={len(color_matches)}(best:{color_best:.2f}) "
                f"scales_hit={sorted(hit_scales) if hit_scales else '[]'}"
                f"{edge_skipped}"
            )

            combined = raw_matches + edge_matches + color_matches
            nms_matches = self._non_maximum_suppression(combined, iou_threshold=0.3)

            for match in nms_matches:
                x, y, w, h, score, scale = match

                if x < 0 or y < 0 or x + w > img_w or y + h > img_h:
                    continue

                shape = {
                    'type': tmpl_shape_type,
                    'x': int(x),
                    'y': int(y),
                    'width': int(w),
                    'height': int(h),
                    'confidence': float(score),
                    'detection_method': 'learned',
                    'template_id': tmpl_id,
                }

                if tmpl_shape_type == 'circle':
                    cx = int(x + w / 2)
                    cy = int(y + h / 2)
                    radius = int(min(w, h) / 2)
                    shape['center_x'] = cx
                    shape['center_y'] = cy
                    shape['radius'] = radius

                all_matches.append(shape)

        # Cross-template deduplication: remove overlapping matches from different templates
        all_matches = self._deduplicate_learned_matches(all_matches)

        pre_filter = len(all_matches)

        circle_color_mask = None
        rect_red_mask = None
        has_circle_types = any(s['type'] == 'circle' for s in all_matches)
        has_rect_types = any(s['type'] == 'rectangle' for s in all_matches)

        if has_circle_types:
            sample_info = self._analyze_sample_circle(img)
            if sample_info is not None:
                color_type = sample_info.get('color_type', 'blue')
                circle_color_mask = self._build_color_mask(img, color_type)

        if has_rect_types:
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            mask_low = cv2.inRange(hsv, np.array([0, 60, 60]), np.array([10, 255, 255]))
            mask_high = cv2.inRange(hsv, np.array([165, 60, 60]), np.array([180, 255, 255]))
            rect_red_mask = cv2.bitwise_or(mask_low, mask_high)

        verified = []
        for verify_idx, s in enumerate(all_matches):
            raise_if_cancelled(should_cancel, verify_idx, every=8)
            if s['type'] == 'circle' and circle_color_mask is not None:
                cx = s.get('center_x', s['x'] + s['width'] // 2)
                cy = s.get('center_y', s['y'] + s['height'] // 2)
                radius = s.get('radius', min(s['width'], s['height']) // 2)
                if radius < 5 or not self._verify_circle_has_color(circle_color_mask, cx, cy, radius):
                    continue
                if not self._verify_circle_circularity(circle_color_mask, cx, cy, radius):
                    logger.debug(
                        f"Learned circle at ({cx},{cy}) r={radius} rejected: low circularity"
                    )
                    continue
            elif s['type'] == 'rectangle' and rect_red_mask is not None:
                if not self._has_complete_red_border(rect_red_mask, s['x'], s['y'], s['width'], s['height']):
                    continue
            verified.append(s)

        # Exclude shapes in legend region (upper-left)
        legend_bbox = self._detect_legend_region(img)
        if legend_bbox:
            lx, ly, lw, lh = legend_bbox
            verified = [s for s in verified
                        if not (lx <= s.get('center_x', s['x'] + s['width'] // 2) <= lx + lw
                                and ly <= s.get('center_y', s['y'] + s['height'] // 2) <= ly + lh)]

        # Exclude shapes in title block region (lower-right)
        title_bbox = self._detect_title_block(img)
        if title_bbox:
            tx, ty, tw, th = title_bbox
            verified = [s for s in verified
                        if not (tx <= s.get('center_x', s['x'] + s['width'] // 2) <= tx + tw
                                and ty <= s.get('center_y', s['y'] + s['height'] // 2) <= ty + th)]

        # Exclude shapes outside drawing frame
        frame_top, frame_bottom = self._detect_drawing_frame(img)
        if frame_top is not None or frame_bottom is not None:
            verified = [s for s in verified
                        if (frame_top is None or s.get('center_y', s['y'] + s['height'] // 2) > frame_top)
                        and (frame_bottom is None or s.get('center_y', s['y'] + s['height'] // 2) < frame_bottom)]

        logger.info(
            f"Learned template matching found {pre_filter} candidates from {len(templates)} templates, "
            f"{len(verified)} passed color verification + region exclusion"
        )
        return verified

    def deduplicate_with_existing(self, learned_shapes, existing_shapes, iou_threshold=0.5):
        """Remove learned detections that overlap with existing standard detections.

        Args:
            learned_shapes: Shapes from template matching
            existing_shapes: Shapes from the standard CV pipeline
            iou_threshold: Overlap threshold above which a learned shape is dropped

        Returns:
            Filtered list of learned shapes with no significant overlap.
        """
        if not existing_shapes:
            return learned_shapes

        unique = []
        for ls in learned_shapes:
            is_dup = False
            for es in existing_shapes:
                iou = self._calculate_iou(
                    ls['x'], ls['y'], ls['width'], ls['height'],
                    es['x'], es['y'], es['width'], es['height']
                )
                if iou > iou_threshold:
                    is_dup = True
                    break
            if not is_dup:
                unique.append(ls)

        logger.info(f"Dedup: {len(learned_shapes)} learned → {len(unique)} unique (vs {len(existing_shapes)} existing)")
        return unique

    def _deduplicate_learned_matches(self, matches, iou_threshold=0.3):
        """Remove overlapping detections across different templates."""
        if not matches:
            return []
        matches = sorted(matches, key=lambda m: m['confidence'], reverse=True)
        kept = []
        for m in matches:
            is_dup = False
            for k in kept:
                iou = self._calculate_iou(
                    m['x'], m['y'], m['width'], m['height'],
                    k['x'], k['y'], k['width'], k['height']
                )
                if iou > iou_threshold:
                    is_dup = True
                    break
            if not is_dup:
                kept.append(m)
        return kept

