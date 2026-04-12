# KB X/Twitter Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Phase 0 (X enrichment) to the KB compile pipeline — stitches self-threads and downloads media from tweets before compilation.

**Architecture:** Modifications to the existing `plugins/kb/skills/kb/SKILL.md` compile workflow. Phase 0 runs before Incremental Detection, modifying raw files in place. Phase 1 gets merged-file cleanup logic. Phase 4 clears the recompile flag. No new skill files — all changes are prompt instructions in the existing skill.

**Tech Stack:** Claude Code skill (markdown prompt), bird CLI (`@steipete/bird`), curl, git

**Spec:** `docs/superpowers/specs/2026-04-11-kb-x-enrich-design.md` (rev 17)

---

### Task 1: Verify bird CLI commands work as expected

**Files:**
- None (read-only verification)

Before writing any skill instructions, verify the bird CLI commands documented in the spec actually work. This prevents writing instructions that reference non-existent flags or produce unexpected output formats.

- [ ] **Step 1: Check bird CLI is installed and get version**

Run:
```bash
bird --version
```

Expected: Version string (v0.8.x). If not installed, run `npm install -g @steipete/bird` first.

- [ ] **Step 2: Verify bird whoami works with cookie-source**

Run:
```bash
bird whoami --cookie-source chrome
```

Expected: JSON or text output showing the authenticated X user. If auth fails, ensure you're logged into X in Chrome.

- [ ] **Step 3: Verify bird read returns expected JSON structure**

Pick a known tweet ID (find one from `raw/articles/x/` in the user's KB). Run:
```bash
bird read <tweet-id> --json --cookie-source chrome 2>/dev/null | head -50
```

Expected: JSON with fields including `id`, `text`, `author`, `media` (array), `conversationId`, `inReplyToStatusId`. Note the exact field names — they may differ from the spec's assumptions.

- [ ] **Step 4: Verify bird thread returns expected JSON structure**

Using the same tweet ID:
```bash
bird thread <tweet-id> --json --all --cookie-source chrome 2>/dev/null | head -100
```

Expected: JSON array (or object with array) containing multiple tweets from the conversation. Each tweet should have `id`, `text`, `author` (with `id` and `username`), `inReplyToStatusId`, `media`, `conversationId`.

- [ ] **Step 5: Document any field name differences**

If bird CLI's actual JSON field names differ from the spec (e.g., `author.id` vs `authorId`, `media.url` vs `media[].media_url`), note them. The SKILL.md instructions must reference the ACTUAL field names.

**Do not commit anything.** This is a discovery step. Record findings for use in subsequent tasks.

---

### Task 2: Add Phase 0 (X Enrichment) to SKILL.md

**Files:**
- Modify: `plugins/kb/skills/kb/SKILL.md:57-67` (insert Phase 0 before Incremental Detection)

This is the core implementation task. Add the complete X Enrichment phase to the compile workflow. The enrichment section goes between the "Compile" trigger line and the "Incremental Detection" section.

- [ ] **Step 1: Read the current SKILL.md**

```bash
cat -n plugins/kb/skills/kb/SKILL.md | head -70
```

Confirm the insertion point: after line 59 (`**Trigger:** User adds files to \`raw/\` and says "compile" or "update the wiki".`) and before line 61 (`### Incremental Detection`).

- [ ] **Step 2: Insert Phase 0 enrichment section**

Insert the following content after the Compile trigger line and before Incremental Detection. This is the complete Phase 0 specification distilled from the design spec into actionable skill instructions:

```markdown
### X Enrichment (Phase 0)

Enriches raw tweet files before compilation. Stitches same-author self-threads and downloads media (images, videos, PDFs) into the vault. Runs only if `integrations.x.enrich` exists in `kb.yaml`.

**Config check (first — zero side effects):**

1. Read `integrations.x` from `kb.yaml`. If `enabled` is false or `enrich` section missing → skip Phase 0.
2. If both `enrich.threads` and `enrich.media` are `false` → log "X enrichment: both threads and media disabled — skipping" and skip Phase 0. No bird CLI check, no auth, no file scan.

**Guards (only if at least one enrich toggle is true):**

3. Run `bird --version`. If fails → log warning "bird CLI not found — skipping enrichment", skip Phase 0.
4. Build auth flags from config: `--cookie-source <integrations.x.browser>`. If `browser_profile` is set: add `--chrome-profile "<profile>"` (chrome) or `--firefox-profile "<profile>"` (firefox). These flags are referred to as `<bird-auth>` below.
5. Run `bird whoami <bird-auth>`. If fails → log "X auth expired — skipping enrichment", skip Phase 0 entirely. Do not attempt per-file calls.

**Scan and cap:**

6. Glob `raw/articles/x/**/*.md`. For each file, apply two-stage eligibility:
   - **Stage 1 (state):** Skip if frontmatter has `enriched: true`, `enriched: skipped`, or `enriched: merged`. Continue if no `enriched` field, `enriched: failed`, or `enriched: false`.
   - **Stage 2 (URL):** Parse tweet URL from frontmatter `source` field only (not body). If no parseable tweet URL → set `enriched: skipped`, remove from candidates.
7. Separate candidates: **fresh** (no `enriched` field) and **retries** (`enriched: failed`/`false`). Sort each group by file mtime (oldest first).
8. Apply `enrich.max_files_per_run` cap (default: 20): take fresh candidates first, fill remaining slots from retries. Log "N files deferred to next compile run" if more exist.

**Path A — Threads enabled** (`enrich.threads: true`, the default):

9. For each selected candidate, fetch thread: `bird thread <tweet-id> --json --all <bird-auth>`. Insert `enrich.api_delay_ms` (default: 1000ms) delay between calls.
10. **Walk the self-thread chain** for each candidate:
    - Record the bookmarked tweet's author ID as the target author.
    - **Walk UP:** From the bookmarked tweet, follow `inReplyToStatusId` links collecting tweets where the author ID matches the target. Stop at a different author or the conversation root.
    - **Walk DOWN (from bookmarked tweet only):** Starting from the bookmarked tweet, look for tweets whose `inReplyToStatusId` equals the current node's ID AND whose author ID matches. If exactly one match: add it, advance, repeat. If zero or multiple: stop. Do NOT walk down from ancestors — only from the bookmarked tweet.
    - Merge ancestor chain + bookmarked tweet + descendant chain. Sort chronologically.
11. **Compute `thread_dedup_key`** = `"<root_id>:<leaf_id>"` from the stitched chain. For single tweets, both IDs are the same.
12. **Cross-run dedup:** Scan files in `raw/articles/x/` with `enriched: true` for matching `thread_dedup_key`. If match found → mark candidate `enriched: merged` with `canonical_file` pointing to the existing file.
13. **Within-run dedup:** Group remaining candidates by `thread_dedup_key`. If multiple share a key, select the canonical (tweet ID matching chain root, or earliest). Do NOT mark others merged yet.
14. **Enrich each canonical:**
    - If chain has 2+ tweets, stitch into the raw file using fenced markers:
      ```
      <!-- enrich:thread -->
      > **Thread by @<author>** (N tweets):
      >
      > [1/N] First tweet text...
      > [2/N] Second tweet text...
      <!-- /enrich:thread -->
      ```
    - If `enrich.media: true`, download media from all tweets in the chain (see Media Download below).
    - Set frontmatter: `thread_dedup_key`, `thread_root_id`, `thread_leaf_id`, `conversation_id`, `thread_length`, `enriched: true`, `enriched_at` (ISO 8601).
    - On any failure (bird non-zero exit, bookmarked tweet missing from response, required parent missing during chain walk) → set `enriched: failed`, continue to next candidate.
15. **Finalize dedup:** For each within-run group whose canonical succeeded (`enriched: true`), mark non-canonicals `enriched: merged` with `canonical_file` (vault-relative path) and `thread_dedup_key`. If canonical failed, leave duplicates unchanged (eligible for retry).

**Path B — Media only** (`enrich.threads: false` AND `enrich.media: true`):

16. For each selected candidate, fetch single tweet: `bird read <tweet-id> --json <bird-auth>`. Insert `api_delay_ms` delay between calls.
17. Write identity fields: `thread_dedup_key: "<tweet_id>:<tweet_id>"`, `thread_root_id`, `thread_leaf_id` (all equal to the tweet ID). No thread stitching, no dedup.
18. Download media from the bookmarked tweet only (see Media Download below).
19. Set frontmatter: `enriched: true`, `enriched_at`, identity fields. On failure → `enriched: failed`.

#### Media Download

Downloads images, videos, and PDFs from tweets for vault-level preservation. Media is stored in `media/x/` at the vault root (sibling of `raw/`, NOT inside `raw/`). Obsidian resolves `![[filename]]` embeds by name from anywhere in the vault.

1. Collect media from all tweets in the stitched chain (Path A) or the single tweet (Path B). Deduplicate by URL — first chronological occurrence determines the filename.
2. **Download by type:**

   | Type | Source | Filename |
   |------|--------|----------|
   | Photo | `media.url` (or equivalent bird field) | `<source_tweet_id>-<n>.<detected_ext>` |
   | Video / GIF | `media.videoUrl` (or equivalent) | `<source_tweet_id>-<n>.mp4` |
   | PDF (linked) | URL from tweet links matching `.pdf`, `arxiv.org/pdf/`, `papers.ssrn.com`, `openreview.net/pdf` | `<source_tweet_id>-<n>.pdf` |

   `<source_tweet_id>` = tweet containing the media. `<n>` = 1-indexed media position within that tweet. `<detected_ext>` = from URL path or magic bytes (JPEG `FF D8` → `.jpg`, PNG `89 50 4E 47` → `.png`).

3. **Download command:** `curl -sfL --max-time 30 -o <dest> <url>`
4. **Post-download validation:**
   - File > 1KB (reject tiny error pages)
   - Images: verify magic bytes (JPEG or PNG)
   - Videos: file > 10KB
   - If validation fails: delete file, log warning, skip that media item
5. **Video size guard:** Before downloading videos, send `curl -sfLI <url>` to check `Content-Length`. If exceeds `enrich.video_max_mb` (default: 100MB), skip and log as text link. If absent, download with `--max-filesize`. After download, verify file size on disk — delete if over limit.
6. **Inject embeds** within fenced markers:
   ```
   <!-- enrich:media -->
   > **Media:**
   > ![[<tweet_id>-1.jpg]]
   > ![[<tweet_id>-2.mp4]]
   <!-- /enrich:media -->
   ```
   Failed downloads appear as text links: `> Failed to download: <url>`
7. Run `mkdir -p media/x/` if any media was downloaded.

**v1 contract:** Enrichment enriches raw sources. Media and thread context are visible when browsing `raw/articles/x/` in Obsidian. The compile pipeline (Phases 1-4) remains text-only — media embeds may or may not appear in wiki articles depending on the extractor.
```

- [ ] **Step 3: Verify the insertion doesn't break SKILL.md structure**

```bash
head -5 plugins/kb/skills/kb/SKILL.md
```

Expected: YAML frontmatter opens with `---`.

```bash
grep -c "^###" plugins/kb/skills/kb/SKILL.md
```

Expected: count increased by 2 (new `### X Enrichment (Phase 0)` and `#### Media Download` sections).

- [ ] **Step 4: Commit**

```bash
git add plugins/kb/skills/kb/SKILL.md
git commit -m "feat(kb): add Phase 0 X enrichment to compile workflow

Adds thread stitching (self-thread chain walk via bird CLI) and media
download (images, videos, PDFs) as a pre-compile enrichment phase.
Includes two-stage eligibility, cross-run and within-run dedup,
branch-safe downward walk, and fenced marker idempotency."
```

---

### Task 3: Modify Incremental Detection for merged file handling

**Files:**
- Modify: `plugins/kb/skills/kb/SKILL.md` (Incremental Detection section, ~line 61)

Add merged-file filtering, canonical validation, all-or-nothing cleanup, and restart-safe requeue logic to Phase 1.

- [ ] **Step 1: Read the current Incremental Detection section**

```bash
grep -n "Incremental Detection" plugins/kb/skills/kb/SKILL.md
```

Locate the exact line numbers of the Incremental Detection section.

- [ ] **Step 2: Add merged file handling after existing step 5**

After the existing step 5 ("Only process what changed -- never recompile the entire source tree"), add:

```markdown
6. **Handle `enriched: merged` files** (state-derived, restart-safe): For each file in `raw/articles/x/` with `enriched: merged` in frontmatter:

   a. **Validate `canonical_file`:** Read the merged file's `canonical_file` frontmatter (vault-relative path like `raw/articles/x/name.md`). Valid if ALL of: (1) path is under `raw/articles/x/`, (2) file exists, (3) target has `enriched: true`, (4) target's `thread_dedup_key` matches merged file's `thread_dedup_key`.

   b. **If invalid:** Log warning. Do NOT clean up any index/source entries. Add the merged file to the process list as a normal source (live fallback — preserves source coverage).

   c. **If valid — set flag FIRST, then clean up:** Write `needs_canonical_recompile: true` to the merged file's frontmatter and flush to disk BEFORE any cleanup. Then:
      - Remove merged file entry from `wiki/_index.md` (if present)
      - Remove merged file entry from `wiki/_sources.md` (if present)
      - In any wiki article's frontmatter `sources:` array, replace the merged file with the canonical. If canonical already listed, just drop the merged entry.
      - Log cleanup in `wiki/_evolution.md`

   d. **Queue canonical:** Add the validated canonical to the process list (if not already there).

   e. **Skip merged file from extraction:** Do not add valid-canonical merged files to the process list — the canonical file covers them.
```

- [ ] **Step 3: Verify the section reads coherently**

Read back the full Incremental Detection section to confirm the flow makes sense: existing steps 1-5 (unchanged) followed by new step 6 (merged file handling).

- [ ] **Step 4: Commit**

```bash
git add plugins/kb/skills/kb/SKILL.md
git commit -m "feat(kb): add merged file handling to Incremental Detection

Phase 1 now validates canonical_file (structural + identity check),
performs all-or-nothing cleanup of index/source entries, and queues
canonicals for recompilation. Flag-before-cleanup ordering ensures
restart safety."
```

---

### Task 4: Modify Index Maintenance for needs_canonical_recompile flag clear

**Files:**
- Modify: `plugins/kb/skills/kb/SKILL.md` (Index Maintenance section, ~line 191)

- [ ] **Step 1: Read the current Index Maintenance section**

```bash
grep -n "Index Maintenance" plugins/kb/skills/kb/SKILL.md
```

- [ ] **Step 2: Add flag-clear step after existing index updates**

After the existing `_evolution.md` bullet, add:

```markdown
- **Clear `needs_canonical_recompile`:** After all wiki changes are ready, scan `raw/articles/x/` for files with `needs_canonical_recompile: true`. For each, remove the field from frontmatter. Stage these changes alongside all other Phase 4 changes so they are included in the same commit. This ensures the one-shot requeue flag is cleared atomically with the compile results.
```

- [ ] **Step 3: Commit**

```bash
git add plugins/kb/skills/kb/SKILL.md
git commit -m "feat(kb): clear needs_canonical_recompile in Phase 4 commit

Flag cleared in same git commit as wiki changes, ensuring no crash
window between compile success and flag clear."
```

---

### Task 5: Add enrichment-related common mistakes

**Files:**
- Modify: `plugins/kb/skills/kb/SKILL.md` (Common Mistakes section, end of file)

- [ ] **Step 1: Read current Common Mistakes section**

```bash
tail -20 plugins/kb/skills/kb/SKILL.md
```

- [ ] **Step 2: Append enrichment-specific mistakes**

Add to the end of the Common Mistakes list:

```markdown
- Placing media files inside `raw/` instead of `media/x/` at the vault root -- binary files in `raw/` get picked up by the compile glob as source candidates
- Running bird API calls before the `bird whoami` auth preflight -- if auth is expired, every per-file call will fail
- Marking duplicate files `enriched: merged` before the canonical is confirmed `enriched: true` -- if canonical fails, duplicates are lost
- Using `author.username` instead of author ID for thread chain walk -- usernames are mutable handles, not stable identifiers
- Walking the thread chain DOWN from ancestors instead of the bookmarked tweet -- ancestor-level branches can interfere with descent
- Cleaning up wiki index/source entries for a merged file before writing `needs_canonical_recompile: true` -- crash between cleanup and flag-write loses the requeue obligation
- Scanning the file body (not just frontmatter `source` field) for tweet URLs -- this can accidentally enrich manual files that merely reference tweets
```

- [ ] **Step 3: Commit**

```bash
git add plugins/kb/skills/kb/SKILL.md
git commit -m "docs(kb): add enrichment-related common mistakes"
```

---

### Task 6: Add enrichment config documentation to SKILL.md

**Files:**
- Modify: `plugins/kb/skills/kb/SKILL.md` (after External Sources section, ~line 28)

- [ ] **Step 1: Insert enrichment configuration reference**

After the External Sources section (after the closing of the `When external_sources is present:` block), add:

```markdown
### X Enrichment Configuration

`kb.yaml` may contain an `integrations.x.enrich` section controlling pre-compile enrichment of tweet files:

```yaml
integrations:
  x:
    enabled: true
    enrich:
      threads: true           # stitch self-threads (default: true)
      media: true             # download images/videos/PDFs (default: true)
      video_max_mb: 100       # skip videos larger than this
      max_files_per_run: 20   # cap enrichment per compile
      api_delay_ms: 1000      # delay between bird API calls
    browser: chrome           # cookie source for bird CLI
    browser_profile: null     # optional, for multi-profile browsers
    media_dir: media/x        # vault-level media storage (outside raw/)
```

When `integrations.x.enrich` is present, compile runs Phase 0 (X Enrichment) before Incremental Detection. If the section is missing or both toggles are `false`, Phase 0 is skipped entirely.
```

- [ ] **Step 2: Commit**

```bash
git add plugins/kb/skills/kb/SKILL.md
git commit -m "docs(kb): add X enrichment config reference to SKILL.md"
```

---

### Task 7: Bump plugin version to 1.6.0

**Files:**
- Modify: `plugins/kb/.claude-plugin/plugin.json`
- Modify: `.claude-plugin/marketplace.json`

- [ ] **Step 1: Update plugin.json version**

Edit `plugins/kb/.claude-plugin/plugin.json`: change `"version": "1.5.1"` to `"version": "1.6.0"`.

- [ ] **Step 2: Update marketplace.json version**

Edit `.claude-plugin/marketplace.json`: change the `kb` plugin version to `"1.6.0"`.

- [ ] **Step 3: Commit**

```bash
git add plugins/kb/.claude-plugin/plugin.json .claude-plugin/marketplace.json
git commit -m "chore: bump plugin version to 1.6.0 for X enrichment"
```

---

### Task 8: Update CLAUDE.md skills list

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Read current skills section**

```bash
grep -A 15 "## Skills" CLAUDE.md
```

- [ ] **Step 2: Update kb skill description**

The `kb` skill description currently says "compile, query, lint, evolve". Update it to mention the enrichment capability:

Change:
```markdown
- `kb` -- Main operating skill with four workflows: compile, query, lint, evolve.
```

To:
```markdown
- `kb` -- Main operating skill with four workflows: compile (with X enrichment), query, lint, evolve.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update kb skill description for X enrichment"
```

---

### Task 9: Integration test — verify enrichment on real KB

**Files:**
- None (read-only test against user's live KB)

This is a manual smoke test. The enrichment must be tested against actual tweet files in the user's KB.

- [ ] **Step 1: Check the user's KB has unenriched tweet files**

```bash
# Read kb.yaml to find the KB path
cat kb.yaml | head -20

# Check for existing raw tweet files
ls raw/articles/x/ 2>/dev/null | head -10

# Check how many lack enriched frontmatter
grep -rL "enriched:" raw/articles/x/*.md 2>/dev/null | wc -l
```

Expected: At least 1 tweet file without `enriched:` in frontmatter.

- [ ] **Step 2: Add enrichment config to kb.yaml (if not present)**

If `integrations.x.enrich` is not already in `kb.yaml`, add it:

```yaml
integrations:
  x:
    # ... existing fields ...
    media_dir: media/x
    enrich:
      threads: true
      media: true
      video_max_mb: 100
      max_files_per_run: 3    # small cap for testing
      api_delay_ms: 1000
```

Use `max_files_per_run: 3` for testing to limit API calls.

- [ ] **Step 3: Run /kb compile and verify Phase 0 executes**

Invoke `/kb compile` in a Claude Code session within the KB directory. Observe:

1. Phase 0 should log: bird version check, auth preflight, candidate scan count
2. For each candidate: thread fetch (or single-tweet fetch), chain walk results, enrichment status
3. Check that processed files now have `enriched: true` in frontmatter
4. Check that thread files have `thread_dedup_key`, `thread_root_id`, `thread_leaf_id`
5. Check that `<!-- enrich:thread -->` markers appear in stitched files
6. Check that media files appear in `media/x/` (if tweets had media)
7. Check that `<!-- enrich:media -->` markers appear with `![[filename]]` embeds

- [ ] **Step 4: Verify incremental behavior**

Run `/kb compile` a second time. Verify:

1. Phase 0 skips already-enriched files ("Stage 1 skip" for `enriched: true`)
2. No additional bird API calls for already-processed files
3. Phase 1-4 proceed normally

- [ ] **Step 5: Test dedup (if applicable)**

If the user has bookmarked multiple tweets from the same self-thread:

1. Verify that after enrichment, one file is canonical (`enriched: true`) and others are merged (`enriched: merged` with `canonical_file`)
2. Verify that merged files are skipped during extraction
3. Verify that the canonical file contains the full stitched thread

- [ ] **Step 6: Reset test cap**

After testing, update `max_files_per_run` back to `20` (or the user's preferred value) in `kb.yaml`.

---

## Self-Review Checklist

### Spec Coverage

| Spec Section | Plan Task |
|---|---|
| Context / Architecture | Task 2 (Phase 0 insertion) |
| Thread Stitching | Task 2 (Path A steps 9-15) |
| Media Download | Task 2 (Media Download subsection) |
| Enrichment Tracking | Task 2 (eligibility, frontmatter states) |
| Configuration | Task 6 (config documentation) |
| Compile Skill Modifications — Phase 0 | Task 2 |
| Compile Skill Modifications — Phase 1 | Task 3 |
| Compile Skill Modifications — Phase 4 | Task 4 |
| Decisions Log | Encoded in implementation choices |
| Edge Cases | Task 5 (common mistakes) + Task 2 (inline) |

### Type Consistency

- `thread_dedup_key` format: `"<root_id>:<leaf_id>"` — consistent across Tasks 2, 3
- `canonical_file` format: vault-relative path `raw/articles/x/<name>.md` — consistent across Tasks 2, 3
- `needs_canonical_recompile` lifecycle: set in Task 3 (Phase 1), cleared in Task 4 (Phase 4)
- `<bird-auth>` flags: built once in guards, used everywhere — consistent in Task 2
- Media path: `media/x/` at vault root — consistent in Task 2

### No Placeholders

All tasks contain complete content. No TBD, TODO, or "fill in later" entries.
