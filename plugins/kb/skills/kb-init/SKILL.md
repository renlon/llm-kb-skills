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

If **no**: skip. The user can set this up later by re-running `kb-init` or manually editing `kb.yaml`.

If **yes**, execute all sub-steps automatically — the user should only need to interact for the browser login:

#### 5a. Find or install the CLI

1. **Search for existing install:**
   ```bash
   find ~ -maxdepth 4 -path "*/notebooklm-py/.venv/bin/notebooklm" -type f 2>/dev/null | head -1
   ```

2. **If not found — install automatically:**

   **Find Python 3.10+** (required by notebooklm-py — 3.9 and below fail with `str | None` syntax errors):
   ```bash
   for v in python3.13 python3.12 python3.11 python3.10; do
     p=$(which $v 2>/dev/null || find /opt/homebrew/bin /usr/local/bin -name "$v" -type f 2>/dev/null | head -1)
     if [ -n "$p" ]; then echo "$p"; break; fi
   done
   ```
   If no Python 3.10+ found, report: "NotebookLM requires Python 3.10+. Install with: `brew install python@3.12`" and skip this integration.

   **Create venv and install:**
   ```bash
   PYTHON_BIN="<path from above>"
   mkdir -p ~/notebooklm-py
   $PYTHON_BIN -m venv ~/notebooklm-py/.venv
   ~/notebooklm-py/.venv/bin/pip install 'notebooklm-py[browser]'
   ~/notebooklm-py/.venv/bin/playwright install chromium
   ```

   **Verify the install works:**
   ```bash
   ~/notebooklm-py/.venv/bin/notebooklm --version
   ```
   If this fails, report the error and skip this integration.

3. **If found** — capture the absolute path. Verify it works with `<cli_path> --version`.

Set `NOTEBOOKLM_VENV` to the venv directory (e.g., `~/notebooklm-py/.venv`) for subsequent steps.

#### 5b. Authenticate

**IMPORTANT:** All `notebooklm` commands must run with the venv activated so that `playwright` is on PATH. Always prefix commands with `source <NOTEBOOKLM_VENV>/bin/activate &&`.

1. **Check current auth:**
   ```bash
   source <NOTEBOOKLM_VENV>/bin/activate && notebooklm auth check --json
   ```

2. **If auth fails — guide the user through browser login:**

   Tell the user:
   > I need you to log into Google for NotebookLM. I'll open a browser — sign into your Google account, wait for the NotebookLM homepage to fully load, then **press Enter** in the terminal. Do NOT press Ctrl+C.

   Then instruct the user to run:
   ```
   ! source <NOTEBOOKLM_VENV>/bin/activate && notebooklm login
   ```
   This is the **only manual step** in the entire setup. It must be run by the user because it requires interactive browser input.

3. **After the user reports login is complete, verify:**
   ```bash
   source <NOTEBOOKLM_VENV>/bin/activate && notebooklm auth check --json
   ```
   Check that `status` is `"ok"` in the JSON response. If still failing (`storage_state.json` not found), the login did not save properly. Tell the user:
   > The login didn't save. Please try again — after signing in and seeing the NotebookLM homepage, press **Enter** (Return key) in the terminal, not Ctrl+C.

   Retry up to 2 times. If auth still fails after retries, write config with `enabled: false` and report that the user can authenticate later by running `source ~/notebooklm-py/.venv/bin/activate && notebooklm login`.

#### 5c. Configure preferences

1. **Language:** Ask what language generated content should use. Default: `en`. Common options: `zh_Hans` (Simplified Chinese), `zh_Hant` (Traditional Chinese), `ja`, `ko`.

2. **Lessons path:** Auto-detect from `external_sources` configured in step 4 — look for a label containing "lesson". If not found, default to `<vault_path>/lessons`. Confirm with user.

#### 5d. Write config

Write to `kb.yaml` under `integrations.notebooklm`. All paths must be **absolute**:

```yaml
integrations:
  notebooklm:
    enabled: true
    cli_path: /absolute/path/to/notebooklm-py/.venv/bin/notebooklm
    venv_path: /absolute/path/to/notebooklm-py/.venv
    lessons_path: /absolute/path/to/lessons
    wiki_path: /absolute/path/to/wiki
    output_path: /absolute/path/to/output
    cleanup_days: 7
    max_sources_per_notebook: 45
    language: en
    podcast:
      format: deep-dive
      length: long
    quiz:
      difficulty: medium
      quantity: standard
```

- `cli_path`: absolute path to the `notebooklm` binary inside the venv
- `venv_path`: absolute path to the venv directory (used for `source <venv_path>/bin/activate` in all CLI commands)
- `lessons_path`, `wiki_path`, `output_path`: resolved from vault path and external sources

#### 5e. Podcast Post-Processing Setup (new)

If the user enabled NotebookLM (step 5a-5d above), also set up the prerequisites for intro music assembly and transcript generation.

**A. Install additional venv dependencies** (both for fresh setup and for existing venvs that predate this feature):

```bash
source <NOTEBOOKLM_VENV>/bin/activate && \
  pip install -q 'faster-whisper>=1.0.0' 'pyannote.audio>=3.1.0' 'PyYAML>=6.0'
```

Verify the imports land:

```bash
source <NOTEBOOKLM_VENV>/bin/activate && \
  python3 -c "import faster_whisper, pyannote.audio, yaml; print('OK')"
```

If the verify step fails, report the stderr to the user, point at `plugins/kb/skills/kb-notebooklm/scripts/requirements.txt`, and STOP.

**B. Verify ffmpeg + ffprobe are on PATH:**

```bash
command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null && echo "ffmpeg OK" || echo "ffmpeg MISSING"
```

If missing, guide the user:

> 封面与 intro music 功能需要 ffmpeg。请运行:
> ```
> brew install ffmpeg
> ```
> 完成后重新运行 `/kb-init`。

Record `ffmpeg_available = <bool>`. If unavailable, the skill will proceed but write `intro_music: null` into `kb.yaml` so assembly silently skips per-episode.

**C. HuggingFace token + pyannote license acceptance (for transcripts):**

Check if `HUGGINGFACE_TOKEN` is already set:

```bash
test -n "$HUGGINGFACE_TOKEN" && echo "Token present" || echo "Token missing"
```

If missing, ask the user:

> 是否要启用podcast 字幕/转录功能（需要 HuggingFace 帐号 + 接受两个 pyannote 模型协议）？
> - 启用后可生成 WebVTT 字幕 + markdown 逐字稿
> - 不启用也能用 podcast 功能，仅跳过转录

- **启用 (yes):**
  1. 在浏览器打开 https://huggingface.co/pyannote/segmentation-3.0 并点击 "Agree and access repository"
  2. 在浏览器打开 https://huggingface.co/pyannote/speaker-diarization-3.1 并点击 "Agree and access repository"
  3. 在 https://huggingface.co/settings/tokens 创建一个 read-scope token
  4. 将以下内容加入你的 shell profile (~/.zshrc 或 ~/.bashrc):
     ```
     export HUGGINGFACE_TOKEN=hf_...
     ```
  5. 运行 `source ~/.zshrc` 或重启终端
  6. 完成后按 Enter 继续

  Verify:
  ```bash
  test -n "$HUGGINGFACE_TOKEN" && echo "Token set" || echo "Token still missing"
  ```
  If still missing, warn the user and fall back to `transcript_enabled = false`.

- **跳过 (no):** Set `transcript_enabled = false`.

If the token IS set, attempt a dry-run model download to verify license acceptance:

```bash
source <NOTEBOOKLM_VENV>/bin/activate && \
  python3 -c "
from pyannote.audio import Pipeline
import os
try:
    Pipeline.from_pretrained('pyannote/speaker-diarization-3.1', use_auth_token=os.environ['HUGGINGFACE_TOKEN'])
    print('License check: OK')
except Exception as e:
    print(f'License check FAILED: {e}')
    raise SystemExit(1)
"
```

If this fails, warn the user that one or both licenses haven't been accepted. Point them back to the two URLs and fall back to `transcript_enabled = false`.

**D. Persist the outcome to `kb.yaml`:**

Non-destructive merge into `kb.yaml`. Under `integrations.notebooklm.podcast` (create if missing):

```yaml
integrations:
  notebooklm:
    podcast:
      transcript:
        enabled: <transcript_enabled>       # explicit: true or false based on token/license outcome
        model: "large-v3"
        device: "auto"
        language: "zh"
      hosts: ["瓜瓜龙", "海发菜"]
      extra_host_names: []
      intro_music_length_seconds: 12
      intro_crossfade_seconds: 3
      # intro_music: <omit this line if ffmpeg is unavailable; else leave commented
      #              as a hint for the user to set a path later>
```

**E. Note on model caching:** `faster-whisper` uses the standard HuggingFace cache at `~/.cache/huggingface/hub/`. If the user has VoxToriApp installed on the same machine, the `large-v3` model is likely already cached at `~/.cache/huggingface/hub/models--Systran--faster-whisper-large-v3` and will be reused automatically. Do NOT override `HF_HOME` in this skill.

#### 5f. Seed `shows[0]` (MANDATORY — always runs when NotebookLM is enabled)

Fresh installs MUST create a single `shows[0]` entry with `default: true`. **Never write the
legacy flat single-show podcast config for new installs** — the `integrations.shows[0]` format
is the only supported shape going forward.

**Prompt the user for show identity (use defaults if they press Enter/skip):**

```
Show ID (lowercase, hyphens only, e.g. "quanzhan-ai") [quanzhan-ai]: <input>
Show title (e.g. "全栈AI") [全栈AI]: <input>
Host 1 name [瓜瓜龙]: <input>
Host 2 name [海发菜]: <input>
```

Validate the show id: must match `^[a-z][a-z0-9\-]{0,31}$`. If invalid, re-prompt.

**Write to `kb.yaml` under `integrations.shows` (non-destructive merge — append after notebooklm/xiaoyuzhou):**

```yaml
integrations:
  shows:
    - id: <prompted-id>             # e.g. quanzhan-ai
      title: '<prompted-title>'     # e.g. 全栈AI
      default: true
      language: zh_Hans
      hosts: [<host-1>, <host-2>]
      episodes_registry: episodes.yaml
      wiki_episodes_dir: episodes/<prompted-id>
      podcast_format: deep-dive
      podcast_length: long
      intro_music: null             # user can set path later; null = no intro music
      intro_music_length_seconds: 12
      intro_crossfade_seconds: 3
      transcript:
        enabled: <transcript_enabled>
        model: large-v3
        device: auto
        language: zh
      xiaoyuzhou:
        podcast_id: null            # filled when first episode is published
```

**`episodes_registry` and `wiki_episodes_dir`** are always relative (resolved against project
root at runtime). Do NOT write absolute paths here.

**Create the wiki episodes subdirectory immediately:**

```bash
mkdir -p "<wiki_path>/episodes/<prompted-id>"
```

This ensures the directory exists before the first compile or backfill-index run.

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
  # shows: section is written by step 5f when NotebookLM is enabled.
  # It MUST be present and MUST contain at least one show with default: true
  # for kb-notebooklm and kb-publish to function. See step 5f for schema.
```

When the user sets up Smaug (during init or later), save the install path here. The kb skill reads this to find Smaug without searching every time.

**IMPORTANT:** Do NOT write a flat/legacy single-show podcast config (e.g., top-level
`integrations.notebooklm.podcast.hosts`, `integrations.xiaoyuzhou.episodes_registry` as the
sole registry pointer). New installs always use `integrations.shows[0]`. The `shows[0]` entry
is the single source of truth for show identity, hosts, registry path, and wiki directory.

### 8. Scaffold Directories

Create: `raw/articles/`, `raw/papers/`, `raw/repos/`, `raw/notes/`, `raw/images/`, `raw/transcripts/`, `raw/datasets/`, `wiki/`, `output/`. Plus `.obsidian/` if new vault.

If a show was configured in step 5f, also create `wiki/episodes/<show-id>/` at this point (or confirm it was already created in step 5f — both paths are idempotent).

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
- Do not write the legacy flat single-show config (top-level `integrations.notebooklm.podcast.*`) as the sole podcast identity for new installs. Always seed `integrations.shows[0]` with `default: true` via step 5f.
- Do not skip creating `wiki/episodes/<show-id>/` -- kb-publish and backfill-index expect the directory to exist.
