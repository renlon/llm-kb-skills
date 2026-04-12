---
name: kb-x-setup
user-invocable: true
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, AskUserQuestion
description: "Use when setting up automated X/Twitter ingestion into the knowledge base, or when user says 'setup x', 'connect twitter', 'auto-capture tweets', 'x sync', or 'setup smaug'. Configures Smaug to periodically fetch liked and bookmarked tweets into raw/articles/x/ for compilation."
---

# X/Twitter Auto-Ingestion Setup

Set up automated ingestion of X/Twitter likes and bookmarks into the knowledge base. Uses [Smaug](https://github.com/alexknowshtml/smaug) for fetching and cron for scheduling.

**Invocation:** `/kb-x-setup` (no arguments -- fully conversational)

**Executor:** Opus single-pass. No subagents.

## Prerequisites Gate

**First action:** Read `kb.yaml` from the project root.

- If `kb.yaml` is missing: tell the user to run `/kb-init` first and **stop**.
- If `kb.yaml` exists: check for `integrations.x` section to detect if this is a re-run.

## Re-Run Detection

If `integrations.x` already exists in `kb.yaml`:

1. Report current config: source, browser, cron interval, enabled status
2. Ask: "X integration is already configured. What would you like to change?"
   - Switch browser
   - Change fetch source (likes / bookmarks / both)
   - Change cron interval
   - Enable / disable
   - Refresh authentication (re-test cookie access)
   - Nothing -- exit
3. Apply the requested change and update `kb.yaml`
4. If cron interval changed, update the cron entry (see Cron Setup below)
5. Report the updated config and exit

**Do not re-run the full setup flow on re-run.** Jump directly to the change menu.

## First-Time Setup Flow

### Step 1: Check Node.js

Run: `node --version`

- If Node.js >= 18: proceed
- If missing or too old: tell the user to install Node.js 18+ and **stop**

### Step 2: Install Smaug

Check if Smaug is already installed:
- Read `integrations.smaug.path` from `kb.yaml`
- If the path exists and contains `package.json`: skip this step
- Otherwise:

1. Use AskUserQuestion: "Where should I install Smaug? (default: `~/smaug`)"
2. Run:
   ```bash
   git clone https://github.com/alexknowshtml/smaug <path> && cd <path> && npm install
   ```
3. Update `kb.yaml`:
   ```yaml
   integrations:
     smaug:
       path: <absolute_path>
   ```

### Step 3: Browser Authentication

1. Use AskUserQuestion: "Which browser are you logged into X with?" Options:
   - Chrome (default)
   - Safari
   - Firefox

2. Configure bird CLI for that browser. Run:
   ```bash
   cd <smaug_path> && npx bird config set browser <browser>
   ```

3. Verify auth with a test fetch:
   ```bash
   cd <smaug_path> && npx smaug fetch --source likes -n 1
   ```

4. If test fails:
   - Ask: "Are you logged into X in {browser}? Try opening x.com, make sure you're signed in, then let me retry."
   - Retry once after user confirms
   - If still failing: report the error and **stop**. Do not proceed with broken auth.

### Step 4: Confirm Fetch Source

Use AskUserQuestion: "What should I capture from X?" Options:
- Both likes and bookmarks (default)
- Likes only
- Bookmarks only

Map the answer to `both`, `likes`, or `bookmarks`.

### Step 5: Install Bridge Script

1. Locate the x-sync.sh template bundled with this skill. Read it from the plugin's skill directory:
   ```bash
   find ~/.claude/plugins/cache/llm-kb-skills -path '*/kb-x-setup/x-sync.sh' -type f 2>/dev/null | head -1
   ```

2. Copy to the KB project root:
   ```bash
   cp <template_path> <kb_root>/x-sync.sh
   chmod +x <kb_root>/x-sync.sh
   ```

3. Create the target directory:
   ```bash
   mkdir -p <kb_root>/raw/articles/x
   ```

### Step 6: Set Up Cron

1. Use AskUserQuestion: "How often should I fetch? (default: every 2 hours)" Options:
   - Every 1 hour
   - Every 2 hours (default)
   - Every 4 hours
   - Every 12 hours

2. Map to cron expressions:
   - 1 hour: `0 * * * *`
   - 2 hours: `0 */2 * * *`
   - 4 hours: `0 */4 * * *`
   - 12 hours: `0 */12 * * *`

3. Detect Node.js PATH for cron environment:
   ```bash
   NODE_BIN_DIR=$(dirname "$(which node)")
   ```

4. Install cron job with idempotent replacement:
   ```bash
   crontab -l 2>/dev/null | grep -v '# kb-x-sync' | { cat; echo "{cron_expr} PATH={NODE_BIN_DIR}:\$PATH /bin/bash {kb_root}/x-sync.sh  # kb-x-sync"; } | crontab -
   ```

5. Verify:
   ```bash
   crontab -l | grep kb-x-sync
   ```

### Step 7: Update kb.yaml

Add the full X integration config:

```yaml
integrations:
  smaug:
    path: <absolute_smaug_path>
  x:
    source: <both|likes|bookmarks>
    raw_dir: raw/articles/x
    cron_interval: "<cron_expr>"
    browser: <chrome|safari|firefox>
    enabled: true
```

### Step 8: TOS Disclosure

Tell the user:

> "**Note:** This uses browser session cookies to access X's internal API, which technically violates X's Terms of Service. This is standard practice for personal read-only use with minimal practical risk, but you should be aware."

### Step 9: Confirmation

Report:
- Smaug installed at: `<path>`
- Fetching: `<source>` from X
- Browser: `<browser>`
- Schedule: every `<interval>`
- Output: `raw/articles/x/`
- Status: `x-sync-status.json`
- Logs: `logs/x-sync.log`

Then:
> "Setup complete. Your X likes and bookmarks will be fetched automatically. Run `/kb compile` anytime to process new tweets into wiki articles. Run `/kb-x-setup` again to change settings."

## Common Mistakes

- Do not proceed past auth verification if the test fetch fails. Broken auth means the cron job will silently fail.
- Do not create duplicate cron entries. Always grep out the old `# kb-x-sync` line before appending.
- Do not hardcode paths in the cron entry without the NODE_BIN_DIR prefix -- `npx` will not be found in cron's minimal environment.
- Do not skip the TOS disclosure. The user should make an informed decision.
- Do not run `/kb compile` as part of this skill. Compilation is a separate user action.
- Do not modify `x-sync.sh` during setup -- it reads `kb.yaml` at runtime, so config changes take effect immediately.
