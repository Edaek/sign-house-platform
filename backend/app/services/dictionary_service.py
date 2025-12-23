"""Dictionary service for English-Chinese translation lookups and template auto-fill.

This is an English-first dictionary where each English word can have multiple
Chinese translations stored as an array.
"""
from app import mongo


def lookup_english(chinese):
    """
    Look up the English word for a Chinese term.
    Returns the first matching English word (for auto-fill).
    
    Args:
        chinese: Chinese text to look up
        
    Returns:
        First matching English word if found, None otherwise
    """
    if not chinese or not chinese.strip():
        return None
    
    chinese = chinese.strip()
    
    # Find entries where chinese array contains this term
    entry = mongo.db.dictionary.find_one({'chinese': chinese})
    if entry and entry.get('english'):
        return entry['english']
    
    return None


def lookup_english_all(chinese):
    """
    Look up all English words for a Chinese term.
    Returns all matching English words (for dropdown selection).
    
    Args:
        chinese: Chinese text to look up
        
    Returns:
        List of matching English words, empty list if not found
    """
    if not chinese or not chinese.strip():
        return []
    
    chinese = chinese.strip()
    
    # Find all entries where chinese array contains this term
    entries = list(mongo.db.dictionary.find({'chinese': chinese}))
    
    return [entry.get('english') for entry in entries if entry.get('english')]


def lookup_chinese(english):
    """
    Look up the Chinese translations for an English word.
    Returns the first Chinese translation (for auto-fill).
    
    Args:
        english: English text to look up
        
    Returns:
        First Chinese translation if found, None otherwise
    """
    if not english or not english.strip():
        return None
    
    # Case-insensitive lookup for English
    entry = mongo.db.dictionary.find_one({
        'english': {'$regex': f'^{english.strip()}$', '$options': 'i'}
    })
    
    if entry:
        chinese = entry.get('chinese', [])
        # Handle both array and legacy string format
        if isinstance(chinese, list) and len(chinese) > 0:
            return chinese[0]  # Return first translation
        elif isinstance(chinese, str) and chinese:
            return chinese
    
    return None


def lookup_chinese_all(english):
    """
    Look up all Chinese translations for an English word.
    
    Args:
        english: English text to look up
        
    Returns:
        List of Chinese translations, empty list if not found
    """
    if not english or not english.strip():
        return []
    
    # Case-insensitive lookup for English
    entry = mongo.db.dictionary.find_one({
        'english': {'$regex': f'^{english.strip()}$', '$options': 'i'}
    })
    
    if entry:
        chinese = entry.get('chinese', [])
        # Handle both array and legacy string format
        if isinstance(chinese, list):
            return chinese
        elif isinstance(chinese, str) and chinese:
            return [chinese]
    
    return []


def lookup_sign(english):
    """
    Look up the sign name/code for an English word.
    
    Args:
        english: English text to look up
        
    Returns:
        Sign name/code if found, None otherwise
    """
    if not english or not english.strip():
        return None
    
    # Case-insensitive lookup for English
    entry = mongo.db.dictionary.find_one({
        'english': {'$regex': f'^{english.strip()}$', '$options': 'i'}
    })
    
    if entry:
        sign = entry.get('sign', '')
        if sign:
            return sign
    
    return None


def lookup_entry(english):
    """
    Look up the full dictionary entry for an English word.
    Returns sign and chinese translations together.
    
    Args:
        english: English text to look up
        
    Returns:
        Tuple of (sign, chinese_list) if found, (None, []) otherwise
    """
    if not english or not english.strip():
        return None, []
    
    # Case-insensitive lookup for English
    entry = mongo.db.dictionary.find_one({
        'english': {'$regex': f'^{english.strip()}$', '$options': 'i'}
    })
    
    if entry:
        sign = entry.get('sign', '') or None
        chinese = entry.get('chinese', [])
        # Handle both array and legacy string format
        if isinstance(chinese, str):
            chinese = [chinese] if chinese else []
        return sign, chinese
    
    return None, []


def lookup_translation(text):
    """
    Automatically detect if text is English or Chinese and look up its translation.
    
    Args:
        text: Text to look up (either English or Chinese)
        
    Returns:
        Tuple of (english, chinese_list) - one will be the original, 
        one will be the lookup result (as list for chinese)
    """
    if not text or not text.strip():
        return None, []
    
    text = text.strip()
    
    # Check if the text contains Chinese characters
    has_chinese = any('\u4e00' <= char <= '\u9fff' for char in text)
    
    if has_chinese:
        # Text is Chinese, look up English
        english = lookup_english(text)
        return english, [text]
    else:
        # Text is English, look up Chinese
        chinese_list = lookup_chinese_all(text)
        return text, chinese_list


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
            # Have English, need Chinese - get first translation
            chinese = lookup_chinese(english_val)
            if chinese:
                if chinese_col_idx < len(cells):
                    cells[chinese_col_idx]['value'] = chinese
                    stats['chinese_filled'] += 1
            else:
                stats['not_found'] += 1
                
        elif chinese_val and not english_val:
            # Have Chinese, need English - get first match
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
            # Have English, need Chinese - get first translation
            chinese = lookup_chinese(english_val)
            if chinese:
                chinese_cell.value = chinese
                stats['chinese_filled'] += 1
            else:
                stats['not_found'] += 1
                
        elif chinese_val and not english_val:
            # Have Chinese, need English - get first match
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
    Get all dictionary entries as lookup dictionaries.
    
    Returns:
        Tuple of (english_to_chinese, chinese_to_english, english_to_sign) dictionaries
        - english_to_chinese: maps lowercase english to list of chinese translations
        - chinese_to_english: maps each chinese term to its english word
        - english_to_sign: maps lowercase english to sign name/code
    """
    entries = list(mongo.db.dictionary.find({}))
    
    english_to_chinese = {}
    chinese_to_english = {}
    english_to_sign = {}
    
    for entry in entries:
        english = entry.get('english', '').strip()
        sign = entry.get('sign', '').strip()
        chinese = entry.get('chinese', [])
        
        # Handle legacy string format
        if isinstance(chinese, str):
            chinese = [chinese] if chinese else []
        
        if english:
            english_to_chinese[english.lower()] = chinese
            english_to_sign[english.lower()] = sign
            
            # Map each Chinese translation back to this English word
            for cn in chinese:
                if cn:
                    chinese_to_english[cn] = english
    
    return english_to_chinese, chinese_to_english, english_to_sign


def batch_lookup(texts, direction='auto'):
    """
    Perform batch lookups for multiple texts.
    
    Args:
        texts: List of texts to look up
        direction: 'en_to_cn', 'cn_to_en', or 'auto'
        
    Returns:
        Dictionary mapping original texts to their translations
        - For en_to_cn: returns first Chinese translation
        - For cn_to_en: returns first English match
    """
    if not texts:
        return {}
    
    results = {}
    english_to_chinese, chinese_to_english, _ = get_all_entries_dict()
    
    for text in texts:
        if not text or not str(text).strip():
            results[text] = None
            continue
        
        text_str = str(text).strip()
        
        if direction == 'en_to_cn':
            chinese_list = english_to_chinese.get(text_str.lower(), [])
            results[text] = chinese_list[0] if chinese_list else None
        elif direction == 'cn_to_en':
            results[text] = chinese_to_english.get(text_str)
        else:
            # Auto-detect
            has_chinese = any('\u4e00' <= char <= '\u9fff' for char in text_str)
            if has_chinese:
                results[text] = chinese_to_english.get(text_str)
            else:
                chinese_list = english_to_chinese.get(text_str.lower(), [])
                results[text] = chinese_list[0] if chinese_list else None
    
    return results


def batch_lookup_all(texts, direction='auto'):
    """
    Perform batch lookups for multiple texts, returning all translations.
    
    Args:
        texts: List of texts to look up
        direction: 'en_to_cn', 'cn_to_en', or 'auto'
        
    Returns:
        Dictionary mapping original texts to their translation lists
    """
    if not texts:
        return {}
    
    results = {}
    english_to_chinese, chinese_to_english, _ = get_all_entries_dict()
    
    for text in texts:
        if not text or not str(text).strip():
            results[text] = []
            continue
        
        text_str = str(text).strip()
        
        if direction == 'en_to_cn':
            results[text] = english_to_chinese.get(text_str.lower(), [])
        elif direction == 'cn_to_en':
            english = chinese_to_english.get(text_str)
            results[text] = [english] if english else []
        else:
            # Auto-detect
            has_chinese = any('\u4e00' <= char <= '\u9fff' for char in text_str)
            if has_chinese:
                english = chinese_to_english.get(text_str)
                results[text] = [english] if english else []
            else:
                results[text] = english_to_chinese.get(text_str.lower(), [])
    
    return results
