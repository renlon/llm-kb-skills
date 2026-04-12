---
name: kb-x-setup
user-invocable: true
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, AskUserQuestion
description: "Use when setting up automated X/Twitter ingestion into the knowledge base, or when user says 'setup x', 'connect twitter', 'auto-capture tweets', 'x sync', or 'setup smaug'. Configures Smaug to periodically fetch liked and bookmarked tweets into raw/articles/x/ for compilation."
---

# X/Twitter Auto-Ingestion Setup

Set up automated ingestion of X/Twitter likes and bookmarks into the knowledge base. Uses [Smaug](https://github.com/alexknowshtml/smaug) for fetching and cron for scheduling. Smaug outputs directly to the KB's `raw/articles/x/` directory — no bridge scripts or extra tools needed.

**Invocation:** `/kb-x-setup` (no arguments -- fully conversational)

**Executor:** Opus single-pass. No subagents.

## Vault Cleanliness Principle

Nothing goes in the KB directory except tweet markdown files in `raw/articles/x/`. All Smaug config, state, logs, and dependencies stay in Smaug's own directory (e.g., `~/smaug/`).

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
5. If source changed, update `smaug.config.json` at the Smaug path
6. Report the updated config and exit

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

### Step 3: Install Bird CLI

Bird CLI is the underlying tool Smaug uses to access X/Twitter. Check if it's installed:

```bash
bird --version 2>/dev/null
```

If not installed:
```bash
npm install -g @steipete/bird
```

**Note:** The `@steipete/bird` package shows a deprecation warning — this is expected. It is the correct package and still works.

Verify installation:
```bash
bird --version
```

### Step 4: Browser Authentication

1. Use AskUserQuestion: "Which browser are you logged into X with?" Options:
   - Chrome (default)
   - Safari
   - Firefox

2. **Do NOT run `npx bird config set browser`** — that command does not exist. Bird reads cookies directly from the browser's cookie store using the `--cookie-source` flag.

3. Verify auth with a test fetch:
   ```bash
   bird bookmarks -n 1 --json --cookie-source <browser> 2>&1 | head -5
   ```

4. If test fails:
   - Ask: "Are you logged into X in {browser}? Try opening x.com, make sure you're signed in, then let me retry."
   - Retry once after user confirms
   - If still failing: report the error and **stop**. Do not proceed with broken auth.

### Step 5: Confirm Fetch Source

Use AskUserQuestion: "What should I capture from X?" Options:
- Both likes and bookmarks (default)
- Likes only
- Bookmarks only

Map the answer to `both`, `likes`, or `bookmarks`.

### Step 6: Configure Smaug Output

Generate `smaug.config.json` at `<smaug_path>/smaug.config.json`. This tells Smaug where to file different types of content. All category folders point to the KB's `raw/articles/x/` directory (absolute path).

```json
{
  "source": "<both|likes|bookmarks>",
  "archiveFile": "./bookmarks.md",
  "pendingFile": "./.state/pending-bookmarks.json",
  "stateFile": "./.state/bookmarks-state.json",
  "timezone": "<user's local timezone>",
  "categories": {
    "github": {
      "match": ["github.com"],
      "action": "file",
      "folder": "<kb_root>/raw/articles/x",
      "template": "tool",
      "description": "GitHub repositories and code"
    },
    "article": {
      "match": ["medium.com", "substack.com", "dev.to", "blog", "article"],
      "action": "file",
      "folder": "<kb_root>/raw/articles/x",
      "template": "article",
      "description": "Blog posts and articles"
    },
    "x-article": {
      "match": ["/i/article/"],
      "action": "file",
      "folder": "<kb_root>/raw/articles/x",
      "template": "x-article",
      "description": "X/Twitter long-form articles"
    },
    "tweet": {
      "match": [],
      "action": "capture",
      "folder": null,
      "template": null,
      "description": "Plain tweets - captured in bookmarks.md only"
    }
  },
  "autoInvokeClaude": true,
  "cliTool": "claude",
  "claudeModel": "sonnet",
  "claudeTimeout": 900000
}
```

**Timezone:** Detect with `date +%Z` or ask the user. Common values: `America/New_York`, `America/Los_Angeles`, `Asia/Shanghai`, `Asia/Tokyo`, `Europe/London`.

**Note:** Plain tweets (no links) go to `bookmarks.md` in Smaug's directory only. Tweets with links (articles, GitHub repos, X articles) get filed as markdown to `raw/articles/x/`. This is Smaug's default behavior — tweets without links don't generate enough content for a useful wiki article.

If `smaug.config.json` already exists, read it first and merge — do not overwrite user customizations. Only update `source` and category `folder` paths.

### Step 7: Create Target Directory

```bash
mkdir -p <kb_root>/raw/articles/x
```

### Step 8: Verify Fetch Works

Run a test fetch to confirm everything is wired up:

```bash
cd <smaug_path> && npx smaug fetch --source <source> -n 1 2>&1 | head -30
```

Check that files appear in `raw/articles/x/` (only if the fetched tweet had a link).

### Step 9: Set Up Cron

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

4. Install cron job with idempotent replacement. The cron command runs Smaug directly — no bridge script:
   ```bash
   crontab -l 2>/dev/null | grep -v '# kb-x-sync' | { cat; echo "{cron_expr} PATH={NODE_BIN_DIR}:\$PATH cd {smaug_path} && npx smaug fetch --source {source} >> {smaug_path}/smaug-cron.log 2>&1  # kb-x-sync"; } | crontab -
   ```

5. Verify:
   ```bash
   crontab -l | grep kb-x-sync
   ```

### Step 10: Update kb.yaml

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

### Step 11: TOS Disclosure

Tell the user:

> "**Note:** This uses browser session cookies to access X's internal API, which technically violates X's Terms of Service. This is standard practice for personal read-only use with minimal practical risk, but you should be aware."

### Step 12: Confirmation

Report a summary table with:
- Smaug installed at: `<path>`
- Fetching: `<source>` from X
- Browser: `<browser>` (auto-extracts cookies)
- Schedule: every `<interval>` (cron)
- Output: `raw/articles/x/` (only thing touching the KB)
- Config/state/logs: all stay in `<smaug_path>/`

Then:
> "Setup complete. Your X likes and bookmarks will be fetched automatically. Run `/kb compile` anytime to process new tweets into wiki articles. Run `/kb-x-setup` again to change settings."

## Common Mistakes

- **Do NOT run `npx bird config set browser`** — that command does not exist. Bird uses `--cookie-source <browser>` flag.
- **Do NOT install random `bird` npm packages.** The correct one is `@steipete/bird`. It shows a deprecation warning — ignore it, the package works.
- Do not proceed past auth verification if the test fetch fails. Broken auth means the cron job will silently fail.
- Do not create duplicate cron entries. Always grep out the old `# kb-x-sync` line before appending.
- Do not hardcode paths in the cron entry without the NODE_BIN_DIR prefix — `npx` will not be found in cron's minimal environment.
- Do not skip the TOS disclosure. The user should make an informed decision.
- Do not run `/kb compile` as part of this skill. Compilation is a separate user action.
- Do not place scripts, logs, config, or state files in the KB directory. Everything except tweet markdown files stays in Smaug's directory.
- Do not overwrite an existing `smaug.config.json` without reading it first — merge changes to preserve user customizations.
