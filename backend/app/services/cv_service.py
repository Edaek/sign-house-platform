import os
import re
import cv2
import numpy as np
import logging

from app.services.ocr_service import clean_ocr_text, is_valid_sign_code

logger = logging.getLogger(__name__)


class CVService:
    """Service for computer vision shape detection."""
    
    def __init__(self):
        """Initialize CV service with default parameters."""
        self._ocr_engine = None
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
            # Blue color range in HSV (covers typical blue markers)
            'lower_blue': np.array([100, 50, 50]),
            'upper_blue': np.array([130, 255, 255]),
            'template_padding': 5,        # Padding around extracted template
            'min_circularity': 0.6,       # Minimum circularity score for template detection
        }
        
        # Red rectangle detection parameters
        self.red_rect_params = {
            'min_area': 1400,  # Increased to filter small false positives
            'max_area': 5000,  # Labels are small
            'min_width': 50,  # Labels are at least ~50px wide
            'max_width': 115,  # Allow wider labels like S10-122 (~108px)
            'min_height': 22,  # Labels are at least ~22px tall
            'max_height': 38,  # Labels are not too tall
            'min_aspect_ratio': 1.5,  # Labels are wider than tall (w/h > 1.5)
            'max_aspect_ratio': 4.5,  # Allow wide labels like S10-122
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
    
    def load_image(self, image_path):
        """Load an image from file.
        
        Args:
            image_path: Path to the image file
            
        Returns:
            Tuple of (original image, grayscale image)
        """
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
        
        for color_type in ['blue', 'red']:
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
    
    def detect_circles_by_template(self, image_path, params=None):
        """Detect circles matching the sample from upper-right corner.
        
        Uses the sample circle to learn:
        1. The exact COLOR (BGR values and color type from sample)
        2. The exact SIZE (radius)
        
        Then finds all circles across the floorplan matching the sample.
        
        Args:
            image_path: Path to the image file
            params: Optional dictionary of detection parameters
            
        Returns:
            List of detected circles with bounding box info
        """
        if params:
            self.template_circle_params.update(params)
        
        img, gray = self.load_image(image_path)
        h, w = img.shape[:2]
        
        sample_info = self._analyze_sample_circle(img)
        
        if sample_info is None:
            return []
        
        target_radius = sample_info['radius']
        sample_bgr = sample_info['bgr_color']
        color_type = sample_info.get('color_type', 'blue')
        sample_location = sample_info.get('location')
        
        # Detect legend box in upper-left corner to exclude from detection
        legend_bbox = self._detect_legend_region(img)
        
        # Build color mask using detected color type
        color_dominant = self._build_color_mask(img, color_type)
        
        # Also check color distance from sample BGR
        b, g, r = cv2.split(img)
        color_dist = np.sqrt(
            (b.astype(float) - sample_bgr[0]) ** 2 +
            (g.astype(float) - sample_bgr[1]) ** 2 +
            (r.astype(float) - sample_bgr[2]) ** 2
        )
        color_tolerance = 80
        color_similar = color_dist < color_tolerance
        
        # Combine: pixel must match color type AND be similar to sample color
        color_mask = ((color_dominant > 0) & color_similar).astype(np.uint8) * 255
        
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
        color_mask = cv2.dilate(color_mask, kernel, iterations=1)
        
        color_mask_blurred = cv2.GaussianBlur(color_mask, (5, 5), 1)
        
        # Size tolerance: 35%
        size_tolerance = 0.35
        min_radius = max(5, int(target_radius * (1 - size_tolerance)))
        max_radius = int(target_radius * (1 + size_tolerance))
        
        circles = cv2.HoughCircles(
            color_mask_blurred,
            cv2.HOUGH_GRADIENT,
            dp=1.0,
            minDist=int(target_radius * 0.8),
            param1=50,
            param2=14,
            minRadius=min_radius,
            maxRadius=max_radius
        )
        
        detected = []
        
        if circles is not None:
            circles = np.round(circles[0, :]).astype("int")
            
            for (cx, cy, radius) in circles:
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
                }
                
                keep, text, conf = self._verify_shape_content(img, candidate, color_type=color_type)
                if not keep:
                    continue
                
                if text:
                    candidate['extracted_text'] = text
                    candidate['ocr_confidence'] = conf
                
                detected.append(candidate)
        
        # --- Contour-based detection pass (catches circles Hough misses) ---
        kern_size = max(3, int(target_radius * 0.15))
        open_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kern_size, kern_size))
        contour_mask = cv2.morphologyEx(raw_color_mask, cv2.MORPH_OPEN, open_kernel)
        contours, _ = cv2.findContours(contour_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        radius_lo = target_radius * 0.55
        radius_hi = target_radius * 1.45

        for contour in contours:
            area = cv2.contourArea(contour)
            if area < 200:
                continue
            perimeter = cv2.arcLength(contour, True)
            if perimeter == 0:
                continue
            circularity = 4 * np.pi * area / (perimeter * perimeter)
            if circularity < 0.45:
                continue
            (ccx, ccy), cradius = cv2.minEnclosingCircle(contour)
            if not (radius_lo <= cradius <= radius_hi):
                continue

            # Use equivalent radius from area for more robust radius estimate
            equiv_radius = np.sqrt(area / np.pi)
            # Average with minEnclosingCircle radius (weighted toward equiv)
            cradius = equiv_radius * 0.7 + cradius * 0.3

            # Use fitEllipse for sub-pixel center when enough points available
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
            }

            keep, text, conf = self._verify_shape_content(img, candidate, color_type=color_type)
            if not keep:
                continue
            if text:
                candidate['extracted_text'] = text
                candidate['ocr_confidence'] = conf
            detected.append(candidate)

        detected = self._remove_duplicate_circles(detected, min_distance=int(target_radius * 0.8))
        
        # Secondary pass: detect circles of other colors
        secondary_colors = [c for c in ('yellow', 'red') if c != color_type]
        for sec_color_name in secondary_colors:
            sec_detected = self._detect_secondary_color_circles(
                img, gray, target_radius, sec_color_name, detected, sample_location)
            detected.extend(sec_detected)
            detected = self._remove_duplicate_circles(detected, min_distance=int(target_radius * 0.8))
        
        # Cross-color containment: remove small circles fully inside larger ones
        detected = self._remove_contained_circles(detected)
        
        # Exclude circles inside the legend region
        if legend_bbox:
            lx, ly, lw, lh = legend_bbox
            detected = [d for d in detected
                        if not (lx <= d['center_x'] <= lx + lw and ly <= d['center_y'] <= ly + lh)]
        
        # Exclude circles inside the title block region (right-bottom corner)
        title_bbox = self._detect_title_block(img)
        if title_bbox:
            tx, ty, tw, th = title_bbox
            detected = [d for d in detected
                        if not (tx <= d['center_x'] <= tx + tw and ty <= d['center_y'] <= ty + th)]
        
        detected.sort(key=lambda c: (c['y'], c['x']))
        
        return detected
    
    def _detect_secondary_color_circles(self, img, gray, target_radius, sec_color, existing, sample_location):
        """Run a secondary detection pass for circles of a different color.
        
        For filled circles (like yellow), independently estimates the actual
        radius from contour analysis rather than relying on the primary sample's
        target_radius.
        """
        h, w = img.shape[:2]
        
        color_mask = self._build_color_mask(img, sec_color)
        
        if cv2.countNonZero(color_mask) < 100:
            return []
        
        # Clean up the mask
        kernel = np.ones((3, 3), np.uint8)
        color_mask_clean = cv2.morphologyEx(color_mask, cv2.MORPH_CLOSE, kernel)
        color_mask_clean = cv2.morphologyEx(color_mask_clean, cv2.MORPH_OPEN, kernel)
        
        # --- Step 1: Estimate actual yellow circle radius from contours ---
        est_contours, _ = cv2.findContours(
            color_mask_clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        radii = []
        for c in est_contours:
            area = cv2.contourArea(c)
            if area < 300:
                continue
            peri = cv2.arcLength(c, True)
            if peri == 0:
                continue
            circ = 4 * np.pi * area / (peri * peri)
            if circ > 0.85:
                _, r = cv2.minEnclosingCircle(c)
                radii.append(r)
        
        if radii:
            yellow_target = int(np.median(radii))
            yellow_target = max(int(target_radius * 0.5), min(yellow_target, int(target_radius * 3.0)))
            min_radius = max(5, int(min(radii) * 0.7))
            max_radius = int(max(radii) * 1.3)
            max_radius = min(max_radius, int(target_radius * 4.0))
        else:
            yellow_target = target_radius
            min_radius = max(5, int(target_radius * 0.5))
            max_radius = int(target_radius * 3.5)
        
        # --- Step 2: Hough detection on Canny edges (no blur) ---
        edges = cv2.Canny(color_mask_clean, 50, 150)
        
        # Pre-compute connected component labels for shape validation
        num_labels, labels, cc_stats, _ = cv2.connectedComponentsWithStats(color_mask_clean)
        
        circles = cv2.HoughCircles(
            edges,
            cv2.HOUGH_GRADIENT,
            dp=1.0,
            minDist=int(yellow_target * 0.8),
            param1=50,
            param2=14 if sec_color == 'red' else 10,
            minRadius=min_radius,
            maxRadius=max_radius
        )
        
        detected = []
        
        if circles is not None:
            circles = np.round(circles[0, :]).astype("int")
            
            for (cx, cy, radius) in circles:
                if sample_location:
                    dist_to_sample = np.sqrt(
                        (cx - sample_location[0]) ** 2 + (cy - sample_location[1]) ** 2)
                    if dist_to_sample < yellow_target * 2:
                        continue
                
                if not self._verify_circle_has_color(color_mask_clean, cx, cy, radius):
                    continue
                
                # For red circles: skip contour verification (red text inside
                # makes the interior non-empty, causing false rejections)
                
                # Verify the connected component at this point is roughly circular
                if 0 <= cy < h and 0 <= cx < w:
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
                
                too_close = False
                for d in existing:
                    dist = np.sqrt((cx - d['center_x']) ** 2 + (cy - d['center_y']) ** 2)
                    d_radius = d.get('radius', 0)
                    if radius > d_radius * 1.5:
                        continue
                    if dist < max(yellow_target * 0.7, d_radius):
                        too_close = True
                        break
                if too_close:
                    continue
                
                # Refine center using color mask ring moments + fitEllipse
                r_pad = int(radius * 1.3)
                y1c = max(0, cy - r_pad)
                y2c = min(h, cy + r_pad)
                x1c = max(0, cx - r_pad)
                x2c = min(w, cx + r_pad)
                roi_sec = color_mask_clean[y1c:y2c, x1c:x2c]
                roi_h_s, roi_w_s = roi_sec.shape[:2]
                local_cx_s = cx - x1c
                local_cy_s = cy - y1c
                outer_m = np.zeros((roi_h_s, roi_w_s), dtype=np.uint8)
                inner_m = np.zeros((roi_h_s, roi_w_s), dtype=np.uint8)
                cv2.circle(outer_m, (local_cx_s, local_cy_s), int(radius * 1.2), 255, -1)
                cv2.circle(inner_m, (local_cx_s, local_cy_s), int(radius * 0.6), 255, -1)
                ring_sec = cv2.bitwise_and(roi_sec, outer_m)
                ring_sec = cv2.bitwise_and(ring_sec, cv2.bitwise_not(inner_m))
                ring_pts = np.column_stack(np.where(ring_sec > 0))
                if len(ring_pts) >= 5:
                    try:
                        ell = cv2.fitEllipse(ring_pts[:, ::-1])
                        ecx_s, ecy_s = ell[0]
                        rcx = int(round(x1c + ecx_s))
                        rcy = int(round(y1c + ecy_s))
                        if abs(rcx - cx) < radius * 0.3 and abs(rcy - cy) < radius * 0.3:
                            cx, cy = rcx, rcy
                    except cv2.error:
                        pass
                
                adj_radius = radius
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
                }
                
                keep, text, conf = self._verify_shape_content(
                    img, candidate, color_type=None if sec_color == 'red' else sec_color)
                if keep:
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
        circ_threshold = 0.6 if sec_color == 'red' else 0.45
        
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < 300:
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
            
            too_close = False
            for d in existing + detected:
                dist = np.sqrt((ccx - d['center_x']) ** 2 + (ccy - d['center_y']) ** 2)
                d_radius = d.get('radius', 0)
                if cradius > d_radius * 1.5:
                    continue
                if dist < max(yellow_target * 0.7, d_radius):
                    too_close = True
                    break
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
            }
            
            keep, text, conf = self._verify_shape_content(
                img, candidate, color_type=None if sec_color == 'red' else sec_color)
            if keep:
                if text:
                    candidate['extracted_text'] = text
                    candidate['ocr_confidence'] = conf
                detected.append(candidate)
            elif not text or not text.strip():
                detected.append(candidate)
        
        return detected
    
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

    def _verify_circle_circularity(self, color_mask, cx, cy, radius, min_circularity=0.40):
        """Verify that a detected circle region contains a sufficiently circular contour.

        Crops the color mask around the circle, finds contours, and checks
        if the best contour has circularity above the threshold.
        """
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
        3. Fixed fallback region (conservative upper-left 15% x 20%)

        Returns:
            Tuple (x, y, w, h) of the legend bounding box, or None if not found.
        """
        box = self._detect_legend_by_contour(img)
        if box:
            return box

        box = self._detect_legend_by_keywords(img)
        if box:
            return box

        h, w = img.shape[:2]
        return (0, 0, int(w * 0.20), int(h * 0.15))

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

        best_box = None
        best_area = 0

        for contour in contours:
            area = cv2.contourArea(contour)
            if area < min_legend_area:
                continue

            peri = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.02 * peri, True)

            if len(approx) >= 4:
                x, y, bw, bh = cv2.boundingRect(contour)
                aspect = bw / bh if bh > 0 else 0
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
    
    def _detect_title_block(self, img):
        """Detect the title block region in the bottom-right corner of the image.
        
        Searches for a bordered rectangle anchored to the bottom-right corner.
        The title block must touch (or nearly touch) both the right and bottom edges.
        
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
                    # Must be anchored to the bottom-right corner of the search region
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
    
    def _verify_circle_has_color(self, color_mask, cx, cy, radius):
        """Verify that a detected circle location actually has colored pixels.
        
        Checks that there are colored pixels along the circle perimeter.
        
        Args:
            color_mask: Binary mask of colored pixels
            cx, cy: Circle center
            radius: Circle radius
            
        Returns:
            True if the circle perimeter has enough colored pixels
        """
        h, w = color_mask.shape
        
        # Sample points around the circle perimeter
        num_samples = 16
        colored_count = 0
        
        for i in range(num_samples):
            angle = 2 * np.pi * i / num_samples
            px = int(cx + radius * np.cos(angle))
            py = int(cy + radius * np.sin(angle))
            
            # Check bounds
            if 0 <= px < w and 0 <= py < h:
                # Check a small area around the point
                y1, y2 = max(0, py - 2), min(h, py + 3)
                x1, x2 = max(0, px - 2), min(w, px + 3)
                region = color_mask[y1:y2, x1:x2]
                if np.any(region > 0):
                    colored_count += 1
        
        # At least 50% of perimeter samples should have color
        return colored_count >= num_samples * 0.5
    
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
        """Lazily initialize a PaddleOCR engine for circle content verification."""
        if self._ocr_engine is None:
            from paddleocr import PaddleOCR
            self._ocr_engine = PaddleOCR(
                lang='en',
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        return self._ocr_engine

    def _verify_shape_content(self, img, shape, color_type=None):
        """Validate a detected shape by running OCR and checking if the text
        matches a sign code pattern.

        Args:
            img: Full BGR image (numpy array)
            shape: Dict with at least 'type', 'x', 'y', 'width', 'height'.
                   Circles also need 'center_x', 'center_y', 'radius'.
            color_type: 'blue' or 'red' — the circle outline color, used to
                        filter out foreign-colored text from the crop.

        Returns:
            Tuple of (keep: bool, text: str, confidence: float)
        """
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
            for result in ocr.predict(cropped_bgr):
                texts = result.get('rec_texts', [])
                scores = result.get('rec_scores', [])

                combined = ' '.join(t.strip() for t in texts if t.strip())
                cleaned = clean_ocr_text(combined)
                avg_conf = sum(scores) / len(scores) if scores else 0.0

                if not cleaned:
                    return (False, '', avg_conf)

                keep = is_valid_sign_code(cleaned, strict=True)
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
        pad = max(3, int(radius * 0.15))
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
        elif color_type == 'yellow' and len(roi.shape) == 3:
            # For yellow filled circles: neutralize the yellow background to white
            # but keep the dark/red text intact for OCR
            yellow_mask = self._build_color_mask(roi, 'yellow')
            yellow_mask = cv2.dilate(yellow_mask, np.ones((3, 3), np.uint8), iterations=1)
            roi[yellow_mask > 0] = (255, 255, 255)
            # Enhance remaining text contrast with adaptive threshold
            gray_tmp = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            enhanced = cv2.adaptiveThreshold(
                gray_tmp, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 15, 8)
            roi = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)

        roi_h, roi_w = roi.shape[:2]
        local_cx = cx - x1
        local_cy = cy - y1
        inner_r = max(3, int(radius * 0.92))

        mask = np.zeros((roi_h, roi_w), dtype=np.uint8)
        cv2.circle(mask, (local_cx, local_cy), inner_r, 255, -1)

        if len(roi.shape) == 3:
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        else:
            gray = roi.copy()

        masked = np.full((roi_h, roi_w), 255, dtype=np.uint8)
        masked[mask > 0] = gray[mask > 0]

        scale = max(3.0, 120.0 / max(roi_h, 1))
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

    def _build_color_mask(self, img_region, color_type):
        """Build a binary mask for pixels of a given color type.
        
        Args:
            img_region: BGR image region
            color_type: 'blue', 'red', or 'yellow'
            
        Returns:
            Binary mask (uint8, 0 or 255)
        """
        b, g, r = cv2.split(img_region)
        threshold = 30
        
        if color_type == 'blue':
            mask = ((b.astype(int) > r.astype(int) + threshold) &
                    (b.astype(int) > g.astype(int) + threshold) &
                    (b > 100)).astype(np.uint8) * 255
        elif color_type == 'red':
            hsv = cv2.cvtColor(img_region, cv2.COLOR_BGR2HSV)
            h_ch, s_ch, v_ch = cv2.split(hsv)
            mask_low = cv2.inRange(hsv, np.array([0, 60, 60]), np.array([10, 255, 255]))
            mask_high = cv2.inRange(hsv, np.array([165, 60, 60]), np.array([180, 255, 255]))
            mask = cv2.bitwise_or(mask_low, mask_high)
        elif color_type == 'yellow':
            hsv = cv2.cvtColor(img_region, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, np.array([12, 60, 80]), np.array([42, 255, 255]))
        else:
            mask = np.zeros(img_region.shape[:2], dtype=np.uint8)
        
        return mask
    
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
        """Analyze the sample circle in upper-right corner to extract its properties.
        
        Tries multiple color channels (blue, red) to find the sample circle.
        
        Args:
            img: BGR image
            
        Returns:
            Dict with 'radius', 'bgr_color', 'color_type' or None if not found
        """
        h, w = img.shape[:2]
        ratio = self.template_circle_params['search_region_ratio']
        
        search_w = int(w * ratio)
        search_h = int(h * ratio)
        search_region = img[0:search_h, w - search_w:w]
        
        # Try each color in priority order
        candidates = []
        for color_type in ['blue', 'red']:
            color_mask = self._build_color_mask(search_region, color_type)
            contour, circularity, radius = self._find_best_circle_in_mask(color_mask)
            
            if contour is not None and circularity >= 0.4:
                candidates.append({
                    'contour': contour,
                    'circularity': circularity,
                    'radius': radius,
                    'color_type': color_type,
                    'color_mask': color_mask,
                })
        
        if not candidates:
            return None
        
        # Pick the best candidate by circularity
        best = max(candidates, key=lambda c: c['circularity'])
        best_contour = best['contour']
        color_mask = best['color_mask']
        
        (cx_local, cy_local), _ = cv2.minEnclosingCircle(best_contour)
        # Use moments centroid for more accurate center
        M = cv2.moments(best_contour)
        if M['m00'] > 0:
            cx_local = M['m10'] / M['m00']
            cy_local = M['m01'] / M['m00']
        cx_full = int(round(cx_local)) + (w - search_w)
        cy_full = int(round(cy_local))
        
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
    
    def has_sample_circle(self, image_path):
        """Check if the image has a sample circle in the upper-right corner.
        
        Used for auto-detection to decide between circle and rectangle detection.
        
        Args:
            image_path: Path to the image file
            
        Returns:
            True if a sample circle is found, False otherwise
        """
        img, _ = self.load_image(image_path)
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
        
        circles = sorted(circles, key=lambda c: c['confidence'], reverse=True)
        
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
        
        for color_type in ['blue', 'red']:
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
    
    def detect_red_rectangles(self, image_path, params=None):
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
            self.red_rect_params.update(params)
        
        img, gray = self.load_image(image_path)
        
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
                
                # Label size filter (h min lowered to 14 for thin borders)
                if w >= 40 and w <= 110 and h >= 14 and h <= 60 and bounding_area >= 600:
                    if bounding_area > 0 and area > 0:
                        rect_ratio = area / bounding_area
                        if rect_ratio >= 0.15:  # Very low threshold for thin border contours
                            rect_contour = np.array([
                                [[x, y]], [[x+w, y]], [[x+w, y+h]], [[x, y+h]]
                            ], dtype=np.int32)
                            contours3.append(rect_contour)
        
        # Process all sets of contours
        all_contours = list(contours1) + list(contours2) + list(contours3)
        
        for contour in all_contours:
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
                if rectangularity < 0.7:  # At least 70% fill
                    continue
            
            # Duplicate check (very large grid to merge near-duplicates)
            rect_key = (x // 30, y // 30)
            if rect_key in seen_rects:
                continue
            
            # KEY FILTER: must have red border on all 4 sides AND white interior
            has_red = self._has_complete_red_border(red_mask, x, y, w, h)
            has_white = self._has_white_interior(gray, x, y, w, h)
            
            if has_red and has_white:
                candidate = {
                    'type': 'rectangle',
                    'x': int(x),
                    'y': int(y),
                    'width': int(w),
                    'height': int(h),
                }

                keep, text, conf = self._verify_shape_content(img, candidate)
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
    
    def _has_white_interior(self, gray_image, x, y, w, h):
        """Check if the interior of a rectangle has mostly white pixels with some text.
        
        Args:
            gray_image: Grayscale image
            x, y, w, h: Rectangle bounding box
            
        Returns:
            True if the interior is mostly white but has some dark text
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
        
        # Count white pixels (above threshold)
        white_pixels = np.sum(interior > self.red_rect_params['white_threshold'])
        total_pixels = interior.size
        white_ratio = white_pixels / total_pixels
        
        # Must have enough white (label background)
        if white_ratio < self.red_rect_params['white_ratio_min']:
            return False
        
        # But not TOO white - valid labels have BLACK text inside
        # If > 82% white, it's likely empty area or red text (not black)
        if white_ratio > 0.82:
            return False
        
        return True
    
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
        """Build a scale set that always includes 1.0 and clusters steps nearby."""
        near = [0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15, 1.2]
        wide = [0.5, 0.65, 0.8, 1.4, 1.7, 2.0, 2.5]
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

    def detect_from_learned_templates(self, image_path, templates, shape_type=None):
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

        Returns:
            List of shape dicts in the standard detection output format.
        """
        if not templates:
            return []

        img, gray = self.load_image(image_path)
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

        for tmpl_info in templates:
            if shape_type and tmpl_info.get('shape_type') != shape_type:
                continue

            tmpl_path = tmpl_info.get('image_path', '')
            if not os.path.exists(tmpl_path):
                logger.warning(f"Template image not found: {tmpl_path}")
                continue

            template_img = cv2.imread(tmpl_path)
            if template_img is None:
                continue

            tmpl_h, tmpl_w = template_img.shape[:2]
            if tmpl_h < 10 or tmpl_w < 10:
                continue

            tmpl_id = str(tmpl_info.get('_id', ''))
            tmpl_shape_type = tmpl_info.get('shape_type', 'rectangle')
            color_profile = tmpl_info.get('color_profile')

            # Prepare template variants
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

            # Strategy 2: Dilated + blurred edges
            edge_matches = self._multi_scale_match_on_prepared(
                img_edges_smooth, tmpl_edges_smooth, scales, threshold=0.55
            )

            # Strategy 3: Color mask (only if template has a colored border)
            if color_profile and color_profile.get('dominant_sat', 0) >= 50:
                tmpl_color_mask = self._build_hsv_color_mask(template_img, color_profile)
                img_color_mask = self._build_hsv_color_mask(img, color_profile)
                if tmpl_color_mask is not None and img_color_mask is not None:
                    color_matches = self._multi_scale_match_on_prepared(
                        img_color_mask, tmpl_color_mask, scales, threshold=0.5
                    )

            raw_best = max((m[4] for m in raw_matches), default=0)
            edge_best = max((m[4] for m in edge_matches), default=0)
            color_best = max((m[4] for m in color_matches), default=0)
            logger.info(
                f"Template {tmpl_id[:8]}: "
                f"raw={len(raw_matches)}(best:{raw_best:.2f}) "
                f"edge={len(edge_matches)}(best:{edge_best:.2f}) "
                f"color={len(color_matches)}(best:{color_best:.2f})"
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
        for s in all_matches:
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
        title_x = int(img_w * 0.70)
        title_y = int(img_h * 0.60)
        verified = [s for s in verified
                    if not (s.get('center_x', s['x'] + s['width'] // 2) >= title_x
                            and s.get('center_y', s['y'] + s['height'] // 2) >= title_y)]

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

