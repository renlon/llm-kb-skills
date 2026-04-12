# KB-NotebookLM Bridge Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a `/kb-notebooklm` skill that bridges the MLL knowledge base with Google NotebookLM, enabling automated podcast generation from lessons, quiz/flashcard creation, wiki digest audio, topic-focused reports, and research audio summaries.

**Architecture:** Single SKILL.md file under `plugins/kb/skills/kb-notebooklm/`. The skill reads config from `kb.yaml` and mutable state from `.notebooklm-state.yaml`. All NotebookLM operations use the `notebooklm` CLI with explicit `--notebook` flags (no shared context). State management uses inline `python3 -c` commands for YAML parsing, SHA-256 hashing, and atomic writes.

**Tech Stack:** Claude Code skill (markdown prompt), `notebooklm` CLI, `python3` (inline for YAML/hashing)

**Spec:** `docs/superpowers/specs/2026-04-12-kb-notebooklm-bridge-design.md` (revision 6)

---

### Task 1: Create skill directory and SKILL.md skeleton

**Files:**
- Create: `plugins/kb/skills/kb-notebooklm/SKILL.md`

- [ ] **Step 1: Create the skill directory**

```bash
mkdir -p plugins/kb/skills/kb-notebooklm
```

- [ ] **Step 2: Write SKILL.md with frontmatter, overview, prerequisites, and subcommand reference**

Create `plugins/kb/skills/kb-notebooklm/SKILL.md` with frontmatter, overview, prerequisites check, config reference, subcommand table, and natural language routing. This is the skeleton that all subsequent tasks build upon.

The frontmatter must include:
```yaml
---
name: kb-notebooklm
user-invocable: true
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, Agent, AskUserQuestion
description: "Use when the user wants to generate NotebookLM content (podcasts, quizzes, reports, digests) from KB sources, or when user says 'podcast', 'quiz', 'flashcards', 'digest', 'research audio', or '/kb-notebooklm'. Also triggers on intent like 'create a podcast from my lessons', 'quiz me on recent lessons', 'summarize wiki changes'."
---
```

The overview section must cover:
- What the skill does (bridge KB content to NotebookLM)
- The two layers (content pipeline + intelligent orchestrator)
- That it builds on top of the global NotebookLM skill (does not duplicate)
- Invocation: `/kb-notebooklm <subcommand>` or natural language

The prerequisites section (Common Preamble) must be the **first action on every invocation**:
1. `which notebooklm` — if not found, report install instructions and stop
2. `notebooklm auth check --json` — if fails, tell user to run `notebooklm login` and stop
3. Read `kb.yaml` — if `integrations.notebooklm` missing or `enabled: false`, report and stop
4. Read `.notebooklm-state.yaml` — if missing, initialize empty; if corrupt YAML, back up to `.bak.<timestamp>` and re-initialize

The subcommand table from spec: podcast, quiz, digest, report, research-audio, cleanup, status.

The natural language routing table from spec with topic extraction rules (exclude "on" as trigger).

The CLI command convention: always use `--notebook <id>` or `-n <id>`, never `notebooklm use`.

- [ ] **Step 3: Verify the skill is discovered**

```bash
cd /Users/dragon/PycharmProjects/llm-kb-skills
ls plugins/kb/skills/kb-notebooklm/SKILL.md
```

Expected: file exists with frontmatter and skeleton sections.

- [ ] **Step 4: Commit**

```bash
cd /Users/dragon/PycharmProjects/llm-kb-skills
git add plugins/kb/skills/kb-notebooklm/SKILL.md
git commit -m "feat(kb-notebooklm): add skill skeleton with frontmatter and prerequisites"
```

---

### Task 2: Write state management section

**Files:**
- Modify: `plugins/kb/skills/kb-notebooklm/SKILL.md`

- [ ] **Step 1: Add the State Management section to SKILL.md**

After the prerequisites section, add a "State Management" section that documents:

**State file location:** `<project_root>/.notebooklm-state.yaml` (alongside `kb.yaml`)

**State schema** (the exact YAML structure the skill reads/writes):
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

**Reading state** — inline python3 command:
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

**Writing state** — atomic write via temp file + mv:
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

**Corrupt state recovery:** back up to `.notebooklm-state.yaml.bak.<ISO-timestamp>`, warn user, re-initialize.

**Pruning:** on every write, remove `runs` entries older than `cleanup_days * 2`.

**Concurrency:** single-writer only. Document this limitation.

- [ ] **Step 2: Add the Deduplication section**

After State Management, add a "Deduplication" section documenting:

**Dedup key:** `workflow + sources_hash + params_hash`

**`sources_hash` computation** — inline python3:
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

**`params_hash` computation** — per workflow:
- podcast: `format + length + language + instruction_template`
- quiz: `difficulty + quantity + language`
- digest: `language + instruction_template`
- report: `topic + format + language`
- research-audio: `language + instruction_template`

**Dedup check algorithm** from spec (5 steps including pending/completed/failed branching and partial retry).

**Partial retry:** reuse existing notebook if accessible, skip completed artifacts, re-generate only failed ones. If notebook gone, recreate and re-add sources.

- [ ] **Step 3: Add the Source Count Limits section**

Document the oldest-first selection, truncation to `max_sources_per_notebook`, and watermark cursor rules. Include the all-or-nothing source failure model.

- [ ] **Step 4: Commit**

```bash
cd /Users/dragon/PycharmProjects/llm-kb-skills
git add plugins/kb/skills/kb-notebooklm/SKILL.md
git commit -m "feat(kb-notebooklm): add state management, deduplication, and source limits"
```

---

### Task 3: Write the `podcast` workflow

**Files:**
- Modify: `plugins/kb/skills/kb-notebooklm/SKILL.md`

- [ ] **Step 1: Add the `podcast` workflow section**

Add a `## Workflow: podcast` section with the complete step-by-step algorithm from the spec:

1. Glob `lessons_path/**/*.md`, exclude `README.md`
2. Filter by `(mtime, path) > state.last_podcast` cursor (null = all)
3. If `--topic`, further filter by grepping content + filenames (case-insensitive)
4. Sort by mtime ascending (oldest first), truncate to `max_sources_per_notebook`
5. Compute `sources_hash` and `params_hash`, run dedup check
6. If no files match, report and stop
7. Confirm with user: list files, ask to proceed
8. `notebooklm create "MLL Podcast YYYY-MM-DD" --json` -> capture notebook ID
9. Immediately persist notebook to state with `status: pending`
10. For each file: `notebooklm source add <path> --notebook <id> --json` — any failure aborts entire run (mark notebook `failed`)
11. Poll `notebooklm source list --notebook <id> --json` every 15s until all ready (timeout 600s). Any source `error` aborts.
12. `notebooklm generate audio "<instructions>" --format <format> --length <length> --language <language> --notebook <id> --json`
13. `notebooklm artifact list --notebook <id> --json` -> get artifact ID
14. Persist preliminary run record with artifact `status: pending`
15. Spawn background Agent with `run_in_background: true` to wait + download
16. On success: advance `last_podcast` cursor (if unfiltered, and all artifacts ok), update notebook to `completed`, update run artifact to `completed`
17. Run auto-cleanup

Include the audio instructions template: "Cover the key concepts from these lessons: [titles]. Make it engaging and educational. Highlight connections between topics. Target audience: someone learning ML/AI concepts."

Include output filename logic: `podcast-YYYY-MM-DD.mp3` or `podcast-<topic>-YYYY-MM-DD.mp3`.

- [ ] **Step 2: Add the Async Completion Model section**

Document the async flow (shared by podcast, digest, research-audio):
- CLI contract: `generate --json` returns task_id, resolve via `artifact list`
- Background Agent prompt template
- State written before wait (status: pending), finalized after success
- Session recovery: detect pending runs, check artifact status, resume
- Fallback: if session ending, report artifact ID for manual download
- Sync artifacts (quiz, flashcards, report): wait inline, no background agent

- [ ] **Step 3: Verify skill file is well-formed**

```bash
head -5 plugins/kb/skills/kb-notebooklm/SKILL.md  # check frontmatter
wc -l plugins/kb/skills/kb-notebooklm/SKILL.md     # reasonable length
```

- [ ] **Step 4: Commit**

```bash
cd /Users/dragon/PycharmProjects/llm-kb-skills
git add plugins/kb/skills/kb-notebooklm/SKILL.md
git commit -m "feat(kb-notebooklm): add podcast workflow and async completion model"
```

---

### Task 4: Write the `quiz` workflow

**Files:**
- Modify: `plugins/kb/skills/kb-notebooklm/SKILL.md`

- [ ] **Step 1: Add the `quiz` workflow section**

Add a `## Workflow: quiz` section. This is the most complex workflow because it generates two artifact types (quiz + flashcards) with partial-retry support.

Steps 1-6: same pattern as podcast, but uses `state.last_quiz` cursor.

Step 7: **Partial-retry check** — if dedup found a matching run, inspect per-artifact status:
- If prior notebook accessible: reuse it, skip to generation of failed artifacts only
- If prior notebook gone: create new notebook, re-add sources, generate only failed artifacts
- Report what is being retried

Step 8: Confirm with user (or for partial retry: "Will retry failed artifact(s): [list]")

Steps 9-12: Create notebook (skip if reusing), persist, add sources (skip if reusing), wait for ready (skip if reusing)

Step 13: **Generate quiz** (skip if `completed` in prior run):
- `notebooklm generate quiz --difficulty <D or config.quiz.difficulty> --quantity <config.quiz.quantity> --language <config.language> --notebook <id> --json`
- Wait inline (quiz is relatively fast)
- Download: `notebooklm download quiz --format markdown <output>/quiz-YYYY-MM-DD.md -n <id>`
- Download: `notebooklm download quiz --format json <output>/quiz-YYYY-MM-DD.json -n <id>`
- Topic filenames: `quiz-<topic>-YYYY-MM-DD.md/.json`

Step 14: **Generate flashcards** (skip if `completed` in prior run):
- `notebooklm generate flashcards --difficulty <D or config.quiz.difficulty> --quantity <config.quiz.quantity> --language <config.language> --notebook <id> --json`
- Wait inline, download as markdown
- Topic filename: `flashcards-<topic>-YYYY-MM-DD.md`

Step 15: Finalize state:
- Run record with `artifacts` array (per-artifact `output_files[]` and `status`)
- If all artifacts succeeded AND unfiltered: advance `last_quiz` cursor
- If any artifact failed: do NOT advance cursor. Mark notebook `failed`.
- If topic-filtered: do NOT advance cursor regardless.

Step 16: Auto-cleanup

- [ ] **Step 2: Commit**

```bash
cd /Users/dragon/PycharmProjects/llm-kb-skills
git add plugins/kb/skills/kb-notebooklm/SKILL.md
git commit -m "feat(kb-notebooklm): add quiz workflow with partial-retry support"
```

---

### Task 5: Write the `digest`, `report`, and `research-audio` workflows

**Files:**
- Modify: `plugins/kb/skills/kb-notebooklm/SKILL.md`

- [ ] **Step 1: Add the `digest` workflow**

`## Workflow: digest` — generates an audio summary of wiki changes since last digest.

1. Glob `wiki_path/**/*.md` (recursive)
2. Filter by `(mtime, path) > state.last_digest` cursor
3. Exclude index files: `_index.md`, `_sources.md`, `_categories.md`, `_evolution.md`
4. Sort oldest-first, truncate to `max_sources_per_notebook`
5. Dedup check
6. If no changed files, report and stop
7. Confirm with user
8. Create notebook "MLL Wiki Digest YYYY-MM-DD", persist with `status: pending`
9. Add sources (all-or-nothing), wait for ready
10. `notebooklm generate audio "Summarize the key changes and new knowledge in these wiki articles. Focus on what's new, why it matters, and how topics connect." --language <lang> --notebook <id> --json`
11. Async wait + download to `<output>/digest-YYYY-MM-DD.mp3`
12. Finalize: advance `last_digest` cursor, update notebook to `completed`, append run
13. Auto-cleanup

- [ ] **Step 2: Add the `report` workflow**

`## Workflow: report` — generates a topic-focused report across lessons and wiki.

1. `--topic` required. If missing, ask user.
2. Search `lessons_path/**/*.md` and `wiki_path/**/*.md` (recursive) — grep content + filenames for topic (case-insensitive). Exclude `README.md` and index files.
3. Sort oldest-first, truncate to `max_sources_per_notebook`
4. Dedup check (params_hash includes `topic + format + language`)
5. If no matches, report and stop
6. Confirm with user
7. Create notebook "MLL Report: <topic> YYYY-MM-DD", persist
8. Add sources (all-or-nothing), wait for ready
9. `notebooklm generate report --format <F or briefing-doc> --language <lang> --notebook <id> --append "Focus on the topic: <topic>" --json`
10. Wait inline (reports are sync/fast), download to `<output>/report-<topic>-YYYY-MM-DD.md`
11. Finalize: append run, update notebook. Does NOT advance any watermark.
12. Auto-cleanup

- [ ] **Step 3: Add the `research-audio` workflow**

`## Workflow: research-audio` — turns research output into a podcast.

1. Glob `output_path/**/*report*.md` and `output_path/**/*research*.md`
2. Sort by mtime descending, take most recent (or let user choose if multiple)
3. Dedup check
4. If no files, report and stop
5. Confirm with user
6. Create notebook "MLL Research Audio YYYY-MM-DD", persist
7. Add sources (all-or-nothing), wait for ready
8. `notebooklm generate audio "Summarize these research findings. Cover key discoveries, methodology, and implications. Make it accessible." --language <lang> --notebook <id> --json`
9. Async wait + download to `<output>/research-audio-YYYY-MM-DD.mp3`
10. Finalize: append run, update notebook. Does NOT advance any watermark.
11. Auto-cleanup

- [ ] **Step 4: Commit**

```bash
cd /Users/dragon/PycharmProjects/llm-kb-skills
git add plugins/kb/skills/kb-notebooklm/SKILL.md
git commit -m "feat(kb-notebooklm): add digest, report, and research-audio workflows"
```

---

### Task 6: Write the `cleanup` and `status` workflows

**Files:**
- Modify: `plugins/kb/skills/kb-notebooklm/SKILL.md`

- [ ] **Step 1: Add the `cleanup` workflow**

`## Workflow: cleanup`

1. Read `notebooks` from state file
2. For each notebook where `created` is older than N days (default `cleanup_days`):
   - Confirm with user before first deletion, then batch the rest
   - `notebooklm delete <notebook_id>`
   - Remove from `notebooks` in state
3. Also clean up `pending` or `failed` notebooks older than 1 day (orphaned)
4. Prune `runs` older than `cleanup_days * 2`
5. Write state (atomic)

- [ ] **Step 2: Add the `status` workflow**

`## Workflow: status`

1. Read state file
2. Display in a formatted summary:
   - Last podcast: cursor mtime + path
   - Last digest: cursor mtime + path
   - Last quiz: cursor mtime + path
   - Active notebooks: count, list with status (pending/completed/failed)
   - In-flight jobs: notebooks with `status: pending`
   - Notebooks pending cleanup (older than `cleanup_days`)
   - Total runs recorded

- [ ] **Step 3: Add the Error Handling section**

Add a comprehensive error handling reference table matching the spec's error table. Include the all-or-nothing source model, watermark-safe failure behavior, and async timeout handling.

- [ ] **Step 4: Add the Autonomy Rules section**

Document what runs without confirmation vs what requires the single workflow confirmation prompt. Match the spec exactly.

- [ ] **Step 5: Commit**

```bash
cd /Users/dragon/PycharmProjects/llm-kb-skills
git add plugins/kb/skills/kb-notebooklm/SKILL.md
git commit -m "feat(kb-notebooklm): add cleanup, status, error handling, and autonomy rules"
```

---

### Task 7: Add `kb.yaml` config section to MLL project

**Files:**
- Modify: `/Users/dragon/Documents/MLL/kb.yaml`

- [ ] **Step 1: Read current kb.yaml**

```bash
cat /Users/dragon/Documents/MLL/kb.yaml
```

- [ ] **Step 2: Add the `integrations.notebooklm` section**

Add under the existing `integrations` key (or create it if missing):

```yaml
integrations:
  notebooklm:
    enabled: true
    lessons_path: /Users/dragon/Documents/MLL/lessons
    wiki_path: /Users/dragon/Documents/MLL/wiki
    output_path: /Users/dragon/Documents/MLL/output
    cleanup_days: 7
    max_sources_per_notebook: 45
    language: zh_Hans
    podcast:
      format: deep-dive
      length: default
    quiz:
      difficulty: medium
      quantity: standard
```

Preserve all existing content in `kb.yaml`. Only add the new section.

- [ ] **Step 3: Verify the YAML is valid**

```bash
python3 -c "import yaml; yaml.safe_load(open('/Users/dragon/Documents/MLL/kb.yaml'))" && echo "Valid YAML"
```

Expected: "Valid YAML"

- [ ] **Step 4: Commit (in the MLL repo)**

```bash
cd /Users/dragon/Documents/MLL
git add kb.yaml
git commit -m "config: add integrations.notebooklm section for kb-notebooklm skill"
```

---

### Task 8: End-to-end verification with `status` subcommand

**Files:**
- No new files

- [ ] **Step 1: Verify the skill is loaded**

After reloading plugins, confirm `kb-notebooklm` appears in the skill list. Check by reading the SKILL.md frontmatter:

```bash
head -5 /Users/dragon/PycharmProjects/llm-kb-skills/plugins/kb/skills/kb-notebooklm/SKILL.md
```

Expected: frontmatter with `name: kb-notebooklm`

- [ ] **Step 2: Test prerequisites check**

Verify the skill would pass the common preamble:

```bash
which notebooklm && echo "CLI found" || echo "CLI not found"
notebooklm auth check --json
python3 -c "import yaml; c = yaml.safe_load(open('/Users/dragon/Documents/MLL/kb.yaml')); print('notebooklm config:', 'found' if c.get('integrations',{}).get('notebooklm') else 'missing')"
```

Expected: CLI found, auth check output, config found.

- [ ] **Step 3: Test state initialization**

Verify that reading a non-existent state file returns empty defaults:

```bash
cd /Users/dragon/Documents/MLL
python3 -c "
import yaml, json
try:
    with open('.notebooklm-state.yaml') as f:
        state = yaml.safe_load(f) or {}
    print(json.dumps(state, default=str, indent=2))
except FileNotFoundError:
    print('State file not found - will be initialized on first run')
"
```

Expected: "State file not found" (clean start) or existing state content.

- [ ] **Step 4: Test file selection for podcast**

Verify that lesson files can be globbed and sorted:

```bash
python3 -c "
import glob, os, json
files = sorted(glob.glob('/Users/dragon/Documents/MLL/lessons/**/*.md', recursive=True))
files = [f for f in files if not f.endswith('README.md')]
result = [{'path': f, 'mtime': os.path.getmtime(f)} for f in files]
print(json.dumps(result, indent=2))
print(f'\nTotal: {len(result)} lesson files')
"
```

Expected: list of lesson files with mtimes, matching what we saw earlier (~12 files).

- [ ] **Step 5: Final commit for the llm-kb-skills repo**

```bash
cd /Users/dragon/PycharmProjects/llm-kb-skills
git add -A
git status
# If there are any uncommitted changes, commit them
git diff --cached --stat && git commit -m "feat(kb-notebooklm): complete skill implementation" || echo "Nothing to commit"
```
