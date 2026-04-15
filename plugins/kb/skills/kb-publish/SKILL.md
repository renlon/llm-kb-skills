---
name: kb-publish
user-invocable: true
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, Agent, AskUserQuestion
description: "Use when publishing a podcast episode to 小宇宙FM, or when user says 'publish podcast', 'upload episode', 'publish to xiaoyuzhou', or '/kb-publish'. Takes an audio file, generates Chinese title/description, creates cover art via Gemini, and uploads to 小宇宙FM."
---

# kb-publish Skill — Podcast Episode Publisher for 小宇宙FM

Publish a podcast episode to 小宇宙FM. Takes an audio file, generates a Chinese title and description, optionally generates cover art via Gemini (Nano Banana), and automates upload via Playwright browser automation.

**Invocation:** `/kb-publish <audio_file_path> [topic description] [--mode draft|publish]`

**Executor:** Opus single-pass. No subagents.

## Workflow

### Step 1: Preamble — Read Configuration and Create Staging Directory

1. Read `kb.yaml` from the project root. Look for the `integrations.xiaoyuzhou` section.

2. **If missing:** Run the First-Run Setup (see below), then re-read `kb.yaml`.

3. **If `enabled: false`:** Report "小宇宙 integration is disabled in kb.yaml." and STOP.

4. **Normalize paths:** Set `project_root` = directory containing `kb.yaml`. Resolve relative paths:
   - `cookies_path` → `<project_root>/<cookies_path>`
   - `staging_dir` → `<project_root>/<staging_dir>`
   - `venv_path` is always absolute

5. **Validate required keys:** Verify `podcast_id` and `venv_path` are present and non-null.
   - If `venv_path` is null/missing → run Setup Step S2
   - If `podcast_id` is missing → ask user for it

6. **Backfill defaults:** If `integrations.gemini` section is missing, treat as `gemini_available = false`.

7. **Determine mode** from user input. Default: `draft`. Accept `--mode draft` or `--mode publish`.

8. **Create run staging directory:**
   ```
   <staging_dir>/<YYYYMMDD-HHMMSS>-episode/
   ```
   Create with `mkdir -p`. This is `run_staging_dir`. Rename the slug after title is confirmed in Step 4.

9. **Determine cover generation capability:**
   - `integrations.gemini.enabled: false` → `gemini_available = false`
   - `GEMINI_API_KEY` env var not set → warn "GEMINI_API_KEY not found, cover generation unavailable." → `gemini_available = false`
   - Otherwise → `gemini_available = true`

10. **Verify venv and dependencies:**
    ```bash
    source "<venv_path>/bin/activate" && python3 -c "import google.genai; import playwright.sync_api; import yaml; print('OK')" && python3 -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(headless=True); b.close(); p.stop(); print('Chromium OK')"
    ```
    If this fails → run Setup Step S2 automatically.

### Step 2: Validate Audio File

1. Parse the audio file path from the user's invocation.
2. Verify the file exists: `test -f "<audio_path>"`.
3. Check the extension is one of: `.mp3`, `.wav`, `.m4a`, `.flac` (case-insensitive). If not, report supported formats and STOP.
4. Verify non-empty: `test -s "<audio_path>"`.
5. Record: `audio_path`, `audio_filename` (basename), `audio_extension`, `audio_size_mb` (via `du -m` or `stat`).
6. Report: "Audio file: <audio_filename> (<audio_size_mb> MB)"

### Step 3: Analyze Content for Title/Description

Determine episode content using these sources in priority order:

1. **User context** — any topic, description, or theme the user provided in their invocation or current conversation.
2. **Audio filename** — extract topic hints (e.g., `podcast-ml-transformers-2026-04-15.mp3` → "ML Transformers"). Strip common prefixes like `podcast-`, dates, and extensions.
3. **Conversation history** — if the user recently ran `/kb-notebooklm`, the conversation may contain topic details.

If none of these yield enough context, ask the user:
"请提供这期节目的主题简述（中文或英文都可以）。"

Record the resulting `topic_summary` and `key_concepts` list.

**Note:** This skill does NOT read `.notebooklm-state.yaml`. It works with any audio file from any source.

### Step 4: Generate Episode Title and Description

Generate in Chinese (中文):

- **Title (标题):** 10-25 characters. Engaging, describes the core topic. No generic titles like "第X期" or "播客第N集".
- **Description (节目简介):** 100-300 characters. Covers: what the episode discusses, key takeaways, target audience. Plain text (no markdown).

Present both to the user:
```
**标题:** <title>
**节目简介:** <description>

确认以上信息？(yes/回车确认，或提供修改意见)
```

Wait for user confirmation. If user provides edits, apply them.

After title is confirmed, rename the staging directory:
```bash
mv "<run_staging_dir>" "<staging_dir>/<YYYYMMDD-HHMMSS>-<title_slug>/"
```
Update `run_staging_dir` to the new path. Use a sanitized slug: lowercase, hyphens, no special chars, max 40 chars.

### Step 5: Generate or Collect Cover Art

**Path A — `gemini_available = true`:**

1. Determine the skill directory path (where this SKILL.md lives). Read the brand template:
   - Check `integrations.gemini.cover_style_override` in kb.yaml — if set, read that path
   - Otherwise read `<skill_dir>/prompts/cover-style.md`

2. Construct the prompt by replacing `{topic}` with the episode topic and `{concepts}` with the key concepts list.

3. Write the constructed prompt to a temp file `<run_staging_dir>/prompt.txt` (avoids shell injection from model-generated text). Execute:
   ```bash
   source "<venv_path>/bin/activate" && python3 "<skill_dir>/scripts/generate_cover.py" \
     --prompt-file "<run_staging_dir>/prompt.txt" \
     --output "<run_staging_dir>/cover.png" \
     --model "<integrations.gemini.model>" \
     --aspect "<integrations.gemini.cover_aspect>"
   ```

4. If exit 0 → set `cover_path = "<run_staging_dir>/cover.png"`. Report "封面已生成。"

5. If exit 1 → warn user with the error from stderr. Fall through to Path B.

**Path B — Gemini unavailable or failed:**

Prompt user:
"封面图片生成不可用。请选择：\n1. 提供封面图片路径\n2. 跳过封面（skip）"

- If user provides a path: verify it exists, copy to `<run_staging_dir>/` preserving original extension. Set `cover_path` to the copy.
- If user says skip / "2": set `cover_path = null`.

### Step 6: Stage Remaining Assets

1. Symlink the audio file into `run_staging_dir` preserving the original filename:
   ```bash
   ln -s "<audio_path>" "<run_staging_dir>/<audio_filename>"
   ```
   If symlink fails (cross-device), fall back to `cp`.

2. Derive dashboard URL:
   ```
   https://podcaster.xiaoyuzhoufm.com/podcasts/<podcast_id>/contents-management/episodes
   ```

3. Write `<run_staging_dir>/metadata.json`:
   ```json
   {
     "title": "<episode_title>",
     "description": "<episode_description>",
     "audio_path": "<absolute_path_to_staged_audio>",
     "cover_path": "<absolute_path_or_null>",
     "topic": "<topic_summary>",
     "timestamp": "<ISO-8601>",
     "source_audio": "<original_user_path>",
     "gemini_model": "<model_or_null>",
     "mode": "<draft_or_publish>",
     "dashboard_url": "<derived_url>",
     "staging_dir": "<absolute_run_staging_dir>"
   }
   ```

### Step 7: Upload to 小宇宙FM via Playwright

Write title and description to temp files in the staging dir (avoids shell injection from model-generated Chinese text):
- `<run_staging_dir>/title.txt` — episode title
- `<run_staging_dir>/description.txt` — episode description

Build the upload command. Only include `--cover` if `cover_path` is not null:

```bash
source "<venv_path>/bin/activate" && python3 "<skill_dir>/scripts/upload_xiaoyuzhou.py" \
  --cookies "<cookies_path>" \
  --audio "<run_staging_dir>/<audio_filename>" \
  [--cover "<cover_path>"] \
  --title-file "<run_staging_dir>/title.txt" \
  --description-file "<run_staging_dir>/description.txt" \
  --dashboard-url "<dashboard_url>" \
  --selectors "<skill_dir>/references/xiaoyuzhou-selectors.yaml" \
  --staging-dir "<run_staging_dir>" \
  --mode "<mode>"
```

Parse the JSON output from stdout.

If the script opens a headed browser for login (cookies expired), it will print to stderr. The user needs to complete login in the browser window. The script auto-continues after login.

### Step 8: Report

Based on the JSON result:

**Draft success (`success: true, mode: draft`):**
```
节目已保存为草稿。

**标题:** <title>
**简介:** <description>
**封面:** <cover_path or "无">
**草稿链接:** <dashboard_url>

所有文件保存在: <run_staging_dir>/
```

**Publish success (`success: true, mode: publish`):**
```
节目已发布！

**标题:** <title>
**简介:** <description>
**封面:** <cover_path or "无">
**节目链接:** <episode_url>

所有文件保存在: <run_staging_dir>/
```

**Failure (`success: false`):**
```
上传失败。

**错误:** <error>
**截图:** <screenshot path or "无">

所有文件已准备在 `<staging_dir>/`。
请打开以下链接手动上传: <dashboard_url>
```

---

## First-Run Setup

Triggered when `integrations.xiaoyuzhou` is missing from `kb.yaml`.

### Step S1: Gemini API Key (Optional)

Check `GEMINI_API_KEY` env var. If not set:

Ask: "是否要设置 Gemini 用于自动生成封面？（也可以跳过，手动提供封面。）"

- **Yes:** Guide user to https://ai.google.dev/ to create a free API key. Instruct:
  "请将以下内容添加到你的 shell profile (~/.zshrc 或 ~/.bashrc):
  `export GEMINI_API_KEY=your_key_here`
  然后运行 `source ~/.zshrc` 或重启终端。"
  Wait for user confirmation. Verify: `test -n "$GEMINI_API_KEY" && echo "Key is set" || echo "Key not found"`.
  Set `gemini_enabled = true`.

- **No / Skip:** Set `gemini_enabled = false`.

### Step S2: Create Dedicated Venv and Install Dependencies

```bash
python3 -m venv "<project_root>/.venv-kb-publish"
source "<project_root>/.venv-kb-publish/bin/activate" && \
  pip install -r "<skill_dir>/scripts/requirements.txt" && \
  playwright install chromium
```

Verify:
```bash
source "<project_root>/.venv-kb-publish/bin/activate" && \
  python3 -c "import google.genai; import playwright.sync_api; import yaml; print('OK')" && \
  python3 -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(headless=True); b.close(); p.stop(); print('Chromium OK')"
```

If verify fails, report the error and STOP.

Set `venv_path = "<project_root>/.venv-kb-publish"`.

### Step S3: 小宇宙 Login

Run a minimal Playwright script to open the browser for login:

```bash
source "<venv_path>/bin/activate" && python3 -c "
from playwright.sync_api import sync_playwright
import json, time
with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto('https://podcaster.xiaoyuzhoufm.com/dashboard')
    print('请在浏览器中登录小宇宙播客后台。登录完成后会自动保存登录状态。', flush=True)
    deadline = time.time() + 300
    while time.time() < deadline:
        if 'podcaster.xiaoyuzhoufm.com' in page.url and '/login' not in page.url.lower():
            break
        time.sleep(2)
    cookies = page.context.cookies()
    with open('<cookies_path>', 'w') as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)
    print('登录成功，cookies已保存。', flush=True)
    browser.close()
"
```

Replace `<cookies_path>` with the resolved absolute path.

### Step S4: Write kb.yaml Config

Non-destructive merge into `kb.yaml`. Read the existing file, parse YAML, add/update only these keys:

```yaml
integrations:
  xiaoyuzhou:
    enabled: true
    podcast_id: "69ddba132ea7a36bbf1efa77"
    cookies_path: ".xiaoyuzhou-cookies.json"
    staging_dir: "output/xiaoyuzhou-staging"
    venv_path: "<absolute_venv_path>"
  gemini:
    enabled: <gemini_enabled>
    model: "gemini-2.5-flash-image"
    cover_aspect: "1:1"
```

Use the Edit tool to merge — do not overwrite the entire file.

### Step S5: Update .gitignore

Read `.gitignore`. Add these entries if not already present:

```
.xiaoyuzhou-cookies.json
.venv-kb-publish/
output/
```
