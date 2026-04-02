---
user-invocable: true
allowed-tools: Read, Write, Glob, WebSearch, Task, AskUserQuestion
description: Conduct preliminary research on a target topic and generate a research outline. Used for academic research, benchmark research, technology selection, and similar scenarios.
---
> **Attribution:** Originally authored by [Weizhena](https://github.com/Weizhena/Deep-Research-skills). Included with attribution for use in the Deep query workflow.

# Research Skill - Preliminary Research

## Trigger Method
`/research <topic>`

## Execution Flow

### Step 1: Generate Initial Framework Using Model's Internal Knowledge
Based on the topic, use the model's existing knowledge to generate:
- A list of main research objects/items in the field
- A suggested framework of research fields

Output {step1_output} and use AskUserQuestion to confirm:
- Does the items list need additions or removals?
- Does the field framework meet the requirements?

### Step 2: Web Search Supplement
Use AskUserQuestion to inquire about the time range (e.g., last 6 months, 2024 to present, no limit).

**Parameter Collection**:
- `{topic}`: Research topic input by user
- `{YYYY-MM-DD}`: Current date
- `{step1_output}`: Complete output content generated in Step 1
- `{time_range}`: Time range specified by user

**Hard Constraint**: The following prompt must be strictly reproduced, only replacing variables in {xxx}, no rewriting of structure or wording allowed.

Launch 1 web-search-agent (background), **Prompt Template**:
```python
prompt = f"""## Task
Research Topic: {topic}
Current Date: {YYYY-MM-DD}

Based on the following preliminary framework, supplement the latest items and recommended research fields.

## Existing Framework
{step1_output}

## Objectives
1. Verify if existing items miss important objects
2. Supplement items based on missing objects
3. Continue searching for {topic}-related items within {time_range} and supplement
4. Supplement new fields

## Output Requirements
Return structured results directly (do not write files):

### Supplemented Items
- item_name: Brief explanation (why should it be included)
...

### Recommended Additional Fields
- field_name: Field description (why this dimension is needed)
...

### Information Sources
- [Source 1](url1)
- [Source 2](url2)
"""
```

**One-shot Example** (assuming research on AI Coding development history):
```
## Task
Research Topic: AI Coding Development History
Current Date: 2025-12-30

Based on the following preliminary framework, supplement the latest items and recommended research fields.

## Existing Framework
### Items List
1. GitHub Copilot: Developed by Microsoft/GitHub, first mainstream AI programming assistant
2. Cursor: AI-first IDE, based on VSCode
...

### Field Framework
- Basic Info: name, release_date, company
- Technical Features: underlying_model, context_window
...

## Objectives
1. Verify if existing items miss important objects
2. Supplement items based on missing objects
3. Continue searching for AI Coding Development History-related items within 2024 to present and supplement
4. Supplement new fields

## Output Requirements
Return structured results directly (do not write files):

### Supplemented Items
- item_name: Brief explanation (why should it be included)
...

### Recommended Additional Fields
- field_name: Field description (why this dimension is needed)
...

### Information Sources
- [Source 1](url1)
- [Source 2](url2)
```

### Step 3: Inquire About User's Existing Fields
Use AskUserQuestion to ask if the user has predefined field files, read and merge if available.

### Step 4: Generate Outline (Separate Files)
Merge {step1_output}, {step2_output} and user's existing fields to generate two files:

**outline.yaml** (items + configuration):
- topic: Research topic
- items: List of research objects
- execution:
  - batch_size: Number of parallel agents (requires AskUserQuestion confirmation)
  - items_per_agent: Number of items per agent for research (requires AskUserQuestion confirmation)
  - output_dir: Results output directory (default ./results)

**fields.yaml** (field definitions):
- Field categories and definitions
- Each field's name, description, detail_level
- detail_level hierarchy: Minimal → Brief → Detailed
- uncertain: List of uncertain fields (preserved fields, automatically filled in deep phase)

### Step 5: Output and Confirmation
- Create directory: `./{topic_slug}/`
- Save: `outline.yaml` and `fields.yaml`
- Display to user for confirmation

## Output Path
```
{current_working_directory}/{topic_slug}/
  ├── outline.yaml    # items list + execution configuration
  └── fields.yaml     # field definitions
```

## Follow-up Commands
- `/research-add-items` - Supplement items
- `/research-add-fields` - Supplement fields
- `/research-deep` - Start deep research