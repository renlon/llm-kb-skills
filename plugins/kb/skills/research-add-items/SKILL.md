---
user-invocable: true
description: Add items (research subjects) to existing research outline.
allowed-tools: Bash, Read, Write, Glob, WebSearch, Task, AskUserQuestion
---
> **Attribution:** Originally authored by [Weizhena](https://github.com/Weizhena/Deep-Research-skills). Included with attribution for use in the Deep query workflow.

# Research Add Items - Add Research Subjects

## Trigger Method
`/research-add-items`

## Execution Process

### Step 1: Auto-locate Outline
Search for `*/outline.yaml` files in the current working directory and read automatically.

### Step 2: Parallel Collection of Additional Sources
Execute simultaneously:
- **A. Ask User**: What items need to be added? Do you have specific names?
- **B. Ask About Web Search**: Should we start an agent to search for more items?

### Step 3: Merge and Update
- Append new items to outline.yaml
- Show to user for confirmation
- Avoid duplicates
- Save updated outline

## Output
Updated `{topic}/outline.yaml` file (modified in place)