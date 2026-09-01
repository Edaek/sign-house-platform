import os
import gc
import fitz  # PyMuPDF

from app.services.job_cancel import JobCancelledError, raise_if_cancelled


class PDFService:
    """Service for PDF processing and conversion."""
    
    def __init__(self, dpi=200):
        """Initialize PDF service.
        
        Args:
            dpi: Resolution for image conversion (default 200)
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
    
    def convert_to_images(self, pdf_path, output_dir, format='png', preview_dpi=None,
                          should_cancel=None):
        """Convert PDF pages to images.
        
        Args:
            pdf_path: Path to the PDF file
            output_dir: Directory to save images
            format: Image format (png or jpg)
            preview_dpi: If set, also generates a lower-res preview at this DPI
            
        Returns:
            List of dictionaries with page info and image paths
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        
        os.makedirs(output_dir, exist_ok=True)
        
        preview_dir = None
        if preview_dpi:
            preview_dir = os.path.join(output_dir, 'previews')
            os.makedirs(preview_dir, exist_ok=True)
        
        doc = fitz.open(pdf_path)
        pages = []
        
        mat = fitz.Matrix(self.zoom, self.zoom)
        preview_mat = fitz.Matrix(preview_dpi / 72, preview_dpi / 72) if preview_dpi else None
        
        for page_num in range(len(doc)):
            raise_if_cancelled(should_cancel, page_num, every=1)
            page = doc.load_page(page_num)
            
            pix = page.get_pixmap(matrix=mat)
            
            base_name = os.path.splitext(os.path.basename(pdf_path))[0]
            image_filename = f"{base_name}_page_{page_num + 1}.{format}"
            image_path = os.path.join(output_dir, image_filename)
            
            pix.save(image_path)
            
            page_info = {
                'page_number': page_num + 1,
                'image_path': image_path,
                'width': pix.width,
                'height': pix.height
            }
            
            del pix
            
            if preview_mat and preview_dir:
                preview_pix = page.get_pixmap(matrix=preview_mat)
                preview_path = os.path.join(preview_dir, image_filename)
                preview_pix.save(preview_path)
                page_info['preview_path'] = preview_path
                del preview_pix
            
            pages.append(page_info)
            gc.collect()
        
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
        
        mat = fitz.Matrix(self.zoom, self.zoom)
        
        page = doc.load_page(page_number - 1)
        pix = page.get_pixmap(matrix=mat)
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        pix.save(output_path)
        
        result = {
            'page_number': page_number,
            'image_path': output_path,
            'width': pix.width,
            'height': pix.height
        }
        
        del pix
        gc.collect()
        
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
