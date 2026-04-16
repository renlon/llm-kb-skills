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

### Episode Registry (Single-Writer: kb-publish)

The skill maintains an episode registry at the project root (`episodes.yaml`, alongside `kb.yaml`; path configurable via `integrations.xiaoyuzhou.episodes_registry` in kb.yaml). **kb-publish is the sole writer.** kb-notebooklm reads the registry but never writes to it. This registry:

- Tracks episodes through a state machine: `generated → draft → published`
- Entries are keyed by `audio` filename (stable across state transitions)
- EP `id` is assigned only at publish time (publication order, not generation order)
- Entries with `status: generated` have `id: null`

**Schema:**

```yaml
episodes:
  - id: 1                   # assigned at publish time (null until published)
    title: "EP1 | 为什么你的顶级显卡在大模型面前会'罢工'？"
    topic: "GPU Computing & CUDA"  # short English topic label
    description: "从GPU架构讲起..."  # 节目简介 (set at publish time)
    date: 2026-04-13         # publish date
    status: published        # generated → draft → published
    audio: podcast-hardware-2026-04-12.mp3   # stable key
    notebook_id: "uuid"      # links to .notebooklm-state.yaml
    depth: intro             # intro | intermediate | deep-dive
    concepts_covered:
      - name: "GPU vs CPU Architecture"
        depth: explained     # mentioned | explained | deep-dive
      - name: "CUDA Programming Model"
        depth: explained
    open_threads:
      - "Tensor Cores and mixed-precision training"
    source_lessons: []
next_id: 2                   # next publication ID
```

If the registry file doesn't exist, initialize it with `episodes: []` and `next_id: 1`.

**State transitions:**
- `generated`: entry created by preflight sidecar import (Step 2b). `id` is `null`, `title`/`description`/`date` are `null`.
- `draft`: entry updated when uploaded as draft. `id` is still `null`. Title set (no EP prefix).
- `published`: entry updated when published. `id` assigned from `next_id`, `next_id` incremented. Title set with `EP{id}` prefix.

**Re-run guard:** If an entry already has `status: published` and `id` is non-null, do NOT reassign `id` or increment `next_id`. Log a warning and skip registry update.

**Lookup rule:** When `kb-publish` processes an audio file, check if an entry with matching `audio` key already exists. If yes, update that entry (state transition, respecting re-run guard). If no, create a new entry.

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

11. **Read episode registry:**
    Read the file at `integrations.xiaoyuzhou.episodes_registry` (default: `episodes.yaml` at
    project root, alongside `kb.yaml`).
    If the file doesn't exist, initialize with `episodes: []` and `next_id: 1`.
    Record `current_episodes` list and `next_episode_id`.

12. **Resolve browser data path:**
    Read `integrations.xiaoyuzhou.browser_data` (default: `.xiaoyuzhou-browser-data`).
    Resolve relative to project root. This directory stores Playwright persistent context
    (cookies + localStorage + sessionStorage). Login is only needed on first run.

### Step 2: Validate Audio File

1. Parse the audio file path from the user's invocation.
2. Verify the file exists: `test -f "<audio_path>"`.
3. Check the extension is one of: `.mp3`, `.wav`, `.m4a`, `.flac` (case-insensitive). If not, report supported formats and STOP.
4. Verify non-empty: `test -s "<audio_path>"`.
5. Record: `audio_path`, `audio_filename` (basename), `audio_extension`, `audio_size_mb` (via `du -m` or `stat`).
6. Report: "Audio file: <audio_filename> (<audio_size_mb> MB)"

### Step 2b: Preflight — Sidecar Import & Publish Guard

**Publish guard:** Check if a registry entry with `audio == basename(audio_path)` already
has `status: published`. If so, stop immediately:
"⚠ 已发布: EP{id}「{title}」已使用此音频文件发布。如需重新发布请使用 --force-republish。"
Do NOT proceed to upload.

**Sidecar import:** Check if `<audio_path>.manifest.yaml` exists alongside the audio file.
If found:
1. Read the sidecar manifest.
2. **Validate:** confirm `manifest.audio == basename(audio_path)`. If mismatch, warn and skip import.
3. Check if a registry entry with matching `audio` key already exists.
4. If existing entry has `status: published`: skip import (entry is frozen). Log warning.
5. If existing entry has `status: generated` or `draft`: merge any fields from the sidecar that are currently null/empty.
6. If no existing entry: create a schema-complete entry with `status: generated`, `id: null`, `title: null`, `description: null`, `date: null`, and all content manifest fields from the sidecar (`topic`, `depth`, `concepts_covered`, `open_threads`, `source_lessons`, `notebook_id`).
7. Write the registry atomically (write to temp file, rename).
8. Delete the sidecar file only after successful registry write.

### Step 3: Analyze Content for Title/Description

Determine episode content using these sources in priority order:

1. **User context** — any topic, description, or theme the user provided in their invocation or current conversation.
2. **Audio filename** — extract topic hints (e.g., `podcast-ml-transformers-2026-04-15.mp3` → "ML Transformers"). Strip common prefixes like `podcast-`, dates, and extensions.
3. **Conversation history** — if the user recently ran `/kb-notebooklm`, the conversation may contain topic details.

If none of these yield enough context, ask the user:
"请提供这期节目的主题简述（中文或英文都可以）。"

Record the resulting `topic_summary` and `key_concepts` list.

**Topic overlap check:**

Cross-reference the proposed topic against **published episodes only** (filter
`current_episodes` to `status == 'published'`). Compare against
`episode.concepts_covered[].name` and `episode.open_threads`. Report the relationship:

- **No overlap:** Proceed normally.
- **Overlaps with published episode:** Warn the user:
  "⚠ 本期主题与已发布的 EP{N}「{title}」有重叠。EP{N} 已覆盖: {concepts}。
   建议: 本期侧重于 {new_angle} 或标记为进阶/深度内容。"
- **Addresses an open thread:** Note it positively:
  "✓ 本期内容回应了 EP{N} 留下的话题: {open_thread}"

**Note:** This skill does NOT read `.notebooklm-state.yaml`. It works with any audio file from any source.

### Step 4: Generate Episode Title and Description

Generate in Chinese (中文):

- **Title (标题):**
  - **If `--mode publish`:** Format: `EP{next_episode_id} | {口语化标题}`
    EP number is assigned now and committed to the registry on success.
  - **If `--mode draft`:** Format: `{口语化标题}` (no EP prefix).
    Drafts do not get EP numbers. The current automation creates drafts on 小宇宙 but
    cannot promote them to published — that requires manual action on the platform.
    If the user later publishes via `/kb-publish --mode publish` with the same audio,
    a new platform episode is created (the draft remains orphaned on 小宇宙).
  - The 口语化标题 portion should be 10-20 characters
  - Style: 吸引人 (eye-catching), 接地气 (down-to-earth), 口语化 (conversational)
  - Use question format or relatable framing, NOT academic titles
  - Good: "EP3 | Flash Attention 和 KV Cache：让推理快十倍的秘密" (publish mode)
  - Good: "Flash Attention 和 KV Cache：让推理快十倍的秘密" (draft mode)
  - Bad: "EP3 | 注意力机制优化方法综述" (too academic)
- **Description (节目简介):** 100-300 characters. Covers: what the episode discusses,
  key takeaways, target audience. Plain text (no markdown).
  If this episode builds on a published episode, mention it:
  "本期是第{N}期的进阶内容，建议先收听第{N}期了解基础概念。"
  (Only reference published EP numbers, never provisional ones.)

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
  --browser-data "<browser_data_path>" \
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

On first run, the browser opens headed and the user must log in (QR code scan).
Subsequent runs reuse the persistent context — no login needed.

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

### Step 8b: Update Episode Registry

**On success, update the episode registry:**

1. Read `episodes.yaml`.
2. Look for an existing entry with matching `audio` key.
3. **If entry exists with `status: published`** (re-run guard):
   - Log warning: "Episode already published as EP{id}. Registry not modified."
   - Do NOT reassign `id` or increment `next_id`. Skip to step 6.
4. **If entry exists with `status: generated` or `draft`** (state transition):
   - Update `status` to `published` (or `draft` if `--mode draft`).
   - If publishing and `id` is `null`: assign `id` from `next_id`, set `date` to today, increment `next_id`.
   - Merge `title`, `description`, and `topic` from the current upload.
   - Content manifest fields (`concepts_covered`, `open_threads`, `source_lessons`, `depth`) are already populated from the sidecar — preserve them.
5. **If no entry exists** (new audio without prior generation):
   - Create a schema-complete entry with all fields:
     - `audio`: `basename(audio_path)`
     - `topic`: from `topic_summary` in Step 3
     - `id`: if publishing, assign from `next_id` and increment. If draft, set `null`.
     - `title`: the generated title (with or without EP prefix per mode)
     - `description`: the generated description
     - `date`: today if publishing, `null` if draft
     - `status`: `published` or `draft` per mode
     - `notebook_id`: `null` (non-NotebookLM audio)
     - `depth`: estimated from topic analysis in Step 3
     - `concepts_covered`: from key concepts in Step 3
     - `open_threads`: `[]` (unknown for non-NotebookLM audio)
     - `source_lessons`: `[]`
6. Write `episodes.yaml` atomically (write to temp file, rename).

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

Login is handled automatically by the upload script's persistent context.
On first run of `/kb-publish`, the browser opens headed and navigates to the
dashboard. If not logged in, the user completes QR code login in the browser window.
The persistent context saves all browser state (cookies, localStorage, sessionStorage)
to `<browser_data_path>/`. Subsequent runs are automatic.

No separate login step is needed.

### Step S4: Write kb.yaml Config

Non-destructive merge into `kb.yaml`. Read the existing file, parse YAML, add/update only these keys:

```yaml
integrations:
  xiaoyuzhou:
    enabled: true
    podcast_id: "69ddba132ea7a36bbf1efa77"
    browser_data: ".xiaoyuzhou-browser-data"
    episodes_registry: "episodes.yaml"
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
.xiaoyuzhou-browser-data/
.venv-kb-publish/
output/
```
