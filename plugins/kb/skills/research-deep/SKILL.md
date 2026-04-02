---
user-invocable: true
description: Read research outline and launch independent agents for in-depth research on each item. Task output disabled.
allowed-tools: Bash, Read, Write, Glob, WebSearch, Task
---
> **Attribution:** Originally authored by [Weizhena](https://github.com/Weizhena/Deep-Research-skills). Included with attribution for use in the Deep query workflow.

# Research Deep - Deep Research

## Trigger Method
`/research-deep`

## Execution Flow

### Step 1: Auto-locate Outline
Find `*/outline.yaml` file in current working directory, read items list and execution configuration (including items_per_agent).

### Step 2: Resume From Checkpoint
- Check completed JSON files in output_dir
- Skip already completed items

### Step 3: Batch Execution
- Execute in batches by batch_size (need user approval to proceed to next batch after completing one)
- Each agent handles items_per_agent projects
- Launch web-search-agent (background parallel, task output disabled)

**Parameter Retrieval**:
- `{topic}`: topic field from outline.yaml
- `{item_name}`: name field of item
- `{item_related_info}`: complete yaml content of item (name + category + description etc.)
- `{output_dir}`: execution.output_dir from outline.yaml (default ./results)
- `{fields_path}`: absolute path to {topic}/fields.yaml
- `{output_path}`: absolute path to {output_dir}/{item_name_slug}.json (slugify item_name: replace spaces with _, remove special characters)

**Hard Constraint**: The following prompt must be strictly recited, only replace variables in {xxx}, do not rewrite structure or wording.

**Prompt Template**:
```python
prompt = f"""## Task
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
"""
```

**One-shot Example** (assuming research on GitHub Copilot):
```
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
```

### Step 4: Wait and Monitor
- Wait for current batch to complete
- Launch next batch
- Show progress

### Step 5: Summary Report
After all completion, output:
- Number of completed items
- Failed/uncertain marked items
- Output directory

## Agent Configuration
- Background execution: Yes
- Task Output: Disabled (agent has clear output file when completed)
- Resume from checkpoint: Yes