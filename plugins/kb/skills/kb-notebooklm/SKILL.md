---
name: kb-notebooklm
user-invocable: true
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, Agent, AskUserQuestion
description: "Use when the user wants to generate NotebookLM content (podcasts, quizzes, reports, digests) from KB sources, or when user says 'podcast', 'quiz', 'flashcards', 'digest', 'research audio', or '/kb-notebooklm'. Also triggers on intent like 'create a podcast from my lessons', 'quiz me on recent lessons', 'summarize wiki changes'."
---

# kb-notebooklm Skill — Knowledge Base to NotebookLM Bridge

Bridge the user's MLL (My Lessons Learned) knowledge base with Google NotebookLM to automate content generation. This skill provides intelligent orchestration for creating podcasts, quizzes, digests, reports, and research audio from KB sources.

**Invocation:** `/kb-notebooklm <subcommand>` or natural language

**Executor:** Opus single-pass with Agent delegation for parallel workflows

## Overview

This skill operates in two layers:

1. **Content Pipeline:** Automatically selects relevant KB files (lessons, wiki articles, research reports) based on timestamps, topics, and content type
2. **Intelligent Orchestrator:** Routes requests to the global NotebookLM skill with proper notebook selection, source management, and state tracking

**Key Design Principles:**
- Builds on top of the global NotebookLM skill (does not duplicate API interaction)
- Single-writer concurrency model (one MLL operation at a time)
- All `notebooklm` CLI commands use explicit `--notebook <id>` or `-n <id>`, never `notebooklm use`
- State managed in `.notebooklm-state.yaml` (separate from kb.yaml)
- Configuration in `kb.yaml` under `integrations.notebooklm`

## Common Preamble (Prerequisites)

**MUST BE THE FIRST ACTION ON EVERY INVOCATION:**

1. **Check NotebookLM CLI installation:**
   ```bash
   which notebooklm
   ```
   If not found, report: "NotebookLM CLI not installed. Run: `pip install notebooklm-py`" and STOP.

2. **Check authentication:**
   ```bash
   notebooklm auth check --json
   ```
   If fails, report: "NotebookLM not authenticated. Run: `notebooklm login` and follow the prompts." and STOP.

3. **Read configuration:**
   ```bash
   # Read kb.yaml
   ```
   Check for `integrations.notebooklm` section. If missing or `enabled: false`, report: "NotebookLM integration not enabled in kb.yaml. Add:\n```yaml\nintegrations:\n  notebooklm:\n    enabled: true\n```" and STOP.

4. **Initialize or read state file:**
   ```bash
   # Read .notebooklm-state.yaml
   ```
   - If missing: Initialize empty state file with structure
   - If corrupt YAML: Backup to `.notebooklm-state.yaml.bak.<timestamp>` and re-initialize
   - If valid: Load state

## Subcommands

| Command | Description | File Selection |
|---------|-------------|----------------|
| `podcast [--topic X]` | Generate podcast from new lessons since last run | Lessons newer than `last_podcast` timestamp, optionally filtered by topic |
| `quiz [--topic X] [--difficulty D]` | Generate quiz/flashcards from lessons | Lessons newer than `last_quiz` timestamp, optionally filtered by topic |
| `digest` | Summarize wiki changes as podcast | Wiki articles changed since `last_digest` timestamp |
| `report [--topic X] [--format F]` | Generate topic-focused report | Lessons + wiki articles matching topic |
| `research-audio` | Convert research results to podcast | Latest `output_path/**/*.md` research reports |
| `cleanup [--days N]` | Delete old MLL notebooks | Notebooks older than N days (default from config) |
| `status` | Show last runs and active notebooks | Reads state file |

## Natural Language Routing

When invoked via natural language, route to subcommands based on keywords:

| Keywords | Routes To | Example |
|----------|-----------|---------|
| "podcast", "audio", "listen" | `podcast` | "make a podcast about attention" → `podcast --topic attention` |
| "quiz", "test", "flashcard" | `quiz` | "quiz me on this week's lessons" → `quiz` |
| "digest", "summary", "changes", "what's new" | `digest` | "what's changed in the wiki?" → `digest` |
| "report", "briefing", "study guide" | `report` | "generate a study guide about quantization" → `report --topic quantization --format study-guide` |
| "research", "findings" | `research-audio` | "make a podcast from my research" → `research-audio` |
| "clean", "delete old" | `cleanup` | "clean up old notebooks" → `cleanup` |
| "status", "what's running" | `status` | "what's the status?" → `status` |

**Topic Extraction Rules:**
- Text after "about", "for", "regarding" becomes `--topic` parameter
- "on" is EXCLUDED as a topic trigger (too many false positives)
- Examples:
  - "podcast about attention" → `--topic attention`
  - "quiz for quantum mechanics" → `--topic "quantum mechanics"`
  - "podcast on Monday" → NO topic (false positive)

## CLI Command Convention

**ALWAYS** use explicit notebook specification:
```bash
# CORRECT — flag comes after the command
notebooklm source add file.md --notebook <id>
notebooklm generate audio "instructions" -n <id>

# NEVER use
notebooklm use <id>  # WRONG — writes to shared global context
```

This ensures stateless operation and prevents cross-session contamination.

## State Management

**State file location:** `<project_root>/.notebooklm-state.yaml` (alongside `kb.yaml`)

**State schema:**
```yaml
last_podcast:                    # (mtime, path) tuple cursor, or null
  mtime: "2026-04-12T14:30:00.123456Z"
  path: "/path/to/last/processed/file.md"
last_digest: null
last_quiz: null

notebooks:                       # tracked for cleanup
  - id: "notebook-uuid"
    title: "MLL Podcast 2026-04-12"
    created: "2026-04-12T14:30:00.123456Z"
    workflow: podcast
    status: pending              # pending | completed | failed

runs:                            # dedup history
  - workflow: podcast
    timestamp: "2026-04-12T14:30:00.123456Z"
    sources_hash: "sha256..."
    params_hash: "sha256..."
    artifacts:
      - type: audio
        output_files:
          - /path/to/podcast-2026-04-12.mp3
        status: completed        # pending | completed | failed
    notebook_id: "notebook-uuid"
```

**Reading state:**
```bash
python3 -c "
import yaml, json, sys
try:
    with open('.notebooklm-state.yaml') as f:
        state = yaml.safe_load(f) or {}
    print(json.dumps(state, default=str))
except FileNotFoundError:
    print('{}')
except yaml.YAMLError as e:
    print(json.dumps({'error': str(e)}))
    sys.exit(1)
"
```

**Writing state (atomic write via temp file + mv):**
```bash
python3 -c "
import yaml, json, tempfile, shutil, sys, os
state = json.loads(sys.stdin.read())
state_path = '.notebooklm-state.yaml'
state_dir = os.path.dirname(os.path.abspath(state_path)) or '.'
with tempfile.NamedTemporaryFile(mode='w', dir=state_dir, suffix='.tmp', delete=False) as f:
    yaml.dump(state, f, default_flow_style=False, allow_unicode=True)
    tmp = f.name
shutil.move(tmp, state_path)
" <<< '<json-encoded-state>'
```

**Corrupt state recovery:** Backup to `.notebooklm-state.yaml.bak.<ISO-timestamp>`, warn user, re-initialize empty state.

**Pruning:** On every write, remove `runs` entries older than `cleanup_days * 2` (default 14 days).

**Concurrency:** Single-writer only. One MLL operation at a time. This is a known limitation.

## Deduplication

**Dedup key:** `workflow + sources_hash + params_hash`

**Computing `sources_hash`:**
```bash
python3 -c "
import hashlib, json, os, sys
files = json.loads(sys.stdin.read())  # list of file paths
entries = []
for f in sorted(files):
    mtime = os.path.getmtime(f)
    entries.append(f'{f}:{mtime}')
print(hashlib.sha256('\n'.join(entries).encode()).hexdigest())
" <<< '["file1.md", "file2.md"]'
```

**Computing `params_hash` (per workflow):**
- **podcast:** `format + length + language + instruction_template`
- **quiz:** `difficulty + quantity + language`
- **digest:** `language + instruction_template`
- **report:** `topic + format + language`
- **research-audio:** `language + instruction_template`

**Deduplication algorithm (5 steps):**

1. **Compute `sources_hash`:** For each selected file, get path and mtime (ISO 8601), sort by path, join as `path:mtime\n`, SHA-256 hash.

2. **Compute `params_hash`:** From workflow's generation parameters (see above).

3. **Search `runs` in state:** Look for matching `workflow + sources_hash + params_hash` (includes pending, completed, failed).

4. **If match found:**
   - **If any artifact `pending` (in-flight):** Session recovery. Check artifact status via `notebooklm artifact list -n <notebook_id>`. Download if completed, re-wait if still in progress, or mark failed.
   - **If all artifacts `completed` and all `output_files` exist on disk:** Skip generation, report what was skipped, STOP.
   - **If artifact `completed` but output file missing:** Re-download only (use existing notebook, no re-generation).
   - **If any artifact `failed`:** Partial retry: reuse existing notebook if still accessible, skip completed artifacts, re-generate only failed ones. If notebook gone, recreate and re-add sources.
   - **Report** what is being skipped vs re-generated vs re-downloaded.

5. **If no match:** Proceed with full generation (new notebook).

**Partial retry:** Reuse existing notebook if accessible, skip completed artifacts, re-generate only failed ones. If notebook no longer accessible, recreate notebook and re-add sources.

## Source Count Limits

**Selection order:** Oldest-first. Incremental workflows sort by mtime ascending, take first `max_sources_per_notebook` (default 45, configurable in `kb.yaml`).

**When files exceed limit:**
1. Sort all matching files oldest-first (by mtime ascending)
2. Take first `max_sources_per_notebook` files
3. Log warning: "Found N files, limit is M. Processing oldest M files. Remaining files will be processed in next run."
4. Proceed with truncated set

**Watermark cursor rules:**
- **Cursor structure:** `last_<workflow>` stores `(mtime, path)` tuple, not just timestamp
- **Filter rule:** Select files where `(mtime, path) > last_<workflow>` (lexicographic comparison)
- **Why tuple cursor:** Eliminates equal-mtime skip bug. When multiple files share same mtime, path breaks the tie.
- **After successful batch:** Cursor advances to `(mtime, path)` of last file in the sorted batch (oldest-first order)
- **Example:**
  ```yaml
  last_podcast:
    mtime: "2026-04-12T14:30:00.123456Z"
    path: "/kb/lessons/lesson-042.md"
  ```
  Next run will process files where `(mtime, path) > ("2026-04-12T14:30:00.123456Z", "/kb/lessons/lesson-042.md")`

**Source failure model:**
- **All-or-nothing:** Any source failure aborts entire run
- **On source failure:**
  - Mark notebook status as `failed` in state
  - Do NOT advance watermark cursor
  - Do NOT generate artifacts
  - Report which source failed and why
- **Rationale:** Partial source sets produce incomplete artifacts. Better to fail loudly and retry with full source set.

## Workflows

_(Section to be populated in Task 4)_

### Podcast Workflow

_(To be populated in Task 4)_

### Quiz Workflow

_(To be populated in Task 4)_

### Digest Workflow

_(To be populated in Task 4)_

### Report Workflow

_(To be populated in Task 4)_

### Research-Audio Workflow

_(To be populated in Task 4)_

### Cleanup Workflow

_(To be populated in Task 4)_

### Status Workflow

_(To be populated in Task 4)_

## Error Handling

_(Section to be populated in Task 5)_

## Autonomy Rules

_(Section to be populated in Task 6)_
