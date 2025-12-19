"""Dictionary service for English-Chinese translation lookups and template auto-fill."""
from app import mongo


def lookup_english(chinese):
    """
    Look up the English translation for a Chinese term.
    
    Args:
        chinese: Chinese text to look up
        
    Returns:
        English translation if found, None otherwise
    """
    if not chinese or not chinese.strip():
        return None
    
    entry = mongo.db.dictionary.find_one({'chinese': chinese.strip()})
    if entry and entry.get('english'):
        return entry['english']
    
    return None


def lookup_chinese(english):
    """
    Look up the Chinese translation for an English term.
    
    Args:
        english: English text to look up
        
    Returns:
        Chinese translation if found, None otherwise
    """
    if not english or not english.strip():
        return None
    
    # Case-insensitive lookup for English
    entry = mongo.db.dictionary.find_one({
        'english': {'$regex': f'^{english.strip()}$', '$options': 'i'}
    })
    if entry and entry.get('chinese'):
        return entry['chinese']
    
    return None


def lookup_translation(text):
    """
    Automatically detect if text is English or Chinese and look up its translation.
    
    Args:
        text: Text to look up (either English or Chinese)
        
    Returns:
        Tuple of (english, chinese) - one will be the original, one will be the lookup result
    """
    if not text or not text.strip():
        return None, None
    
    text = text.strip()
    
    # Check if the text contains Chinese characters
    has_chinese = any('\u4e00' <= char <= '\u9fff' for char in text)
    
    if has_chinese:
        # Text is Chinese, look up English
        english = lookup_english(text)
        return english, text
    else:
        # Text is English, look up Chinese
        chinese = lookup_chinese(text)
        return text, chinese


def fill_template_gaps(rows, english_col_name, chinese_col_name, columns):
    """
    Fill missing English or Chinese values in template rows using dictionary lookups.
    
    Args:
        rows: List of row dictionaries from template (each with 'cells' list)
        english_col_name: Name of the English column
        chinese_col_name: Name of the Chinese column
        columns: List of column info dictionaries with 'name' and 'column' keys
        
    Returns:
        Tuple of (updated_rows, fill_stats) where fill_stats is a dict with:
        - english_filled: count of English values filled
        - chinese_filled: count of Chinese values filled
        - not_found: count of values not found in dictionary
    """
    # Find column indices
    english_col_idx = None
    chinese_col_idx = None
    
    for col in columns:
        col_name = col.get('name', '').strip()
        if col_name == english_col_name:
            english_col_idx = col['column'] - 1  # Convert to 0-based index
        elif col_name == chinese_col_name:
            chinese_col_idx = col['column'] - 1
    
    if english_col_idx is None or chinese_col_idx is None:
        return rows, {'english_filled': 0, 'chinese_filled': 0, 'not_found': 0, 'error': 'Column not found'}
    
    stats = {
        'english_filled': 0,
        'chinese_filled': 0,
        'not_found': 0
    }
    
    for row in rows:
        cells = row.get('cells', [])
        
        # Get current values
        english_val = ''
        chinese_val = ''
        
        if english_col_idx < len(cells):
            english_val = str(cells[english_col_idx].get('value', '')).strip()
        
        if chinese_col_idx < len(cells):
            chinese_val = str(cells[chinese_col_idx].get('value', '')).strip()
        
        # Skip if both are filled or both are empty
        if (english_val and chinese_val) or (not english_val and not chinese_val):
            continue
        
        # Fill missing value
        if english_val and not chinese_val:
            # Have English, need Chinese
            chinese = lookup_chinese(english_val)
            if chinese:
                if chinese_col_idx < len(cells):
                    cells[chinese_col_idx]['value'] = chinese
                    stats['chinese_filled'] += 1
            else:
                stats['not_found'] += 1
                
        elif chinese_val and not english_val:
            # Have Chinese, need English
            english = lookup_english(chinese_val)
            if english:
                if english_col_idx < len(cells):
                    cells[english_col_idx]['value'] = english
                    stats['english_filled'] += 1
            else:
                stats['not_found'] += 1
    
    return rows, stats


def fill_template_file_gaps(template_path, english_col_name, chinese_col_name):
    """
    Fill missing English or Chinese values directly in an Excel template file.
    
    Args:
        template_path: Path to the Excel template file
        english_col_name: Name of the English column
        chinese_col_name: Name of the Chinese column
        
    Returns:
        Dictionary with fill statistics
    """
    import os
    from openpyxl import load_workbook
    from openpyxl.utils import get_column_letter
    
    if not os.path.exists(template_path):
        return {'error': f'Template not found: {template_path}'}
    
    workbook = load_workbook(template_path)
    sheet = workbook.active
    
    # Find column indices from header row
    english_col_idx = None
    chinese_col_idx = None
    
    for cell in sheet[1]:
        if cell.value:
            col_name = ' '.join(str(cell.value).split())  # Normalize
            if col_name == english_col_name:
                english_col_idx = cell.column
            elif col_name == chinese_col_name:
                chinese_col_idx = cell.column
    
    if english_col_idx is None or chinese_col_idx is None:
        workbook.close()
        return {
            'error': f'Columns not found. Looking for "{english_col_name}" and "{chinese_col_name}"',
            'english_filled': 0,
            'chinese_filled': 0,
            'not_found': 0
        }
    
    stats = {
        'english_filled': 0,
        'chinese_filled': 0,
        'not_found': 0
    }
    
    # Iterate through data rows (skip header)
    for row_idx in range(2, sheet.max_row + 1):
        english_cell = sheet.cell(row=row_idx, column=english_col_idx)
        chinese_cell = sheet.cell(row=row_idx, column=chinese_col_idx)
        
        english_val = str(english_cell.value).strip() if english_cell.value else ''
        chinese_val = str(chinese_cell.value).strip() if chinese_cell.value else ''
        
        # Skip if both are filled or both are empty
        if (english_val and chinese_val) or (not english_val and not chinese_val):
            continue
        
        # Fill missing value
        if english_val and not chinese_val:
            # Have English, need Chinese
            chinese = lookup_chinese(english_val)
            if chinese:
                chinese_cell.value = chinese
                stats['chinese_filled'] += 1
            else:
                stats['not_found'] += 1
                
        elif chinese_val and not english_val:
            # Have Chinese, need English
            english = lookup_english(chinese_val)
            if english:
                english_cell.value = english
                stats['english_filled'] += 1
            else:
                stats['not_found'] += 1
    
    # Save the workbook
    workbook.save(template_path)
    workbook.close()
    
    return stats


def get_all_entries_dict():
    """
    Get all dictionary entries as a lookup dictionary.
    
    Returns:
        Tuple of (english_to_chinese, chinese_to_english) dictionaries
    """
    entries = list(mongo.db.dictionary.find({}))
    
    english_to_chinese = {}
    chinese_to_english = {}
    
    for entry in entries:
        english = entry.get('english', '').strip()
        chinese = entry.get('chinese', '').strip()
        
        if english and chinese:
            english_to_chinese[english.lower()] = chinese
            chinese_to_english[chinese] = english
    
    return english_to_chinese, chinese_to_english


def batch_lookup(texts, direction='auto'):
    """
    Perform batch lookups for multiple texts.
    
    Args:
        texts: List of texts to look up
        direction: 'en_to_cn', 'cn_to_en', or 'auto'
        
    Returns:
        Dictionary mapping original texts to their translations
    """
    if not texts:
        return {}
    
    results = {}
    english_to_chinese, chinese_to_english = get_all_entries_dict()
    
    for text in texts:
        if not text or not str(text).strip():
            results[text] = None
            continue
        
        text_str = str(text).strip()
        
        if direction == 'en_to_cn':
            results[text] = english_to_chinese.get(text_str.lower())
        elif direction == 'cn_to_en':
            results[text] = chinese_to_english.get(text_str)
        else:
            # Auto-detect
            has_chinese = any('\u4e00' <= char <= '\u9fff' for char in text_str)
            if has_chinese:
                results[text] = chinese_to_english.get(text_str)
            else:
                results[text] = english_to_chinese.get(text_str.lower())
    
    return results

