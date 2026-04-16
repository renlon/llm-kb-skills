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
            checked = False
            # Strategy 1: click the checkbox input directly
            try:
                cb = page.locator("input[type='checkbox']").last
                if cb.is_visible(timeout=2000):
                    cb.check(force=True)
                    checked = True
                    log("Agreement checked (checkbox input).")
            except Exception:
                pass
            # Strategy 2: click to the left of the agreement text
            if not checked:
                try:
                    agreement = page.locator(selectors["agreement_text"]).first
                    if agreement.is_visible(timeout=2000):
                        bbox = agreement.bounding_box()
                        if bbox:
                            page.mouse.click(bbox["x"] - 15, bbox["y"] + bbox["height"] / 2)
                            checked = True
                            log("Agreement checked (text click).")
                except Exception:
                    pass
            # Strategy 3: click the label/span containing the agreement text
            if not checked:
                try:
                    page.locator("text=阅读并同意").first.click()
                    checked = True
                    log("Agreement checked (label click).")
                except Exception:
                    pass
            if not checked:
                log("WARNING: Could not check agreement checkbox. Submit may fail.")

            # --- Step 6b: Select publish mode ---
            # The platform may pre-select "立即发布" by default.
            # For draft mode: ensure "定时发布" is selected (which effectively saves as draft
            # since no time is set), or deselect "立即发布" if possible.
            if args.mode == "draft":
                log("Draft mode — checking if 立即发布 is pre-selected...")
                try:
                    # Click 定时发布 to deselect 立即发布
                    scheduled_btn = page.locator(selectors["publish_scheduled"]).first
                    if scheduled_btn.is_visible(timeout=2000):
                        scheduled_btn.click()
                        page.wait_for_timeout(500)
                        log("Switched to 定时发布 (draft mode).")
                except Exception:
                    log("WARNING: Could not switch publish mode. May publish immediately.")
            else:
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
