# kb-publish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a new `kb-publish` skill that publishes podcast episodes to 小宇宙FM — generating Chinese titles/descriptions, creating cover art via Gemini, and automating upload via Playwright.

**Architecture:** Modular Python scripts orchestrated by a SKILL.md prompt. `generate_cover.py` handles Gemini image generation. `upload_xiaoyuzhou.py` handles Playwright browser automation. The SKILL.md orchestrates the full workflow: config reading, audio validation, content analysis, metadata generation, cover art, staging, upload, and reporting.

**Tech Stack:** Python 3.10+, `google-genai` (Gemini API), `playwright` (browser automation), `pyyaml` (YAML parsing), Claude Code SKILL.md prompt

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `plugins/kb/skills/kb-publish/SKILL.md` | Orchestration prompt — the entire workflow |
| Create | `plugins/kb/skills/kb-publish/scripts/generate_cover.py` | Gemini API → cover image PNG |
| Create | `plugins/kb/skills/kb-publish/scripts/upload_xiaoyuzhou.py` | Playwright browser automation → 小宇宙 upload |
| Create | `plugins/kb/skills/kb-publish/scripts/requirements.txt` | Python dependencies |
| Create | `plugins/kb/skills/kb-publish/prompts/cover-style.md` | Brand template for consistent cover art |
| Create | `plugins/kb/skills/kb-publish/references/xiaoyuzhou-selectors.yaml` | CSS selectors for dashboard |
| Modify | `CLAUDE.md` | Add kb-publish to Skills section |

---

### Task 1: Create requirements.txt and directory structure

**Files:**
- Create: `plugins/kb/skills/kb-publish/scripts/requirements.txt`

- [ ] **Step 1: Create the skill directory structure**

```bash
mkdir -p plugins/kb/skills/kb-publish/scripts
mkdir -p plugins/kb/skills/kb-publish/prompts
mkdir -p plugins/kb/skills/kb-publish/references
```

- [ ] **Step 2: Write requirements.txt**

Create `plugins/kb/skills/kb-publish/scripts/requirements.txt`:

```
google-genai>=1.0.0
playwright>=1.40.0
pyyaml>=6.0
```

- [ ] **Step 3: Commit**

```bash
git add plugins/kb/skills/kb-publish/scripts/requirements.txt
git commit -m "chore: scaffold kb-publish skill directory structure"
```

---

### Task 2: Create xiaoyuzhou-selectors.yaml

**Files:**
- Create: `plugins/kb/skills/kb-publish/references/xiaoyuzhou-selectors.yaml`

- [ ] **Step 1: Write the selectors file**

Create `plugins/kb/skills/kb-publish/references/xiaoyuzhou-selectors.yaml`:

```yaml
# 小宇宙 Podcaster Dashboard Selectors
# Updated: 2026-04-15
#
# These selectors are best-effort. The dashboard is a closed SPA that can
# change without notice. When selectors fail, the upload script captures a
# screenshot and returns an error JSON so assets can be uploaded manually.

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

- [ ] **Step 2: Commit**

```bash
git add plugins/kb/skills/kb-publish/references/xiaoyuzhou-selectors.yaml
git commit -m "feat(kb-publish): add xiaoyuzhou dashboard selectors"
```

---

### Task 3: Create cover-style.md brand template

**Files:**
- Create: `plugins/kb/skills/kb-publish/prompts/cover-style.md`

- [ ] **Step 1: Write the brand template**

Create `plugins/kb/skills/kb-publish/prompts/cover-style.md`:

```markdown
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

- [ ] **Step 2: Commit**

```bash
git add plugins/kb/skills/kb-publish/prompts/cover-style.md
git commit -m "feat(kb-publish): add cover art brand template"
```

---

### Task 4: Write generate_cover.py

**Files:**
- Create: `plugins/kb/skills/kb-publish/scripts/generate_cover.py`

- [ ] **Step 1: Write the script**

Create `plugins/kb/skills/kb-publish/scripts/generate_cover.py`:

```python
#!/usr/bin/env python3
"""Generate podcast cover art via Google Gemini (Nano Banana) image generation."""

import argparse
import os
import sys
import time


def parse_args():
    parser = argparse.ArgumentParser(description="Generate cover art via Gemini API")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prompt", help="Image generation prompt (inline)")
    group.add_argument("--prompt-file", help="Path to file containing the prompt")
    parser.add_argument("--output", required=True, help="Output file path (PNG)")
    parser.add_argument("--model", default="gemini-2.5-flash-image", help="Gemini model name")
    parser.add_argument("--aspect", default="1:1", help="Aspect ratio (e.g., 1:1, 16:9)")
    return parser.parse_args()


def generate_image(client, model, prompt, aspect):
    from google.genai import types

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio=aspect),
        ),
    )

    for part in response.parts:
        if part.inline_data is not None:
            return part.as_image()

    raise RuntimeError("No image data in Gemini response")


def main():
    args = parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    from google import genai

    client = genai.Client(api_key=api_key)

    prompt = args.prompt
    if args.prompt_file:
        with open(args.prompt_file, "r", encoding="utf-8") as f:
            prompt = f.read().strip()

    last_error = None
    for attempt in range(2):
        try:
            image = generate_image(client, args.model, prompt, args.aspect)
            os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
            image.save(args.output)
            print(f"Cover saved to {args.output}", file=sys.stderr)
            sys.exit(0)
        except Exception as e:
            last_error = e
            if attempt == 0:
                print(f"Attempt 1 failed: {e}. Retrying in 5s...", file=sys.stderr)
                time.sleep(5)

    print(f"Failed after 2 attempts: {last_error}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Make the script executable**

```bash
chmod +x plugins/kb/skills/kb-publish/scripts/generate_cover.py
```

- [ ] **Step 3: Commit**

```bash
git add plugins/kb/skills/kb-publish/scripts/generate_cover.py
git commit -m "feat(kb-publish): add Gemini cover art generation script"
```

---

### Task 5: Write upload_xiaoyuzhou.py

**Files:**
- Create: `plugins/kb/skills/kb-publish/scripts/upload_xiaoyuzhou.py`

- [ ] **Step 1: Write the script**

Create `plugins/kb/skills/kb-publish/scripts/upload_xiaoyuzhou.py`:

```python
#!/usr/bin/env python3
"""Upload a podcast episode to 小宇宙FM via Playwright browser automation."""

import argparse
import json
import os
import sys
import time

import yaml
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


def parse_args():
    parser = argparse.ArgumentParser(description="Upload episode to 小宇宙FM")
    parser.add_argument("--cookies", required=True, help="Path to cookies JSON file")
    parser.add_argument("--audio", required=True, help="Path to audio file")
    parser.add_argument("--cover", default=None, help="Path to cover image (optional)")
    title_group = parser.add_mutually_exclusive_group(required=True)
    title_group.add_argument("--title", help="Episode title (inline)")
    title_group.add_argument("--title-file", help="Path to file containing the title")
    desc_group = parser.add_mutually_exclusive_group(required=True)
    desc_group.add_argument("--description", help="Episode description (inline)")
    desc_group.add_argument("--description-file", help="Path to file containing the description")
    parser.add_argument("--dashboard-url", required=True, help="小宇宙 dashboard URL")
    parser.add_argument("--selectors", required=True, help="Path to selectors YAML file")
    parser.add_argument("--staging-dir", required=True, help="Path to staging directory for screenshots")
    parser.add_argument("--mode", choices=["draft", "publish"], default="draft", help="Save as draft or publish")
    return parser.parse_args()


def load_selectors(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_cookies(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_cookies(context, path):
    cookies = context.cookies()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)


def output_result(result):
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if result.get("success") else 1)


def capture_screenshot(page, staging_dir, name="error"):
    path = os.path.join(staging_dir, f"{name}.png")
    try:
        page.screenshot(path=path)
    except Exception:
        path = None
    return path


def is_logged_in(page, selectors):
    login_detection = selectors.get("login_detection", {})
    dashboard_pattern = login_detection.get("dashboard_url_pattern", "podcaster.xiaoyuzhoufm.com")
    login_pattern = login_detection.get("login_url_pattern", "xiaoyuzhoufm.com/login")
    # Explicitly check for login redirect first
    if login_pattern in page.url:
        return False
    return dashboard_pattern in page.url


def wait_for_login(page, selectors, timeout_s=300):
    login_detection = selectors.get("login_detection", {})
    dashboard_pattern = login_detection.get("dashboard_url_pattern", "podcaster.xiaoyuzhoufm.com")
    print("请在浏览器中登录小宇宙。登录完成后脚本将自动继续。", file=sys.stderr)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if dashboard_pattern in page.url:
            return True
        time.sleep(2)
    return False


def navigate_with_retry(page, url, selectors):
    for attempt in range(2):
        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
            return
        except Exception as e:
            if attempt == 0:
                print(f"Navigation failed: {e}. Retrying...", file=sys.stderr)
                time.sleep(2)
            else:
                raise


def main():
    args = parse_args()

    # Resolve title and description from inline args or files
    if args.title_file:
        with open(args.title_file, "r", encoding="utf-8") as f:
            args.title = f.read().strip()
    if args.description_file:
        with open(args.description_file, "r", encoding="utf-8") as f:
            args.description = f.read().strip()

    selectors = load_selectors(args.selectors)
    cookies = load_cookies(args.cookies)

    with sync_playwright() as p:
        # Phase 1: Try headless with cookies
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        if cookies:
            context.add_cookies(cookies)
        page = context.new_page()

        try:
            navigate_with_retry(page, args.dashboard_url, selectors)
        except Exception as e:
            browser.close()
            output_result({
                "success": False,
                "error": f"Navigation failed: {e}",
                "screenshot": None,
                "dashboard_url": args.dashboard_url,
                "staging_dir": args.staging_dir,
            })

        # Phase 2: Auth check
        if not is_logged_in(page, selectors):
            browser.close()
            # Relaunch headed for manual login
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()
            navigate_with_retry(page, args.dashboard_url, selectors)

            if not wait_for_login(page, selectors, timeout_s=300):
                screenshot = capture_screenshot(page, args.staging_dir, "login_timeout")
                browser.close()
                output_result({
                    "success": False,
                    "error": "Login timed out after 300s",
                    "screenshot": screenshot,
                    "dashboard_url": args.dashboard_url,
                    "staging_dir": args.staging_dir,
                })

            save_cookies(context, args.cookies)
            print("登录成功，cookies已保存。", file=sys.stderr)
        else:
            # Refresh cookies on successful headless auth
            save_cookies(context, args.cookies)

        # Phase 3: Create episode (no retries after this point)
        try:
            # Click new episode button
            page.click(selectors["new_episode_button"], timeout=10000)
            page.wait_for_load_state("networkidle", timeout=15000)

            # Upload audio
            audio_input = page.locator(selectors["audio_upload_input"])
            audio_input.set_input_files(args.audio)
            # Wait for processing to complete (up to 600s for large files)
            processing = selectors.get("audio_processing_indicator", ".upload-progress")
            try:
                page.wait_for_selector(processing, state="visible", timeout=10000)
            except PlaywrightTimeout:
                pass  # Processing indicator might not appear for small files
            try:
                page.wait_for_selector(processing, state="hidden", timeout=600000)
            except PlaywrightTimeout:
                screenshot = capture_screenshot(page, args.staging_dir, "audio_timeout")
                browser.close()
                output_result({
                    "success": False,
                    "error": "Audio upload/processing timed out after 600s",
                    "screenshot": screenshot,
                    "dashboard_url": args.dashboard_url,
                    "staging_dir": args.staging_dir,
                })

            # Fill title
            title_input = page.locator(selectors["title_input"]).first
            title_input.fill(args.title)

            # Fill description
            desc_input = page.locator(selectors["description_input"]).first
            desc_input.fill(args.description)

            # Upload cover (optional)
            if args.cover and os.path.exists(args.cover):
                cover_input = page.locator(selectors["cover_upload_input"])
                cover_input.set_input_files(args.cover)
                page.wait_for_timeout(3000)  # Wait for cover upload

            # Save/publish
            if args.mode == "draft":
                page.click(selectors["draft_button"], timeout=10000)
            else:
                page.click(selectors["publish_button"], timeout=10000)

            # Wait for confirmation: success indicator OR URL change
            pre_save_url = page.url
            page.wait_for_timeout(3000)
            success_sel = selectors.get("success_indicator", ".success-toast")
            confirmed = False
            try:
                page.wait_for_selector(success_sel, state="visible", timeout=10000)
                confirmed = True
            except PlaywrightTimeout:
                # Check if URL changed (some dashboards redirect on success)
                if page.url != pre_save_url:
                    confirmed = True

            current_url = page.url

            if not confirmed:
                screenshot = capture_screenshot(page, args.staging_dir, "unconfirmed")
                browser.close()
                output_result({
                    "success": False,
                    "error": "Save/publish action did not produce a confirmation signal",
                    "screenshot": screenshot,
                    "dashboard_url": args.dashboard_url,
                    "staging_dir": args.staging_dir,
                })

            browser.close()

            if args.mode == "draft":
                output_result({
                    "success": True,
                    "mode": "draft",
                    "dashboard_url": args.dashboard_url,
                })
            else:
                output_result({
                    "success": True,
                    "mode": "publish",
                    "episode_url": current_url,
                })

        except Exception as e:
            screenshot = capture_screenshot(page, args.staging_dir, "error")
            browser.close()
            output_result({
                "success": False,
                "error": str(e),
                "screenshot": screenshot,
                "dashboard_url": args.dashboard_url,
                "staging_dir": args.staging_dir,
            })


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Make the script executable**

```bash
chmod +x plugins/kb/skills/kb-publish/scripts/upload_xiaoyuzhou.py
```

- [ ] **Step 3: Commit**

```bash
git add plugins/kb/skills/kb-publish/scripts/upload_xiaoyuzhou.py
git commit -m "feat(kb-publish): add Playwright upload script for 小宇宙FM"
```

---

### Task 6: Write SKILL.md

**Files:**
- Create: `plugins/kb/skills/kb-publish/SKILL.md`

This is the core orchestration file. It contains the full workflow prompt that Claude executes.

- [ ] **Step 1: Write the SKILL.md**

Create `plugins/kb/skills/kb-publish/SKILL.md`:

````markdown
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
````

- [ ] **Step 2: Commit**

```bash
git add plugins/kb/skills/kb-publish/SKILL.md
git commit -m "feat(kb-publish): add main orchestration SKILL.md"
```

---

### Task 7: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` — add `kb-publish` to the Skills section

- [ ] **Step 1: Read current CLAUDE.md Skills section**

Read `CLAUDE.md` and locate the `## Skills` section.

- [ ] **Step 2: Add kb-publish entry**

Add the following line after the last skill entry in the Skills list:

```
- `kb-publish` -- Publish podcast episodes to 小宇宙FM with auto-generated Chinese title/description and Gemini cover art.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add kb-publish to CLAUDE.md skills list"
```

---

### Task 8: Manual Verification — Selector Discovery

**Files:**
- Modify: `plugins/kb/skills/kb-publish/references/xiaoyuzhou-selectors.yaml` (if selectors need updating)

This task requires a browser. The selectors in `xiaoyuzhou-selectors.yaml` are best-effort guesses. Before relying on the upload script, you need to verify them against the actual dashboard.

- [ ] **Step 1: Open the dashboard and inspect elements**

Run the venv setup if not already done, then launch a headed browser:

```bash
source "<venv_path>/bin/activate" && python3 -c "
from playwright.sync_api import sync_playwright
import json, time
with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    cookies_path = '.xiaoyuzhou-cookies.json'
    try:
        with open(cookies_path) as f:
            cookies = json.load(f)
        page.context.add_cookies(cookies)
    except FileNotFoundError:
        pass
    page.goto('https://podcaster.xiaoyuzhoufm.com/podcasts/69ddba132ea7a36bbf1efa77/contents-management/episodes')
    print('Browser open. Inspect the dashboard elements and update selectors.')
    print('Press Ctrl+C to close when done.')
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    browser.close()
"
```

- [ ] **Step 2: Update selectors YAML with actual values**

Based on what you observe in the dashboard, update `plugins/kb/skills/kb-publish/references/xiaoyuzhou-selectors.yaml` with the correct CSS selectors.

- [ ] **Step 3: Commit if changes were made**

```bash
git add plugins/kb/skills/kb-publish/references/xiaoyuzhou-selectors.yaml
git commit -m "fix(kb-publish): update selectors from live dashboard inspection"
```

---

### Task 9: End-to-end Test — Dry Run

- [ ] **Step 1: Run the full skill with a test audio file**

Invoke `/kb-publish` with a real audio file in draft mode. Verify:

1. Config is read correctly from `kb.yaml`
2. Audio file is validated
3. Title and description are generated in Chinese
4. Cover art is generated (or manual fallback works)
5. Assets are staged correctly in a timestamped subdirectory
6. `metadata.json` is written with all fields
7. Upload script launches, authenticates, and creates a draft

- [ ] **Step 2: Verify the draft on 小宇宙**

Open the dashboard in a browser and confirm the draft episode exists with the correct title, description, audio, and cover.

- [ ] **Step 3: Test fallback paths**

Test these scenarios:
- Run with `GEMINI_API_KEY` unset → should prompt for manual cover or skip
- Run with `integrations.gemini.enabled: false` → should prompt for manual cover or skip
- Run with expired cookies → should open headed browser for re-login

- [ ] **Step 4: Commit any fixes discovered during testing**

```bash
git add -u
git commit -m "fix(kb-publish): fixes from end-to-end testing"
```
