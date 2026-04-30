import os
import fitz  # PyMuPDF


class PDFService:
    """Service for PDF processing and conversion."""
    
    def __init__(self, dpi=300):
        """Initialize PDF service.
        
        Args:
            dpi: Resolution for image conversion (default 300)
        """
        self.dpi = dpi
        self.zoom = dpi / 72  # 72 is the default PDF DPI
    
    def get_page_count(self, pdf_path):
        """Get the number of pages in a PDF.
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            Number of pages
        """
        doc = fitz.open(pdf_path)
        count = len(doc)
        doc.close()
        return count
    
    def convert_to_images(self, pdf_path, output_dir, format='png'):
        """Convert PDF pages to images.
        
        Args:
            pdf_path: Path to the PDF file
            output_dir: Directory to save images
            format: Image format (png or jpg)
            
        Returns:
            List of dictionaries with page info and image paths
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        
        os.makedirs(output_dir, exist_ok=True)
        
        doc = fitz.open(pdf_path)
        pages = []
        
        # Create transformation matrix for resolution
        mat = fitz.Matrix(self.zoom, self.zoom)
        
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            
            # Render page to image
            pix = page.get_pixmap(matrix=mat)
            
            # Generate output filename
            base_name = os.path.splitext(os.path.basename(pdf_path))[0]
            image_filename = f"{base_name}_page_{page_num + 1}.{format}"
            image_path = os.path.join(output_dir, image_filename)
            
            # Save image
            pix.save(image_path)
            
            pages.append({
                'page_number': page_num + 1,
                'image_path': image_path,
                'width': pix.width,
                'height': pix.height
            })
        
        doc.close()
        
        return pages
    
    def convert_single_page(self, pdf_path, page_number, output_path, format='png'):
        """Convert a single PDF page to an image.
        
        Args:
            pdf_path: Path to the PDF file
            page_number: Page number (1-indexed)
            output_path: Path for the output image
            format: Image format (png or jpg)
            
        Returns:
            Dictionary with page info
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        
        doc = fitz.open(pdf_path)
        
        if page_number < 1 or page_number > len(doc):
            doc.close()
            raise ValueError(f"Invalid page number: {page_number}")
        
        # Create transformation matrix for resolution
        mat = fitz.Matrix(self.zoom, self.zoom)
        
        page = doc.load_page(page_number - 1)  # 0-indexed
        pix = page.get_pixmap(matrix=mat)
        
        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        pix.save(output_path)
        
        result = {
            'page_number': page_number,
            'image_path': output_path,
            'width': pix.width,
            'height': pix.height
        }
        
        doc.close()
        
        return result
    
    def get_page_info(self, pdf_path):
        """Get information about all pages in a PDF.
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            List of page information dictionaries
        """
        doc = fitz.open(pdf_path)
        pages = []
        
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            rect = page.rect
            
            pages.append({
                'page_number': page_num + 1,
                'width': rect.width,
                'height': rect.height,
                'rotation': page.rotation
            })
        
        doc.close()
        
        return pages

