# Episode Continuity & Podcast Pipeline Improvements — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish episode tracking, content deduplication, and series continuity across the podcast generation (kb-notebooklm) and publishing (kb-publish) skills — so future episodes build on previous ones instead of repeating content.

**Architecture:** `kb-publish` owns a shared `episodes.yaml` registry (single-writer). Entries are keyed by audio filename and transition through `generated → draft → published` states. `kb-notebooklm` writes a sidecar `<audio>.manifest.yaml` alongside each generated MP3 (concepts, depth, open threads); `kb-publish` consumes the sidecar on upload and merges it into the registry entry. Before generating new podcasts, the registry is compiled into a "series bible" injected into NotebookLM's prompt, instructing AI hosts to reference previous episodes and avoid re-explaining covered material. The publishing skill is also updated with correct browser automation (persistent context), cover style, and title format.

**Tech Stack:** SKILL.md prompts (Claude Code), YAML schemas, Python 3 + Playwright (browser automation), Gemini API (cover art)

---

## Why We Are Doing This

During the first real use of the podcast pipeline (2026-04-15), several problems surfaced:

1. **No episode tracking.** The kb-publish skill had no concept of episode IDs or history. Each upload was treated as a standalone event with no awareness of what came before.

2. **No content deduplication across episodes.** kb-notebooklm's dedup checks if the *exact same files* were processed (via `sources_hash`), but has zero awareness of *topic overlap*. If new lessons about "attention" arrive, it would generate a new podcast that re-explains self-attention from scratch — unaware that EP2 already covered this.

3. **No series continuity.** The podcast prompt (`podcast-tutor.md`) tells NotebookLM to "cover these lessons" but has no concept of "you already explained this in EP2, reference it instead." Episodes are generated in isolation with no awareness of the series arc.

4. **Browser automation failures.** The upload script used `browser.launch()` + cookie persistence, which failed because 小宇宙FM also checks localStorage/sessionStorage. Every script run required manual QR code login. CSS selectors were wrong for the actual UI (wrong button text, wrong crop dialog, wrong file upload pattern).

5. **Style inconsistencies.** Cover art and title style had no clear guidelines. The user wants: covers that are 大气/简约/接地气/吸引人, titles that are 口语化 with EP numbers.

## What Problem We're Solving

The podcast pipeline has two skills that don't talk to each other:

```
kb-notebooklm (generates audio) ──→ output/notebooklm/*.mp3 ──→ kb-publish (uploads to 小宇宙)
                                    output/notebooklm/*.mp3.manifest.yaml (sidecar)
```

There is no shared state between them. This causes:
- **Duplicate content:** New lessons on a published topic produce episodes that re-explain everything from scratch
- **No series identity:** Episodes are standalone — no "as we discussed in EP2..." references
- **No episode numbering:** Titles don't carry EP IDs, making it hard for listeners to navigate
- **Manual tracking:** The user has to remember what was published and what wasn't

## What the Goal Is

After this plan is implemented:

1. **A shared `episodes.yaml` registry** (owned by `kb-publish`, single-writer) tracks episodes through a state machine: `generated → draft → published`. Entries are keyed by audio filename. Each entry carries: ID (assigned at publish time), title, date, topic, audio file, and a **content manifest** (concepts covered, depth level, open threads).

2. **Before generating a new podcast**, kb-notebooklm reads the registry, cross-checks topics, warns about overlap, and injects a **series bible** into the NotebookLM prompt — so AI hosts naturally say "we covered this in EP2" instead of re-explaining. After generation, it writes a sidecar `<audio>.manifest.yaml` alongside the MP3.

3. **Before publishing**, kb-publish reads the registry and the sidecar manifest (if present) to assign the next EP number, format the title as `EP{N} | 口语化标题`, and check for topic overlap. EP numbers reflect **publication order**, not generation order.

4. **Browser automation works reliably** — persistent context (login once, never again), correct selectors, correct file upload pattern.

5. **Cover art and title style** follow the user's preferences consistently.

## What We Expect to See

After implementation, running the pipeline on new "attention" lessons should produce:

```
$ /kb-notebooklm podcast

I'd generate an episode on "Attention 进阶: Flash Attention 与 KV Cache":
  - lesson-045-flash-attention.md → NEW (was open thread in EP2)
  - lesson-046-kv-cache.md → NEW (was open thread in EP2)
  - lesson-047-attention-basics.md → OVERLAP with EP2 (skip or merge?)

The series bible will instruct hosts to say:
  "我们在第二期详细讲过注意力机制的基础，还没听过的朋友可以回去听一下。
   今天我们要更深入地看看 Flash Attention 和 KV Cache..."

Proceed?
```

And publishing should auto-assign EP3:

```
$ /kb-publish output/notebooklm/podcast-attention-advanced-2026-04-20.mp3

**标题:** EP3 | Flash Attention 和 KV Cache：让大模型跑得更快的两个关键优化
**节目简介:** ...

⚠ 与已发布节目的关联: EP2 覆盖了注意力机制基础。本期为进阶内容。
```

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `plugins/kb/skills/kb-publish/SKILL.md` | Add episode registry, title format, cover style, persistent context, corrected selectors |
| Modify | `plugins/kb/skills/kb-publish/prompts/cover-style.md` | Updated brand template (大气/简约/接地气/吸引人) |
| Modify | `plugins/kb/skills/kb-publish/references/xiaoyuzhou-selectors.yaml` | Corrected selectors from actual UI |
| Modify | `plugins/kb/skills/kb-publish/scripts/upload_xiaoyuzhou.py` | Persistent context, expect_file_chooser, corrected selectors |
| Modify | `plugins/kb/skills/kb-notebooklm/SKILL.md` | Sidecar manifest generation, series bible injection, published topic cross-check |
| Modify | `plugins/kb/skills/kb-notebooklm/prompts/podcast-tutor.md` | Add `{series_context}` placeholder for series bible |
| Modify | `CLAUDE.md` | Update kb-publish and kb-notebooklm descriptions |
| Runtime | `output/notebooklm/<audio>.manifest.yaml` | Sidecar manifest written by kb-notebooklm, consumed by kb-publish |

---

## Schemas

### episodes.yaml (shared registry — single-writer: kb-publish)

**Ownership:** `kb-publish` is the sole writer. `kb-notebooklm` reads only.

**State machine:** Each entry transitions through: `generated → draft|published`.
- `generated`: created by `kb-publish` preflight when it consumes a sidecar manifest from `kb-notebooklm`. `id` is `null`.
- `draft`: uploaded to 小宇宙 as draft (not yet public). `id` is `null`. EP number not yet assigned. **Note:** The current automation does not support promoting a draft to published on 小宇宙 — that requires manual action on the platform or a future automation.
- `published`: live on 小宇宙. `id` assigned from `next_id`. This is the terminal state.

**Re-run safety:** Once `status: published` and `id` is non-null, the entry is frozen. Re-running `kb-publish` on the same audio is a no-op for the registry (log a warning, do not re-assign `id` or increment `next_id`).

**Keying:** Entries are keyed by `audio` filename (stable across state transitions). EP `id` is assigned only at publish time (reflects publication order, not generation order). Entries with `status: generated` have `id: null`.

```yaml
# episodes.yaml (at project root, alongside kb.yaml)
# Single-writer: kb-publish. kb-notebooklm reads only.
# Entries keyed by audio filename, transition: generated → draft → published.

episodes:
  - id: 1                      # assigned at publish time (publication order)
    title: "EP1 | 为什么你的顶级显卡在大模型面前会'罢工'？"
    topic: "GPU Computing & CUDA"  # short English topic label
    description: "从GPU架构讲起..."  # 节目简介 (set at publish time)
    date: 2026-04-13            # publish date
    status: published           # generated | draft | published
    audio: podcast-hardware-2026-04-12.mp3   # stable key
    notebook_id: "15713c31-..."  # links to .notebooklm-state.yaml
    depth: intro                # intro | intermediate | deep-dive
    concepts_covered:
      - name: "GPU vs CPU Architecture"
        depth: explained        # mentioned | explained | deep-dive
      - name: "CUDA Programming Model"
        depth: explained
      - name: "Memory Bandwidth Bottlenecks"
        depth: explained
    open_threads:               # things hinted at but not covered
      - "Tensor Cores and mixed-precision training"
      - "Multi-GPU scaling (NVLink, PCIe)"
    source_lessons: []          # lesson file basenames that were fed to NotebookLM

  - id: 2
    title: "EP2 | 聊聊 Attention：大模型为什么能'看懂'上下文？"
    topic: "Attention Mechanism"
    description: "今天我们聊聊大模型..."
    date: 2026-04-15
    status: published
    audio: podcast-attention-2026-04-12.mp3
    notebook_id: "0e2b44f1-..."
    depth: intro
    concepts_covered:
      - name: "Self-Attention (Q/K/V)"
        depth: explained
      - name: "Scaled Dot-Product Attention"
        depth: explained
      - name: "Multi-Head Attention"
        depth: explained
      - name: "Transformer Architecture"
        depth: mentioned
    open_threads:
      - "Positional encoding"
      - "KV Cache optimization"
      - "Flash Attention"
    source_lessons: []

  - id: null                    # not yet published — no EP number
    title: null
    topic: "Quantization"       # from sidecar manifest
    description: null            # set at publish time
    date: null
    status: generated
    audio: podcast-quantization-2026-04-14.mp3
    notebook_id: "abc123-..."
    depth: intro
    concepts_covered:
      - name: "Quantization Basics"
        depth: explained
    open_threads:
      - "GPTQ vs AWQ comparison"
    source_lessons:
      - lesson-050-quantization.md

next_id: 3                      # next publication ID (only incremented on publish)
```

### Sidecar manifest (written by kb-notebooklm alongside generated audio)

After podcast generation, `kb-notebooklm` writes `<audio_filename>.manifest.yaml` in the same directory as the MP3. This is the handoff to `kb-publish`.

```yaml
# output/notebooklm/podcast-attention-advanced-2026-04-20.mp3.manifest.yaml
# Written by kb-notebooklm after generation. Consumed by kb-publish on upload.

audio: podcast-attention-advanced-2026-04-20.mp3
topic: "Flash Attention & KV Cache"
notebook_id: "def456-..."
generated_date: 2026-04-20
depth: intermediate
concepts_covered:
  - name: "Flash Attention"
    depth: explained
  - name: "KV Cache Optimization"
    depth: explained
  - name: "Self-Attention"
    depth: mentioned           # recap only, covered in EP2
open_threads:
  - "Multi-Query Attention (MQA)"
  - "Ring Attention for long sequences"
source_lessons:
  - lesson-045-flash-attention.md
  - lesson-046-kv-cache.md
```

### Series Bible (compiled at generation time, injected into prompt)

```
SERIES CONTINUITY — "全栈AI" Podcast

The following PUBLISHED episodes have established knowledge with the audience.
Use this to avoid repetition and build on prior content.
(Note: the episode number for THIS episode will be assigned at publish time.)

EP1: GPU Computing & CUDA (intro)
  Covered: GPU vs CPU architecture, CUDA programming model, memory bandwidth bottlenecks
  Listener already knows: what a GPU is, why it's faster for parallel work, basic CUDA concepts
  Open threads: Tensor Cores, multi-GPU scaling

EP2: Attention Mechanism (intro)
  Covered: Self-attention (Q/K/V), scaled dot-product attention, multi-head attention
  Listener already knows: how attention computes relevance scores, what Q/K/V are
  Open threads: positional encoding, KV Cache, Flash Attention

RULES:
- If a concept was EXPLAINED in a previous episode, DO NOT re-explain it.
  Say: "我们在第N期详细讲过[concept]，还没听过的朋友可以回去听一下"
  Then build on top of it.
- If a concept was only MENTIONED, you may briefly recap (1-2 sentences) before going deeper.
- If this episode is a deep-dive on a previous intro topic, explicitly frame it:
  "上次我们聊了[topic]的基础，今天我们要更深入地看看..."
- Always reference specific episode numbers so listeners can navigate the series.
- When an open thread from a previous episode is being addressed, call it out:
  "上次留了个悬念说要聊[topic]，今天我们来填这个坑"
```

---

### Task 1: Update cover-style.md prompt template

**Files:**
- Modify: `plugins/kb/skills/kb-publish/prompts/cover-style.md`

- [ ] **Step 1: Replace cover-style.md with updated brand template**

Replace the entire contents of `plugins/kb/skills/kb-publish/prompts/cover-style.md` with:

```markdown
Generate a podcast cover image for the show "全栈AI" (Full-Stack AI).

**Style requirements (核心风格要求):**
- 大气 (grand, impressive) — bold visual impact, confident composition, not timid or cluttered
- 简约 (minimalist) — clean lines, limited color palette, generous negative space
- 接地气 (down-to-earth, relatable) — approachable, not overly abstract or academic
- 吸引人 (eye-catching) — strong focal point that stands out at thumbnail size
- 和这期节目贴切 (relevant to the episode topic) — visual metaphor should clearly connect to the subject

**Visual direction:**
- Dark background (deep navy or charcoal)
- Warm accent colors (coral, amber, gold gradients)
- Central visual element representing the topic: {topic}
- No text in the image — keep it purely visual
- 1400x1400 square format, must look good as a small podcast thumbnail

**Mood:** Professional yet approachable, intellectual curiosity, technical depth made accessible

**Topic for this episode:** {topic}
**Key concepts:** {concepts}
```

- [ ] **Step 2: Commit**

```bash
git add plugins/kb/skills/kb-publish/prompts/cover-style.md
git commit -m "feat(kb-publish): update cover prompt — 大气/简约/接地气/吸引人 style"
```

---

### Task 2: Update xiaoyuzhou-selectors.yaml with correct selectors

**Files:**
- Modify: `plugins/kb/skills/kb-publish/references/xiaoyuzhou-selectors.yaml`

- [ ] **Step 1: Replace selectors with values discovered from actual UI testing**

Replace the entire contents of `plugins/kb/skills/kb-publish/references/xiaoyuzhou-selectors.yaml` with:

```yaml
# 小宇宙 Podcaster Dashboard Selectors
# Updated: 2026-04-15
# Source: actual UI testing — the dashboard is a two-panel editor:
#   Left: title input + rich text show notes (ProseMirror/contenteditable)
#   Right: audio upload (+), publish mode, cover upload
#   Bottom: agreement checkbox + "创建" button
#
# Audio and cover uploads use click-to-open file pickers, NOT direct <input> elements.
# Use Playwright's expect_file_chooser() to intercept the native file dialog.

# Episodes list page
new_episode_button: "text=/创建单集/"

# Create episode page — right panel (audio)
audio_upload_text: "text=/点击上传音频/"
# Use expect_file_chooser() after clicking audio_upload_text

# Create episode page — left panel (metadata)
title_input: "input[placeholder*='标题']"
description_editor:
  # Show notes uses a rich-text editor. Try selectors in order:
  - "[contenteditable='true']"
  - ".ProseMirror"
  - "textarea"

# Create episode page — right panel (cover)
cover_upload_text: "text=/点击上传封面/"
# Use expect_file_chooser() after clicking cover_upload_text
cover_crop_confirm: "text=/^裁剪$/"     # NOT "确定" — the crop dialog button says "裁剪"

# Publish options
publish_now: "text=立即发布"
publish_scheduled: "text=定时发布"

# Agreement + submit
agreement_text: "text=阅读并同意"       # Click to the left of this text to hit the checkbox
create_button: "text=/^创建$/"          # Use .last to avoid matching "创建单集" header

login_detection:
  dashboard_url_pattern: "podcaster.xiaoyuzhoufm.com"
  login_url_pattern: "xiaoyuzhoufm.com/login"
```

- [ ] **Step 2: Commit**

```bash
git add plugins/kb/skills/kb-publish/references/xiaoyuzhou-selectors.yaml
git commit -m "fix(kb-publish): correct selectors from actual UI testing"
```

---

### Task 3: Rewrite upload_xiaoyuzhou.py — persistent context + correct automation

**Files:**
- Modify: `plugins/kb/skills/kb-publish/scripts/upload_xiaoyuzhou.py`

This is the biggest code change. The current script uses `browser.launch()` + cookie injection, which fails because 小宇宙 checks localStorage/sessionStorage. Each run required manual QR login.

- [ ] **Step 1: Rewrite upload_xiaoyuzhou.py**

Replace the entire contents of `plugins/kb/skills/kb-publish/scripts/upload_xiaoyuzhou.py` with a script that:

1. Uses `launch_persistent_context(browser_data_dir)` instead of `browser.launch()` + cookies
2. Accepts `--browser-data` argument (path to persistent context directory)
3. On first run: detects login page, prints message, waits for user to log in (up to 10 minutes)
4. On subsequent runs: persistent context has full browser state, no login needed
5. Uses `page.expect_file_chooser()` for audio and cover uploads (click the upload area, intercept file dialog)
6. Crop dialog: clicks "裁剪" not "确定"
7. Agreement checkbox: clicks to the left of "阅读并同意" text using bounding box coordinates
8. Create button: uses `text=/^创建$/` with `.last` to avoid matching the "创建单集" heading
9. Falls back to `--cookies` if `--browser-data` is not provided (backward compat)
10. Keeps browser open for 15 seconds after submission so user can verify
11. JSON output on stdout: `{success, mode, error, dashboard_url, episode_url}` (matches current consumer contract)

The full replacement script (approximately 200 lines):

```python
#!/usr/bin/env python3
"""Upload a podcast episode to 小宇宙FM via Playwright browser automation.

Uses persistent browser context for login state persistence:
- First run: headed browser, user logs in manually, state saved to disk
- Subsequent runs: automatic, no login needed

Audio and cover uploads use expect_file_chooser() to intercept native file dialogs.
"""

import argparse
import json
import os
import sys
import time

import yaml
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


def parse_args():
    parser = argparse.ArgumentParser(description="Upload episode to 小宇宙FM")
    parser.add_argument("--browser-data", default=None,
                        help="Path to persistent browser context directory (preferred)")
    parser.add_argument("--cookies", default=None,
                        help="Path to cookies JSON file (legacy fallback)")
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
    parser.add_argument("--staging-dir", required=True,
                        help="Path to staging directory for screenshots")
    parser.add_argument("--mode", choices=["draft", "publish"], default="draft",
                        help="Save as draft or publish immediately")
    return parser.parse_args()


def load_selectors(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def output_result(result):
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if result.get("success") else 1)


def capture_screenshot(page, staging_dir, name="error"):
    path = os.path.join(staging_dir, f"{name}.png")
    try:
        page.screenshot(path=path, full_page=True)
    except Exception:
        path = None
    return path


def get_url(page):
    """Get current URL via JS (SPA-safe)."""
    try:
        return page.evaluate("window.location.href")
    except Exception:
        return page.url


def log(msg):
    print(f">>> {msg}", file=sys.stderr, flush=True)


def main():
    args = parse_args()

    if args.title_file:
        with open(args.title_file, "r", encoding="utf-8") as f:
            args.title = f.read().strip()
    if args.description_file:
        with open(args.description_file, "r", encoding="utf-8") as f:
            args.description = f.read().strip()

    selectors = load_selectors(args.selectors)

    with sync_playwright() as p:
        # --- Browser setup ---
        if args.browser_data:
            os.makedirs(args.browser_data, exist_ok=True)
            context = p.chromium.launch_persistent_context(
                args.browser_data, headless=False,
                viewport={"width": 1280, "height": 900})
            page = context.new_page()
            use_persistent = True
        else:
            # Legacy fallback: launch + cookies
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
            if args.cookies and os.path.exists(args.cookies):
                with open(args.cookies, "r") as f:
                    cookies = json.load(f)
                if cookies:
                    context.add_cookies(cookies)
            page = context.new_page()
            use_persistent = False

        # --- Navigate ---
        page.goto(args.dashboard_url, wait_until="networkidle", timeout=30000)
        current_url = get_url(page)
        log(f"Current page: {current_url}")

        # --- Login check ---
        if "/login" in current_url.lower():
            log("Please log in to 小宇宙 in the browser window. "
                "This is only needed once with persistent context.")
            deadline = time.time() + 600
            while time.time() < deadline:
                cur = get_url(page)
                if "/login" not in cur.lower() and "podcaster.xiaoyuzhoufm.com" in cur:
                    log(f"Login detected: {cur}")
                    break
                time.sleep(2)
            else:
                capture_screenshot(page, args.staging_dir, "login_timeout")
                context.close()
                output_result({"success": False, "error": "Login timed out (600s)",
                               "dashboard_url": args.dashboard_url,
                               "staging_dir": args.staging_dir})
                return
            page.goto(args.dashboard_url, wait_until="networkidle", timeout=30000)
        else:
            log("Already logged in.")
            if "contents-management/episodes" not in current_url:
                page.goto(args.dashboard_url, wait_until="networkidle", timeout=30000)

        page.wait_for_timeout(2000)

        try:
            # --- Step 1: Click "创建单集" ---
            log("Clicking create episode...")
            page.locator(selectors["new_episode_button"]).first.click()
            page.wait_for_timeout(3000)

            # --- Step 2: Upload audio via file chooser ---
            log(f"Uploading audio: {os.path.basename(args.audio)}")
            with page.expect_file_chooser(timeout=10000) as fc_info:
                page.locator(selectors["audio_upload_text"]).first.click()
            fc_info.value.set_files(args.audio)
            log("Audio file selected, waiting for processing...")

            # Wait for audio processing (duration display indicates completion)
            audio_ready = False
            for i in range(120):  # up to 10 minutes
                page.wait_for_timeout(5000)
                try:
                    if page.locator("text=/\\d{2,}:\\d{2}/").first.is_visible(timeout=1000):
                        log("Audio upload complete.")
                        audio_ready = True
                        break
                except Exception:
                    pass
                if i % 12 == 0 and i > 0:
                    log(f"  Still processing... ({(i+1)*5}s)")
            if not audio_ready:
                capture_screenshot(page, args.staging_dir, "audio_timeout")
                context.close()
                output_result({"success": False,
                               "error": "Audio processing timed out (600s). "
                                        "File may be too large or upload failed.",
                               "dashboard_url": args.dashboard_url,
                               "staging_dir": args.staging_dir})
                return

            # --- Step 3: Fill title ---
            log(f"Filling title: {args.title}")
            page.locator(selectors["title_input"]).first.fill(args.title)

            # --- Step 4: Fill show notes ---
            log("Filling show notes...")
            desc_selectors = selectors.get("description_editor", ["[contenteditable='true']"])
            if isinstance(desc_selectors, str):
                desc_selectors = [desc_selectors]
            for sel in desc_selectors:
                try:
                    editor = page.locator(sel).first
                    if editor.is_visible(timeout=2000):
                        editor.click()
                        page.keyboard.type(args.description, delay=10)
                        log("Show notes filled.")
                        break
                except Exception:
                    continue

            # --- Step 5: Upload cover (optional) ---
            if args.cover and os.path.exists(args.cover):
                log("Uploading cover...")
                with page.expect_file_chooser(timeout=10000) as fc_info:
                    page.locator(selectors["cover_upload_text"]).first.click()
                fc_info.value.set_files(args.cover)
                page.wait_for_timeout(3000)

                # Handle crop dialog
                try:
                    crop_btn = page.locator(selectors["cover_crop_confirm"]).first
                    if crop_btn.is_visible(timeout=8000):
                        crop_btn.click()
                        log("Cover crop confirmed.")
                        page.wait_for_timeout(3000)
                except Exception:
                    pass

            # --- Step 6: Agreement checkbox ---
            log("Checking agreement...")
            try:
                agreement = page.locator(selectors["agreement_text"]).first
                if agreement.is_visible(timeout=3000):
                    bbox = agreement.bounding_box()
                    if bbox:
                        page.mouse.click(bbox["x"] - 20, bbox["y"] + bbox["height"] / 2)
                        log("Agreement checked.")
            except Exception:
                try:
                    page.locator("input[type='checkbox']").first.check()
                except Exception:
                    pass

            # --- Step 6b: Select publish mode ---
            if args.mode == "publish":
                log("Selecting publish mode...")
                try:
                    publish_btn = page.locator(selectors["publish_now"]).first
                    publish_btn.click(timeout=5000)
                    page.wait_for_timeout(500)
                except Exception as e:
                    capture_screenshot(page, args.staging_dir, "publish_mode_fail")
                    context.close()
                    output_result({"success": False,
                                   "error": f"Failed to select publish mode: {e}. "
                                            "Episode NOT submitted — use --mode draft if intended.",
                                   "dashboard_url": args.dashboard_url,
                                   "staging_dir": args.staging_dir})
                    return

            page.wait_for_timeout(1000)
            capture_screenshot(page, args.staging_dir, "before_submit")

            # --- Step 7: Click "创建" ---
            log(f"Clicking create (mode={args.mode})...")
            page.locator(selectors["create_button"]).last.click()

            # Wait for result
            page.wait_for_timeout(8000)
            episode_url = get_url(page)
            capture_screenshot(page, args.staging_dir, "final")

            if "create/episode" not in episode_url:
                log("Episode created successfully!")
                output_result({"success": True, "mode": args.mode,
                               "dashboard_url": args.dashboard_url,
                               "episode_url": episode_url})
            else:
                capture_screenshot(page, args.staging_dir, "unconfirmed")
                output_result({"success": False, "error": "Still on create page after submit",
                               "dashboard_url": args.dashboard_url,
                               "episode_url": episode_url,
                               "staging_dir": args.staging_dir})

        except Exception as e:
            capture_screenshot(page, args.staging_dir, "error")
            output_result({"success": False, "error": str(e),
                           "dashboard_url": args.dashboard_url,
                           "staging_dir": args.staging_dir})
        finally:
            try:
                log("Browser closing in 15 seconds...")
                page.wait_for_timeout(15000)
                context.close()
            except Exception:
                pass  # context may already be closed by an early-exit path


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add plugins/kb/skills/kb-publish/scripts/upload_xiaoyuzhou.py
git commit -m "feat(kb-publish): rewrite upload script — persistent context, correct selectors"
```

---

### Task 4: Update kb-publish SKILL.md — episode registry, title format, cover style, browser automation

**Files:**
- Modify: `plugins/kb/skills/kb-publish/SKILL.md`

This is the largest single change. The SKILL.md needs updates across multiple steps. Rather than listing every line change, the following sections describe **what to change in each step** of the existing SKILL.md.

- [ ] **Step 1: Add Episode Registry section after the Workflow heading, before Step 1**

Insert a new section after the `## Workflow` line and before `### Step 1`:

```markdown
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
- `generated`: entry created by preflight sidecar import (Task 4 Step 2). `id` is `null`, `title`/`description`/`date` are `null`.
- `draft`: entry updated when uploaded as draft. `id` is still `null`. Title set (no EP prefix).
- `published`: entry updated when published. `id` assigned from `next_id`, `next_id` incremented. Title set with `EP{id}` prefix.

**Re-run guard:** If an entry already has `status: published` and `id` is non-null, do NOT reassign `id` or increment `next_id`. Log a warning and skip registry update.

**Lookup rule:** When `kb-publish` processes an audio file, check if an entry with matching `audio` key already exists. If yes, update that entry (state transition, respecting re-run guard). If no, create a new entry.
```

- [ ] **Step 2: Update Step 1 (Preamble) — add browser_data and episodes_registry config**

In the existing Step 1, after reading `kb.yaml`, add:

```markdown
5. **Read episode registry:**
   Read the file at `integrations.xiaoyuzhou.episodes_registry` (default: `episodes.yaml` at
   project root, alongside `kb.yaml`).
   If the file doesn't exist, initialize with `episodes: []` and `next_id: 1`.
   Record `current_episodes` list and `next_episode_id`.

6. **Resolve browser data path:**
   Read `integrations.xiaoyuzhou.browser_data` (default: `.xiaoyuzhou-browser-data`).
   Resolve relative to project root. This directory stores Playwright persistent context
   (cookies + localStorage + sessionStorage). Login is only needed on first run.
```

Also update the kb.yaml config template in Step S4 to include:

```yaml
integrations:
  xiaoyuzhou:
    enabled: true
    podcast_id: "69ddba132ea7a36bbf1efa77"
    browser_data: ".xiaoyuzhou-browser-data"
    episodes_registry: "episodes.yaml"  # root-level, alongside kb.yaml
    staging_dir: "output/xiaoyuzhou-staging"
    venv_path: "<absolute_venv_path>"
```

And update Step S5 (.gitignore) to add `.xiaoyuzhou-browser-data/`.

- [ ] **Step 2b: Add Step 2b (Preflight Sidecar Import) — after audio validation**

After Step 2 validates and resolves `audio_path`, insert:

```markdown
### Step 2b: Preflight — Sidecar Import & Publish Guard

**Publish guard:** Check if a registry entry with `audio == basename(audio_path)` already
has `status: published`. If so, stop immediately:
"⚠ 已发布: EP{id}「{title}」已使用此音频文件发布。如需重新发布请使用 --force-republish。"
Do NOT proceed to upload. (Unless `--force-republish` flag is provided, which is not
implemented yet — future work.)

**Sidecar import:** Check if `<audio_path>.manifest.yaml` exists alongside the audio file.
If found:
1. Read the sidecar manifest.
2. **Validate:** confirm `manifest.audio == basename(audio_path)`. If mismatch, warn
   and skip import (do not delete sidecar).
3. Check if a registry entry with matching `audio` key already exists.
4. If existing entry has `status: published`: skip import (entry is frozen). Log warning.
5. If existing entry has `status: generated` or `draft`: merge any fields from the
   sidecar that are currently null/empty.
6. If no existing entry: create a schema-complete entry with `status: generated`,
   `id: null`, `title: null`, `description: null`, `date: null`, and all content
   manifest fields from the sidecar (`topic`, `depth`, `concepts_covered`,
   `open_threads`, `source_lessons`, `notebook_id`).
7. Write the registry atomically (write to temp file, rename).
8. Delete the sidecar file only after successful registry write.

This step requires `audio_path` (resolved in Step 2) and the registry (loaded in Step 1).
It ensures the `generated` state is reachable before upload proceeds.
```

- [ ] **Step 3: Update Step 3 (Analyze Content) — add topic overlap check**

After determining the `topic_summary` and `key_concepts`, add:

```markdown
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
```

- [ ] **Step 4: Update Step 4 (Generate Title) — episode ID prefix and 口语化 style**

Replace the existing title generation guidance with:

```markdown
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
```

- [ ] **Step 5: Update Step 5 (Cover Art) — reference prompt template, remove inline style**

Replace the inline brand guidelines in Step 5 with:

```markdown
**Path A — `gemini_available = true`:**

1. Read the brand template from `<skill_dir>/prompts/cover-style.md`.
   If `integrations.gemini.cover_style_override` is set in kb.yaml, read that path instead.

2. Replace `{topic}` with the episode topic and `{concepts}` with the key concepts list.

3. Write the constructed prompt to `<run_staging_dir>/prompt.txt`.
```

Remove the existing inline style description ("Clean, modern, minimalist design", hex colors, etc.) — the `cover-style.md` template is the single source of truth.

- [ ] **Step 6: Update Step 7 (Upload) — persistent context and correct automation**

Replace the existing upload command construction with:

```markdown
Build the upload command. Use `--browser-data` for persistent login context.
Only include `--cover` if `cover_path` is not null:

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

On first run, the browser opens headed and the user must log in (QR code scan).
Subsequent runs reuse the persistent context — no login needed.
```

- [ ] **Step 7: Update Step 8 (Report) — write to episode registry on success**

Add to the success reporting section:

```markdown
**On success, update the episode registry:**

1. Read `episodes.yaml`.
2. Look for an existing entry with matching `audio` key.
3. **If entry exists with `status: published`** (re-run guard):
   - Log warning: "Episode already published as EP{id}. Registry not modified."
   - Do NOT reassign `id` or increment `next_id`. Skip to step 5.
4. **If entry exists with `status: generated` or `draft`** (state transition):
   - Update `status` to `published` (or `draft` if `--mode draft`).
   - If publishing and `id` is `null`: assign `id` from `next_id`, set `date` to today,
     increment `next_id`.
   - Merge `title`, `description`, and `topic` from the current upload.
   - Content manifest fields (`concepts_covered`, `open_threads`, `source_lessons`, `depth`)
     are already populated from the sidecar — preserve them.
5. **If no entry exists** (new audio without prior generation):
   - Sidecar was already consumed in preflight (step 6 of preamble). If preflight found
     a sidecar, an entry should already exist — this path is for non-NotebookLM audio.
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
```

- [ ] **Step 8: Update Step S3 (Login) — use persistent context**

Replace the existing login flow (which opens a one-off browser and saves cookies) with:

```markdown
### Step S3: 小宇宙 Login

Login is handled automatically by the upload script's persistent context.
On first run of `/kb-publish`, the browser opens headed and navigates to the
dashboard. If not logged in, the user completes QR code login in the browser window.
The persistent context saves all browser state (cookies, localStorage, sessionStorage)
to `<browser_data_path>/`. Subsequent runs are automatic.

No separate login step is needed.
```

- [ ] **Step 9: Commit**

```bash
git add plugins/kb/skills/kb-publish/SKILL.md
git commit -m "feat(kb-publish): add episode registry, title format, cover style, persistent context"
```

---

### Task 5: Update kb-notebooklm — episode manifest, series bible, topic cross-check

**Files:**
- Modify: `plugins/kb/skills/kb-notebooklm/SKILL.md`
- Modify: `plugins/kb/skills/kb-notebooklm/prompts/podcast-tutor.md`

- [ ] **Step 1: Update podcast-tutor.md — add series context placeholder**

At the very beginning of `prompts/podcast-tutor.md`, before the existing opening line, insert:

```markdown
{series_context}

```

This placeholder is replaced at runtime with the compiled series bible (see Step 6i in SKILL.md). When no previous episodes exist, it is replaced with an empty string.

Also replace the last line of the file:
```
Cover these lessons: [comma-separated lesson titles]. Highlight connections between topics where they exist.
```

With a placeholder:
```
{lesson_list}
```

This avoids duplication — the SKILL.md's Step 6i already appends lesson titles at runtime. The `{lesson_list}` placeholder is replaced with `Cover these lessons: [actual titles]. Highlight connections between topics where they exist.` at generation time.

- [ ] **Step 2: Add "Episode Continuity" section to SKILL.md**

After the `## Deduplication` section and before `## Source Count Limits`, insert a new section:

```markdown
## Episode Continuity

When generating podcasts, the skill maintains continuity with previously published episodes
via the episode registry managed by kb-publish.

### Episode Registry

**Location:** Read `integrations.xiaoyuzhou.episodes_registry` from `kb.yaml`. If the key
is missing or the file doesn't exist, skip all continuity features (graceful degradation).

**Schema:** See kb-publish SKILL.md for the full schema. The fields relevant to
kb-notebooklm are:

- `episodes[].id` — episode number
- `episodes[].title` — published title
- `episodes[].depth` — intro | intermediate | deep-dive
- `episodes[].concepts_covered[]` — list of {name, depth} pairs
- `episodes[].open_threads[]` — topics hinted at but not covered
- `episodes[].source_lessons[]` — lesson file basenames used

### Published Topic Cross-Check (Podcast Workflow Step 5b)

After topic grouping (Step 5) and before generation (Step 6), cross-check each
proposed episode group against the published episodes:

1. For each proposed episode group, extract its key concepts (from lesson titles
   and first 10 lines of each lesson).
2. Compare against `episodes[].concepts_covered[].name` across all published episodes.
3. Classify the relationship:

   - **No overlap:** Proceed normally.
   - **Partial overlap (new angle):** Some concepts overlap but the new lessons go deeper
     or cover adjacent material. Recommend as a follow-up/deep-dive episode.
   - **High overlap:** Most concepts already covered at similar depth. Recommend skipping
     or combining with genuinely new material.
   - **Addresses open thread:** The new lessons cover a topic listed in a published
     episode's `open_threads`. Flag positively.

4. Present findings to the user:

   ```
   Episode group "Attention 进阶" — cross-check with published episodes:

   ✓ Addresses EP2 open thread: "Flash Attention"
   ✓ Addresses EP2 open thread: "KV Cache optimization"
   ⚠ Partial overlap with EP2: "Self-Attention" was explained at intro level
     → Recommend: frame as deep-dive, reference EP2 for basics

   Proposed approach:
   - Include: lesson-045-flash-attention.md, lesson-046-kv-cache.md
   - Exclude: lesson-047-attention-basics.md (covered in EP2 at same depth)
   - Frame as: EP2 deep-dive follow-up

   Proceed? (y/adjust/skip)
   ```

### Series Bible Compilation (Podcast Workflow Step 6i)

Before generating audio, compile a series bible from **published episodes only**
(not `generated` or `draft` entries — those are pre-publication and may never ship):

1. Read `episodes.yaml`.
2. For each entry with `status: published`, extract: id, topic, depth, concepts_covered
   (names only), open_threads. Use `topic` (not `title`) in the bible to avoid the
   `EP2: EP2 | ...` duplication.
3. Format as a series bible block (see below).
4. Read `prompts/podcast-tutor.md`. Replace `{series_context}` with the compiled bible.
   If no published episodes exist, replace with empty string.

**Series bible format:**

```
SERIES CONTINUITY — "全栈AI" Podcast

The following PUBLISHED episodes have established knowledge with the audience.
Build on prior content instead of repeating it.
(The episode number for THIS episode will be assigned at publish time.)

EP1: {topic} ({depth})
  Covered: {comma-separated concept names}
  Open threads: {comma-separated open threads}

EP2: {topic} ({depth})
  Covered: {comma-separated concept names}
  Open threads: {comma-separated open threads}

RULES FOR THIS EPISODE:
- If a concept was EXPLAINED in a previous episode, DO NOT re-explain it from scratch.
  Instead say: "我们在第N期详细讲过这个，还没听过的朋友可以回去听一下"
  Then build on top of it with new depth or a new angle.
- If a concept was only MENTIONED (not explained), you may briefly recap (1-2 sentences)
  before going deeper.
- If this episode is a deep-dive on a previous intro topic, explicitly frame it:
  "上次我们聊了X的基础，今天我们要更深入地看看..."
- When addressing an open thread from a previous episode, call it out:
  "上次留了个悬念说要聊X，今天我们来填这个坑"
- Always reference specific episode numbers so listeners can navigate the series.
```

**Series bible length management:**

- For 10 or fewer published episodes: include full detail for all episodes.
- For 11-30 episodes: full detail for the 5 most recent, summarized (`topic` + `depth` only)
  for older episodes.
- For 30+ episodes: full detail for 5 most recent, summarize the rest as topic clusters
  (e.g., "EP1-EP8 covered foundational ML: GPU computing, attention, transformers, ...").

### Sidecar Manifest Generation (Post-Generation)

After podcast generation completes, `kb-notebooklm` writes a sidecar manifest alongside the
generated audio file. **It does NOT write to `episodes.yaml`** — that is `kb-publish`'s
responsibility (single-writer rule).

1. After podcast generation completes (Step 7), read the source lesson files.
2. Extract: key concepts (from headings and content), estimate depth per concept,
   identify topics mentioned but not deeply covered (open threads).
3. Write to `<audio_path>.manifest.yaml` (e.g., `output/notebooklm/podcast-attention-2026-04-20.mp3.manifest.yaml`).

**Sidecar schema:**

```yaml
audio: podcast-attention-2026-04-20.mp3
topic: "Flash Attention & KV Cache"
notebook_id: "uuid"
generated_date: 2026-04-20
depth: intermediate
concepts_covered:
  - name: "Flash Attention"
    depth: explained
  - name: "KV Cache Optimization"
    depth: explained
open_threads:
  - "Multi-Query Attention"
source_lessons:
  - lesson-045-flash-attention.md
  - lesson-046-kv-cache.md
```

When `kb-publish` processes this audio file, it reads the sidecar, merges the content manifest
into the registry entry, and deletes the sidecar after successful consumption.
```

- [ ] **Step 3: Update Podcast Workflow Step 5 — insert Step 5b reference**

In the existing Podcast Workflow, after Step 5 (topic grouping) and before Step 6, add:

```markdown
5b. **Published topic cross-check:** If episode registry is available, run the
    cross-check described in the "Episode Continuity" section above. Present findings
    to user and wait for confirmation before proceeding to generation.
```

- [ ] **Step 4: Update Podcast Workflow Step 6i — inject series bible**

In the existing Step 6i (Generate audio), update the audio instructions section:

Replace:
```
Read the prompt from `prompts/podcast-tutor.md` relative to this skill's directory.
Append the lesson titles for this episode group to the end of the prompt.
```

With:
```
Read the prompt from `prompts/podcast-tutor.md` relative to this skill's directory.

**Series bible injection:** If the episode registry exists and contains published
episodes, compile the series bible (see "Episode Continuity" section) and replace
the `{series_context}` placeholder in the prompt. If no registry or no published
episodes, replace `{series_context}` with an empty string.

**Lesson list injection:** Replace the `{lesson_list}` placeholder with:
"Cover these lessons: [comma-separated lesson titles]. Highlight connections
between topics where they exist."
```

- [ ] **Step 5: Update Podcast Workflow Step 7 — write content manifest**

In the existing Step 7 (On background agent success), after "Write updated state to file", add:

```markdown
- **Write sidecar manifest:** Write `<audio_path>.manifest.yaml` alongside the generated
  MP3 file. Include: `audio` (filename), `topic` (short English topic label derived from
  the lesson group name), `notebook_id`, `generated_date`, `depth` estimated from source
  lesson complexity, `concepts_covered` extracted from source lesson headings and content,
  `open_threads` from related topics mentioned but not deeply covered, and `source_lessons`
  as the basenames of the lesson files used. **Do NOT write to `episodes.yaml`** — that is
  `kb-publish`'s responsibility (single-writer rule).
```

- [ ] **Step 6: Commit**

```bash
git add plugins/kb/skills/kb-notebooklm/SKILL.md
git add plugins/kb/skills/kb-notebooklm/prompts/podcast-tutor.md
git commit -m "feat(kb-notebooklm): add episode continuity — manifest, series bible, topic cross-check"
```

---

### Task 6: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update skill descriptions**

In the Skills section of `CLAUDE.md`, update the kb-publish and kb-notebooklm entries:

Replace:
```
- `kb-publish` -- Publish podcast episodes to 小宇宙FM with auto-generated Chinese title/description and Gemini cover art.
```

With:
```
- `kb-publish` -- Publish podcast episodes to 小宇宙FM. Assigns episode IDs from shared registry, generates 口语化 titles with EP prefix, creates cover art via Gemini (大气/简约/接地气 style), uploads via Playwright persistent context. Writes content manifest (concepts covered, depth, open threads) to episodes.yaml after upload.
- `kb-notebooklm` -- Bridge KB to Google NotebookLM for podcasts, quizzes, digests, reports. Before podcast generation, cross-checks published episodes to avoid duplicate content and injects series bible into prompt for episode-to-episode continuity.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update kb-publish and kb-notebooklm descriptions in CLAUDE.md"
```

---

### Task 7: Bump version and update marketplace

**Files:**
- Modify: `plugins/kb/.claude-plugin/plugin.json`
- Modify: `.claude-plugin/marketplace.json`

- [ ] **Step 1: Bump plugin version to 1.12.0**

In `plugins/kb/.claude-plugin/plugin.json`, change `"version": "1.11.0"` to `"version": "1.12.0"`.

In `.claude-plugin/marketplace.json`, update the version field to match `"1.12.0"`.

This is a minor version bump (new feature: episode continuity).

- [ ] **Step 2: Commit**

```bash
git add plugins/kb/.claude-plugin/plugin.json .claude-plugin/marketplace.json
git commit -m "chore: bump version to 1.12.0 for episode continuity feature"
```

---

### Task 8: Backfill episodes.yaml in the MLL vault (data fix, not repo change)

**Files:**
- Modify: `/Users/dragon/Documents/MLL/episodes.yaml` (in the user's vault root, alongside kb.yaml)

This is a one-time data fix to populate the episode registry with correct data from the current state.

- [ ] **Step 1: Backfill episodes.yaml with complete data**

Replace the contents of `/Users/dragon/Documents/MLL/episodes.yaml` with properly populated data including notebook_ids from `.notebooklm-state.yaml`, audio file paths, and initial content manifests derived from the lesson topics that were used to generate each podcast.

Include unpublished generated podcasts (quantization, neural-networks) as `status: generated` so the registry knows they exist and can be published next.

- [ ] **Step 2: No commit needed** — this file is in the user's vault, not the plugin repo. It lives at the vault root (tracked in git, not gitignored).

---

### Task 9: Verification smoke tests

After all code changes are committed, verify the implementation handles edge cases correctly.

- [ ] **Step 1: First run with no registry**

Verify that `kb-publish` initializes `episodes.yaml` from scratch when the file doesn't exist:
1. Temporarily rename `episodes.yaml` to `episodes.yaml.bak`.
2. Read the SKILL.md preamble step and trace the logic: does it create the file with correct initial content?
3. Confirm the initialization path writes `episodes: []` and `next_id: 1`.
4. Confirm that after the preflight sidecar import (if a sidecar exists), the registry contains the imported entry.
5. Restore `episodes.yaml.bak`.
(Note: a full upload is not required — trace the SKILL.md logic manually.)

- [ ] **Step 2: Sidecar consumption**

Verify that `kb-publish` correctly consumes a sidecar manifest:
1. Create a test sidecar `<audio>.manifest.yaml` with known content.
2. Run `/kb-publish` on that audio file.
3. Confirm the registry entry contains the sidecar's `concepts_covered`, `open_threads`, etc.
4. Confirm the sidecar file is deleted after consumption.

- [ ] **Step 3: State transition (generated → published)**

Verify that publishing an already-generated episode transitions the existing entry:
1. Confirm a `status: generated` entry exists in the registry (e.g., from backfill).
2. Run `/kb-publish` on the matching audio file.
3. Confirm the entry is updated in-place (not duplicated): `status: published`, `id` assigned, `date` set.

- [ ] **Step 4: Series bible at boundary sizes**

Verify series bible compilation at: 0 episodes (empty string), 1 episode, 10 episodes (full detail), 11+ episodes (summarized older ones). Read the compiled prompt and confirm format matches the spec.

- [ ] **Step 5: Draft mode verification**

Verify that `--mode draft` correctly:
1. Does NOT click the "立即发布" selector.
2. Clicks "创建" to save as draft.
3. Does NOT assign an EP `id` in the registry (remains `null`).

- [ ] **Step 6: Audio without sidecar**

Verify that publishing a non-NotebookLM audio file (no sidecar manifest) produces a valid registry entry with minimal manifest data from topic analysis.

- [ ] **Step 7: Out-of-order publish (draft A → publish B → publish A)**

Verify EP numbering stays correct when episodes are published out of generation order:
1. Two entries exist: audio-A (`status: generated`) and audio-B (`status: generated`).
2. Publish audio-B first → gets EP3 (or whatever `next_id` is).
3. Publish audio-A next → gets EP4.
4. Confirm no ID collision, both entries updated in-place, `next_id` is now 5.

- [ ] **Step 8: Sidecar retry after failed upload**

Verify that if `kb-publish` fails mid-upload (e.g., audio timeout), the sidecar was already consumed in the preflight step and the registry entry exists as `status: generated`. On retry, the entry should be found by `audio` key and transitioned (not duplicated).

- [ ] **Step 9: Re-run on already-published audio**

Verify the re-run guard: running `/kb-publish --mode publish` on an audio that's already `status: published` should log a warning and leave `id` and `next_id` unchanged.

- [ ] **Step 10: Draft then publish same audio**

Verify: draft audio-A → registry entry has `status: draft`, `id: null`. Then publish audio-A → a new 小宇宙 episode is created (draft is orphaned on platform), registry entry transitions to `status: published` with `id` assigned.

---

## Self-Review Checklist

1. **Spec coverage:**
   - Episode registry schema (single-writer, state machine): Schemas section, Task 4 Step 1
   - Registry write/read: Task 4 Steps 2/7 (kb-publish writes), Task 5 Step 2 (kb-notebooklm reads)
   - Sidecar manifest: Schemas section, Task 5 Steps 2/5, Task 4 Step 2 (preflight import), Task 4 Step 7 (merge on success)
   - Title format (EP{N} | 口语化): Task 4 Step 4
   - Cover style (大气/简约/接地气): Task 1 (prompt template), Task 4 Step 5 (SKILL.md reference)
   - Browser automation (persistent context): Task 3 (script), Task 4 Steps 6/8 (SKILL.md)
   - Draft/publish mode: Task 3 (Step 6b in script), Task 4 Step 7 (registry handling)
   - Selectors (创建单集, 裁剪, file chooser): Task 2 (YAML), Task 3 (script)
   - Audio timeout hard-fail: Task 3 (script)
   - Topic cross-check before generation: Task 5 Steps 2/3
   - Series bible in prompt: Task 5 Steps 1/2/4
   - Backfill existing data: Task 8
   - Preflight sidecar import: Task 4 Step 2b (after audio_path resolved, makes `generated` state reachable)
   - Prompt placeholders: Task 5 Steps 1/4 ({series_context} and {lesson_list} in podcast-tutor.md)
   - Vault reorganization: NotebookLM output in `output/notebooklm/`, episodes.yaml at project root
   - Verification: Task 9 (10 smoke test scenarios including re-run guard and draft-then-publish)
   - Version bump: Task 7
   - CLAUDE.md update: Task 6

2. **Placeholder scan:** No TBDs, TODOs, or "fill in later" found. All code steps include actual code.

3. **Type consistency:** `episodes.yaml` schema is defined once (Schemas section) and referenced consistently in Tasks 4 and 5. Sidecar manifest schema defined once (Schemas section) and referenced in Tasks 4 and 5. Field names (`concepts_covered`, `open_threads`, `source_lessons`, `depth`) are used consistently across all tasks.

4. **Ownership clarity:** `kb-publish` is the sole writer to `episodes.yaml`. `kb-notebooklm` writes sidecar manifests only. No concurrent write conflicts possible.

5. **Open items from Round 5 peer review (low-risk, addressable during implementation):**
   - `kb-init` config template still defaults `output_path` to `output/` — update to `output/notebooklm/` during implementation.
   - Concurrent `kb-publish` runs: currently assumed serial per vault. If parallelism is needed, add `flock`/lockfile around `episodes.yaml` read-modify-write.
   - Legacy `cookies_path` config: remove references during SKILL.md update (Task 4).
