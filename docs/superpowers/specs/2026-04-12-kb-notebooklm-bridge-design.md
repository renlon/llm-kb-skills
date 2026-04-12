# KB-NotebookLM Bridge Skill Design

**Date:** 2026-04-12
**Revision:** 6 (post peer-consensus round 4)
**Scope:** New skill `kb-notebooklm` for the `llm-kb-skills` plugin

## Problem

The user maintains a personal knowledge base (MLL) with lessons, wiki articles, raw sources, and research output. Google NotebookLM can generate podcasts, quizzes, flashcards, reports, and other artifacts from document sources. Today these are separate systems with no automated bridge. The user wants to:

1. Generate a daily podcast from newly written lesson docs
2. Create quizzes and flashcards from lesson content
3. Summarize wiki changes as audio digests
4. Produce topic-focused reports across lessons and wiki
5. Turn research output into audio summaries

## Design

### Two Layers

**Layer 1 — Content Pipeline:** Moves KB content into NotebookLM and generates artifacts. Handles file selection, source uploading, artifact generation, and downloading.

**Layer 2 — Intelligent Orchestrator:** Higher-level workflows that understand KB structure (lessons, wiki articles, raw sources, research output) and compose multi-step pipelines.

The raw NotebookLM skill (installed globally at `~/.claude/skills/notebooklm/SKILL.md`) already handles direct CLI operations. This skill does not duplicate that — it builds on top of it.

### Architecture

Single skill `kb-notebooklm` with a SKILL.md that:

1. Reads `kb.yaml` for config and `.notebooklm-state.yaml` for mutable state
2. Accepts both subcommands and natural language
3. Routes to the appropriate workflow
4. Each workflow follows: **select files -> dedup check -> create notebook (persist immediately) -> add sources -> wait for processing -> generate artifact -> wait for completion -> download -> finalize state -> cleanup**

### Concurrency Model

**Single-writer only.** The skill assumes one Claude session operates on the state file at a time. Concurrent invocations (e.g., two terminal sessions) are not supported and may corrupt state. The state file uses atomic writes (write-to-tmp + mv) to protect against partial writes from crashes, but not against concurrent readers/writers.

### Subcommands

| Command | Description | File Selection |
|---------|-------------|----------------|
| `podcast [--topic X]` | Podcast from new lessons since last run | Lessons newer than `last_podcast` timestamp, optionally filtered by topic |
| `quiz [--topic X] [--difficulty D]` | Quiz/flashcards from lessons | Lessons newer than `last_quiz` timestamp, optionally filtered by topic |
| `digest` | Wiki changes summary as podcast | Wiki articles changed since `last_digest` timestamp |
| `report [--topic X] [--format F]` | Topic-focused report | Lessons + wiki articles matching topic |
| `research-audio` | Research results to podcast | Latest `output_path/**/*.md` research reports |
| `cleanup [--days N]` | Delete old MLL notebooks | Notebooks older than N days (default from config) |
| `status` | Show last runs, active notebooks | Reads state file |

### Natural Language Routing

The skill also accepts free-text input and routes to the correct subcommand:

| Keywords | Routes To |
|----------|-----------|
| "podcast", "audio", "listen" | `podcast` |
| "quiz", "test", "flashcard" | `quiz` |
| "digest", "summary", "changes", "what's new" | `digest` |
| "report", "briefing", "study guide" | `report` |
| "research", "findings" | `research-audio` |
| "clean", "delete old" | `cleanup` |
| "status", "what's running" | `status` |

Topic extraction: text after "about", "for", "regarding" becomes `--topic`. Note: "on" is excluded as a topic trigger because it causes false positives (e.g., "quiz me on this week's lessons" should route to `quiz` without a topic, not `quiz --topic "this week's lessons"`).

Examples:
- "make a podcast about attention" -> `podcast --topic attention`
- "quiz me on this week's lessons" -> `quiz`
- "what's changed in the wiki?" -> `digest`
- "generate a study guide about quantization" -> `report --topic quantization --format study-guide`

### Config in `kb.yaml`

Added under the existing `integrations` section. This is **read-only config** — no mutable state here.

```yaml
integrations:
  notebooklm:
    enabled: true
    lessons_path: /Users/dragon/Documents/MLL/lessons
    wiki_path: /Users/dragon/Documents/MLL/wiki
    output_path: /Users/dragon/Documents/MLL/output
    cleanup_days: 7
    max_sources_per_notebook: 45    # stay under NotebookLM's 50-source limit
    language: zh_Hans               # global language for all artifact generation
    podcast:
      format: deep-dive             # deep-dive|brief|critique|debate
      length: default               # short|default|long
    quiz:
      difficulty: medium            # easy|medium|hard
      quantity: standard            # fewer|standard|more
```

**Key design choices:**
- `language` is a top-level setting under `notebooklm:`. All artifact types (podcast, quiz, digest, report) use it.
- `wiki_path` is explicitly configured (not assumed as a relative path).
- `max_sources_per_notebook` caps sources to stay under NotebookLM's platform limit.
- No `state` section — mutable state is stored separately.

### State File: `.notebooklm-state.yaml`

Mutable state lives in a separate file at the KB project root (alongside `kb.yaml`), not inside `kb.yaml`. This prevents config corruption from frequent writes.

**Path:** `<project_root>/.notebooklm-state.yaml`

```yaml
last_podcast:                                # (mtime, path) tuple cursor
  mtime: "2026-04-12T14:30:00Z"
  path: "/Users/dragon/Documents/MLL/lessons/Word2vec_Embeddings_Training_2026-04-09.md"
last_digest:
  mtime: "2026-04-11T09:00:00Z"
  path: "/Users/dragon/Documents/MLL/wiki/attention_mechanisms.md"
last_quiz: null                              # null = include all files

notebooks:
  - id: "abc123de-..."
    title: "MLL Podcast 2026-04-12"
    created: "2026-04-12T14:30:00Z"
    workflow: podcast
    status: completed                    # pending | completed | failed

runs:
  - workflow: podcast
    timestamp: "2026-04-12T14:30:00Z"
    sources_hash: "a1b2c3..."
    params_hash: "d4e5f6..."
    artifacts:
      - type: audio
        output_files:
          - /Users/dragon/Documents/MLL/output/podcast-2026-04-12.mp3
        status: completed               # completed | failed
    notebook_id: "abc123..."

  - workflow: quiz                       # example: quiz with multiple output files
    timestamp: "2026-04-12T16:00:00Z"
    sources_hash: "g7h8i9..."
    params_hash: "j0k1l2..."
    artifacts:
      - type: quiz
        output_files:
          - /Users/dragon/Documents/MLL/output/quiz-2026-04-12.md
          - /Users/dragon/Documents/MLL/output/quiz-2026-04-12.json
        status: completed
      - type: flashcards
        output_files:
          - /Users/dragon/Documents/MLL/output/flashcards-2026-04-12.md
        status: failed                   # will be retried on next run
    notebook_id: "def456..."
```

**Timestamps:** All time values use ISO 8601 with fractional seconds and timezone (`YYYY-MM-DDTHH:MM:SS.ffffffZ`). Filesystem mtime is read at full precision available from `os.path.getmtime()` (typically microsecond on macOS/Linux). This ensures the `(mtime, path)` cursor doesn't lose precision at second boundaries.

**State file writes:** The LLM agent reads the full file, modifies in memory, and writes the entire file back atomically (write to `.notebooklm-state.yaml.tmp`, then `mv` to `.notebooklm-state.yaml`). Background subagents do NOT write state — they report results back to the main conversation, which then writes state.

**Corrupt state recovery:** If the state file fails to parse as YAML, back it up to `.notebooklm-state.yaml.bak.<timestamp>`, log a warning with the backup path, and initialize fresh. This preserves evidence for debugging while allowing the skill to continue. The user is warned that dedup history was lost and duplicate artifacts may be generated.

**Pruning:** The `runs` array is pruned on every write. Entries older than `cleanup_days * 2` (default: 14 days) are removed. This bounds growth to roughly 2-4 entries per day.

## Deduplication

**No duplicate artifacts.** Before generating any content, check whether an equivalent artifact already exists.

The dedup key is: `workflow type + sources_hash + params_hash`. This ensures that the same sources with different generation parameters (e.g., different podcast format, quiz difficulty, or language) are treated as distinct requests.

**`sources_hash`:** SHA-256 of the sorted list of `filepath:mtime` pairs (one per line). Changes when files are added, removed, or edited. Since source uploads use an all-or-nothing model (any failure aborts the run), the `sources_hash` computed at selection time is always identical to the final processed set.

**`params_hash`:** SHA-256 of the generation parameters that materially affect output. Per workflow:
- `podcast`: `format + length + language + instruction_template`
- `quiz`: `difficulty + quantity + language`
- `digest`: `language + instruction_template`
- `report`: `topic + format + language`
- `research-audio`: `language + instruction_template`

**Dedup check (runs after file selection, before notebook creation):**

1. Compute `sources_hash`:
   - For each selected file, get its path and filesystem mtime (as ISO 8601)
   - Sort by path
   - Join as `path:mtime\n` and compute SHA-256
2. Compute `params_hash` from the workflow's generation parameters
3. Search `runs` in state file for an entry matching `workflow + sources_hash + params_hash` (includes `pending`, `completed`, and `failed` runs)
4. If match found:
   - Check per-artifact status in the matched run record
   - If any artifact is `pending` (in-flight) -> **session recovery**: check artifact status via `notebooklm artifact list -n <notebook_id>`, then download if completed, re-wait if still in progress, or mark failed
   - If all artifacts `completed` and all `output_files` exist on disk -> skip, stop
   - If an artifact is `completed` but an output file is missing -> **re-download only** (use the existing notebook, no re-generation)
   - If any artifact is `failed` -> **partial retry**: reuse the existing notebook (if still in state and accessible), skip completed artifacts, re-generate only failed ones
   - Report what is being skipped vs re-generated vs re-downloaded
5. If no match -> proceed with full generation (create new notebook)

**Partial retry ordering:** When dedup triggers a partial retry, the workflow skips directly to the generation step for the failed artifact, using the `notebook_id` from the matched run record. It does NOT create a new notebook or re-add sources.

**Same-day, different content:** If a lesson file is edited after a podcast was generated, its mtime changes, producing a different `sources_hash`. A new podcast is generated.

**Same sources, different params:** Running `podcast --format deep-dive` and then `podcast --format critique` with the same sources produces different `params_hash` values. Both generate.

**Topic-filtered runs:** Different topic filters select different files, producing different `sources_hash` values. Naturally deduplicated.

## Source Count Limits and Incremental Selection

NotebookLM imposes per-notebook source limits (Standard: 50, Plus: 100). The `max_sources_per_notebook` config (default: 45) prevents hitting this limit.

**Selection order: oldest-first.** Incremental workflows (`podcast`, `quiz`, `digest`) sort candidate files by mtime ascending (oldest first) and take the first `max_sources_per_notebook`. This ensures that the backlog drains in order — older files are processed before newer ones, and no file is permanently skipped.

**When selected files exceed `max_sources_per_notebook`:**

1. Sort selected files by modification date (oldest first)
2. Take the first `max_sources_per_notebook` files
3. Log warning: "Selected N files but limited to <max> oldest-first. Remaining files will be included in the next run: [list]"
4. Proceed with the truncated set

**Watermark cursor:** `last_<workflow>` stores a `(mtime, path)` tuple — the mtime and path of the last successfully processed file in sorted order. Selection filters using `(mtime, path) > last_<workflow>` (lexicographic comparison on the tuple). This eliminates the equal-mtime skip bug: files with the same mtime are disambiguated by path.

```yaml
last_podcast:
  mtime: "2026-04-12T14:30:00Z"
  path: "/Users/dragon/Documents/MLL/lessons/Word2vec_Embeddings_Training_2026-04-09.md"
```

After a successful batch:
- The cursor advances to the `(mtime, path)` of the last file in the sorted batch
- Files that exceeded the limit (newer than the batch) remain eligible for the next run

**Source failure model: all-or-nothing.** If any source fails to add or reaches `error` status during processing, the entire run aborts. The notebook is marked `failed` in state (for cleanup), the watermark is NOT advanced, and no artifacts are generated. This prevents the watermark from skipping past failed files. The user is informed which source failed and can retry the entire run after investigating.

**Example:** 60 files eligible, limit 45. Oldest 45 are selected. All sources add and process successfully. Watermark advances to the mtime of the 45th file. The remaining 15 newer files are picked up on the next run. If source #12 fails, the entire run aborts — watermark stays, all 45 files are retried next run.

## Workflow Details

### Common Preamble (all workflows)

1. Verify `notebooklm` CLI is on PATH (check with `which notebooklm`)
2. Run `notebooklm auth check --json` — if auth fails, tell user to run `notebooklm login` and stop
3. Read `kb.yaml` — if `integrations.notebooklm` is missing or `enabled: false`, report and stop
4. Read `.notebooklm-state.yaml` — if missing, initialize with empty defaults; if corrupt, back up and re-initialize (see State File section)
5. **(After file selection in each workflow)** Enforce source count limit (oldest-first), then run dedup check

### CLI Command Convention

All `notebooklm` commands that target a specific notebook use the explicit `-n <notebook_id>` or `--notebook <notebook_id>` flag. The skill does **NOT** use `notebooklm use <id>` (which writes to shared global context). This prevents interference with other NotebookLM sessions or background agents.

### Immediate Notebook Persistence

Notebooks are persisted to state **immediately after creation** with `status: pending`. This ensures that if the workflow fails or the session terminates, the notebook is still tracked for cleanup. The status transitions are:

- `pending` — notebook created, sources being added or generation in progress
- `completed` — all artifacts generated and downloaded successfully
- `failed` — generation or download failed; notebook kept for cleanup

### Watermark Rules

**Unfiltered runs** (`podcast`, `quiz`, `digest` without `--topic`): advance the global `last_<workflow>` cursor to the `(mtime, path)` of the last file in the sorted batch. Only advance when **all** artifacts for the batch succeed.

**Topic-filtered runs** (`podcast --topic X`, `quiz --topic X`): do **NOT** advance the global watermark. A topic-filtered run only processes a subset of eligible files. Advancing the global watermark would permanently skip unrelated files that were newer than the old watermark but not matched by the topic filter. Topic-filtered runs rely solely on dedup to prevent re-generation.

**`report` and `research-audio`**: do not advance any watermark (they are not incremental).

### `podcast [--topic X]`

1. Glob `lessons_path/**/*.md` (recursive), exclude `README.md`
2. Filter to files with filesystem mtime > `state.last_podcast` (if `last_podcast` is null, include all files)
3. If `--topic` provided, further filter by grepping file content and filenames for the topic string (case-insensitive)
4. Sort by mtime ascending (oldest first), enforce source count limit
5. Run dedup check — if duplicate, stop
6. If no files match -> report "No new lessons since last podcast" and stop
7. **Confirm with user:** "Will create a podcast from N lessons: [list]. Proceed?"
8. `notebooklm create "MLL Podcast YYYY-MM-DD" --json` -> capture notebook ID
9. **Immediately persist** notebook to state file with `status: pending`
10. For each selected lesson file: `notebooklm source add <filepath> --notebook <notebook_id> --json`
    - If any source add fails: mark notebook as `failed` in state, report which source failed, stop. (All-or-nothing — see Source Failure Model)
11. Wait for all sources to be ready: poll `notebooklm source list --notebook <notebook_id> --json` every 15s until all status=ready (timeout: 600s). If any source reaches `error` status: mark notebook `failed`, report error, stop.
12. `sources_hash` is the hash of the full selected set (no recomputation needed since all sources must succeed)
13. `notebooklm generate audio "<instructions>" --format <config.podcast.format> --length <config.podcast.length> --language <config.language> --notebook <notebook_id> --json` -> parse response
14. **Long wait — use Agent tool** (see Async Completion Model below)
    - Output filename: `podcast-YYYY-MM-DD.mp3` or `podcast-<topic>-YYYY-MM-DD.mp3` if topic-filtered
15. On success, finalize state:
    - If unfiltered and all artifacts succeeded: advance `last_podcast` cursor to `(mtime, path)` of the last file in the sorted batch
    - If topic-filtered: do NOT advance `last_podcast`
    - Update notebook status to `completed`, append to `runs` with final `sources_hash` and `params_hash`
16. Run auto-cleanup: delete notebooks where `created` is older than `cleanup_days`

**Audio instructions template:** "Cover the key concepts from these lessons: [comma-separated lesson titles]. Make it engaging and educational. Highlight connections between topics where they exist. Target audience: someone learning ML/AI concepts."

### `quiz [--topic X] [--difficulty D]`

1. Glob `lessons_path/**/*.md` (recursive), exclude `README.md`
2. Filter to files with filesystem mtime > `state.last_quiz` (each workflow tracks its own timestamp)
3. If `--topic` provided, further filter by grepping file content and filenames
4. Sort by mtime ascending (oldest first), enforce source count limit
5. Run dedup check
6. If no files match -> report "No new lessons since last quiz" and stop
7. **Check for partial-retry:** If dedup found a matching run (step 5), check per-artifact status. If retrying:
   - If the prior run's notebook is still accessible: reuse it (skip to step 13, generating only failed artifacts)
   - If the prior run's notebook is gone: proceed with new notebook creation (step 8), then generate only failed artifacts
   - Report: "Retrying failed artifact(s): [list]. Reusing existing notebook: [yes/no]"
8. **Confirm with user:** "Will generate quiz + flashcards from N lessons: [list]. Proceed?" (or for partial retry: "Will retry failed artifact(s): [list]. Proceed?")
9. Create notebook: `notebooklm create "MLL Quiz YYYY-MM-DD" --json` (skip if reusing)
10. **Immediately persist** notebook to state file with `status: pending` (skip if reusing)
11. Add sources with `--notebook <notebook_id>` (same all-or-nothing error handling as podcast; skip if reusing)
12. Wait for sources to be ready (same as podcast — any source error aborts the run; skip if reusing)
13. **Generate quiz** (skip if already `completed` in a prior partial run):
    - `notebooklm generate quiz --difficulty <D or config.quiz.difficulty> --quantity <config.quiz.quantity> --language <config.language> --notebook <notebook_id> --json`
    - Wait for completion, then download:
    - `notebooklm download quiz --format markdown <output_path>/quiz-YYYY-MM-DD.md -n <notebook_id>`
    - `notebooklm download quiz --format json <output_path>/quiz-YYYY-MM-DD.json -n <notebook_id>`
    - If `--topic`, filenames become: `quiz-<topic>-YYYY-MM-DD.md` / `.json`
14. **Generate flashcards** (skip if already `completed` in a prior partial run):
    - `notebooklm generate flashcards --difficulty <D or config.quiz.difficulty> --quantity <config.quiz.quantity> --language <config.language> --notebook <notebook_id> --json`
    - Wait for completion, then download:
    - `notebooklm download flashcards --format markdown <output_path>/flashcards-YYYY-MM-DD.md -n <notebook_id>`
    - If `--topic`, filename becomes: `flashcards-<topic>-YYYY-MM-DD.md`
15. Finalize state:
    - Run record stores `artifacts` array with per-artifact status:
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
    - If unfiltered and all artifacts succeeded: advance `last_quiz` cursor to `(mtime, path)` of last file in batch
    - If topic-filtered: do NOT advance `last_quiz`
    - Update notebook status to `completed` if all artifacts succeeded, or `failed` if any artifact failed
    - Partial success is tracked only at the artifact level within the run record, not at the notebook level
16. Run auto-cleanup

**Partial success:** If quiz succeeds but flashcards fail (or vice versa), the run record reflects per-artifact status. The watermark does **NOT** advance (not all artifacts succeeded). On the next invocation, file selection still includes the same files, dedup matches the `sources_hash + params_hash`, inspects per-artifact status, and re-generates only the failed artifact. Once all artifacts succeed, the watermark advances.

**Notebook reuse on partial retry:** If the matched run's notebook is still accessible (exists in `notebooks` state and responds to `notebooklm artifact list -n <id>`), the skill reuses it — skipping notebook creation and source upload. If the notebook was cleaned up or is inaccessible, the skill creates a new notebook and re-adds sources before retrying the failed artifact.

### `digest`

1. Glob `wiki_path/**/*.md` (recursive, using configured `wiki_path`)
2. Filter to files with filesystem mtime > `state.last_digest`
3. Exclude index files: `_index.md`, `_sources.md`, `_categories.md`, `_evolution.md`
4. Sort by mtime ascending (oldest first), enforce source count limit
5. Run dedup check
6. If no changed files -> report "No wiki changes since last digest" and stop
7. **Confirm with user:** "Will create a wiki digest podcast from N changed articles: [list]. Proceed?"
8. Create notebook: `notebooklm create "MLL Wiki Digest YYYY-MM-DD" --json`
9. **Immediately persist** notebook with `status: pending`
10. Add changed wiki articles as sources with `--notebook <notebook_id>` (all-or-nothing — any failure aborts)
11. Wait for sources to be ready (any source error aborts the run)
13. `notebooklm generate audio "Summarize the key changes and new knowledge in these wiki articles. Focus on what's new, why it matters, and how topics connect." --language <config.language> --notebook <notebook_id> --json`
14. Wait and download to `<output_path>/digest-YYYY-MM-DD.mp3` (via subagent)
15. Finalize state: advance `last_digest` cursor to `(mtime, path)` of last file in batch, update notebook to `completed`, append run
16. Run auto-cleanup

### `report [--topic X] [--format F]`

1. `--topic` is required. If not provided, ask the user.
2. Search both `lessons_path/**/*.md` and `wiki_path/**/*.md` (recursive) for files matching the topic:
   - Grep file content for the topic string (case-insensitive)
   - Also match filenames containing the topic
   - Exclude `README.md` and wiki index files
3. Enforce source count limit (oldest-first)
4. Run dedup check
5. If no files match -> report "No content found for topic '<X>'" and stop
6. **Confirm with user:** "Will generate a <format> report on '<topic>' from N files: [list]. Proceed?"
7. Create notebook: `notebooklm create "MLL Report: <topic> YYYY-MM-DD" --json`
8. **Immediately persist** notebook with `status: pending`
9. Add matching files as sources with `--notebook <notebook_id>`, wait for ready
10. `notebooklm generate report --format <F or briefing-doc> --language <config.language> --notebook <notebook_id> --append "Focus on the topic: <topic>" --json`
    - Default format: `briefing-doc`. Other options: `study-guide`, `blog-post`, `custom`
    - The `--append` flag passes topic-specific instructions to the generation template
12. Wait, download to `<output_path>/report-<topic>-YYYY-MM-DD.md`
13. Finalize state: update notebook to `completed`, append run, run cleanup
    - `report` does not advance any watermark (it is topic-filtered, not incremental)

### `research-audio`

1. Glob `output_path/**/*report*.md` and `output_path/**/*research*.md` (recursive, using configured `output_path`)
2. Sort by modification date, take the most recent (or let user choose if multiple)
3. If no research files -> report "No research output found in <output_path>" and stop
4. Run dedup check
5. **Confirm with user:** "Will create an audio summary of: <filename>. Proceed?"
6. Create notebook: `notebooklm create "MLL Research Audio YYYY-MM-DD" --json`
7. **Immediately persist** notebook with `status: pending`
8. Add research file(s) as sources with `--notebook <notebook_id>`, wait for ready
9. Recompute `sources_hash` from successfully added sources
10. `notebooklm generate audio "Summarize these research findings. Cover key discoveries, methodology, and implications. Make it accessible." --language <config.language> --notebook <notebook_id> --json`
11. Wait and download to `<output_path>/research-audio-YYYY-MM-DD.mp3` (via subagent)
12. Finalize state: update notebook to `completed`, append run, run cleanup
    - `research-audio` does not advance any watermark

### `cleanup [--days N]`

1. Read `notebooks` from state file
2. For each notebook where `created` timestamp is older than N days (default: `cleanup_days` from config):
   - `notebooklm delete <notebook_id>` — confirm with user before first deletion, then batch the rest
   - Remove from `notebooks` in state
3. Also clean up `pending` or `failed` notebooks older than 1 day (likely orphaned)
4. Prune `runs` older than `cleanup_days * 2`
5. Write updated state file (atomic write)

### `status`

1. Read state file
2. Display:
   - Last podcast: timestamp and output file
   - Last digest: timestamp and output file
   - Last quiz: timestamp and output file
   - Active notebooks: count and list with status (pending/completed/failed)
   - Notebooks pending cleanup (older than `cleanup_days`)
   - In-flight jobs (notebooks with `status: pending`)
   - Total runs recorded

## Async Completion Model

NotebookLM artifact generation is long-running (10-45 minutes). The skill uses the **Claude Code Agent tool** to handle this.

### CLI Contract

`notebooklm generate <type> ... --json` returns a JSON object. The key fields vary by artifact type but always include a status indicator. For async artifacts (audio, video), the response contains a `task_id`. The skill then uses `notebooklm artifact list --notebook <notebook_id> --json` to find the corresponding artifact ID and status.

### Async Flow

1. After `notebooklm generate ... --notebook <notebook_id> --json` returns, parse the response.
2. Run `notebooklm artifact list --notebook <notebook_id> --json` to get the artifact ID and current status.
3. **Persist in-flight state:** Write a preliminary run record to state with artifact `status: pending` and the `notebook_id`, `artifact_id`, and expected `output_files`. This ensures that if the session terminates, a future invocation can detect the in-flight job via dedup and attempt to resume (check artifact status, re-download if completed, or re-wait).
4. Spawn a background subagent using the Agent tool with `run_in_background: true`. The subagent prompt:
   ```
   Wait for the latest <type> artifact in notebook <notebook_id> to complete, then download.
   1. Run: notebooklm artifact wait <artifact_id> -n <notebook_id> --timeout <T>
   2. If exit code 0: Run: notebooklm download <type> <output_path> -n <notebook_id>
   3. If exit code 2 (timeout): Report timeout.
   4. If exit code 1 (error): Report error details.
   Report the outcome (success with file path, or failure with reason).
   ```
5. The main conversation continues. The user is notified when the background agent completes.
6. State finalization happens in the main conversation after the background agent reports success: update artifact status from `pending` to `completed`, advance watermark. The subagent does NOT write state.
7. **Session recovery:** If a future invocation finds a run with `status: pending`, it checks `notebooklm artifact list -n <notebook_id> --json`. If the artifact is `completed`, it downloads and finalizes. If still `in_progress`, it re-waits. If `failed`, it marks the run accordingly.

### Sync Artifacts

Some artifact types (mind-map, data-table, report, quiz, flashcards) complete relatively quickly. For these, the skill waits inline (no background agent) and downloads immediately.

**Fallback:** If the session is about to end, skip the background agent. Instead report the artifact ID and notebook ID so the user can download manually: `notebooklm download <type> <path> -n <notebook_id>`.

## Error Handling

| Error | Action |
|-------|--------|
| `notebooklm` not on PATH | Report: "notebooklm CLI not found. Install with `pip install notebooklm-py`." Stop. |
| Auth check fails | Report: "NotebookLM auth expired. Run `notebooklm login`." Stop. |
| `kb.yaml` missing notebooklm config | Report: "Add `integrations.notebooklm` to kb.yaml." Stop. |
| State file missing | Create with empty defaults. Continue. |
| State file corrupt | Back up to `.bak.<timestamp>`, warn user, re-initialize. Continue. |
| Any source add fails | Mark notebook as `failed` in state, report which source failed, stop. Do not advance watermark. (All-or-nothing) |
| Any source enters `error` status | Mark notebook as `failed`, report error, stop. Do not advance watermark. (All-or-nothing) |
| Source count exceeds limit | Truncate oldest-first to `max_sources_per_notebook`, log warning. Remaining files eligible next run. |
| Generation fails (rate limit) | Report to user, suggest retry in 5-10 minutes. Mark notebook `failed`. Do not advance watermark. |
| Artifact wait timeout | Report timeout, suggest `notebooklm artifact list`. Do not finalize state. |
| Download fails | Check artifact status, report clearly. Do not finalize state. |
| No files match selection | Report clearly, do not create empty notebook. |
| Partial failure (quiz ok, flashcards failed) | Record per-artifact status in run record. Watermark does NOT advance (not all artifacts succeeded). Next run: dedup detects matching run, inspects per-artifact status, re-generates only failed artifact. |
| Session terminates mid-workflow | Notebook persisted as `pending` in state. Cleanup will handle it after 1 day. |

## Autonomy Rules

**Run without confirmation:**
- File selection, filtering, and source count enforcement
- `notebooklm auth check`
- `notebooklm source list` / `notebooklm artifact list`
- Reading `kb.yaml` and state file
- Natural language routing and intent parsing
- State file updates (after user-approved operations complete)
- Downloading artifacts (after user approved generation)
- Auto-cleanup of notebooks older than `cleanup_days` at the end of a workflow

**Ask before running (single confirmation per workflow):**
- The workflow confirmation prompt (step 7 in podcast, etc.) covers: notebook creation, source adding, artifact generation, waiting, downloading, and state update as a single approval
- Explicit `cleanup` subcommand (confirm before first deletion)

**Rationale:** The user approves the workflow once at the confirmation prompt. Everything after that (source upload, generation, wait, download, state update, auto-cleanup) is autonomous. This avoids repeated confirmation prompts per run.

## File Structure

```
plugins/kb/skills/
  kb-notebooklm/
    SKILL.md              # Skill definition with all workflow logic
```

Single SKILL.md file. State management (YAML read/write, SHA-256 hashing, mtime comparison) is performed by the LLM agent using inline `python3 -c` commands via Bash. No separate helper scripts.

**Required system tools:**
- `notebooklm` CLI (from `notebooklm-py` package)
- `python3` (for YAML parsing via `import yaml`, SHA-256 via `hashlib`, mtime reads via `os.path.getmtime`)

**Atomic state writes:** State file updates use `python3 -c` to write to a temp file and `mv` atomically:
```python
import yaml, tempfile, os, shutil
# ... modify state dict ...
with tempfile.NamedTemporaryFile(mode='w', dir=state_dir, suffix='.tmp', delete=False) as f:
    yaml.dump(state, f)
    tmp = f.name
shutil.move(tmp, state_path)
```

## Prerequisites

- `notebooklm-py` Python package installed (with `[browser]` extra for login)
- Playwright Chromium installed (`playwright install chromium`)
- Authenticated session (`notebooklm login` completed)
- `integrations.notebooklm` section present in `kb.yaml`
- `python3` with `pyyaml` available on PATH (for inline state management)

## Out of Scope

- Scheduling/cron for daily runs (user can set this up separately via `auto-compile.sh` pattern)
- NotebookLM notebook management beyond cleanup (use the global NotebookLM skill directly)
- Chat with NotebookLM sources (use the global skill)
- Sharing/permissions management (use the global skill)
