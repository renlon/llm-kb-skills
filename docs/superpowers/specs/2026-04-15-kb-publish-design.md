# kb-publish — Podcast Publishing Skill Design

**Date:** 2026-04-15
**Status:** Draft
**Skill name:** `kb-publish`

## Summary

A new skill that takes a podcast audio file, auto-generates a Chinese episode title and description from user-provided context or filename analysis, optionally generates a branded cover image via Gemini (Nano Banana), and publishes the episode to 小宇宙FM via Playwright browser automation.

## Requirements

### Functional

1. **Input:** User provides a path to a podcast audio file (MP3, WAV, M4A, or FLAC), optionally a topic description, and optionally a mode (`draft` or `publish`, default: `draft`)
2. **Title & Description Generation:** LLM generates a Chinese (中文) episode title and show notes/description from user-provided context, audio filename hints, or conversation history
3. **Cover Art Generation (optional):** Calls Gemini API with a consistent brand template prompt, producing a 1:1 cover image with per-episode topic variation. If Gemini is unavailable, disabled, or fails, user is prompted to provide a cover manually or skip.
4. **Upload to 小宇宙FM:** Playwright automates the podcaster dashboard to upload the audio, fill in title/description, optionally attach cover art, and save as draft (default) or publish
5. **Session Cookie Persistence:** First run requires manual login (phone + SMS). Cookies are saved and reused for subsequent runs. Re-auth triggered only when cookies expire.

### Non-Functional

- Skill follows existing kb plugin patterns (SKILL.md + scripts + prompts, dedicated venv with `source activate` prefix)
- Graceful degradation at every stage: Gemini unavailable → prompt for manual cover or skip; upload failure → staged assets for manual upload
- Chinese language for all generated episode metadata

## Architecture

### File Structure

```
plugins/kb/skills/kb-publish/
├── SKILL.md                          # Orchestration prompt
├── scripts/
│   ├── generate_cover.py             # Gemini API → cover image
│   ├── upload_xiaoyuzhou.py          # Playwright → 小宇宙 upload
│   └── requirements.txt             # google-genai, playwright, pyyaml
├── prompts/
│   └── cover-style.md               # Brand template for cover art
└── references/
    └── xiaoyuzhou-selectors.yaml     # CSS selectors for dashboard (machine-readable)
```

### Configuration (kb.yaml)

```yaml
integrations:
  xiaoyuzhou:
    enabled: true
    podcast_id: "69ddba132ea7a36bbf1efa77"
    # dashboard_url is derived from podcast_id at runtime:
    # https://podcaster.xiaoyuzhoufm.com/podcasts/<podcast_id>/contents-management/episodes
    cookies_path: ".xiaoyuzhou-cookies.json"    # relative to project root, MUST be in .gitignore
    staging_dir: "output/xiaoyuzhou-staging"    # parent dir; each run creates a timestamped subdirectory
    venv_path: null                             # set during setup, e.g. "/path/to/.venv-kb-publish"

  gemini:
    enabled: true                               # false = skip cover generation, prompt for manual cover or skip
    # GEMINI_API_KEY read from environment variable
    model: "gemini-2.5-flash-image"
    cover_aspect: "1:1"
    # cover_style resolved relative to skill directory: plugins/kb/skills/kb-publish/prompts/cover-style.md
    # user can override with an absolute path:
    # cover_style_override: "/path/to/custom-cover-style.md"
```

**Config semantics:**
- `integrations.gemini.enabled: false` or `GEMINI_API_KEY` not set → skip auto cover generation, prompt user for manual cover or skip
- `integrations.xiaoyuzhou.enabled: false` → skill is fully disabled, STOP

### State Management

No persistent state file. This is a stateless publish-on-demand skill. Persisted data:

- **Cookie file** (`.xiaoyuzhou-cookies.json`) — Playwright session cookies, auto-refreshed. MUST be in `.gitignore`.
- **Staging subdirectories** (`output/xiaoyuzhou-staging/<YYYYMMDD-HHMMSS>-<slug>/`) — one per publish run. Each contains audio, cover (if any), and metadata.json. Always kept as a publish log.

## Workflow (7 Steps)

### Step 1: Preamble — Read Configuration and Create Staging Directory

Read `kb.yaml`. Check for `integrations.xiaoyuzhou` section.

**If missing:** Run the first-run setup flow (see "First-Run Setup" section below), then continue. Setup writes `integrations.xiaoyuzhou` to `kb.yaml`, so re-read it after setup completes.

**If present but `enabled: false`:** Report "小宇宙 integration is disabled in kb.yaml." and STOP.

**Normalize paths:** Set `project_root = dirname(kb.yaml)`. Resolve all relative paths in config against `project_root`:
- `cookies_path` → `<project_root>/<cookies_path>` (e.g., `<project_root>/.xiaoyuzhou-cookies.json`)
- `staging_dir` → `<project_root>/<staging_dir>` (e.g., `<project_root>/output/xiaoyuzhou-staging`)
- `venv_path` is always absolute (set during setup)

**Validate required keys:** Verify `podcast_id` and `venv_path` are present and non-null. If `venv_path` is null or missing, run setup Step S2. If `podcast_id` is missing, ask the user for it.

**Backfill defaults:** If `integrations.gemini` section is missing, treat as `gemini_available = false` (same as `enabled: false`).

Determine `mode` from user input (default: `draft`).

**Create run staging directory:** Compute a run-scoped path: `<config.staging_dir>/<YYYYMMDD-HHMMSS>-episode/` (placeholder slug; renamed after title is confirmed in Step 4). Create the directory. All subsequent steps write into this `run_staging_dir`.

Determine cover generation capability:
- If `integrations.gemini.enabled: false` → `gemini_available = false`
- Else if `GEMINI_API_KEY` env var not set → warn "GEMINI_API_KEY not found, cover generation unavailable." → `gemini_available = false`
- Else → `gemini_available = true`

Verify venv and dependencies:
```bash
source "<config.venv_path>/bin/activate" && python3 -c "import google.genai; import playwright.sync_api; import yaml; print('OK')" && python3 -m playwright install --check chromium
```
If venv missing, dependencies not installed, or Chromium not available: run setup Step S2 automatically.

### Step 2: Validate Audio File

Verify the user-provided audio file path exists. Check format via file extension (`.mp3`, `.wav`, `.m4a`, `.flac` — case-insensitive). Verify non-empty via file size.

Preserve the original filename and extension throughout the pipeline. Record: `audio_path`, `audio_filename`, `audio_extension`, `audio_size_mb`.

### Step 3: Analyze Content for Title/Description

Determine episode content using these sources (in priority order):

1. **User context** — any topic, description, or theme the user provided in their invocation message or the current conversation. This is the primary source.
2. **Audio filename** — extract topic hints from the filename (e.g., `podcast-ml-transformers-2026-04-15.mp3` → "ML Transformers").
3. **Conversation history** — if the user recently generated a podcast via `/kb-notebooklm`, the conversation context may contain the topic and source details.

If none of these yield enough context for a meaningful title/description, ask the user: "请提供这期节目的主题简述（中文或英文都可以）。"

**Note:** This skill does NOT read `.notebooklm-state.yaml` or depend on NotebookLM state. It works with any audio file from any source.

### Step 4: Generate Episode Title and Description

Using Opus, generate:
- **Title (标题):** Concise Chinese title, 10-25 characters. Engaging, describes the episode's core topic. No generic titles like "第X期".
- **Description (节目简介):** 100-300 character Chinese description. Includes: what the episode covers, key takeaways, and who would benefit. Formatted for 小宇宙's plain text field.

Present both to the user for quick confirmation before proceeding.

After title is confirmed, rename the staging directory to use a slug of the title (if different from placeholder).

### Step 5: Generate or Collect Cover Art

**Path A — Gemini available (`gemini_available = true`):**

Read the brand template from the skill's `prompts/cover-style.md` (or `cover_style_override` from kb.yaml if set). Construct a Gemini API prompt combining the brand template with the episode topic.

Execute via the dedicated venv:
```bash
source "<config.venv_path>/bin/activate" && python3 "<skill_dir>/scripts/generate_cover.py" \
  --prompt "<constructed_prompt>" \
  --output "<run_staging_dir>/cover.png" \
  --model "<config.gemini.model>" \
  --aspect "<config.gemini.cover_aspect>"
```

On success (exit 0): set `cover_path = "<run_staging_dir>/cover.png"`.

On failure (exit 1): the script handles one internal retry on transient API errors. If it still fails, warn user and fall through to Path B.

**Path B — Gemini unavailable or failed:**

Prompt user: "封面图片生成不可用。请选择：\n1. 提供封面图片路径\n2. 跳过封面（skip）"

- If user provides a path: copy the file to `<run_staging_dir>/` preserving its original extension. Set `cover_path` to the copied file.
- If user says skip: set `cover_path = null`.

### Step 6: Stage Remaining Assets

Symlink (or copy if cross-device) the source audio into `<run_staging_dir>/` preserving the original filename and extension.

Write `metadata.json`:
```json
{
  "title": "<episode_title>",
  "description": "<episode_description>",
  "audio_path": "<absolute_path_to_staged_audio>",
  "cover_path": "<absolute_path_to_staged_cover_or_null>",
  "topic": "<topic_summary>",
  "timestamp": "<ISO-8601>",
  "source_audio": "<original_user_provided_path>",
  "gemini_model": "<model_used_or_null>",
  "mode": "<draft_or_publish>",
  "dashboard_url": "<derived_dashboard_url>",
  "staging_dir": "<absolute_path_to_run_staging_dir>"
}
```

### Step 7: Upload to 小宇宙FM via Playwright

Derive dashboard URL from podcast_id:
```
https://podcaster.xiaoyuzhoufm.com/podcasts/<podcast_id>/contents-management/episodes
```

Build the upload command. Only include `--cover` if `cover_path` is not null:
```bash
source "<config.venv_path>/bin/activate" && python3 "<skill_dir>/scripts/upload_xiaoyuzhou.py" \
  --cookies "<config.cookies_path>" \
  --audio "<run_staging_dir>/<audio_filename>" \
  [--cover "<cover_path>"] \
  --title "<episode_title>" \
  --description "<episode_description>" \
  --dashboard-url "<derived_url>" \
  --selectors "<skill_dir>/references/xiaoyuzhou-selectors.yaml" \
  --staging-dir "<run_staging_dir>" \
  --mode "<mode>"
```

**Script behavior:**

1. **Launch phase:** Start Chromium headless. Load cookies from JSON file (if exists). Set cookies on browser context. Navigate to the dashboard URL.
2. **Auth check:** After navigation, check current URL. If URL contains the login path pattern (from selectors YAML) rather than the dashboard pattern → cookies expired.
   - **Close** the headless browser instance
   - **Relaunch** Chromium in **headed** mode (new browser instance, visible window)
   - Print to stderr: "请在浏览器中登录小宇宙。登录完成后脚本将自动继续。"
   - Poll current URL every 2s. When URL matches dashboard pattern, login is complete. Timeout: 300s.
   - Save new cookies to the cookies JSON file. Continue with this headed browser instance.
3. **Load selectors:** Read `xiaoyuzhou-selectors.yaml` for all CSS selectors and interaction patterns.
4. **Create episode:** Click the new episode button (selector from YAML). Wait for the creation form to load. **No automatic retries after this point** — episode creation is non-idempotent.
5. **Upload audio:** Set audio file on the file input (selector from YAML). Wait for upload/processing to complete (poll for progress indicator to disappear, timeout 600s).
6. **Fill metadata:** Type title into title field. Type description into description field. (Selectors from YAML.)
7. **Upload cover (conditional):** Only if `--cover` flag was provided and the file exists. Set cover image on the file input. Wait for upload confirmation.
8. **Save/publish:** Based on `--mode`:
   - `draft`: Click save-as-draft button. Confirm draft saved (detect URL change or success toast).
   - `publish`: Click publish button. Confirm publish success.
9. **Return result:** Output JSON to stdout:
   - Draft success: `{"success": true, "mode": "draft", "dashboard_url": "<episodes_page_url>"}`
   - Publish success: `{"success": true, "mode": "publish", "episode_url": "<episode_page_url>"}`
   - Failure: `{"success": false, "error": "<message>", "screenshot": "<path>", "dashboard_url": "<url>", "staging_dir": "<path>"}`

**Retry policy:**
- Steps 1-3 (navigation, auth): retry once on network error before failing.
- Steps 4-8 (episode creation, upload, save): **no automatic retry**. On failure, capture screenshot and return error. The staging dir has all assets for manual upload.

### Step 8: Report

Report to user:
- Episode title and description
- Cover art path (if generated/provided)
- Upload result:
  - **Draft success:** "节目已保存为草稿。打开以下链接预览并发布: <dashboard_url>"
  - **Publish success:** "节目已发布！<episode_url>"
  - **Failure:** "上传失败。所有文件已准备在 `<run_staging_dir>/`。请打开 <dashboard_url> 手动上传。错误: <details>"
- Staging dir path (always kept as publish log)

## First-Run Setup

Triggered automatically when `integrations.xiaoyuzhou` is missing from `kb.yaml`.

### Step S1: Gemini API Key (Optional)

Check `GEMINI_API_KEY` env var. If not set:
- Ask: "是否要设置 Gemini 用于自动生成封面？（也可以跳过，手动提供封面。）"
- If yes: guide user to https://ai.google.dev/ to create a free API key. Instruct them to add to shell profile: `export GEMINI_API_KEY=xxx`. Wait for confirmation. Set `integrations.gemini.enabled: true`.
- If no: set `integrations.gemini.enabled: false`.

### Step S2: Create Dedicated Venv and Install Dependencies

Create a Python venv for this skill's dependencies (following the `kb-notebooklm` pattern):

```bash
python3 -m venv "<project_root>/.venv-kb-publish"
source "<project_root>/.venv-kb-publish/bin/activate" && \
  pip install google-genai playwright pyyaml && \
  playwright install chromium
```

Verify installation:
```bash
source "<project_root>/.venv-kb-publish/bin/activate" && \
  python3 -c "import google.genai; import playwright.sync_api; import yaml; print('OK')" && \
  python3 -m playwright install --check chromium
```

Record the venv path in `kb.yaml` → `integrations.xiaoyuzhou.venv_path`.

### Step S3: 小宇宙 Login

Launch Playwright in **headed** mode (using the venv). Navigate to the podcaster dashboard. Print:
"请在浏览器中登录小宇宙播客后台。登录完成后会自动保存登录状态。"

Wait for successful navigation to the dashboard (URL pattern match). Save cookies to `.xiaoyuzhou-cookies.json`.

### Step S4: Write kb.yaml Config

**Non-destructive merge** into existing `kb.yaml` — only add `integrations.xiaoyuzhou` and `integrations.gemini` sections. Do not overwrite existing keys in other sections.

Set all defaults from the Configuration section above. Set `venv_path` to the venv created in S2.

### Step S5: Update .gitignore

Ensure these entries are in `.gitignore` (add if missing, don't duplicate):
- `.xiaoyuzhou-cookies.json`
- `.venv-kb-publish/`
- `output/` (staging directories and other generated output)

## Script Specifications

### generate_cover.py

**Input flags:** `--prompt`, `--output`, `--model` (default: `gemini-2.5-flash-image`), `--aspect` (default: `1:1`)
**Env:** `GEMINI_API_KEY`
**Dependencies:** `google-genai`
**Behavior:**
1. Read `GEMINI_API_KEY` from environment. If not set, exit 1 with "GEMINI_API_KEY not set" on stderr.
2. Initialize `genai.Client()`
3. Call `client.models.generate_content()` with:
   - `model`: from `--model` flag
   - `contents`: the `--prompt` text
   - `config`: `GenerateContentConfig(response_modalities=['IMAGE'], image_config=ImageConfig(aspect_ratio=<--aspect>))`
4. Iterate `response.parts`, find `part.inline_data`, save as PNG to `--output`
5. On API error (rate limit, network, server error): wait 5s, retry once. If retry also fails, exit 1.
6. Exit 0 on success. Exit 1 with error message on stderr on failure.

### upload_xiaoyuzhou.py

**Input flags:** `--cookies`, `--audio`, `--cover` (optional), `--title`, `--description`, `--dashboard-url`, `--selectors`, `--staging-dir`, `--mode` (draft|publish, default: draft)
**Dependencies:** `playwright`, `pyyaml`
**Output:** JSON to stdout (always, even on failure).
**Behavior:**
1. Load selectors from `--selectors` YAML file
2. Load cookies from `--cookies` JSON file (if file exists; empty list if not)
3. Launch Chromium headless. Create context with cookies. Navigate to `--dashboard-url`.
4. Check auth state: if current URL matches login pattern from selectors → close browser, relaunch headed, wait for manual login (URL poll every 2s, 300s timeout), save cookies
5. Click new episode button, upload audio, fill title + description, upload cover (if `--cover` provided), save/publish based on `--mode`
6. On success: output success JSON to stdout
7. On failure: capture screenshot to `--staging-dir`, output error JSON to stdout (includes `dashboard_url` from `--dashboard-url` and `staging_dir` from `--staging-dir`)

**Retry policy within script:**
- Navigation and auth (steps 1-4): retry once on network error.
- Post-creation (steps 5+): no retry. Fail immediately with screenshot.

### references/xiaoyuzhou-selectors.yaml

Machine-readable YAML file containing CSS selectors and interaction patterns. Updated separately from Python logic.

```yaml
# 小宇宙 Podcaster Dashboard Selectors
# Updated: 2026-04-15

new_episode_button: "button:has-text('新建单集')"
audio_upload_input: "input[type='file'][accept*='audio']"
audio_processing_indicator: ".upload-progress, .processing-indicator"
title_input: "input[name='title'], input[placeholder*='标题']"
description_input: "textarea[name='description'], textarea[placeholder*='简介']"
cover_upload_input: "input[type='file'][accept*='image']"
draft_button: "button:has-text('存草稿'), button:has-text('保存')"
publish_button: "button:has-text('发布')"
success_indicator: ".episode-detail, .success-toast"
login_detection:
  dashboard_url_pattern: "podcaster.xiaoyuzhoufm.com"
  login_url_pattern: "xiaoyuzhoufm.com/login"
```

**Note:** These selectors are best-effort. The dashboard is a closed SPA that can change without notice. When selectors fail, the script captures a screenshot and falls back to manual upload via the staging dir.

## Brand Template (prompts/cover-style.md)

Resolved relative to the skill directory (`plugins/kb/skills/kb-publish/prompts/cover-style.md`). Users can override by setting `cover_style_override` in kb.yaml to an absolute path.

```
Generate a podcast cover image with these brand guidelines:

**Visual Style:**
- Clean, modern, minimalist design
- Dark background (deep navy #1a1a2e or charcoal #16213e)
- Accent color: warm gradient (coral #e94560 to gold #f5a623)
- Abstract geometric shapes or subtle tech-inspired patterns

**Layout:**
- Central visual element representing the episode topic: {topic}
- No text in the image (title overlay is handled by the podcast platform)
- Balanced composition suitable for small thumbnail display (1400x1400)

**Mood:** Professional yet approachable, intellectual curiosity

**Topic for this episode:** {topic}
**Key concepts:** {concepts}
```

## Error Handling

| Failure | Recovery |
|---|---|
| `GEMINI_API_KEY` not set | Warn, prompt for manual cover or skip, continue |
| `integrations.gemini.enabled: false` | Prompt for manual cover or skip, continue |
| Gemini API rate limit / error | Handled inside `generate_cover.py` (one internal retry after 5s). If script exits 1, prompt for manual cover or skip. Continue. |
| Cookies expired / missing | Close headless browser, relaunch headed, prompt manual login, save new cookies, continue |
| Dashboard UI changed (selector not found) | Screenshot to staging dir, return error JSON with dashboard_url and staging_dir. Skill reports for manual upload. |
| Audio upload timeout (>600s) | Screenshot, return error JSON. Skill reports staging dir for manual upload. |
| Network error (pre-creation) | Retry once. If still failing, save staging assets, report for manual upload. |
| Network error (post-creation) | No retry. Screenshot, return error JSON. Report for manual upload. |
| Unsupported audio format | Report supported formats (MP3, WAV, M4A, FLAC), STOP |
| Venv or dependency missing | Run setup Step S2 automatically |

## Security

- `GEMINI_API_KEY` read from environment variable only, never stored in files or logs
- 小宇宙 session cookies stored in `.xiaoyuzhou-cookies.json` — MUST be in `.gitignore`
- No personal information (phone numbers, SMS codes) stored or logged
- Scripts never echo secrets to stdout/stderr
- Staging folder metadata.json does not contain credentials

## SKILL.md Frontmatter

```yaml
---
name: kb-publish
user-invocable: true
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, Agent, AskUserQuestion
description: "Use when publishing a podcast episode to 小宇宙FM, or when user says 'publish podcast', 'upload episode', 'publish to xiaoyuzhou', or '/kb-publish'. Takes an audio file, generates Chinese title/description, creates cover art via Gemini, and uploads to 小宇宙FM."
---
```

## Dependencies

- Python 3.10+
- `google-genai` (Gemini API SDK)
- `playwright` (browser automation)
- `pyyaml` (selector file parsing)
- Chromium (installed via `playwright install chromium`, verified during readiness check)
- `GEMINI_API_KEY` environment variable (optional — only needed for auto cover art generation)
- Dedicated venv at path stored in `integrations.xiaoyuzhou.venv_path`
