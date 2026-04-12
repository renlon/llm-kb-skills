---
name: kb
description: "Use when compiling raw sources into the wiki, querying the knowledge base, running health checks or lint on the wiki, evolving or improving wiki coverage, or when user says 'compile', 'update the wiki', 'query', 'lint', 'health check', 'evolve', 'what's missing', or 'suggest improvements'. Also triggers on questions that should be answered from the knowledge base."
---

## Overview

Main operating skill for LLM-maintained knowledge bases. Four workflows: **compile**, **query**, **lint**, **evolve**. All opus-orchestrated with model-aware subagent dispatch.

**First action in every invocation:** read `kb.yaml` from the project root. If missing, tell the user to run `kb-init` and stop.

### External Sources

`kb.yaml` may contain an `external_sources` list -- folders outside the project that should be included in compile, query, lint, and indexing. These are managed manually by the user.

```yaml
external_sources:
  - path: /absolute/path/to/folder
    label: my-notes
    read_only: true
```

When `external_sources` is present:
- **Compile** scans these paths alongside `raw/` for new/changed files. Sources are tracked in `_index.md` with their label prefix (e.g., `external:lessons/file.md`).
- **Query** includes external source content when searching for relevant material.
- **Lint** checks for orphan sources, stale articles, and broken links across external paths.
- **read_only: true** (default) means the skill never modifies, moves, or deletes files in that folder. It only reads from them.
- If an external path does not exist at runtime, log a warning and skip it -- do not fail the workflow.

### X Enrichment Configuration

`kb.yaml` may contain an `integrations.x.enrich` section controlling pre-compile enrichment of tweet files:

```yaml
integrations:
  x:
    enabled: true                # master toggle for X integration (default: true)
    enrich:
      threads: true              # stitch self-threads via bird CLI (default: true)
      media: true                # download images/videos/PDFs (default: true)
      video_max_mb: 100          # skip videos larger than this (default: 100)
      max_files_per_run: 20      # cap enrichment candidates per compile (default: 20)
      api_delay_ms: 1000         # delay between bird API calls in ms (default: 1000)
    browser: chrome              # cookie source for bird CLI auth
    browser_profile: null        # optional, for multi-profile browsers
    media_dir: media/x           # vault-level media storage (outside raw/)
```

When `integrations.x.enrich` is present, compile runs Phase 0 (X Enrichment) before Incremental Detection. If the section is missing or both toggles are `false`, Phase 0 is skipped entirely.

## Obsidian-Native Formatting

All wiki output MUST use Obsidian-native conventions:

- YAML frontmatter delimited by `---`
- `[[wikilinks]]` for ALL internal links -- NEVER use markdown-style `[text](url)` links for internal references
- `[[wikilinks|display text]]` when the display name differs from the target article
- Tags in frontmatter: `tags: [concept, topic]`
- Aliases in frontmatter: `aliases: [alternate name]`
- Image embeds: `![[image-name.png]]`
- Standard markdown for everything else (headings, lists, bold, code blocks, etc.)

## Model Strategy

Always set the `model` parameter explicitly when dispatching subagents.

| Task | Executor | Verifier |
|---|---|---|
| Index scanning, link checking, file diffing | haiku subagents | none |
| Summarizing individual sources | haiku subagents | opus spot-checks |
| Wiki article writing | sonnet subagents | opus reviews before commit |
| Deep research | sonnet subagents | opus orchestrates + verifies |
| Research synthesis / final reports | opus | none |
| Lint issue detection | sonnet subagents | opus prioritizes + filters |
| Query answering | opus | none |
| Consistency checks | sonnet subagents | opus final judgment |

## Workflow 1: Compile

**Trigger:** User adds files to `raw/` and says "compile" or "update the wiki".

### X Enrichment (Phase 0)

Enriches raw tweet files before compilation. Stitches same-author self-threads and downloads media (images, videos, PDFs) into the vault. Runs only if `integrations.x.enrich` exists in `kb.yaml`.

**Config check (first -- zero side effects):**

1. Read `integrations.x` from `kb.yaml`. If `enabled` is false or `enrich` section missing --> skip Phase 0.
2. If both `enrich.threads` and `enrich.media` are `false` --> log "X enrichment: both threads and media disabled -- skipping" and skip Phase 0. No bird CLI check, no auth, no file scan.

**Guards (only if at least one enrich toggle is true):**

3. Run `bird --version`. If fails --> log warning "bird CLI not found -- skipping enrichment", skip Phase 0.
4. Build auth flags from config: `--cookie-source <integrations.x.browser>`. If `browser_profile` is set: add `--chrome-profile "<profile>"` (chrome) or `--firefox-profile "<profile>"` (firefox). These flags are referred to as `<bird-auth>` below.
5. Run `bird whoami <bird-auth>`. If fails --> log "X auth expired -- skipping enrichment", skip Phase 0 entirely. Do not attempt per-file calls.

**Scan and cap:**

6. Glob `raw/articles/x/**/*.md`. For each file, apply two-stage eligibility:
   - **Stage 1 (state):** Skip if frontmatter has `enriched: true`, `enriched: skipped`, or `enriched: merged`. Continue if no `enriched` field, `enriched: failed`, or `enriched: false`.
   - **Stage 2 (URL):** Parse tweet URL from frontmatter `source` field only (not body). If no parseable tweet URL --> set `enriched: skipped`, remove from candidates.
7. Separate candidates: **fresh** (no `enriched` field) and **retries** (`enriched: failed`/`false`). Sort each group by file mtime (oldest first).
8. Apply `enrich.max_files_per_run` cap (default: 20): take fresh candidates first, fill remaining slots from retries. Log "N files deferred to next compile run" if more exist.

**Path A -- Threads enabled** (`enrich.threads: true`, the default):

9. For each selected candidate, fetch thread: `bird thread <tweet-id> --json --all <bird-auth>`. The response is `{ "tweets": [...] }` -- access the array via `.tweets`. Insert `enrich.api_delay_ms` (default: 1000ms) delay between calls.
10. **Walk the self-thread chain** for each candidate:
    - Record the bookmarked tweet's `authorId` (top-level string field) as the target author.
    - **Walk UP:** From the bookmarked tweet, follow `inReplyToStatusId` links collecting tweets where `authorId` matches the target. Stop at a different author or the conversation root.
    - **Walk DOWN (from bookmarked tweet only):** Starting from the bookmarked tweet, look for tweets whose `inReplyToStatusId` equals the current node's `id` AND whose `authorId` matches. If exactly one match: add it, advance, repeat. If zero or multiple: stop. Do NOT walk down from ancestors -- only from the bookmarked tweet.
    - Merge ancestor chain + bookmarked tweet + descendant chain. Sort chronologically by `createdAt`.
11. **Compute `thread_dedup_key`** = `"<root_id>:<leaf_id>"` from the stitched chain. For single tweets, both IDs are the same.
12. **Cross-run dedup:** Scan files in `raw/articles/x/` with `enriched: true` for matching `thread_dedup_key`. If match found --> mark candidate `enriched: merged` with `canonical_file` pointing to the existing file (vault-relative path) and `thread_dedup_key`.
13. **Within-run dedup:** Group remaining candidates by `thread_dedup_key`. If multiple share a key, select the canonical (tweet ID matching chain root, or earliest). Do NOT mark others merged yet -- defer until canonical succeeds.
14. **Enrich each canonical:**
    - If chain has 2+ tweets, stitch into the raw file using fenced markers:
      ```
      <!-- enrich:thread -->
      > **Thread by @<author.username>** (N tweets):
      >
      > [1/N] First tweet text...
      > [2/N] Second tweet text...
      <!-- /enrich:thread -->
      ```
    - If `enrich.media: true`, download media from all tweets in the chain (see Media Download below).
    - Set frontmatter: `thread_dedup_key`, `thread_root_id`, `thread_leaf_id`, `conversation_id`, `thread_length`, `enriched: true`, `enriched_at` (ISO 8601).
    - On any failure (bird non-zero exit, bookmarked tweet missing from response, required parent missing during chain walk) --> set `enriched: failed`, continue to next candidate.
15. **Finalize dedup:** For each within-run group whose canonical succeeded (`enriched: true`), mark non-canonicals `enriched: merged` with `canonical_file` (vault-relative path) and `thread_dedup_key`. If canonical failed, leave duplicates unchanged (eligible for retry).

**Path B -- Media only** (`enrich.threads: false` AND `enrich.media: true`):

16. For each selected candidate, fetch single tweet: `bird read <tweet-id> --json <bird-auth>`. Insert `api_delay_ms` delay between calls.
17. Write identity fields: `thread_dedup_key: "<tweet_id>:<tweet_id>"`, `thread_root_id`, `thread_leaf_id` (all equal to the tweet ID). No thread stitching, no dedup.
18. Download media from the bookmarked tweet only (see Media Download below).
19. Set frontmatter: `enriched: true`, `enriched_at` (ISO 8601), identity fields. On failure --> `enriched: failed`.

#### Media Download

Downloads images, videos, and PDFs from tweets for vault-level preservation. Media is stored in `media/x/` at the vault root (sibling of `raw/`, NOT inside `raw/`). Obsidian resolves `![[filename]]` embeds by name from anywhere in the vault.

1. Collect media from all tweets in the stitched chain (Path A) or the single tweet (Path B). Deduplicate by URL -- first chronological occurrence determines the filename.
2. **Download by type:**

   | Type | Source Field | Filename |
   |------|-------------|----------|
   | Photo | `media[].url` | `<source_tweet_id>-<n>.<detected_ext>` |
   | Video / GIF | `media[].videoUrl` | `<source_tweet_id>-<n>.mp4` |
   | PDF (linked) | Use `--json-full` flag, parse `_raw.legacy.entities.urls[].expanded_url` matching `.pdf`, `arxiv.org/pdf/`, `papers.ssrn.com`, `openreview.net/pdf` | `<source_tweet_id>-<n>.pdf` |

   `<source_tweet_id>` = tweet containing the media. `<n>` = 1-indexed media position within that tweet. `<detected_ext>` = from URL path or magic bytes (JPEG `FF D8` --> `.jpg`, PNG `89 50 4E 47` --> `.png`).

3. **Download command:** `curl -sfL --max-time 30 -o <dest> <url>`. Run `mkdir -p media/x/` before first download.
4. **Post-download validation:**
   - File > 1KB (reject tiny error pages)
   - Images: verify magic bytes (JPEG or PNG)
   - Videos: file > 10KB
   - If validation fails: delete file, log warning, skip that media item
5. **Video size guard:** Before downloading videos, send `curl -sfLI <url>` to check `Content-Length`. If exceeds `enrich.video_max_mb` (default: 100MB), skip and log as text link. If header absent, download with `--max-filesize`. After download, verify file size on disk -- delete if over limit.
6. **PDF detection:** To find linked PDFs, re-fetch the tweet with `--json-full` and parse `_raw.legacy.entities.urls[].expanded_url`. There is no `links` field on bird responses -- expanded URLs are only available via `--json-full`.
7. **Inject embeds** within fenced markers:
   ```
   <!-- enrich:media -->
   > **Media:**
   > ![[<source_tweet_id>-1.jpg]]
   > ![[<source_tweet_id>-2.mp4]]
   <!-- /enrich:media -->
   ```
   Failed downloads appear as text links: `> Failed to download: <url>`

**v1 contract:** Enrichment enriches raw sources. Media and thread context are visible when browsing `raw/articles/x/` in Obsidian. The compile pipeline (Phases 1-4) remains text-only -- media embeds may or may not appear in wiki articles depending on the extractor.

### Incremental Detection

1. Read `wiki/_index.md` (lists every raw source with its last-compiled hash)
2. Scan `raw/` recursively with Glob
3. Scan each `external_sources` path from `kb.yaml` (if any). Prefix entries in the index with `external:<label>/` to distinguish them from `raw/` sources.
4. Diff against index: identify **new**, **changed**, and **deleted** sources
5. Only process what changed -- never recompile the entire source tree
6. **Handle `enriched: merged` files** (state-derived, restart-safe): For each file in `raw/articles/x/` with `enriched: merged` in frontmatter:

   a. **Validate `canonical_file`:** Read the merged file's `canonical_file` frontmatter (vault-relative path like `raw/articles/x/name.md`). Valid if ALL of: (1) path is under `raw/articles/x/`, (2) file exists, (3) target has `enriched: true`, (4) target's `thread_dedup_key` matches merged file's `thread_dedup_key`.

   b. **If invalid:** Log warning. Do NOT clean up any index/source entries. Add the merged file to the process list as a normal source (live fallback -- preserves source coverage).

   c. **If valid -- set flag FIRST, then clean up:** Write `needs_canonical_recompile: true` to the merged file's frontmatter and flush to disk BEFORE any cleanup. Then:
      - Remove merged file entry from `wiki/_index.md` (if present)
      - Remove merged file entry from `wiki/_sources.md` (if present)
      - In any wiki article's frontmatter `sources:` array, replace the merged file with the canonical. If canonical already listed, just drop the merged entry.
      - Log cleanup in `wiki/_evolution.md`

   d. **Queue canonical:** Add the validated canonical to the process list (if not already there).

   e. **Skip merged file from extraction:** Do not add valid-canonical merged files to the process list -- the canonical file covers them.

### Per-File Extraction (sonnet subagents)

For each new or changed source, dispatch a sonnet subagent to:

1. Read the raw source
2. Determine type (article, paper, transcript, dataset, etc.)
3. Extract concepts, claims, entities, and relationships
4. **Choose article format** for each concept -- `default` or `tutorial` (see format selection criteria below)
5. Return a structured extraction object including the chosen format per concept

### Opus Orchestration

After extractions complete, opus:

5. New concepts -> create wiki article
6. Existing concepts -> update and enrich the article with new information
7. Add source backlinks to every article touched
8. Auto-categorize articles into folders based on topic

### Wiki Article Formats

The compile step supports two article formats. The sonnet subagent chooses the format per concept during extraction -- opus does NOT override this choice unless the result is clearly wrong.

#### Format Selection Criteria

Use **tutorial** when ALL of these are true:
- The concept is a learnable technical skill, tool, pattern, or methodology
- The source material contains enough depth for a meaningful deep-dive (not just a passing mention)
- Someone would realistically study this concept to apply it in practice

Use **default** for everything else:
- People, organizations, events, historical facts
- Datasets, benchmarks, reference tables
- Concepts that are descriptive rather than instructional (e.g., a summary of a paper's findings)
- Concepts where the source material is too thin for a full tutorial

When in doubt, use **default**. A concise reference article is better than a padded tutorial.

#### Default Format

```markdown
---
title: "Concept Name"
aliases: [alternate name, abbreviation]
tags: [domain, topic]
article_format: default
sources:
  - "[[raw/articles/source-file.md]]"
created: 2026-04-03
updated: 2026-04-03
---

# Concept Name

Core explanation of the concept.

## Details

Detailed information extracted from sources.

## Relationships

- Related to [[Other Concept]] because...
- Contradicts [[Conflicting Idea]] on the point of...
- Builds on [[Foundation Concept]]

## Sources

- [[raw/articles/source-file.md]] -- key claims extracted from this source
```

#### Tutorial Format

For learnable technical concepts. Follows an easy-to-hard hierarchy so the reader can enter at their level.

```markdown
---
title: "Concept Name"
aliases: [alternate name, abbreviation]
tags: [domain, topic]
article_format: tutorial
sources:
  - "[[raw/articles/source-file.md]]"
created: 2026-04-03
updated: 2026-04-03
---

# Concept Name

## Core Concept

A high-level, plain-English summary. Use a beginner-friendly analogy to ground the idea before introducing any jargon.

## Foundational Context

Define essential vocabulary. Explain the problem this concept solves and why prior approaches fell short. Proactively address the "5 Whys" -- keep asking why until the root motivation is clear.

## Technical Deep-Dive

Transition into mechanics: architecture, algorithms, implementation details. Keep it accessible but rigorous. Use code blocks, diagrams (via `![[image.png]]`), and worked examples where appropriate.

## Best Practices

Real-world production considerations: scalability, cost, evaluation methods, common pitfalls, and failure modes. Link to related concepts via `[[wikilinks]]`.

## Growth Path

Practical next steps to build mastery:
- Specific exercises or projects to try
- Resources for further reading (link to other wiki articles or external sources)
- Common progression from beginner to advanced usage

## Relationships

- Related to [[Other Concept]] because...
- Builds on [[Foundation Concept]]

## Sources

- [[raw/articles/source-file.md]] -- key claims extracted from this source
```

### Index Maintenance

After every compile, update these files:

- **`wiki/_index.md`** -- master list: article name, one-line summary, compiled-from hash
- **`wiki/_sources.md`** -- mapping from raw sources to wiki articles they contributed to
- **`wiki/_categories.md`** -- auto-maintained category tree reflecting folder structure
- **`wiki/_evolution.md`** -- append-only log of auto-evolve actions: `date | trigger | action | articles affected`
- **Clear `needs_canonical_recompile`:** After all wiki changes are ready, scan `raw/articles/x/` for files with `needs_canonical_recompile: true`. For each, remove the field from frontmatter. Stage these changes alongside all other Phase 4 changes so they are included in the same commit. This ensures the one-shot requeue flag is cleared atomically with the compile results.

## Workflow 2: Query

**Trigger:** User asks a question about the knowledge base.

### Step 1: Ask Query Depth

Present three options:

- **Quick** -- wiki-only. Read indexes, find relevant articles, synthesize an answer. No external calls.
- **Standard** -- wiki + web. Start from wiki, use WebSearch/WebFetch to fill gaps.
- **Deep** -- full research pipeline. Invoke `/research` for outline, `/research-deep` dispatches sonnet subagents, opus orchestrates and verifies.

### Step 2: Execute at Chosen Depth

Run the appropriate pipeline. For Standard and Deep, clearly mark which information came from the wiki and which came from external sources.

### Step 3: Render Output

Format the answer according to `kb.yaml` output preferences (markdown, Marp, matplotlib, etc.) and save to `output/`.

### Step 4: Auto-Evolve (background opus subagent)

After delivering the answer to the user, **immediately dispatch a background opus subagent** (via Agent tool with `run_in_background: true`). Do NOT ask the user for permission — this runs silently.

The subagent receives:
- The original query
- The full response (including sources used and depth level)
- The current `wiki/_index.md`

The subagent decides and acts:

1. **New knowledge?** — Did the response contain information not already in the wiki? (External data from Standard/Deep queries, new connections between concepts, corrections to existing articles, newly surfaced entities or claims)
2. **If no** — exit silently. Log nothing. The query was just a read.
3. **If yes** — act:
   - **New concept** → create a wiki article using the appropriate format (default or tutorial, applying the same selection criteria as Compile), place in the right category folder
   - **Enrichment** → update existing articles with new information, add source backlinks
   - **Correction** → update articles where the response contradicted or superseded wiki content
   - **New connections** → add `[[wikilinks]]` between articles that the query revealed are related
   - Update `wiki/_index.md`, `wiki/_sources.md`, `wiki/_categories.md`
   - Append a one-line entry to `wiki/_evolution.md`: `YYYY-MM-DD | query | action taken | articles affected`

**Constraints:**
- Never delete or downgrade existing content — only add or refine
- Never create stub articles under 100 words — if there isn't enough to say, add the knowledge to an existing article instead
- Quick-depth queries rarely produce new knowledge — the subagent should almost always exit silently for these
- The subagent must re-read any article it plans to modify (not rely on cached state)

## Workflow 3: Lint

**Trigger:** "health check", "lint the wiki", or invoked via `/loop` or `/schedule`.

### Checks (sonnet subagents in parallel)

1. **Broken links** -- `[[wikilinks]]` pointing to non-existent articles
2. **Orphan articles** -- wiki articles with zero inbound links
3. **Orphan sources** -- files in `raw/` or `external_sources` paths that were never compiled
4. **Stale articles** -- source file changed since the article was last compiled
5. **Consistency** -- conflicting claims across different articles
6. **Missing backlinks** -- links that should be bidirectional but aren't
7. **Sparse articles** -- articles below ~200 words

### Opus Collation

Opus collates all findings, filters false positives, and prioritizes by severity (critical > warning > info).

### Output

Save to `output/lint-YYYY-MM-DD.md`. Group issues by severity, include suggested fixes, and ask the user if they want auto-fix applied.

## Workflow 4: Evolve

**Trigger:** "evolve the wiki", "suggest improvements", or "what's missing".

### Process

1. Opus reads `wiki/_index.md`, `wiki/_categories.md`, and samples articles
2. Dispatch sonnet subagents to analyze article clusters for:
   - **Gaps** -- concepts referenced in articles that lack their own article
   - **Connections** -- cross-category relationships not yet explored
   - **Missing data** -- claims that could be verified or enriched via web search
   - **Questions** -- interesting unanswered questions surfaced by the existing content
3. Opus collates, deduplicates, and ranks suggestions by value
4. Present as a numbered list with brief rationale for each
5. User picks items -> Claude executes via Compile, Query, or web search as appropriate

## Handling X/Twitter Links

When the user pastes an `x.com` or `twitter.com` URL and wants it added to the knowledge base:

### Step 1: Check if Smaug is configured

Read `kb.yaml` and look for `integrations.smaug.path`. If it exists, verify the path is still valid:

```bash
test -d "<smaug_path>" && test -f "<smaug_path>/smaug.config.json" && echo "smaug-ready" || echo "smaug-missing"
```

If `integrations.smaug` is not in `kb.yaml`, try finding it:

```bash
which bird 2>/dev/null && find ~ -maxdepth 4 -name "smaug.config.json" -type f 2>/dev/null | head -1
```

If found, **save the path to `kb.yaml`** under `integrations.smaug.path` so future sessions don't need to search again.

### Step 2a: Smaug IS available

1. `cd` to the Smaug path from `kb.yaml`
2. Extract the tweet ID from the URL (the numeric part after `/status/`)
3. Run: `npx smaug fetch <tweet_id>` then `npx smaug process`
4. Smaug outputs markdown with frontmatter to its `knowledge/` directory
5. Copy the output to `raw/articles/` and trigger Compile

### Step 2b: Smaug is NOT available

Tell the user you cannot directly fetch X/Twitter content, then present these options:

1. **Install Smaug** (recommended) — `git clone https://github.com/alexknowshtml/smaug && cd smaug && npm install`, then `npx smaug setup` to configure X session cookies (`auth_token` + `ct0` from browser DevTools → Cookies → x.com). After setup, **save the install path to `kb.yaml`** under `integrations.smaug.path`. Note: uses session cookies, technically violates X TOS but practical risk for personal read-only use is very low.
2. **Manual paste** — ask the user to copy-paste the tweet/thread text. Save to `raw/articles/x-<tweet_id>.md` with the tweet URL as a source link.
3. **Thread Reader App** — for threads, suggest pasting the URL at threadreaderapp.com, then copy the unrolled result.
4. **X Data Export** — for bulk import of own tweets/bookmarks: X Settings → Download your data (TOS-compliant, 24-48hr wait).

**If the user provides the tweet content directly** (paste, screenshot, or any other method), accept it immediately and proceed — save to `raw/articles/x-<tweet_id>.md` with proper frontmatter and trigger Compile. Do not gatekeep.

### Smaug output format

Smaug produces markdown like:
```markdown
## @username - Title
> Tweet text

- **Tweet:** https://x.com/...
- **Link:** https://...
- **What:** One-line description
```

And knowledge files with YAML frontmatter in `knowledge/articles/` or `knowledge/tools/`. Both formats are valid raw sources for Compile.

## Common Mistakes

- Running compile on the entire `raw/` folder when only a few files changed -- always use incremental detection
- Using markdown-style links `[text](url)` instead of `[[wikilinks]]` for internal references
- Skipping index updates (`_index.md`, `_sources.md`, `_categories.md`) after compile
- Asking the user whether to file query results -- auto-evolve handles this silently in the background
- Defaulting to Deep query depth for simple factual questions -- try Quick first
- Forgetting to dispatch the auto-evolve subagent after a query -- it must always run, even if it usually exits silently
- Refusing to process an X/Twitter link just because Smaug isn't installed -- always offer alternatives and accept manual paste
- Trying to use WebFetch on X/Twitter URLs -- it always fails due to auth walls, don't bother
- Placing media files inside `raw/` instead of `media/x/` at the vault root -- binary files in `raw/` get picked up by the compile glob as source candidates
- Running bird API calls before the `bird whoami` auth preflight -- if auth is expired, every per-file call will fail
- Marking duplicate files `enriched: merged` before the canonical is confirmed `enriched: true` -- if canonical fails, duplicates are lost
- Using `author.username` instead of `authorId` for thread chain walk -- usernames are mutable handles, not stable identifiers
- Walking the thread chain DOWN from ancestors instead of the bookmarked tweet -- ancestor-level branches can interfere with descent
- Cleaning up wiki index/source entries for a merged file before writing `needs_canonical_recompile: true` -- crash between cleanup and flag-write loses the requeue obligation
- Scanning the file body (not just frontmatter `source` field) for tweet URLs -- this can accidentally enrich manual files that merely reference tweets
