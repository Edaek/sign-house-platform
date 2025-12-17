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
        self.config = '--oem 3 --psm 6'  # LSTM OCR Engine, assume uniform block of text
    
    def preprocess_for_ocr(self, image):
        """Preprocess image for better OCR results.
        
        Args:
            image: Input image (numpy array)
            
        Returns:
            Preprocessed image
        """
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
    
    def extract_text(self, image, preprocess=True):
        """Extract text from an image.
        
        Args:
            image: Input image (numpy array or PIL Image)
            preprocess: Whether to preprocess the image
            
        Returns:
            Tuple of (extracted text, confidence)
        """
        # Convert PIL Image to numpy array if needed
        if isinstance(image, Image.Image):
            image = np.array(image)
        
        if preprocess:
            image = self.preprocess_for_ocr(image)
        
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
        
        return extracted_text, avg_confidence
    
    def extract_text_from_region(self, image_path, x, y, width, height, padding=5):
        """Extract text from a specific region of an image.
        
        Args:
            image_path: Path to the image file
            x, y, width, height: Region coordinates
            padding: Extra padding around the region
            
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
        
        return self.extract_text(region)
    
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
    
    def batch_extract(self, image_path, regions):
        """Extract text from multiple regions.
        
        Args:
            image_path: Path to the image file
            regions: List of region dictionaries with x, y, width, height
            
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
            padding = region.get('padding', 5)
            
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
                results.append(self.extract_text(roi))
        
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

