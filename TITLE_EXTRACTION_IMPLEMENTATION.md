# Floor Plan Title Extraction - Implementation Summary

## Overview

Successfully implemented automatic extraction of floor plan titles from the lower-right corner title block of architectural drawings. The system automatically names floor plans when PDFs are uploaded, using OCR to extract text from the title block region.

## What Was Implemented

### 1. OCR Service Enhancement (`backend/app/services/ocr_service.py`)

Added three new methods to the `OCRService` class:

#### `extract_title_from_floorplan()`
- Extracts title/sheet information from the lower-right corner of floor plans
- Uses configurable region parameters (x, y, width, height as percentages)
- Implements multiple extraction strategies:
  - Pattern matching for "Dwg. No." or "Drawing No." fields
  - Extraction from bottom portion for large text identifiers
  - Fallback to full region text extraction
- Returns cleaned title text or None if extraction fails

#### `_clean_title_text()`
- Removes OCR artifacts (dashes, dots, border characters)
- Sanitizes filename-unsafe characters
- Normalizes whitespace and punctuation
- Returns cleaned text suitable for file/database storage

#### `_validate_title_text()`
- Validates extracted text quality
- Checks minimum/maximum length (3-100 characters)
- Rejects artifact-heavy text (>50% special characters)
- Rejects number-only text (likely page numbers)
- Filters common OCR garbage patterns

### 2. Configuration (`backend/config.py`)

Added four new configuration parameters with defaults:

```python
TITLE_REGION_X_START = 60   # Start at 60% from left
TITLE_REGION_Y_START = 85   # Start at 85% from top  
TITLE_REGION_WIDTH = 40     # Cover right 40% of image
TITLE_REGION_HEIGHT = 15    # Cover bottom 15% of image
```

These can be overridden via environment variables:
- `TITLE_REGION_X_START`
- `TITLE_REGION_Y_START`
- `TITLE_REGION_WIDTH`
- `TITLE_REGION_HEIGHT`

### 3. PDF Upload Integration (`backend/app/api/projects.py`)

Modified the `upload_floorplan()` endpoint to:

1. Import `OCRService`
2. Initialize OCR service with error handling
3. For each PDF page converted to image:
   - Attempt title extraction from lower-right corner
   - Use configurable region parameters from config
   - Log successful extractions (info level)
   - Log failures (warning level)
   - Fall back to default naming if extraction fails
4. Use extracted title as `floor_name` field in database

## Error Handling

Comprehensive error handling at multiple levels:

### OCR Service Level
- Returns `None` on any exception during extraction
- Validates text before returning
- Handles missing/corrupt images gracefully

### Upload Endpoint Level
- Try-except around OCR service initialization
- Try-except around each title extraction attempt
- Checks if OCR service is available before attempting extraction
- Always falls back to default naming: `"Floor {page_number}"`
- Detailed logging for debugging:
  - Info: Successful extraction with title
  - Debug: No title found, using default
  - Warning: Extraction errors with exception details

### Configuration Level
- All config values have sensible defaults
- Uses `.get()` with fallback values to handle missing config

## Testing Results

Tested with sample floor plan images from the uploads directory:

```
✅ LP-T1-21F_page_1.png → "21TH REFUGE FLOOR PLAN - TOWER 1" (Correct!)
✅ LP-T3-RF_page_1.png  → "ROOF FLOOR PLAN - TOWER 3" (Correct!)
```

The system successfully extracts the exact text from the **"Sheet Title & Sign No."** field in the title block.

## Usage

### Automatic (Default Behavior)

When uploading a PDF floor plan:
```
POST /api/projects/{project_id}/floorplan
```

The system automatically:
1. Converts PDF pages to images
2. Attempts title extraction from each image
3. Uses extracted title as floor plan name
4. Falls back to "Floor N" if extraction fails

### Configuration

To adjust title block region, set environment variables:

```bash
# Example: Focus on a smaller region further right
TITLE_REGION_X_START=70
TITLE_REGION_Y_START=88
TITLE_REGION_WIDTH=28
TITLE_REGION_HEIGHT=10
```

## Benefits

1. **Automated Naming**: Floor plans are automatically named with meaningful identifiers
2. **User Time Saved**: No manual renaming required
3. **Consistency**: Extracts names directly from architectural drawings
4. **Graceful Degradation**: Falls back to default naming if extraction fails
5. **Configurable**: Region parameters can be tuned for different drawing styles
6. **Non-Breaking**: Existing functionality unchanged; enhancement is additive

## Future Enhancements (Optional)

If OCR accuracy needs improvement, consider:

1. **Manual Override**: Allow users to edit auto-extracted names
2. **Multiple Strategies**: Try different OCR configurations (PSM modes)
3. **Template Matching**: Learn common title block layouts per project
4. **User Feedback Loop**: Let users mark good/bad extractions to improve accuracy
5. **Region Preview**: Show users what region is being extracted (debugging UI)

## Files Modified

1. `backend/app/services/ocr_service.py` - Added extraction methods
2. `backend/app/api/projects.py` - Integrated into upload flow
3. `backend/config.py` - Added configuration parameters

## Migration Notes

- **No database migrations required** - Uses existing `floor_name` field
- **Backward compatible** - Existing floor plans retain their names
- **Only affects new uploads** - Title extraction runs on PDF upload

## Deployment Checklist

- ✅ Code changes tested locally
- ✅ No breaking changes to existing functionality
- ✅ Error handling in place
- ✅ Logging configured
- ✅ Configuration documented
- ✅ Test files cleaned up

## Configuration Example

Add to `.env` file (optional, defaults work well):

```bash
# Title Block Extraction (optional)
TITLE_REGION_X_START=60
TITLE_REGION_Y_START=85
TITLE_REGION_WIDTH=40
TITLE_REGION_HEIGHT=15
```

---

**Implementation Date:** December 23, 2025
**Status:** ✅ Complete
**All TODOs:** ✅ Completed

