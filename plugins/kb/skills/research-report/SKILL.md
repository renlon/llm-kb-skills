---
user-invocable: true
description: Summarize deep research results into a markdown report, covering all fields, skipping uncertain values.
allowed-tools: Read, Write, Glob, Bash, AskUserQuestion
---
> **Attribution:** Originally authored by [Weizhena](https://github.com/Weizhena/Deep-Research-skills). Included with attribution for use in the Deep query workflow.

# Research Report - Summary Report

## Trigger Method
`/research-report`

## Execution Flow

### Step 1: Locate Results Directory
Find `*/outline.yaml` in current working directory, read topic and output_dir configuration.

### Step 2: Scan Optional Summary Fields
Read all JSON results and extract fields suitable for display in the table of contents (numeric, short indicators), such as:
- github_stars
- google_scholar_cites
- swe_bench_score
- user_scale
- valuation
- release_date

Use AskUserQuestion to ask the user:
- Which fields should be displayed in the table of contents besides item names?
- Provide dynamic option list (based on fields actually present in JSONs)

### Step 3: Generate Python Conversion Script
Generate `generate_report.py` in the `{topic}/` directory with requirements:
- Read all JSONs from output_dir
- Read fields.yaml to get field structure
- Cover all field values from each JSON
- Skip fields containing [uncertain] values
- Skip fields listed in uncertain array
- Generate markdown report format: table of contents (with anchor jumps + user-selected summary fields) + detailed content (organized by field categories)
- Save to `{topic}/report.md`

**Table of Contents Format Requirements**:
- Must include every item
- Each item displays: sequence number, name (anchor link), user-selected summary fields
- Example: `1. [GitHub Copilot](#github-copilot) - Stars: 10k | Score: 85%`

#### Script Technical Points (Must Follow)

**1. JSON Structure Compatibility**
Support two JSON structures:
- Flat structure: fields directly at top level `{"name": "xxx", "release_date": "xxx"}`
- Nested structure: fields in category sub-dicts `{"basic_info": {"name": "xxx"}, "technical_features": {...}}`

Field lookup order: top level -> category mapping key -> traverse all nested dicts

**2. Category Multilingual Mapping**
Category names in fields.yaml and JSON keys can be any combination (Chinese-Chinese, Chinese-English, English-Chinese, English-English). Must establish bidirectional mapping:
```python
CATEGORY_MAPPING = {
    "Basic Info": ["basic_info", "基本信息"],
    "Technical Features": ["technical_features", "technical_characteristics", "技术特性"],
    "Performance Metrics": ["performance_metrics", "performance", "性能指标"],
    "Milestone Significance": ["milestone_significance", "milestones", "里程碑意义"],
    "Business Info": ["business_info", "commercial_info", "商业信息"],
    "Competition & Ecosystem": ["competition_ecosystem", "competition", "竞争与生态"],
    "History": ["history", "历史沿革"],
    "Market Positioning": ["market_positioning", "market", "市场定位"],
}
```

**3. Complex Value Formatting**
- list of dicts (like key_events, funding_history): format each dict as one line, separate kv with ` | `
- Regular lists: short lists joined with commas, long lists displayed with line breaks
- Nested dicts: recursively format, display with semicolons or line breaks
- Long text strings (over 100 characters): add line breaks `<br>` or use blockquote format for better readability

**4. Additional Field Collection**
Collect fields present in JSON but not defined in fields.yaml, put into "Other Information" category. Note filtering:
- Internal fields: `_source_file`, `uncertain`
- Nested structure top-level keys: `basic_info`, `technical_features`, etc.
- `uncertain` array: display each field name line by line, don't compress into one line

**5. Uncertain Value Skipping**
Skip conditions:
- Field value contains `[uncertain]` string
- Field name is in `uncertain` array
- Field value is None or empty string

### Step 4: Execute Script
Run `python {topic}/generate_report.py`

## Output
- `{topic}/generate_report.py` - Conversion script
- `{topic}/report.md` - Summary report