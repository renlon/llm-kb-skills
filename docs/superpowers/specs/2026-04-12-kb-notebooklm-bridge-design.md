# KB-NotebookLM Bridge Skill Design

**Date:** 2026-04-12
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

1. Reads `kb.yaml` for config and state (notebook IDs, last-run dates, cleanup policy)
2. Accepts both subcommands and natural language
3. Routes to the appropriate workflow
4. Each workflow follows: **select files -> create notebook -> add sources -> wait for processing -> generate artifact -> wait for completion -> download -> update state -> cleanup**

### Subcommands

| Command | Description | File Selection |
|---------|-------------|----------------|
| `podcast [--topic X]` | Podcast from new lessons since last run | Lessons newer than `last_podcast` date, optionally filtered by topic |
| `quiz [--topic X] [--difficulty D]` | Quiz/flashcards from lessons | Same selection as podcast, or topic-filtered |
| `digest` | Wiki changes summary as podcast | Wiki articles changed since last digest |
| `report [--topic X] [--format F]` | Topic-focused report | Lessons + wiki articles matching topic |
| `research-audio` | Research results to podcast | Latest `output/*.md` research reports |
| `cleanup [--days N]` | Delete old MLL notebooks | Notebooks older than N days (default from config) |
| `status` | Show last runs, active notebooks | Reads state from `kb.yaml` |

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

Added under the existing `integrations` section:

```yaml
integrations:
  notebooklm:
    enabled: true
    lessons_path: /Users/dragon/Documents/MLL/lessons
    output_path: /Users/dragon/Documents/MLL/output
    cleanup_days: 7
    podcast:
      format: deep-dive      # deep-dive|brief|critique|debate
      length: default         # short|default|long
      language: zh_Hans       # match lesson language
    quiz:
      difficulty: medium      # easy|medium|hard
      quantity: standard      # fewer|standard|more
    state:
      last_podcast: null      # ISO date string, updated after each run
      last_digest: null
      last_quiz: null
      notebooks: []           # [{id, title, created, workflow}]
      runs: []                # [{workflow, date, sources_hash, artifact_type, output_file, notebook_id}]
```

**State management:** The `state` section is updated by the skill after each successful run. The `notebooks` array tracks created notebooks for cleanup. Each entry:

```yaml
notebooks:
  - id: "abc123de-..."
    title: "MLL Podcast 2026-04-12"
    created: "2026-04-12"
    workflow: podcast
```

## Deduplication

**No duplicate artifacts.** Before generating any content, check whether an equivalent artifact already exists. The dedup key is: `workflow type + sorted source file set (by path) + date`.

Each successful generation is recorded in `state.runs`:

```yaml
state:
  runs:
    - workflow: podcast
      date: "2026-04-12"
      sources_hash: "a1b2c3..."   # SHA-256 of sorted source file paths
      artifact_type: audio
      output_file: /Users/dragon/Documents/MLL/output/podcast-2026-04-12.mp3
      notebook_id: "abc123..."
```

**Dedup check (step added to all workflows, after file selection, before notebook creation):**

1. Compute `sources_hash` = SHA-256 of the sorted list of selected file paths (joined by newline)
2. Search `state.runs` for an entry matching `workflow + sources_hash + date`
3. If match found:
   - Report: "Already generated a <workflow> today from the same sources. Output: <output_file>"
   - Verify the output file still exists on disk
   - If output file exists -> skip, stop
   - If output file missing -> proceed (re-generate)
4. If no match -> proceed with generation

**Same-day, different sources:** If new lessons are added after a podcast was generated, the `sources_hash` will differ, so a new podcast is generated. This is correct — the content changed.

**Topic-filtered runs:** Topic is included in the dedup. `podcast --topic attention` and `podcast --topic quantization` on the same day are different runs because they select different files (different `sources_hash`).

## Workflow Details

### Common Preamble (all workflows)

1. Verify `notebooklm` CLI is on PATH (check with `which notebooklm`)
2. Run `notebooklm auth check --json` — if auth fails, tell user to run `notebooklm login` and stop
3. Read `kb.yaml` — if `integrations.notebooklm` is missing or `enabled: false`, report and stop
4. Load state from `kb.yaml`
5. **(After file selection in each workflow)** Run dedup check as described above

### `podcast [--topic X]`

1. Glob `lessons_path/*.md`, exclude `README.md`
2. Filter to files with filesystem modification date > `state.last_podcast` (if `last_podcast` is null, include all files)
3. If `--topic` provided, further filter by grepping file content and filenames for the topic string (case-insensitive)
4. If no files match -> report "No new lessons since last podcast" and stop
5. `notebooklm create "MLL Podcast YYYY-MM-DD" --json` -> capture notebook ID
6. `notebooklm use <id>`
7. For each selected lesson file: `notebooklm source add <filepath> --json`
   - If a source add fails, log warning and continue with remaining files
   - If all source adds fail, delete the notebook and stop
8. Wait for all sources to be ready: `notebooklm source list --json` and check statuses
9. `notebooklm generate audio "<auto-generated instructions>" --format <config.podcast.format> --length <config.podcast.length> --language <config.podcast.language> --json` -> capture artifact ID
10. Spawn background agent to wait and download:
    - `notebooklm artifact wait <artifact_id> -n <notebook_id> --timeout 1200`
    - `notebooklm download audio <output_path>/podcast-YYYY-MM-DD.mp3 -n <notebook_id>`
11. Update `kb.yaml`: set `state.last_podcast` to today, append notebook to `state.notebooks`
12. Run auto-cleanup: delete notebooks from `state.notebooks` where `created` is older than `cleanup_days`

**Audio instructions generation:** The skill composes instructions based on the selected lessons. Example: "Cover the key concepts from these lessons on [topics]. Make it engaging and educational. Target audience: someone learning ML concepts."

### `quiz [--topic X] [--difficulty D]`

Steps 1-8 identical to `podcast` (same file selection, same source setup).

9. `notebooklm generate quiz --difficulty <D or config.quiz.difficulty> --quantity <config.quiz.quantity> --json` -> capture artifact ID
10. Wait for completion, then download:
    - `notebooklm download quiz --format markdown <output_path>/quiz-YYYY-MM-DD.md -n <notebook_id>`
    - Also: `notebooklm download quiz --format json <output_path>/quiz-YYYY-MM-DD.json -n <notebook_id>`
11. Optionally generate flashcards too:
    - `notebooklm generate flashcards --difficulty <D> --quantity <Q> --json`
    - `notebooklm download flashcards --format markdown <output_path>/flashcards-YYYY-MM-DD.md -n <notebook_id>`
12. Update `kb.yaml`: set `state.last_quiz` to today, append notebook to `state.notebooks`
13. Run auto-cleanup

### `digest`

1. Scan `wiki/` for files with modification date > `state.last_digest`
2. Exclude index files: `_index.md`, `_sources.md`, `_categories.md`, `_evolution.md`
3. If no changed files -> report "No wiki changes since last digest" and stop
4. Create notebook: `notebooklm create "MLL Wiki Digest YYYY-MM-DD" --json`
5. Add changed wiki articles as sources
6. Generate audio with instructions: "Summarize the key changes and new knowledge added to this wiki. Focus on what's new and why it matters."
7. Wait, download to `<output_path>/digest-YYYY-MM-DD.mp3`
8. Update `kb.yaml`: set `state.last_digest` to today, append notebook

### `report [--topic X] [--format F]`

1. `--topic` is required. If not provided, ask the user.
2. Search both `lessons_path/*.md` and `wiki/*.md` for files matching the topic:
   - Grep file content for the topic string (case-insensitive)
   - Also match filenames containing the topic
3. If no files match -> report "No content found for topic '<X>'" and stop
4. Create notebook: `notebooklm create "MLL Report: <topic> YYYY-MM-DD" --json`
5. Add matching files as sources
6. Generate report: `notebooklm generate report --format <F or briefing-doc> --json`
   - Default format: `briefing-doc`. Other options: `study-guide`, `blog-post`, `custom`
7. Wait, download to `<output_path>/report-<topic>-YYYY-MM-DD.md`
8. Update state, append notebook, run cleanup

### `research-audio`

1. Glob `output/*report*.md` and `output/*research*.md` for research output files
2. Sort by modification date, take the most recent (or let user choose if multiple)
3. If no research files -> report "No research output found" and stop
4. Create notebook: `notebooklm create "MLL Research Audio YYYY-MM-DD" --json`
5. Add research file(s) as sources
6. Generate audio: instructions tailored to summarizing research findings
7. Wait, download to `<output_path>/research-audio-YYYY-MM-DD.mp3`
8. Update state, append notebook, run cleanup

### `cleanup [--days N]`

1. Read `state.notebooks` from `kb.yaml`
2. For each notebook where `created` date is older than N days (default: `cleanup_days` from config):
   - `notebooklm delete <notebook_id>` (with confirmation)
   - Remove from `state.notebooks`
3. Update `kb.yaml`

### `status`

1. Read state from `kb.yaml`
2. Display:
   - Last podcast date and file
   - Last digest date and file
   - Last quiz date and file
   - Active notebooks (from `state.notebooks`)
   - Notebooks pending cleanup (older than `cleanup_days`)

## Error Handling

| Error | Action |
|-------|--------|
| `notebooklm` not on PATH | Report: "notebooklm CLI not found. Run `pip install notebooklm-py` in your venv." |
| Auth check fails | Report: "NotebookLM auth expired. Run `notebooklm login`." Stop workflow. |
| `kb.yaml` missing notebooklm config | Report: "Add `integrations.notebooklm` to kb.yaml. See docs." Stop. |
| Source add fails for one file | Log warning, continue with remaining sources |
| All source adds fail | Delete the created notebook, report error, stop |
| Generation fails (rate limit) | Report to user, suggest retry in 5-10 minutes. Do not auto-retry. |
| Artifact wait timeout | Report timeout, suggest checking `notebooklm artifact list` manually |
| Download fails | Check artifact status first, report clearly |
| No files match selection criteria | Report clearly (e.g., "No new lessons since last podcast"), do not create empty notebook |

## Autonomy Rules

**Run without confirmation:**
- File selection and filtering
- `notebooklm auth check`
- `notebooklm source list`
- `notebooklm artifact list`
- `notebooklm status`
- Reading `kb.yaml`
- Natural language routing

**Ask before running:**
- Creating notebooks (`notebooklm create`)
- Generating artifacts (`notebooklm generate *`)
- Downloading files (`notebooklm download *`)
- Deleting notebooks (`notebooklm delete`)
- Updating `kb.yaml` state

## File Structure

```
plugins/kb/skills/
  kb-notebooklm/
    SKILL.md          # Skill definition with all workflow logic
```

Single file. No supporting Python scripts needed — all operations use the `notebooklm` CLI via Bash.

## Prerequisites

- `notebooklm-py` Python package installed (with `[browser]` extra for login)
- Playwright Chromium installed (`playwright install chromium`)
- Authenticated session (`notebooklm login` completed)
- `integrations.notebooklm` section present in `kb.yaml`

## Out of Scope

- Scheduling/cron for daily runs (user can set this up separately via `auto-compile.sh` pattern)
- NotebookLM notebook management beyond cleanup (use the global NotebookLM skill directly)
- Chat with NotebookLM sources (use the global skill)
- Sharing/permissions management (use the global skill)
