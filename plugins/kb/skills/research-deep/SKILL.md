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

Read the prompt template from `prompts/deep-research-agent.md` relative to this skill's directory. Replace `{item_related_info}`, `{output_path}`, and `{fields_path}` with the collected parameters.

**Hard Constraint**: The prompt must be strictly reproduced from the template file, only replacing variables in `{xxx}`, no rewriting of structure or wording allowed.

**One-shot Example**: See `prompts/deep-research-agent-example.md` relative to this skill's directory for a concrete example (GitHub Copilot).

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