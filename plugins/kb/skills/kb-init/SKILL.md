---
name: kb-init
description: "Use when setting up a new knowledge base, bootstrapping an Obsidian vault, or when user says 'init kb', 'new knowledge base', 'create kb', or 'setup vault'. Triggers on any request to initialize or scaffold a knowledge base project."
---

## Overview

One-time (or re-runnable) setup that bootstraps a knowledge base project as an Obsidian vault.

## Prerequisites

Obsidian must be installed.

## Plugin Setup

After confirming the vault path, run the bundled setup script via Bash tool:

```bash
# Interactive — asks user about each optional plugin
bash plugins/kb/setup.sh /path/to/vault

# Install everything
bash plugins/kb/setup.sh /path/to/vault --all

# Install specific plugins only
bash plugins/kb/setup.sh /path/to/vault --only dataview,obsidian-git
```

**Required plugins** (always installed):
- **Dataview** — query wiki articles like a database
- **Obsidian Git** — auto-backup vault to git

**Optional plugins** (user chooses interactively):
- **Kanban** — track wiki tasks on boards
- **Outliner** — better list editing for article drafts
- **Tag Wrangler** — rename and merge tags across the wiki
- **Local Images Plus** — download and store remote images locally

**Browser extension** (printed as manual step):
- **Web Clipper** — clip web articles into `raw/`

The script is idempotent — safe to re-run. If Obsidian is open, tell the user to restart it.

## Flow

### 1. Vault Setup

Ask: create a new vault or use an existing directory? If new, scaffold `.obsidian/`. If existing, verify it exists.

### 2. Source Gathering Strategy

Ask how the user wants to get raw data in:

- **Self-serve** -- User drops files in `raw/`. Per-type guidance:
  - Web articles: Obsidian Web Clipper extension -> `raw/articles/`
  - Academic papers (PDF): Download to `raw/papers/`
  - GitHub repos: Clone/snapshot to `raw/repos/`
  - Local markdown/text: Copy to `raw/notes/`
  - Images/diagrams: Place in `raw/images/`
  - YouTube transcripts: Transcript tool -> `raw/transcripts/`
  - Datasets (CSV, JSON): Place in `raw/datasets/`
  - X/Twitter posts: Via [Smaug](https://github.com/alexknowshtml/smaug) (optional) -> `raw/articles/`
- **Assisted** -- Claude fetches via WebFetch, Bash (clone repos, download PDFs, pull transcripts)
- **Mixed** -- Some of each

### 3. Output Format Preferences

Ask which formats the user wants: markdown (always on), Marp slides, matplotlib charts, HTML, CSV, Excalidraw, other. Use an extensible pattern so new formats can be added later.

### 4. External Sources (Optional)

Ask if the user has existing folders of notes or documents outside the project that should be included in the knowledge base. These folders are managed manually by the user -- the kb skill reads them but never writes to them.

For each external folder the user provides:
- Verify the path exists
- Ask for a short label (used in indexes, e.g., `lessons`, `work-notes`)
- Optionally ask if it should be read-only (default: yes) -- read-only means compile will index and extract from these files but never modify them

Store in `kb.yaml` under `external_sources`:

```yaml
external_sources:
  - path: /Users/me/Documents/MLL/lessons
    label: lessons
    read_only: true
  - path: /Users/me/notes/research
    label: research
    read_only: true
```

The user can add more external sources later by editing `kb.yaml` directly or re-running `kb-init`.

### 5. NotebookLM Integration (Optional)

Ask if the user wants to generate podcasts, quizzes, and digests from their knowledge base via Google NotebookLM.

If **yes**:

1. **Check for existing install:** Look for the `notebooklm` binary:
   ```bash
   which notebooklm 2>/dev/null || find ~ -maxdepth 4 -path "*/notebooklm-py/.venv/bin/notebooklm" -type f 2>/dev/null | head -1
   ```

2. **If not found — install:**
   ```bash
   cd ~ && git clone https://github.com/nicholasgcoles/notebooklm-py.git
   cd ~/notebooklm-py && python3 -m venv .venv
   .venv/bin/pip install 'notebooklm-py[browser]'
   .venv/bin/playwright install chromium
   ```
   Capture the absolute path to the binary: `~/notebooklm-py/.venv/bin/notebooklm`

3. **If found** — capture the absolute path.

4. **Authenticate:** Run `<cli_path> auth check --json`. If auth fails, tell the user to run `<cli_path> login` interactively (suggest `! <cli_path> login` so it runs in the current session).

5. **Ask language preference:** What language should generated content use? Default: `en` (English). Common options: `zh_Hans` (Simplified Chinese), `zh_Hant` (Traditional Chinese), `ja`, `ko`, etc.

6. **Ask lessons path:** Where are lesson files stored? Default: `<vault_path>/lessons`. If the user has an external lessons directory (e.g., `~/Documents/MLL/lessons`), use that.

7. **Write config** to `kb.yaml` under `integrations.notebooklm`:
   ```yaml
   integrations:
     notebooklm:
       enabled: true
       cli_path: /absolute/path/to/notebooklm
       lessons_path: /absolute/path/to/lessons
       wiki_path: /absolute/path/to/wiki
       output_path: /absolute/path/to/output
       cleanup_days: 7
       max_sources_per_notebook: 45
       language: zh_Hans
       podcast:
         format: deep-dive
         length: long
       quiz:
         difficulty: medium
         quantity: standard
   ```
   Use absolute paths for `lessons_path`, `wiki_path`, and `output_path` resolved from the vault path and any external sources configured in step 4.

If **no**: skip. The user can set this up later by re-running `kb-init` or manually editing `kb.yaml`.

### 6. Maintenance Cadence

Inform about options:
- Daily/hourly: `/loop` (e.g., `/loop 1d kb lint`)
- Weekly/monthly: `/schedule`
- Manual: just ask anytime

### 7. Generate `kb.yaml`

Write `kb.yaml` at project root with paths, `output_formats`, obsidian config, and an `integrations` section. Example:

```yaml
integrations:
  smaug:
    path: null  # set automatically when Smaug is installed
```

When the user sets up Smaug (during init or later), save the install path here. The kb skill reads this to find Smaug without searching every time.

### 8. Scaffold Directories

Create: `raw/articles/`, `raw/papers/`, `raw/repos/`, `raw/notes/`, `raw/images/`, `raw/transcripts/`, `raw/datasets/`, `wiki/`, `output/`. Plus `.obsidian/` if new vault.

### 9. Write Project Files

- `CLAUDE.md` -- project instructions for future sessions
- `README.md` -- repo docs with prerequisites, setup, workflows, directory structure, and attribution for research skills

### 10. Next Steps Guidance

Tell user what to do next: add sources, compile, and list available workflows (`compile`, `query`, `lint`, `evolve`).

## Common Mistakes

- Do not overwrite an existing `kb.yaml` without confirming with the user first.
- Do not skip the source-gathering strategy question -- it determines the entire workflow.
- Do not create `.obsidian/` inside a directory that is already an Obsidian vault.
- Do not assume output formats -- always ask the user.
