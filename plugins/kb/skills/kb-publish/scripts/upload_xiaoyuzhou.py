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
