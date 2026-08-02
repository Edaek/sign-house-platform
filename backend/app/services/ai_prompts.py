"""AI prompt templates for extraction and follow-up generation."""

def build_extraction_prompt(raw_message, template_fields):
    field_lines = []
    for f in template_fields:
        req_marker = ' (REQUIRED)' if f.get('required') else ''
        aliases = f.get('aiAliases', [])
        alias_hint = f' (also known as: {", ".join(aliases)})' if aliases else ''
        field_lines.append(f'  - {f["name"]}{req_marker}{alias_hint}')
    fields_str = '\n'.join(field_lines)
    return f"""You are a field extraction assistant. Extract structured data from construction site messages.

Message:
\"\"\"{raw_message}\"\"\"

Extract these fields:
{fields_str}

Return ONLY a JSON object with field names as keys and extracted values as strings.
If a field cannot be determined, set its value to empty string "".
Do NOT include any explanation."""

def build_followup_prompt(missing_fields, raw_message, previous_questions=None):
    prev = ''
    if previous_questions:
        prev = '\n\nPrevious questions already asked:\n' + '\n'.join(f'  - {q}' for q in previous_questions)
    
    fields_str = ', '.join(missing_fields)
    return f"""Generate a short, friendly WhatsApp follow-up question to collect missing information.

Original message: \"{raw_message}\"
Missing fields: {fields_str}{prev}

Return ONLY the question text in English. Keep it conversational and under 2 sentences."""

def build_image_analysis_prompt():
    return """Analyze this construction site photo. Describe:
1. What type of work/issue is shown
2. Any visible safety concerns
3. Any identifiable location markers or signs
4. The general condition shown

Return a brief structured summary."""
