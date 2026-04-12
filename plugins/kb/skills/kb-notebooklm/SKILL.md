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

Each workflow follows a common pattern: select source files from the KB, filter by timestamps/topics, compute dedup hashes, create/reuse a notebook, add sources, generate artifacts, and track state. Incremental workflows (podcast, quiz, digest) use watermark cursors to process only new content. Topic-filtered workflows (report, research-audio) ignore watermarks and select all matching content.

### Podcast Workflow

**Command:** `podcast [--topic X]`

**Algorithm (17 steps):**

1. **Glob lessons:** `glob` `config.lessons_path/**/*.md` (recursive), exclude `README.md`

2. **Filter by watermark:** Select files where `(mtime, path) > state.last_podcast`. If `last_podcast` is null, include all files.

3. **Filter by topic (if provided):** If `--topic` specified, further filter by grepping file content and filenames for the topic string (case-insensitive).

4. **Sort and limit:** Sort by mtime ascending (oldest first), truncate to `config.max_sources_per_notebook` (default 45).

5. **Compute hashes:** Calculate `sources_hash` (from file paths and mtimes) and `params_hash` (from format, length, language, instruction template).

6. **Dedup check:** Search `state.runs` for matching `workflow + sources_hash + params_hash`. If match found, follow deduplication algorithm (session recovery, skip, re-download, or partial retry). Otherwise continue.

7. **Handle empty selection:** If no files match after filtering, report "No new lessons since last podcast" and STOP.

8. **Confirm with user:** "Will create a podcast from N lessons: [list titles or filenames]. Proceed?" Wait for user confirmation.

9. **Create notebook:** Run `notebooklm create "MLL Podcast YYYY-MM-DD" --json`, capture notebook ID from JSON response.

10. **Persist notebook immediately:** Write notebook entry to state file with `status: pending`, `workflow: podcast`, `created: <ISO timestamp>`, `id: <notebook_id>`.

11. **Add sources (all-or-nothing):** For each selected lesson file, run `notebooklm source add <filepath> --notebook <notebook_id> --json`. If ANY source add fails: mark notebook as `failed` in state, report which source failed, STOP. Do NOT proceed to generation with partial sources.

12. **Wait for sources ready:** Poll `notebooklm source list --notebook <notebook_id> --json` every 15 seconds until all sources have `status: ready` (timeout: 600 seconds). If any source reaches `status: error`, mark notebook as `failed` in state, report error details, STOP.

13. **Generate audio:** Run `notebooklm generate audio "<instructions>" --format <config.podcast.format> --length <config.podcast.length> --language <config.language> --notebook <notebook_id> --json`.

    **Audio instructions template:**
    ```
    Cover the key concepts from these lessons: [comma-separated lesson titles]. Make it engaging and educational. Highlight connections between topics where they exist. Target audience: someone learning ML/AI concepts.
    ```

14. **Get artifact ID:** Run `notebooklm artifact list --notebook <notebook_id> --json`, extract artifact ID and status from response.

15. **Persist preliminary run record:** Write run entry to `state.runs` with:
    - `workflow: podcast`
    - `timestamp: <ISO timestamp>`
    - `sources_hash: <computed hash>`
    - `params_hash: <computed hash>`
    - `notebook_id: <notebook_id>`
    - `artifacts: [{type: audio, status: pending, output_files: []}]`

16. **Spawn background agent:** Use Agent tool with `run_in_background: true` to wait and download:
    ```
    Wait for artifact <artifact_id> in notebook <notebook_id> to complete, then download.
    1. Run: notebooklm artifact wait <artifact_id> -n <notebook_id> --timeout 2700
    2. If exit code 0: Run: notebooklm download audio <output_path>/<filename> -n <notebook_id>
    3. If exit code 2 (timeout): Report timeout
    4. If exit code 1 (error): Report error details
    Report the outcome (success with file path, or failure with reason).
    ```

    **Output filename logic:**
    - If unfiltered: `podcast-YYYY-MM-DD.mp3`
    - If topic-filtered: `podcast-<topic>-YYYY-MM-DD.mp3`
    - Saved to `config.output_path`

17. **On background agent success (in main conversation after agent reports):**
    - Update artifact in run record: `status: completed`, add `output_files: [<absolute path>]`
    - Update notebook: `status: completed`
    - **Advance watermark cursor (if unfiltered run and all artifacts OK):** Set `state.last_podcast` to `{mtime: <last file mtime>, path: <last file path>}` where "last file" is the last file in the sorted batch (oldest-first order)
    - Run auto-cleanup (see Cleanup Workflow)
    - Write updated state to file

**Session recovery:** If a future invocation finds a run with artifact `status: pending`, check artifact status via `notebooklm artifact list -n <notebook_id> --json`. If `completed`, download and finalize. If `in_progress`, re-wait. If `failed`, mark accordingly.

### Quiz Workflow

**Command:** `quiz [--topic X] [--difficulty D]`

**Algorithm (16 steps):**

1. **Glob lessons:** `glob` `config.lessons_path/**/*.md` (recursive), exclude `README.md`

2. **Filter by watermark:** Select files where `(mtime, path) > state.last_quiz`. If `last_quiz` is null, include all files.

3. **Filter by topic (if provided):** If `--topic` specified, further filter by grepping file content and filenames for the topic string (case-insensitive).

4. **Sort and limit:** Sort by mtime ascending (oldest first), truncate to `config.max_sources_per_notebook` (default 45).

5. **Compute hashes:** Calculate `sources_hash` (from file paths and mtimes) and `params_hash` (from difficulty, quantity, language).

6. **Dedup check:** Search `state.runs` for matching `workflow + sources_hash + params_hash`. If match found, proceed to step 7 (partial-retry check). If no match, skip step 7 and continue to step 8.

7. **Partial-retry check:** If dedup found a matching run, inspect per-artifact status:
   - If prior notebook accessible (exists in state and responds to `notebooklm artifact list -n <id>`): reuse notebook, skip to step 13 to generate only failed artifacts
   - If prior notebook gone: create new notebook (continue to step 9), re-add sources, generate only failed artifacts
   - Report what is being retried (e.g., "Quiz completed previously, retrying flashcards only")

8. **Handle empty selection:** If no files match after filtering, report "No new lessons since last quiz" and STOP.

9. **Confirm with user:** "Will generate quiz + flashcards from N lessons: [list titles or filenames]. Proceed?" For partial retry: "Will retry failed artifact(s): [list]. Proceed?" Wait for user confirmation.

10. **Create notebook (skip if reusing):** Run `notebooklm create "MLL Quiz YYYY-MM-DD" --json`, capture notebook ID from JSON response. Skip this step if reusing notebook from partial retry.

11. **Persist notebook immediately (skip if reusing):** Write notebook entry to state file with `status: pending`, `workflow: quiz`, `created: <ISO timestamp>`, `id: <notebook_id>`. Skip this step if reusing notebook.

12. **Add sources (skip if reusing):** For each selected lesson file, run `notebooklm source add <filepath> --notebook <notebook_id> --json`. If ANY source add fails: mark notebook as `failed` in state, report which source failed, STOP. Wait for sources ready via `notebooklm source list --notebook <notebook_id> --json` every 15 seconds until all sources have `status: ready` (timeout: 600 seconds). Skip this step if reusing notebook.

13. **Generate quiz (skip if already `completed` in prior run):** Run `notebooklm generate quiz --difficulty <D or config.quiz.difficulty> --quantity <config.quiz.quantity> --language <config.language> --notebook <notebook_id> --json`. Wait inline via `notebooklm artifact wait <artifact_id> -n <notebook_id> --timeout 120`. Download quiz in both formats:
    - `notebooklm download quiz --format markdown <output_path>/quiz-YYYY-MM-DD.md -n <notebook_id>`
    - `notebooklm download quiz --format json <output_path>/quiz-YYYY-MM-DD.json -n <notebook_id>`
    
    **Topic filenames:** `quiz-<topic>-YYYY-MM-DD.md/.json`

14. **Generate flashcards (skip if already `completed` in prior run):** Run `notebooklm generate flashcards --difficulty <D or config.quiz.difficulty> --quantity <config.quiz.quantity> --language <config.language> --notebook <notebook_id> --json`. Wait inline via `notebooklm artifact wait <artifact_id> -n <notebook_id> --timeout 120`. Download:
    - `notebooklm download flashcards --format markdown <output_path>/flashcards-YYYY-MM-DD.md -n <notebook_id>`
    
    **Topic filename:** `flashcards-<topic>-YYYY-MM-DD.md`

15. **Finalize state:** Run record with `artifacts` array:
    ```yaml
    artifacts:
      - type: quiz
        output_files:
          - .../quiz-YYYY-MM-DD.md
          - .../quiz-YYYY-MM-DD.json
        status: completed
      - type: flashcards
        output_files:
          - .../flashcards-YYYY-MM-DD.md
        status: completed   # or "failed" if flashcard generation failed
    ```
    
    **Watermark advancement rules:**
    - If unfiltered AND all artifacts succeeded: advance `last_quiz` cursor to `{mtime: <last file mtime>, path: <last file path>}` where "last file" is the last file in the sorted batch (oldest-first order)
    - If topic-filtered: do NOT advance `last_quiz`
    - Update notebook to `completed` if all artifacts succeeded, or `failed` if any failed

16. **Auto-cleanup:** Run cleanup workflow (see Cleanup Workflow).

**Partial success behavior:**

If quiz succeeds but flashcards fail (or vice versa):
- Run record reflects per-artifact status
- Watermark does NOT advance (not all artifacts succeeded)
- On next invocation: same files selected, dedup matches, inspects per-artifact status, re-generates ONLY the failed artifact
- Once all artifacts succeed, watermark advances

**Notebook reuse on partial retry:**

If the matched run's notebook is still accessible (exists in state and responds to `notebooklm artifact list -n <id>`):
- Reuse notebook — skip creation and source upload (steps 10-12)

If notebook was cleaned up or inaccessible:
- Create new notebook and re-add sources before retrying (proceed through steps 10-12)

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

## Async Completion Model

Long-running artifact generation (podcast audio, digest audio, research audio) takes 10-45 minutes to complete. These workflows use the Claude Code Agent tool with `run_in_background: true` to avoid blocking the main conversation.

### CLI Contract

The `notebooklm` CLI provides these commands for async artifact management:

- `notebooklm generate <type> ... --json` - Initiates artifact generation, returns immediately
- `notebooklm artifact list --notebook <notebook_id> --json` - Lists artifacts with ID and status
- `notebooklm artifact wait <artifact_id> -n <notebook_id> --timeout <seconds>` - Blocks until artifact completes or timeout
- `notebooklm download <type> <output_path> -n <notebook_id>` - Downloads completed artifact

For async artifacts (audio, video), the generate command returns immediately. Use `artifact list` to get the artifact ID and status, then `artifact wait` to block until completion.

### Async Flow (7 steps)

1. **Initiate generation:** Run `notebooklm generate <type> "<instructions>" --format <format> --length <length> --language <language> --notebook <notebook_id> --json`. The command returns immediately (non-blocking).

2. **Get artifact ID:** Run `notebooklm artifact list --notebook <notebook_id> --json` to extract the artifact ID and initial status from the response.

3. **Persist in-flight state:** Write preliminary run record to state file with artifact `status: pending` and `notebook_id`. This enables session recovery if the current session ends before completion.

4. **Spawn background subagent:** Use Agent tool with `run_in_background: true`:
   ```
   Wait for artifact <artifact_id> in notebook <notebook_id> to complete, then download.
   1. Run: notebooklm artifact wait <artifact_id> -n <notebook_id> --timeout 2700
   2. If exit code 0: Run: notebooklm download <type> <output_path>/<filename> -n <notebook_id>
   3. If exit code 2 (timeout): Report timeout
   4. If exit code 1 (error): Report error details
   Report the outcome (success with file path, or failure with reason).
   ```

5. **Main conversation continues:** User is notified when the background agent completes. No blocking.

6. **State finalization (in main conversation after background agent reports success):**
   - Update artifact status to `completed`
   - Add `output_files: [<absolute path>]` to artifact record
   - Update notebook status to `completed`
   - Advance watermark cursor if applicable (unfiltered incremental workflows only)
   - Write updated state to file
   - The subagent does NOT write state — only the main conversation updates state.

7. **Session recovery:** If a future invocation finds a run with artifact `status: pending`, check `notebooklm artifact list -n <notebook_id> --json`. If artifact is `completed`, download and finalize state. If `in_progress`, re-wait with new background agent. If `failed`, mark artifact and notebook as `failed` in state.

### Sync Artifacts

Quiz, flashcards, report, mind-map, and data-table artifacts complete quickly (under 60 seconds). These workflows wait inline without background agents:

1. Run `notebooklm generate <type> ... -n <notebook_id> --json`
2. Run `notebooklm artifact list -n <notebook_id> --json` to get artifact ID
3. Run `notebooklm artifact wait <artifact_id> -n <notebook_id> --timeout 120`
4. If success: download immediately via `notebooklm download <type> <output_path> -n <notebook_id>`
5. Update state with `status: completed` and output file path

No background agent needed. User waits for completion before proceeding.

### Fallback for Session Ending

If the session is ending (user says "goodbye" or closes the session) and an async artifact is in-flight, skip the background agent. Instead, report the artifact ID and notebook ID for manual download:

```
Artifact generation in progress. To download when complete:
notebooklm download <type> <output_path> -n <notebook_id>
```

The next skill invocation will detect the pending artifact via session recovery and complete the download automatically.

## Error Handling

_(Section to be populated in Task 5)_

## Autonomy Rules

_(Section to be populated in Task 6)_
