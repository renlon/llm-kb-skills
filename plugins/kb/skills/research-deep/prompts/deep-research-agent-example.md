## Task
Research name: GitHub Copilot
category: International Product
description: Developed by Microsoft/GitHub, first mainstream AI programming assistant, market share about 40%, output structured JSON to /home/weizhena/AIcoding/aicoding-history/results/GitHub_Copilot.json

## Field Definitions
Read /home/weizhena/AIcoding/aicoding-history/fields.yaml to get all field definitions

## Output Requirements
1. Output JSON according to fields defined in fields.yaml
2. Mark uncertain field values as [不确定]
3. Add uncertain array at end of JSON, listing all uncertain field names
4. All field values must be output in Chinese (research process can use English, but final JSON values in Chinese)

## Output Path
/home/weizhena/AIcoding/aicoding-history/results/GitHub_Copilot.json

## Validation
After completing JSON output, run validation script to ensure complete field coverage:
python ~/.claude/skills/research/validate_json.py -f /home/weizhena/AIcoding/aicoding-history/fields.yaml -j /home/weizhena/AIcoding/aicoding-history/results/GitHub_Copilot.json
Task is only complete after validation passes.
