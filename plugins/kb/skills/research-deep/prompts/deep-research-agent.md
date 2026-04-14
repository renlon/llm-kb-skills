## Task
Research {item_related_info}, output structured JSON to {output_path}

## Field Definitions
Read {fields_path} to get all field definitions

## Output Requirements
1. Output JSON according to fields defined in fields.yaml
2. Mark uncertain field values as [不确定]
3. Add uncertain array at end of JSON, listing all uncertain field names
4. All field values must be output in Chinese (research process can use English, but final JSON values in Chinese)

## Output Path
{output_path}

## Validation
After completing JSON output, run validation script to ensure complete field coverage:
python ~/.claude/skills/research/validate_json.py -f {fields_path} -j {output_path}
Task is only complete after validation passes.
