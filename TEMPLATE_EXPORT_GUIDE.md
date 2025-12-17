# Excel Template Export System - User Guide

## Overview

The system now supports exporting extracted floorplan data to your custom Excel templates by matching Sign No. values and updating quantities in the correct floor-specific columns.

## How It Works

### 1. Template Structure Requirements

Your Excel template should have:
- **Row 1**: Column headers
- **Sign No. column**: Contains sign identifiers (e.g., "S10-3", "S11", "S10-125")
- **Floor columns**: Columns for each floor (e.g., "8/F", "21/F", "9/F-20/F...")
- **Data rows**: Existing signs with their information

### 2. Data Flow

```
PDF Floorplans → OCR Extraction → Floor Mapping → Template Export
                      ↓                  ↓              ↓
                 "S10-125"         Floor 1 → 21/F    Update/Add Row
                 Qty: 2            Floor 2 → 8/F     in Template
```

## Step-by-Step Usage

### Step 1: Upload Your Template

1. Go to your project page
2. Upload your Excel template (.xlsx file)
3. The system will parse and store the column structure

### Step 2: Process Floorplans

1. Upload PDF floorplans for your project
2. Run shape detection on each floor
3. Run OCR to extract sign text and quantities
4. Review and correct any misidentified text

### Step 3: Configure Floor Mapping

1. Navigate to the Export page
2. You'll see the "Floor Mapping" section
3. Map each extracted floor to a template column:
   - Floor 1 → Select "21/F" (or your column name)
   - Floor 2 → Select "8/F" (or your column name)
   - etc.
4. Click "Save Mapping"

### Step 4: Export to Excel

1. Click "Download Excel"
2. The system will:
   - Load your template
   - Group data by Sign No.
   - Find existing rows by Sign No. and update quantities
   - Append new rows for signs not in template
   - Save the updated file

## Example

**Extracted Data:**
- Floor 1: S10-125, Qty: 2
- Floor 2: S10-125, Qty: 1
- Floor 1: S11, Qty: 3

**Floor Mapping:**
- Floor 1 → 21/F
- Floor 2 → 8/F

**Template Update:**
- Find row with "S10-125" in Sign No. column
  - Add 2 to "21/F" column
  - Add 1 to "8/F" column
- Find row with "S11" in Sign No. column
  - Add 3 to "21/F" column

## API Endpoints

### Save Floor Mapping
```
PUT /api/projects/<project_id>/template/mapping
Body: { "floor_mapping": { "1": "21/F", "2": "8/F" } }
```

### Get Floor Mapping
```
GET /api/projects/<project_id>/template/mapping
Returns: { "floor_mapping": {...}, "columns": [...] }
```

### Export with Template
```
POST /api/export/excel/<project_id>
Response: Excel file download (uses floor mapping automatically)
```

## Technical Details

### Backend Implementation

**ExcelService.export_with_template_mapping()**
- Groups extracted data by sign text
- Maps floor numbers to column names using floor_mapping
- Searches template for existing rows by Sign No.
- Updates quantities in mapped floor columns
- Appends new rows for unknown signs

**Key Features:**
- Accumulative quantities (adds to existing values)
- Smart row matching by Sign No.
- Automatic new row creation
- Preserves template formatting

### Frontend Implementation

**Floor Mapping UI**
- Displays all unique floors from extracted data
- Shows available floor columns from template
- Dropdown selection for each floor
- Save/load mapping from database
- Validation before export

## Error Handling

### "Floor mapping not configured"
- **Cause**: Template exists but no floor mapping saved
- **Solution**: Configure floor mapping in Export page

### "Column 'Sign No.' not found in template"
- **Cause**: Template doesn't have a "Sign No." column
- **Solution**: Ensure your template has this column in row 1

### "Template not found"
- **Cause**: No template uploaded for project
- **Solution**: Upload template in project settings

## Best Practices

1. **Upload template first** before processing floorplans
2. **Review OCR results** for accuracy before export
3. **Configure floor mapping** once and it's saved for future exports
4. **Test with small dataset** first to verify column mapping
5. **Keep template consistent** - don't change column names after mapping

## Troubleshooting

**Issue**: Export fails with "Export failed" error
- Check backend logs for specific error message
- Verify template file still exists
- Ensure floor mapping is configured

**Issue**: Quantities not appearing in correct columns
- Verify floor mapping is correct
- Check that template column names match exactly
- Review floor numbers in extracted data

**Issue**: New signs not appearing
- Signs are appended to the bottom of the template
- Check the last rows of the exported file

## Future Enhancements

Potential improvements:
- Auto-detect floor column mapping based on naming patterns
- Support for multiple sign columns
- Batch export for multiple projects
- Template validation on upload
- Preview of export before download

