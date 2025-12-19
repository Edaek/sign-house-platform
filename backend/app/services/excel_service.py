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
                # Normalize column name by removing newlines and extra spaces
                normalized_name = ' '.join(str(cell.value).split())
                columns.append({
                    'name': normalized_name,
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
    
    def export_with_template_mapping(self, data, output_path, template_path, floor_mapping, sign_column='Sign No.'):
        """Export data to template by matching Sign No. and updating floor columns.
        
        Args:
            data: List of dictionaries with extracted data (floor_number, text, quantity)
            output_path: Path for the output file
            template_path: Path to the template file
            floor_mapping: Dict mapping floor numbers to column names (e.g., {"1": "21/F", "2": "8/F"})
            sign_column: Name of the column containing sign identifiers (default: "Sign No.")
            
        Returns:
            Path to the created file
        """
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"Template not found: {template_path}")
        
        # Load template
        workbook = load_workbook(template_path)
        sheet = workbook.active
        
        # Parse template columns from the loaded workbook
        # Normalize column names by removing newlines and extra spaces
        column_map = {}
        original_names = {}  # Keep track of original names for matching
        for cell in sheet[1]:
            if cell.value:
                original_name = str(cell.value)
                normalized_name = ' '.join(original_name.split())  # Remove newlines and extra spaces
                column_map[normalized_name] = cell.column
                original_names[normalized_name] = original_name
        
        # Find Sign No. column (with normalization)
        if sign_column not in column_map:
            raise ValueError(f"Column '{sign_column}' not found in template. Available columns: {list(column_map.keys())}")
        
        sign_col_idx = column_map[sign_column]
        
        # Group data by sign text
        sign_data = {}
        for item in data:
            sign_text = item.get('text', '').strip()
            floor_num = str(item.get('floor_number', ''))
            quantity = item.get('quantity', 0)
            
            if not sign_text:
                continue
                
            if sign_text not in sign_data:
                sign_data[sign_text] = {}
            
            # Map floor number to floor column using floor_mapping
            if floor_num in floor_mapping:
                floor_col_name = floor_mapping[floor_num]
                # Normalize floor column name to match template columns
                normalized_floor_col = ' '.join(floor_col_name.split())
                
                if normalized_floor_col in column_map:
                    if normalized_floor_col in sign_data[sign_text]:
                        sign_data[sign_text][normalized_floor_col] += quantity
                    else:
                        sign_data[sign_text][normalized_floor_col] = quantity
        
        # Build index of existing rows by Sign No.
        existing_rows = {}
        for row_idx in range(2, sheet.max_row + 1):
            cell_value = sheet.cell(row=row_idx, column=sign_col_idx).value
            if cell_value:
                existing_rows[str(cell_value).strip()] = row_idx
        
        # Track which signs we've updated
        updated_signs = set()
        
        # Update existing rows
        for sign_text, floor_quantities in sign_data.items():
            if sign_text in existing_rows:
                row_idx = existing_rows[sign_text]
                updated_signs.add(sign_text)
                
                # Update quantities for each floor column
                for floor_col_name, quantity in floor_quantities.items():
                    # Floor column names are already normalized
                    if floor_col_name in column_map:
                        col_idx = column_map[floor_col_name]
                        cell = sheet.cell(row=row_idx, column=col_idx)
                        
                        # Add to existing value if present
                        existing_value = cell.value
                        if existing_value and isinstance(existing_value, (int, float)):
                            cell.value = existing_value + quantity
                        else:
                            cell.value = quantity
                        
                        cell.alignment = self.cell_style['alignment']
        
        # Append new rows for signs not found in template
        next_row = sheet.max_row + 1
        for sign_text, floor_quantities in sign_data.items():
            if sign_text not in updated_signs:
                # Write sign number
                sheet.cell(row=next_row, column=sign_col_idx, value=sign_text)
                
                # Write quantities for each floor
                for floor_col_name, quantity in floor_quantities.items():
                    # Floor column names are already normalized
                    if floor_col_name in column_map:
                        col_idx = column_map[floor_col_name]
                        sheet.cell(row=next_row, column=col_idx, value=quantity)
                
                next_row += 1
        
        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        # Save workbook
        workbook.save(output_path)
        workbook.close()
        
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
    
    def read_template_data(self, template_path):
        """Read all data from a template file.
        
        Args:
            template_path: Path to the Excel template file
            
        Returns:
            Dict with columns (header info) and rows (all data rows)
        """
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"Template not found: {template_path}")
        
        workbook = load_workbook(template_path)
        sheet = workbook.active
        
        # Read columns from first row
        columns = []
        for cell in sheet[1]:
            if cell.value:
                normalized_name = ' '.join(str(cell.value).split())
                columns.append({
                    'name': normalized_name,
                    'column': cell.column,
                    'letter': get_column_letter(cell.column)
                })
            else:
                # Include empty columns to preserve structure
                columns.append({
                    'name': '',
                    'column': cell.column,
                    'letter': get_column_letter(cell.column)
                })
        
        # Read all data rows (starting from row 2), skip empty rows
        rows = []
        for row_idx in range(2, sheet.max_row + 1):
            row_data = {
                'row': row_idx,
                'cells': []
            }
            has_data = False  # Track if row has any non-empty values
            
            for col_idx in range(1, len(columns) + 1):
                cell = sheet.cell(row=row_idx, column=col_idx)
                cell_value = cell.value
                # Convert to appropriate type for JSON
                if cell_value is None:
                    cell_value = ''
                elif isinstance(cell_value, (int, float)):
                    has_data = True  # Numbers count as data
                else:
                    cell_value = str(cell_value)
                    if cell_value.strip():  # Non-empty string
                        has_data = True
                
                row_data['cells'].append({
                    'col': col_idx,
                    'letter': get_column_letter(col_idx),
                    'value': cell_value
                })
            
            # Only include rows that have at least one non-empty cell
            if has_data:
                rows.append(row_data)
        
        workbook.close()
        
        return {
            'columns': columns,
            'rows': rows,
            'total_rows': len(rows),
            'total_columns': len(columns)
        }
    
    def _extract_floor_number(self, text):
        """Extract floor number from a string like 'Floor 21', '21/F', '21F', 'L21', etc.
        
        Args:
            text: String containing floor information
            
        Returns:
            Extracted floor number as string, or None if not found
        """
        import re
        if not text:
            return None
        
        text = str(text).strip()
        
        # Try various patterns to extract floor number
        patterns = [
            r'(\d+)/F',           # "21/F" -> "21"
            r'(\d+)F\b',          # "21F" -> "21"
            r'Floor\s*(\d+)',     # "Floor 21" -> "21"
            r'F(\d+)\b',          # "F21" -> "21"
            r'L(\d+)\b',          # "L21" -> "21"
            r'^(\d+)$',           # Just "21" -> "21"
            r'\b(\d+)\b',         # Any number in the string
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None
    
    def _find_matching_column(self, floor_name, column_map, floor_mapping=None):
        """Find the matching column for a floor name.
        
        Args:
            floor_name: Name of the floor (e.g., "Floor 1", "21/F")
            column_map: Dict of column names to indices
            floor_mapping: Optional explicit mapping from floor numbers to column names
            
        Returns:
            Column name if found, None otherwise
        """
        # First try exact match
        normalized_floor = ' '.join(str(floor_name).split())
        if normalized_floor in column_map:
            return normalized_floor
        
        # Try explicit floor mapping if provided
        if floor_mapping:
            floor_num = self._extract_floor_number(floor_name)
            if floor_num and floor_num in floor_mapping:
                mapped_col = floor_mapping[floor_num]
                normalized_mapped = ' '.join(mapped_col.split())
                if normalized_mapped in column_map:
                    return normalized_mapped
        
        # Try flexible matching based on floor number
        floor_num = self._extract_floor_number(floor_name)
        if floor_num:
            for col_name in column_map.keys():
                col_num = self._extract_floor_number(col_name)
                if col_num and col_num == floor_num:
                    return col_name
        
        return None
    
    def merge_with_ocr_data(self, template_data, ocr_data, floor_mapping=None, sign_column='Sign No.'):
        """Merge OCR extracted data into template data structure.
        
        Args:
            template_data: Dict from read_template_data()
            ocr_data: List of extracted data items with floor_name, text, quantity
            floor_mapping: Optional dict mapping floor numbers to column names (for manual override)
            sign_column: Name of the column containing sign identifiers
            
        Returns:
            Updated template_data with OCR values merged in and ocr_cells tracking
        """
        columns = template_data['columns']
        rows = template_data['rows']
        
        # Build column name to index mapping
        column_map = {}
        for col in columns:
            if col['name']:
                normalized_name = ' '.join(col['name'].split())
                column_map[normalized_name] = col['column'] - 1  # 0-based index for cells array
        
        # Find sign column index
        sign_col_idx = column_map.get(sign_column)
        if sign_col_idx is None:
            # Return unmodified if sign column not found
            template_data['ocr_cells'] = []
            return template_data
        
        # Group OCR data by sign text
        sign_data = {}
        for item in ocr_data:
            sign_text = item.get('text', '').strip()
            floor_name = item.get('floor_name', '')
            quantity = item.get('quantity', 1)
            
            if not sign_text:
                continue
            
            if sign_text not in sign_data:
                sign_data[sign_text] = {}
            
            # Find matching column for this floor (auto-match or use explicit mapping)
            matched_col = self._find_matching_column(floor_name, column_map, floor_mapping)
            
            if matched_col:
                if matched_col in sign_data[sign_text]:
                    sign_data[sign_text][matched_col] += quantity
                else:
                    sign_data[sign_text][matched_col] = quantity
        
        # Track which cells were populated by OCR
        ocr_cells = []
        
        # Build index of existing rows by Sign No.
        row_sign_map = {}
        for row in rows:
            if sign_col_idx < len(row['cells']):
                cell_value = row['cells'][sign_col_idx]['value']
                if cell_value:
                    row_sign_map[str(cell_value).strip()] = row
        
        # Merge OCR data into template
        for sign_text, floor_quantities in sign_data.items():
            if sign_text in row_sign_map:
                row = row_sign_map[sign_text]
                
                for floor_col_name, quantity in floor_quantities.items():
                    if floor_col_name in column_map:
                        col_idx = column_map[floor_col_name]
                        if col_idx < len(row['cells']):
                            # Update cell value
                            existing = row['cells'][col_idx]['value']
                            if existing and isinstance(existing, (int, float)):
                                row['cells'][col_idx]['value'] = existing + quantity
                            else:
                                row['cells'][col_idx]['value'] = quantity
                            
                            # Track this as an OCR-populated cell
                            ocr_cells.append({
                                'row': row['row'],
                                'col': col_idx + 1  # 1-based for consistency
                            })
        
        template_data['ocr_cells'] = ocr_cells
        return template_data
    
    def update_cell(self, template_path, row, col, value):
        """Update a single cell in the template file.
        
        Args:
            template_path: Path to the Excel template file
            row: Row number (1-based)
            col: Column number (1-based)
            value: New cell value
            
        Returns:
            Updated cell info
        """
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"Template not found: {template_path}")
        
        workbook = load_workbook(template_path)
        sheet = workbook.active
        
        cell = sheet.cell(row=row, column=col)
        
        # Try to convert to number if possible
        if value is not None and value != '':
            try:
                # Try integer first
                value = int(value)
            except (ValueError, TypeError):
                try:
                    # Try float
                    value = float(value)
                except (ValueError, TypeError):
                    # Keep as string
                    pass
        
        cell.value = value
        
        workbook.save(template_path)
        workbook.close()
        
        return {
            'row': row,
            'col': col,
            'letter': get_column_letter(col),
            'value': value
        }
    
    def update_cells_batch(self, template_path, updates):
        """Update multiple cells in the template file at once.
        
        Args:
            template_path: Path to the Excel template file
            updates: List of dicts with row, col, value
            
        Returns:
            List of updated cell info
        """
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"Template not found: {template_path}")
        
        workbook = load_workbook(template_path)
        sheet = workbook.active
        
        results = []
        for update in updates:
            row = update['row']
            col = update['col']
            value = update['value']
            
            cell = sheet.cell(row=row, column=col)
            
            # Try to convert to number if possible
            if value is not None and value != '':
                try:
                    value = int(value)
                except (ValueError, TypeError):
                    try:
                        value = float(value)
                    except (ValueError, TypeError):
                        pass
            
            cell.value = value
            
            results.append({
                'row': row,
                'col': col,
                'letter': get_column_letter(col),
                'value': value
            })
        
        workbook.save(template_path)
        workbook.close()
        
        return results

