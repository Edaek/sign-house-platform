import os
import cv2
import numpy as np


class CVService:
    """Service for computer vision shape detection."""
    
    def __init__(self):
        """Initialize CV service with default parameters."""
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
                seen_rects.add(rect_key)
                detected.append({
                    'type': 'rectangle',
                    'x': int(x),
                    'y': int(y),
                    'width': int(w),
                    'height': int(h)
                })
        
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

