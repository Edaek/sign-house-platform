import os
import csv
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter


class ExcelService:
    """Service for Excel file handling and export."""
    
    def __init__(self):
        """Initialize Excel service."""
        self.header_style = {
            'font': Font(bold=True, size=11),
            'fill': PatternFill(start_color='E0E0E0', end_color='E0E0E0', fill_type='solid'),
            'alignment': Alignment(horizontal='center', vertical='center'),
            'border': Border(
                left=Side(style='thin'),
                right=Side(style='thin'),
                top=Side(style='thin'),
                bottom=Side(style='thin')
            )
        }
        
        self.cell_style = {
            'alignment': Alignment(horizontal='left', vertical='center'),
            'border': Border(
                left=Side(style='thin'),
                right=Side(style='thin'),
                top=Side(style='thin'),
                bottom=Side(style='thin')
            )
        }
    
    def parse_template(self, template_path):
        """Parse an Excel template to extract column definitions.
        
        Args:
            template_path: Path to the Excel template file
            
        Returns:
            List of column names from the header row
        """
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"Template not found: {template_path}")
        
        workbook = load_workbook(template_path, read_only=True)
        sheet = workbook.active
        
        columns = []
        
        # Read the first row as headers
        for cell in sheet[1]:
            if cell.value:
                columns.append({
                    'name': str(cell.value),
                    'column': cell.column,
                    'letter': get_column_letter(cell.column)
                })
        
        workbook.close()
        
        return columns
    
    def create_workbook_with_headers(self, columns):
        """Create a new workbook with specified column headers.
        
        Args:
            columns: List of column names or column dictionaries
            
        Returns:
            Workbook object
        """
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = 'Extracted Data'
        
        # Write headers
        for col_idx, column in enumerate(columns, start=1):
            cell = sheet.cell(row=1, column=col_idx)
            
            if isinstance(column, dict):
                cell.value = column.get('name', f'Column {col_idx}')
            else:
                cell.value = column
            
            # Apply header style
            cell.font = self.header_style['font']
            cell.fill = self.header_style['fill']
            cell.alignment = self.header_style['alignment']
            cell.border = self.header_style['border']
        
        return workbook
    
    def export_data(self, data, output_path, template_path=None, column_mapping=None):
        """Export data to an Excel file.
        
        Args:
            data: List of dictionaries with extracted data
            output_path: Path for the output file
            template_path: Optional path to a template file
            column_mapping: Optional mapping of data keys to column names
            
        Returns:
            Path to the created file
        """
        if template_path and os.path.exists(template_path):
            # Use template
            workbook = load_workbook(template_path)
            sheet = workbook.active
            start_row = 2  # Assuming row 1 has headers
        else:
            # Create new workbook with default columns
            default_columns = ['Floor', 'Floor Name', 'Item #', 'Extracted Text', 'Confidence %']
            workbook = self.create_workbook_with_headers(default_columns)
            sheet = workbook.active
            start_row = 2
            
            # Default column mapping
            column_mapping = column_mapping or {
                'floor_number': 1,
                'floor_name': 2,
                'shape_index': 3,
                'text': 4,
                'confidence': 5
            }
        
        # Write data rows
        for row_idx, row_data in enumerate(data, start=start_row):
            if column_mapping:
                for key, col_idx in column_mapping.items():
                    if key in row_data:
                        cell = sheet.cell(row=row_idx, column=col_idx)
                        cell.value = row_data[key]
                        cell.alignment = self.cell_style['alignment']
                        cell.border = self.cell_style['border']
            else:
                # Write in order
                for col_idx, value in enumerate(row_data.values(), start=1):
                    cell = sheet.cell(row=row_idx, column=col_idx)
                    cell.value = value
                    cell.alignment = self.cell_style['alignment']
                    cell.border = self.cell_style['border']
        
        # Auto-adjust column widths
        for column_cells in sheet.columns:
            max_length = 0
            column = column_cells[0].column_letter
            
            for cell in column_cells:
                try:
                    if cell.value:
                        max_length = max(max_length, len(str(cell.value)))
                except:
                    pass
            
            adjusted_width = min(max_length + 2, 50)
            sheet.column_dimensions[column].width = adjusted_width
        
        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        workbook.save(output_path)
        workbook.close()
        
        return output_path
    
    def export_to_csv(self, data, output_path):
        """Export data to a CSV file.
        
        Args:
            data: List of dictionaries with extracted data
            output_path: Path for the output file
            
        Returns:
            Path to the created file
        """
        if not data:
            raise ValueError("No data to export")
        
        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        # Get all unique keys from data
        fieldnames = list(data[0].keys())
        
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(data)
        
        return output_path
    
    def merge_with_template(self, template_path, data, output_path, start_row=2, column_mapping=None):
        """Merge data with an existing template.
        
        Args:
            template_path: Path to the template file
            data: List of dictionaries with extracted data
            output_path: Path for the output file
            start_row: Row to start writing data (default 2, after header)
            column_mapping: Mapping of data keys to column letters/numbers
            
        Returns:
            Path to the created file
        """
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"Template not found: {template_path}")
        
        workbook = load_workbook(template_path)
        sheet = workbook.active
        
        # Parse template columns if no mapping provided
        if not column_mapping:
            columns = self.parse_template(template_path)
            column_mapping = {col['name'].lower().replace(' ', '_'): col['column'] for col in columns}
        
        # Write data
        for row_idx, row_data in enumerate(data, start=start_row):
            for key, value in row_data.items():
                # Try to find matching column
                normalized_key = key.lower().replace(' ', '_')
                
                if normalized_key in column_mapping:
                    col_idx = column_mapping[normalized_key]
                    if isinstance(col_idx, str):
                        # Column letter
                        cell = sheet[f'{col_idx}{row_idx}']
                    else:
                        # Column number
                        cell = sheet.cell(row=row_idx, column=col_idx)
                    
                    cell.value = value
                    cell.alignment = self.cell_style['alignment']
                    cell.border = self.cell_style['border']
        
        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        workbook.save(output_path)
        workbook.close()
        
        return output_path

