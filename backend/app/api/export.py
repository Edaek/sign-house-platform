import os
from datetime import datetime
from flask import Blueprint, request, jsonify, send_file, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId
from app import mongo
from app.models import serialize_doc, create_sign_table_doc, create_sign_row, sign_table_to_dict
from app.services.excel_service import ExcelService
from app.services.dictionary_service import lookup_chinese

export_bp = Blueprint('export', __name__)


@export_bp.route('/preview/<project_id>', methods=['GET'])
@jwt_required()
def preview_export(project_id):
    """Preview all extracted data for a project."""
    user_id = get_jwt_identity()
    
    try:
        project = mongo.db.projects.find_one({
            '_id': ObjectId(project_id),
            'user_id': ObjectId(user_id)
        })
    except:
        return jsonify({'error': 'Invalid project ID'}), 400
    
    if not project:
        return jsonify({'error': 'Project not found'}), 404
    
    # Get all extracted data from all floorplans
    floorplans = list(mongo.db.floorplans.find({
        'project_id': ObjectId(project_id)
    }).sort('floor_number', 1))
    
    all_data = []
    summary_groups = {}  # For cross-floor summary
    
    for fp in floorplans:
        extracted = list(mongo.db.extracted_data.find({
            'floorplan_id': fp['_id']
        }).sort('shape_index', 1))
        
        for data in extracted:
            display_text = data.get('manual_text') or data.get('extracted_text') or ''
            quantity = data.get('quantity', 1)
            merged_count = data.get('merged_count', 1)
            
            # Add to per-floor data
            all_data.append({
                'floor_number': fp['floor_number'],
                'floor_name': fp['floor_name'],
                'shape_index': data['shape_index'],
                'text': display_text,
                'quantity': quantity,
                'merged_count': merged_count,
                'confidence': round((data.get('confidence') or 0) * 100, 1),
                'is_manual': data.get('is_manual', False)
            })
            
            # Group for cross-floor summary
            normalized_text = display_text.strip().lower()
            if normalized_text:  # Skip empty text
                if normalized_text not in summary_groups:
                    summary_groups[normalized_text] = {
                        'text': display_text,  # Keep original case from first occurrence
                        'total_quantity': 0,
                        'floors': set(),
                        'floor_details': []
                    }
                
                summary_groups[normalized_text]['total_quantity'] += quantity
                summary_groups[normalized_text]['floors'].add(fp['floor_number'])
                summary_groups[normalized_text]['floor_details'].append({
                    'floor_number': fp['floor_number'],
                    'floor_name': fp['floor_name'],
                    'quantity': quantity
                })
    
    # Convert summary groups to list and sort
    summary = []
    for normalized_text, group_data in summary_groups.items():
        floors_list = sorted(list(group_data['floors']))
        summary.append({
            'text': group_data['text'],
            'total_quantity': group_data['total_quantity'],
            'floor_count': len(floors_list),
            'floors': floors_list,
            'floor_details': group_data['floor_details']
        })
    
    # Sort summary by text
    summary.sort(key=lambda x: x['text'].lower())
    
    # Get template columns if available
    columns = []
    template = mongo.db.templates.find_one({'project_id': ObjectId(project_id)})
    if template:
        columns = template.get('columns', [])
    
    return jsonify({
        'project': serialize_doc(project),
        'columns': columns,
        'data': all_data,
        'total_items': len(all_data),
        'summary': summary,
        'summary_stats': {
            'unique_items': len(summary),
            'total_floors': len(floorplans)
        }
    }), 200


@export_bp.route('/excel/<project_id>', methods=['POST'])
@jwt_required()
def export_to_excel(project_id):
    """Export project data to Excel using the sign table structure."""
    user_id = get_jwt_identity()
    
    try:
        project = mongo.db.projects.find_one({
            '_id': ObjectId(project_id),
            'user_id': ObjectId(user_id)
        })
    except:
        return jsonify({'error': 'Invalid project ID'}), 400
    
    if not project:
        return jsonify({'error': 'Project not found'}), 404
    
    try:
        # Get or generate sign table data
        sign_table = mongo.db.project_sign_data.find_one({
            'project_id': ObjectId(project_id)
        })
        
        if not sign_table:
            # Generate it if it doesn't exist
            generated_rows, floorplan_columns = _generate_sign_table_from_ocr(project_id)
            sign_table_doc = create_sign_table_doc(project_id, generated_rows, floorplan_columns)
            result = mongo.db.project_sign_data.insert_one(sign_table_doc)
            sign_table = mongo.db.project_sign_data.find_one({'_id': result.inserted_id})
        
        rows = sign_table.get('rows', [])
        floorplan_columns = sign_table.get('floorplan_columns', [])
        
        if not rows:
            return jsonify({'error': 'No data to export. Process floor plans first.'}), 400
        
        excel_service = ExcelService()
        
        # Create export file
        output_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'exports')
        os.makedirs(output_dir, exist_ok=True)
        
        # Sanitize project name for filename
        import re
        safe_name = re.sub(r'[^\w\s-]', '', project["name"]).strip().replace(' ', '_')
        output_path = os.path.join(output_dir, f'export_{project_id}_{safe_name}.xlsx')
        
        # Build column headers: #, Sign No., Sign, English, Chinese, [floor columns...]
        fixed_columns = ['#', 'Sign No.', 'Sign', 'English', 'Chinese']
        all_columns = fixed_columns + floorplan_columns
        
        # Create workbook
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment
        
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = 'Sign Data'
        
        # Row 1: Project name (merged across all columns)
        project_name = project.get('name', 'Untitled Project')
        sheet.cell(row=1, column=1, value=project_name)
        sheet.cell(row=1, column=1).font = Font(bold=True, size=14)
        sheet.cell(row=1, column=1).alignment = Alignment(horizontal='left', vertical='center')
        
        # Row 2: Column headers
        for col_idx, column in enumerate(all_columns, start=1):
            cell = sheet.cell(row=2, column=col_idx)
            cell.value = column
            cell.font = excel_service.header_style['font']
            cell.fill = excel_service.header_style['fill']
            cell.alignment = excel_service.header_style['alignment']
            cell.border = excel_service.header_style['border']
        
        # Write data rows (starting from row 3)
        for row_idx, row_data in enumerate(rows, start=3):
            # Fixed columns
            sheet.cell(row=row_idx, column=1, value=row_data.get('row_number', row_idx - 1))
            sheet.cell(row=row_idx, column=2, value=row_data.get('sign_no', ''))
            sheet.cell(row=row_idx, column=3, value=row_data.get('sign', ''))
            sheet.cell(row=row_idx, column=4, value=row_data.get('english', ''))
            sheet.cell(row=row_idx, column=5, value=row_data.get('chinese', ''))
            
            # Floor count columns
            floor_counts = row_data.get('floor_counts', {})
            for col_offset, floor_name in enumerate(floorplan_columns):
                count = floor_counts.get(floor_name, 0)
                if count > 0:
                    sheet.cell(row=row_idx, column=6 + col_offset, value=count)
            
            # Apply cell styles
            for col_idx in range(1, len(all_columns) + 1):
                cell = sheet.cell(row=row_idx, column=col_idx)
                cell.alignment = excel_service.cell_style['alignment']
                cell.border = excel_service.cell_style['border']
        
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
            sheet.column_dimensions[column].width = max(adjusted_width, 10)
        
        # Save workbook
        workbook.save(output_path)
        workbook.close()
        
        return send_file(
            output_path,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'{project["name"]}_export.xlsx'
        )
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        current_app.logger.error(f'Export failed: {str(e)}\n{error_trace}')
        return jsonify({'error': f'Export failed: {str(e)}'}), 500


@export_bp.route('/csv/<project_id>', methods=['POST'])
@jwt_required()
def export_to_csv(project_id):
    """Export project data to CSV using the sign table structure."""
    user_id = get_jwt_identity()
    
    try:
        project = mongo.db.projects.find_one({
            '_id': ObjectId(project_id),
            'user_id': ObjectId(user_id)
        })
    except:
        return jsonify({'error': 'Invalid project ID'}), 400
    
    if not project:
        return jsonify({'error': 'Project not found'}), 404
    
    try:
        import csv
        
        # Get or generate sign table data
        sign_table = mongo.db.project_sign_data.find_one({
            'project_id': ObjectId(project_id)
        })
        
        if not sign_table:
            # Generate it if it doesn't exist
            generated_rows, floorplan_columns = _generate_sign_table_from_ocr(project_id)
            sign_table_doc = create_sign_table_doc(project_id, generated_rows, floorplan_columns)
            result = mongo.db.project_sign_data.insert_one(sign_table_doc)
            sign_table = mongo.db.project_sign_data.find_one({'_id': result.inserted_id})
        
        rows = sign_table.get('rows', [])
        floorplan_columns = sign_table.get('floorplan_columns', [])
        
        if not rows:
            return jsonify({'error': 'No data to export. Process floor plans first.'}), 400
        
        # Create export file
        output_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'exports')
        os.makedirs(output_dir, exist_ok=True)
        
        import re
        safe_name = re.sub(r'[^\w\s-]', '', project["name"]).strip().replace(' ', '_')
        output_path = os.path.join(output_dir, f'export_{project_id}_{safe_name}.csv')
        
        # Build column headers
        fixed_columns = ['#', 'Sign No.', 'Sign', 'English', 'Chinese']
        all_columns = fixed_columns + floorplan_columns
        
        # Write CSV
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(all_columns)
            
            for row_data in rows:
                row = [
                    row_data.get('row_number', ''),
                    row_data.get('sign_no', ''),
                    row_data.get('sign', ''),
                    row_data.get('english', ''),
                    row_data.get('chinese', '')
                ]
                
                # Add floor counts
                floor_counts = row_data.get('floor_counts', {})
                for floor_name in floorplan_columns:
                    count = floor_counts.get(floor_name, 0)
                    row.append(count if count > 0 else '')
                
                writer.writerow(row)
        
        return send_file(
            output_path,
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'{project["name"]}_export.csv'
        )
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        current_app.logger.error(f'CSV Export failed: {str(e)}\n{error_trace}')
        return jsonify({'error': f'Export failed: {str(e)}'}), 500


@export_bp.route('/complete/<project_id>', methods=['POST'])
@jwt_required()
def mark_complete(project_id):
    """Mark a project as completed."""
    user_id = get_jwt_identity()
    
    try:
        project = mongo.db.projects.find_one({
            '_id': ObjectId(project_id),
            'user_id': ObjectId(user_id)
        })
    except:
        return jsonify({'error': 'Invalid project ID'}), 400
    
    if not project:
        return jsonify({'error': 'Project not found'}), 404
    
    # Check if all floorplans are completed
    incomplete = mongo.db.floorplans.count_documents({
        'project_id': ObjectId(project_id),
        'status': {'$ne': 'completed'}
    })
    
    if incomplete > 0:
        return jsonify({
            'warning': f'{incomplete} floor(s) not yet completed',
            'project': serialize_doc(project)
        }), 200
    
    from datetime import datetime
    mongo.db.projects.update_one(
        {'_id': ObjectId(project_id)},
        {'$set': {'status': 'completed', 'updated_at': datetime.utcnow()}}
    )
    
    project = mongo.db.projects.find_one({'_id': ObjectId(project_id)})
    
    return jsonify({
        'message': 'Project marked as completed',
        'project': serialize_doc(project)
    }), 200


@export_bp.route('/template-data/<project_id>', methods=['GET'])
@jwt_required()
def get_template_data(project_id):
    """Get template data merged with OCR extracted data."""
    user_id = get_jwt_identity()
    
    try:
        project = mongo.db.projects.find_one({
            '_id': ObjectId(project_id),
            'user_id': ObjectId(user_id)
        })
    except:
        return jsonify({'error': 'Invalid project ID'}), 400
    
    if not project:
        return jsonify({'error': 'Project not found'}), 404
    
    # Get template
    template = mongo.db.templates.find_one({'project_id': ObjectId(project_id)})
    if not template:
        return jsonify({'error': 'No template uploaded for this project'}), 404
    
    template_path = template.get('filepath')
    if not template_path or not os.path.exists(template_path):
        return jsonify({'error': 'Template file not found'}), 404
    
    try:
        excel_service = ExcelService()
        
        # Read template data
        template_data = excel_service.read_template_data(template_path)
        
        # Get OCR extracted data
        floorplans = list(mongo.db.floorplans.find({
            'project_id': ObjectId(project_id)
        }).sort('floor_number', 1))
        
        ocr_data = []
        for fp in floorplans:
            extracted = list(mongo.db.extracted_data.find({
                'floorplan_id': fp['_id']
            }).sort('shape_index', 1))
            
            for item in extracted:
                display_text = item.get('manual_text') or item.get('extracted_text') or ''
                ocr_data.append({
                    'floor_number': fp['floor_number'],
                    'floor_name': fp['floor_name'],  # Include floor name for auto-matching
                    'text': display_text,
                    'quantity': item.get('quantity', 1)
                })
        
        # Get floor mapping (optional - auto-matching will work without it)
        floor_mapping = template.get('floor_mapping', {})
        
        # Merge OCR data into template (auto-matches floor names to columns)
        template_data = excel_service.merge_with_ocr_data(
            template_data,
            ocr_data,
            floor_mapping  # Pass mapping as optional override
        )
        
        return jsonify({
            'template': serialize_doc(template),
            'data': template_data
        }), 200
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        current_app.logger.error(f'Failed to read template data: {str(e)}\n{error_trace}')
        return jsonify({'error': f'Failed to read template: {str(e)}'}), 500


@export_bp.route('/template-data/<project_id>', methods=['PUT'])
@jwt_required()
def update_template_data(project_id):
    """Update cells in the template file."""
    user_id = get_jwt_identity()
    
    try:
        project = mongo.db.projects.find_one({
            '_id': ObjectId(project_id),
            'user_id': ObjectId(user_id)
        })
    except:
        return jsonify({'error': 'Invalid project ID'}), 400
    
    if not project:
        return jsonify({'error': 'Project not found'}), 404
    
    # Get template
    template = mongo.db.templates.find_one({'project_id': ObjectId(project_id)})
    if not template:
        return jsonify({'error': 'No template uploaded for this project'}), 404
    
    template_path = template.get('filepath')
    if not template_path or not os.path.exists(template_path):
        return jsonify({'error': 'Template file not found'}), 404
    
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    try:
        excel_service = ExcelService()
        
        # Support both single cell and batch updates
        if 'updates' in data:
            # Batch update
            updates = data['updates']
            if not isinstance(updates, list):
                return jsonify({'error': 'updates must be an array'}), 400
            
            results = excel_service.update_cells_batch(template_path, updates)
            return jsonify({
                'message': f'Updated {len(results)} cells',
                'cells': results
            }), 200
        else:
            # Single cell update
            row = data.get('row')
            col = data.get('col')
            value = data.get('value')
            
            if row is None or col is None:
                return jsonify({'error': 'row and col are required'}), 400
            
            result = excel_service.update_cell(template_path, row, col, value)
            return jsonify({
                'message': 'Cell updated',
                'cell': result
            }), 200
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        current_app.logger.error(f'Failed to update template: {str(e)}\n{error_trace}')
        return jsonify({'error': f'Failed to update template: {str(e)}'}), 500


def _generate_sign_table_from_ocr(project_id):
    """Generate sign table data from OCR extracted data.
    
    Returns:
        Tuple of (rows, floorplan_columns) where:
        - rows: List of sign row dicts
        - floorplan_columns: List of floor names
    """
    # Get all floorplans for the project
    floorplans = list(mongo.db.floorplans.find({
        'project_id': ObjectId(project_id)
    }).sort('floor_number', 1))
    
    # Collect floor names for columns
    floorplan_columns = [fp['floor_name'] for fp in floorplans]
    
    # Group OCR data by unique sign number (normalized text)
    sign_groups = {}
    
    for fp in floorplans:
        floor_name = fp['floor_name']
        
        extracted = list(mongo.db.extracted_data.find({
            'floorplan_id': fp['_id']
        }))
        
        for item in extracted:
            display_text = item.get('manual_text') or item.get('extracted_text') or ''
            sign_no = display_text.strip()
            
            if not sign_no:
                continue
            
            # Use normalized text as key for grouping
            normalized_key = sign_no.lower()
            quantity = item.get('quantity', 1)
            
            if normalized_key not in sign_groups:
                sign_groups[normalized_key] = {
                    'sign_no': sign_no,  # Keep original case
                    'floor_counts': {}
                }
            
            # Add count for this floor
            if floor_name in sign_groups[normalized_key]['floor_counts']:
                sign_groups[normalized_key]['floor_counts'][floor_name] += quantity
            else:
                sign_groups[normalized_key]['floor_counts'][floor_name] = quantity
    
    # Sort by sign_no and create rows with auto-increment
    sorted_signs = sorted(sign_groups.values(), key=lambda x: x['sign_no'].lower())
    
    rows = []
    for idx, sign_data in enumerate(sorted_signs, start=1):
        rows.append(create_sign_row(
            row_number=idx,
            sign_no=sign_data['sign_no'],
            floor_counts=sign_data['floor_counts'],
            sign='',
            english='',
            chinese=''
        ))
    
    return rows, floorplan_columns


@export_bp.route('/sign-table/<project_id>', methods=['GET'])
@jwt_required()
def get_sign_table(project_id):
    """Get or generate sign table data for a project.
    
    The sign table aggregates OCR data by unique sign number and shows
    counts per floorplan. User-editable fields (sign, english, chinese)
    are preserved across regenerations.
    """
    user_id = get_jwt_identity()
    
    try:
        project = mongo.db.projects.find_one({
            '_id': ObjectId(project_id),
            'user_id': ObjectId(user_id)
        })
    except:
        return jsonify({'error': 'Invalid project ID'}), 400
    
    if not project:
        return jsonify({'error': 'Project not found'}), 404
    
    # Check if sign table already exists
    existing_table = mongo.db.project_sign_data.find_one({
        'project_id': ObjectId(project_id)
    })
    
    # Generate fresh data from OCR
    generated_rows, floorplan_columns = _generate_sign_table_from_ocr(project_id)
    
    if existing_table:
        # Merge user-edited fields from existing table
        existing_rows_map = {row['sign_no'].lower(): row for row in existing_table.get('rows', [])}
        
        merged_rows = []
        for gen_row in generated_rows:
            key = gen_row['sign_no'].lower()
            if key in existing_rows_map:
                # Preserve user-edited fields
                existing = existing_rows_map[key]
                gen_row['sign'] = existing.get('sign', '')
                gen_row['english'] = existing.get('english', '')
                gen_row['chinese'] = existing.get('chinese', '')
            merged_rows.append(gen_row)
        
        # Update existing document
        mongo.db.project_sign_data.update_one(
            {'_id': existing_table['_id']},
            {'$set': {
                'rows': merged_rows,
                'floorplan_columns': floorplan_columns,
                'updated_at': datetime.utcnow()
            }}
        )
        
        sign_table = mongo.db.project_sign_data.find_one({'_id': existing_table['_id']})
    else:
        # Create new sign table
        sign_table_doc = create_sign_table_doc(project_id, generated_rows, floorplan_columns)
        result = mongo.db.project_sign_data.insert_one(sign_table_doc)
        sign_table = mongo.db.project_sign_data.find_one({'_id': result.inserted_id})
    
    return jsonify({
        'sign_table': sign_table_to_dict(sign_table),
        'project': serialize_doc(project)
    }), 200


@export_bp.route('/sign-table/<project_id>', methods=['PUT'])
@jwt_required()
def update_sign_table(project_id):
    """Update a cell in the sign table.
    
    Request body:
        {
            "row_number": 1,
            "field": "sign" | "english" | "chinese",
            "value": "new value"
        }
    
    When the english field is updated, chinese is auto-filled from dictionary.
    """
    user_id = get_jwt_identity()
    
    try:
        project = mongo.db.projects.find_one({
            '_id': ObjectId(project_id),
            'user_id': ObjectId(user_id)
        })
    except:
        return jsonify({'error': 'Invalid project ID'}), 400
    
    if not project:
        return jsonify({'error': 'Project not found'}), 404
    
    # Get request data
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    row_number = data.get('row_number')
    field = data.get('field')
    value = data.get('value', '')
    
    if row_number is None:
        return jsonify({'error': 'row_number is required'}), 400
    
    if field not in ['sign', 'english', 'chinese']:
        return jsonify({'error': 'field must be one of: sign, english, chinese'}), 400
    
    # Get existing sign table
    sign_table = mongo.db.project_sign_data.find_one({
        'project_id': ObjectId(project_id)
    })
    
    if not sign_table:
        return jsonify({'error': 'Sign table not found. Generate it first.'}), 404
    
    # Find and update the row
    rows = sign_table.get('rows', [])
    updated = False
    chinese_auto_filled = None
    
    for row in rows:
        if row['row_number'] == row_number:
            row[field] = value
            updated = True
            
            # Auto-fill Chinese when English is updated
            if field == 'english' and value:
                chinese_translation = lookup_chinese(value)
                if chinese_translation:
                    row['chinese'] = chinese_translation
                    chinese_auto_filled = chinese_translation
            
            break
    
    if not updated:
        return jsonify({'error': f'Row {row_number} not found'}), 404
    
    # Save updated table
    mongo.db.project_sign_data.update_one(
        {'_id': sign_table['_id']},
        {'$set': {
            'rows': rows,
            'updated_at': datetime.utcnow()
        }}
    )
    
    response = {
        'message': 'Cell updated',
        'row_number': row_number,
        'field': field,
        'value': value
    }
    
    if chinese_auto_filled:
        response['chinese_auto_filled'] = chinese_auto_filled
    
    return jsonify(response), 200