# KB-NotebookLM Bridge Skill Design

**Date:** 2026-04-12
**Revision:** 2 (post peer-debate review)
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
4. Each workflow follows: **select files -> dedup check -> create notebook -> add sources -> wait for processing -> generate artifact -> wait for completion -> download -> update state -> cleanup**

### Subcommands

| Command | Description | File Selection |
|---------|-------------|----------------|
| `podcast [--topic X]` | Podcast from new lessons since last run | Lessons newer than `last_podcast` timestamp, optionally filtered by topic |
| `quiz [--topic X] [--difficulty D]` | Quiz/flashcards from lessons | Lessons newer than `last_quiz` timestamp, optionally filtered by topic |
| `digest` | Wiki changes summary as podcast | Wiki articles changed since `last_digest` timestamp |
| `report [--topic X] [--format F]` | Topic-focused report | Lessons + wiki articles matching topic |
| `research-audio` | Research results to podcast | Latest `output_path/*.md` research reports |
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

Topic extraction: text after "about", "on", "for", "regarding" becomes `--topic`.

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

**Key changes from v1:**
- `language` is a top-level setting under `notebooklm:`, not nested under `podcast`. All artifact types (podcast, quiz, digest, report) use it.
- `wiki_path` is explicitly configured (not assumed as a relative path).
- `max_sources_per_notebook` caps sources to stay under NotebookLM's platform limit.
- No `state` section — mutable state is stored separately.

### State File: `.notebooklm-state.yaml`

Mutable state lives in a separate file at the KB project root (alongside `kb.yaml`), not inside `kb.yaml`. This prevents config corruption from frequent writes and avoids concurrency issues.

**Path:** `<project_root>/.notebooklm-state.yaml`

```yaml
last_podcast: "2026-04-12T14:30:00Z"    # ISO 8601 timestamp
last_digest: "2026-04-11T09:00:00Z"
last_quiz: "2026-04-10T16:45:00Z"

notebooks:
  - id: "abc123de-..."
    title: "MLL Podcast 2026-04-12"
    created: "2026-04-12T14:30:00Z"
    workflow: podcast

runs:
  - workflow: podcast
    timestamp: "2026-04-12T14:30:00Z"
    sources_hash: "a1b2c3..."
    artifact_type: audio
    output_file: /Users/dragon/Documents/MLL/output/podcast-2026-04-12.mp3
    notebook_id: "abc123..."
```

**Timestamps:** All time values use ISO 8601 with timezone (`YYYY-MM-DDTHH:MM:SSZ`). Compared against filesystem mtime for incremental detection.

**State file writes:** The LLM agent reads the full file, modifies in memory, and writes the entire file back. Since this skill runs single-threaded within one Claude session, there is no concurrency risk. If the file does not exist, the skill creates it with empty defaults.

**Pruning:** The `runs` array is pruned on every write. Entries older than `cleanup_days * 2` (default: 14 days) are removed. This bounds growth to roughly 2-4 entries per day.

## Deduplication

**No duplicate artifacts.** Before generating any content, check whether an equivalent artifact already exists.

The dedup key is: `workflow type + sources_hash`. The `sources_hash` is a SHA-256 of the sorted list of `filepath:mtime` pairs (one per line), so it changes when files are added, removed, or edited.

**Dedup check (runs after file selection, before notebook creation):**

1. Compute `sources_hash`:
   - For each selected file, get its path and filesystem mtime (as ISO 8601)
   - Sort by path
   - Join as `path:mtime\n` and compute SHA-256
2. Search `runs` in state file for an entry matching `workflow + sources_hash`
3. If match found:
   - Report: "Already generated a <workflow> from the same sources on <timestamp>. Output: <output_file>"
   - Verify the output file still exists on disk
   - If output file exists -> skip, stop
   - If output file missing -> proceed (re-generate)
4. If no match -> proceed with generation

**Same-day, different content:** If a lesson file is edited after a podcast was generated, its mtime changes, producing a different `sources_hash`. A new podcast is generated. This is correct — the content changed.

**Same-day, same content:** Running `podcast` twice without any file changes produces the same `sources_hash`. The second run is skipped. This prevents duplicate NotebookLM artifacts.

**Topic-filtered runs:** Different topic filters select different files, producing different `sources_hash` values. `podcast --topic attention` and `podcast --topic quantization` are naturally deduplicated.

## Source Count Limits

NotebookLM imposes per-notebook source limits (Standard: 50, Plus: 100). The `max_sources_per_notebook` config (default: 45) prevents hitting this limit.

**When selected files exceed `max_sources_per_notebook`:**

1. Sort selected files by modification date (newest first)
2. Take the first `max_sources_per_notebook` files
3. Log warning: "Selected N files but limited to <max> newest. Older files excluded: [list]"
4. Proceed with the truncated set

This prioritizes recent content, which aligns with the "new since last run" design. For first-run scenarios (all files selected), only the most recent 45 are included. The user can adjust `max_sources_per_notebook` in `kb.yaml` if they have a higher-tier plan.

## Workflow Details

### Common Preamble (all workflows)

1. Verify `notebooklm` CLI is on PATH (check with `which notebooklm`)
2. Run `notebooklm auth check --json` — if auth fails, tell user to run `notebooklm login` and stop
3. Read `kb.yaml` — if `integrations.notebooklm` is missing or `enabled: false`, report and stop
4. Read `.notebooklm-state.yaml` — if missing, initialize with empty defaults
5. **(After file selection in each workflow)** Enforce source count limit, then run dedup check

### `podcast [--topic X]`

1. Glob `lessons_path/*.md`, exclude `README.md`
2. Filter to files with filesystem mtime > `state.last_podcast` (if `last_podcast` is null, include all files)
3. If `--topic` provided, further filter by grepping file content and filenames for the topic string (case-insensitive)
4. Enforce source count limit (truncate to `max_sources_per_notebook` newest)
5. Run dedup check — if duplicate, stop
6. If no files match -> report "No new lessons since last podcast" and stop
7. **Confirm with user:** "Will create a podcast from N lessons: [list]. Proceed?"
8. `notebooklm create "MLL Podcast YYYY-MM-DD" --json` -> capture notebook ID
9. `notebooklm use <id>`
10. For each selected lesson file: `notebooklm source add <filepath> --json`
    - If a source add fails, log warning and continue with remaining files
    - If all source adds fail, delete the notebook and report error, stop
11. Wait for all sources to be ready: poll `notebooklm source list --json` every 15s until all status=ready (timeout: 600s)
12. `notebooklm generate audio "<instructions>" --format <config.podcast.format> --length <config.podcast.length> --language <config.language> --json` -> capture artifact ID
13. **Long wait — use Agent tool** to spawn a subagent (see Async Completion Model below):
    - Subagent runs: `notebooklm artifact wait <artifact_id> -n <notebook_id> --timeout 1200`
    - Then: `notebooklm download audio <output_path>/podcast-YYYY-MM-DD.mp3 -n <notebook_id>`
    - If `--topic` was provided, filename becomes: `podcast-<topic>-YYYY-MM-DD.mp3`
14. Update state file: set `last_podcast` to now, append notebook to `notebooks`, append to `runs`
15. Run auto-cleanup: delete notebooks from `notebooks` where `created` is older than `cleanup_days`

**Audio instructions:** The skill composes instructions from the selected lessons. Template: "Cover the key concepts from these lessons: [comma-separated lesson titles]. Make it engaging and educational. Highlight connections between topics where they exist. Target audience: someone learning ML/AI concepts."

### `quiz [--topic X] [--difficulty D]`

1. Glob `lessons_path/*.md`, exclude `README.md`
2. Filter to files with filesystem mtime > `state.last_quiz` (NOT `last_podcast` — each workflow tracks its own timestamp)
3. If `--topic` provided, further filter by grepping file content and filenames
4. Enforce source count limit
5. Run dedup check
6. If no files match -> report "No new lessons since last quiz" and stop
7. **Confirm with user:** "Will generate quiz + flashcards from N lessons: [list]. Proceed?"
8. Create notebook: `notebooklm create "MLL Quiz YYYY-MM-DD" --json`
9. `notebooklm use <id>`
10. Add sources (same error handling as podcast)
11. Wait for sources to be ready
12. `notebooklm generate quiz --difficulty <D or config.quiz.difficulty> --quantity <config.quiz.quantity> --language <config.language> --json`
13. Wait for completion, then download:
    - `notebooklm download quiz --format markdown <output_path>/quiz-YYYY-MM-DD.md -n <notebook_id>`
    - `notebooklm download quiz --format json <output_path>/quiz-YYYY-MM-DD.json -n <notebook_id>`
    - If `--topic`, filenames become: `quiz-<topic>-YYYY-MM-DD.md` / `.json`
14. Generate flashcards:
    - `notebooklm generate flashcards --difficulty <D> --quantity <Q> --language <config.language> --json`
    - Wait, then download:
    - `notebooklm download flashcards --format markdown <output_path>/flashcards-YYYY-MM-DD.md -n <notebook_id>`
    - If `--topic`, filename becomes: `flashcards-<topic>-YYYY-MM-DD.md`
15. Update state file: set `last_quiz` to now, append notebook, append runs
16. Run auto-cleanup

### `digest`

1. Glob `wiki_path/*.md` (using configured `wiki_path`, not relative `wiki/`)
2. Filter to files with filesystem mtime > `state.last_digest`
3. Exclude index files: `_index.md`, `_sources.md`, `_categories.md`, `_evolution.md`
4. Enforce source count limit
5. Run dedup check
6. If no changed files -> report "No wiki changes since last digest" and stop
7. **Confirm with user:** "Will create a wiki digest podcast from N changed articles: [list]. Proceed?"
8. Create notebook: `notebooklm create "MLL Wiki Digest YYYY-MM-DD" --json`
9. Add changed wiki articles as sources
10. Wait for sources to be ready
11. `notebooklm generate audio "Summarize the key changes and new knowledge in these wiki articles. Focus on what's new, why it matters, and how topics connect." --language <config.language> --json`
12. Wait and download to `<output_path>/digest-YYYY-MM-DD.mp3` (via subagent)
13. Update state file: set `last_digest` to now, append notebook, append run
14. Run auto-cleanup

### `report [--topic X] [--format F]`

1. `--topic` is required. If not provided, ask the user.
2. Search both `lessons_path/*.md` and `wiki_path/*.md` for files matching the topic:
   - Grep file content for the topic string (case-insensitive)
   - Also match filenames containing the topic
   - Exclude `README.md` and wiki index files
3. Enforce source count limit
4. Run dedup check
5. If no files match -> report "No content found for topic '<X>'" and stop
6. **Confirm with user:** "Will generate a <format> report on '<topic>' from N files: [list]. Proceed?"
7. Create notebook: `notebooklm create "MLL Report: <topic> YYYY-MM-DD" --json`
8. Add matching files as sources, wait for ready
9. `notebooklm generate report --format <F or briefing-doc> --language <config.language> --json`
   - Default format: `briefing-doc`. Other options: `study-guide`, `blog-post`, `custom`
10. Wait, download to `<output_path>/report-<topic>-YYYY-MM-DD.md`
11. Update state, append notebook, append run, run cleanup

### `research-audio`

1. Glob `output_path/*report*.md` and `output_path/*research*.md` (using configured `output_path`)
2. Sort by modification date, take the most recent (or let user choose if multiple)
3. If no research files -> report "No research output found in <output_path>" and stop
4. Run dedup check
5. **Confirm with user:** "Will create an audio summary of: <filename>. Proceed?"
6. Create notebook: `notebooklm create "MLL Research Audio YYYY-MM-DD" --json`
7. Add research file(s) as sources, wait for ready
8. `notebooklm generate audio "Summarize these research findings. Cover key discoveries, methodology, and implications. Make it accessible." --language <config.language> --json`
9. Wait and download to `<output_path>/research-audio-YYYY-MM-DD.mp3` (via subagent)
10. Update state, append notebook, append run, run cleanup

### `cleanup [--days N]`

1. Read `notebooks` from state file
2. For each notebook where `created` timestamp is older than N days (default: `cleanup_days` from config):
   - `notebooklm delete <notebook_id>` — confirm with user before first deletion, then batch the rest
   - Remove from `notebooks` in state
3. Prune `runs` older than `cleanup_days * 2`
4. Write updated state file

### `status`

1. Read state file
2. Display:
   - Last podcast: timestamp and output file
   - Last digest: timestamp and output file
   - Last quiz: timestamp and output file
   - Active notebooks count and list (from `notebooks`)
   - Notebooks pending cleanup (older than `cleanup_days`)
   - Total runs recorded

## Async Completion Model

NotebookLM artifact generation is long-running (10-45 minutes). The skill uses the **Claude Code Agent tool** to handle this:

1. After `notebooklm generate ... --json` returns a `task_id`, the main workflow spawns a subagent using the Agent tool with `run_in_background: true`
2. The subagent prompt includes the exact commands to run:
   ```
   Wait for artifact <artifact_id> in notebook <notebook_id> to complete, then download.
   Run: notebooklm artifact wait <artifact_id> -n <notebook_id> --timeout <T>
   Then: notebooklm download <type> <output_path> -n <notebook_id>
   Report success or failure.
   ```
3. The main conversation continues. The user is notified when the background agent completes.
4. State update happens after the background agent reports success. If the agent reports failure (timeout or error), state is not updated and the user is informed.

**Fallback (if background agent is not suitable):** The skill can instead report the artifact ID and instruct the user to check status later with `notebooklm artifact list` and download manually. This is the safe default if the session is about to end.

## Error Handling

| Error | Action |
|-------|--------|
| `notebooklm` not on PATH | Report: "notebooklm CLI not found. Install with `pip install notebooklm-py`." Stop. |
| Auth check fails | Report: "NotebookLM auth expired. Run `notebooklm login`." Stop. |
| `kb.yaml` missing notebooklm config | Report: "Add `integrations.notebooklm` to kb.yaml." Stop. |
| State file missing | Create with empty defaults. Continue. |
| State file corrupt | Log warning, re-initialize with empty defaults. Continue. |
| Source add fails for one file | Log warning, continue with remaining sources. |
| All source adds fail | Delete the created notebook, report error, stop. |
| Source count exceeds limit | Truncate to newest `max_sources_per_notebook`, log warning. Continue. |
| Generation fails (rate limit) | Report to user, suggest retry in 5-10 minutes. Do not auto-retry. |
| Artifact wait timeout | Report timeout, suggest `notebooklm artifact list`. Do not update state. |
| Download fails | Check artifact status, report clearly. Do not update state. |
| No files match selection | Report clearly, do not create empty notebook. |
| Partial failure (notebook created, generation failed) | Leave notebook in state for cleanup. Report error to user. |

## Autonomy Rules

**Run without confirmation:**
- File selection, filtering, and source count enforcement
- `notebooklm auth check`
- `notebooklm source list` / `notebooklm artifact list`
- Reading `kb.yaml` and state file
- Natural language routing and intent parsing
- State file updates (after user-approved operations complete)
- Age-based notebook cleanup during auto-cleanup step
- Downloading artifacts (after user approved generation)

**Ask before running (single confirmation per workflow):**
- The workflow confirmation prompt (step 7 in podcast, etc.) covers: notebook creation, source adding, and artifact generation as a single approval
- Explicit `cleanup` subcommand (confirm before first deletion)
- `notebooklm delete` when called directly

**Rationale:** The user approves the workflow once at the confirmation prompt. Everything after that (source upload, generation, wait, download, state update, auto-cleanup) is autonomous. This avoids 5+ confirmation prompts per run.

## File Structure

```
plugins/kb/skills/
  kb-notebooklm/
    SKILL.md              # Skill definition with all workflow logic
```

Single SKILL.md file. State management (YAML read/write, SHA-256 hashing, mtime comparison) is performed by the LLM agent using inline `python3 -c` commands via Bash. No separate helper scripts.

**Required system tools:**
- `notebooklm` CLI (from `notebooklm-py` package)
- `python3` (for YAML parsing, SHA-256, mtime reads — already available in the environment)

## Prerequisites

- `notebooklm-py` Python package installed (with `[browser]` extra for login)
- Playwright Chromium installed (`playwright install chromium`)
- Authenticated session (`notebooklm login` completed)
- `integrations.notebooklm` section present in `kb.yaml`
- `python3` available on PATH (for inline state management)

## Out of Scope

- Scheduling/cron for daily runs (user can set this up separately via `auto-compile.sh` pattern)
- NotebookLM notebook management beyond cleanup (use the global NotebookLM skill directly)
- Chat with NotebookLM sources (use the global skill)
- Sharing/permissions management (use the global skill)
