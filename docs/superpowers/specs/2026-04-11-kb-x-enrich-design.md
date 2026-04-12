# KB X/Twitter Enrichment — Design Spec

**Goal:** Add a pre-compile enrichment phase to the KB pipeline that (1) preserves tweet media (images, videos, PDFs) in the Obsidian vault for human consumption and (2) stitches self-threads into coherent raw files before compilation.

**Non-goal:** Semantic extraction from media. The compile pipeline (Phases 1-4) remains text-only. Media files are vault attachments — visible to human readers in Obsidian but not processed by the LLM extractor. Future multimodal extraction is out of scope for this design.

**Scope:** KB skill layer only. No Smaug fork. Enrichment runs as Phase 0 of `/kb compile`.

**Date:** 2026-04-11 (revised 2026-04-12 after peer debate, rev 17)

---

## Context

The existing X/Twitter pipeline:

```
X likes/bookmarks → Smaug (cron) → raw/articles/x/ → /kb compile → wiki
```

**Current gaps:**

1. **Media:** Smaug is a text-only archiver. It does not download images, videos, or PDFs from tweets. Visual content (infographics, diagrams, screenshots) is lost — not even preserved as vault attachments.
2. **Threads:** Smaug fetches only the immediate parent tweet (1 level up). Self-threads — where one author posts a chain of replies to get around the character limit — are not stitched together. Each bookmarked tweet becomes a separate file with no thread context.

**Key discovery:** Bird CLI (`@steipete/bird` v0.8.0), already installed by `kb-x-setup`, has capabilities Smaug doesn't use:
- `bird thread <tweet-id> --all` — fetches the full conversation thread containing a tweet (paginated)
- `bird read` JSON includes `conversationId` (groups all tweets in a thread), `media[]` (type, url, videoUrl, dimensions), `inReplyToStatusId`, and stable `authorId`
- `bird whoami` / `bird check` — verify auth status
- `bird search`, `bird user-tweets` also available if needed

These capabilities enable a KB-layer enrichment phase that enhances Smaug's output without modifying Smaug itself.

---

## Architecture

### Pipeline Change

Current compile flow:

```
raw/articles/x/  →  Incremental Detection  →  Extraction  →  Article Writing  →  Index
```

New compile flow:

```
raw/articles/x/  →  X ENRICHMENT (Phase 0)  →  Incremental Detection  →  Extraction  →  Article Writing  →  Index
```

### How Enrichment Integrates

Phase 0 modifies raw markdown files in place (adds thread context, media embeds, frontmatter flags). This changes their content hash. The existing Phase 1 (Incremental Detection) then sees them as "changed" and recompiles them normally. Phases 1-4 remain text-only and do not process media files.

**Required Phase 1 changes:**

**Required Phase 1 changes** (state-derived, restart-safe):

Phase 1 (Incremental Detection) checks the `enriched` frontmatter field during its source scan. This is derived from current file state on every run — not from an in-memory transition set — so it is automatically restart-safe if a previous compile was interrupted.

1. **Skip merged files during extraction (with invalid-canonical exception):** Any file with `enriched: merged` in frontmatter is excluded from the "process" list — UNLESS its `canonical_file` fails validation in step 2a (see below). If the canonical is invalid, the merged file is NOT skipped — it is extracted normally as a live source, preserving source coverage until the user fixes the canonical pointer.

2. **Clean up merged files in indexes (all-or-nothing, gated on canonical validity):** For each file with `enriched: merged`:

   **a. Validate `canonical_file` first (before any mutations):**
   - **Format:** `canonical_file` is always a vault-relative path (e.g., `raw/articles/x/neural-computers.md`), matching the format used in `wiki/_sources.md` and article `sources:` arrays.
   - **Valid if ALL of:** (a) it is a vault-relative path under `raw/articles/x/` (reject paths containing `..` or outside that prefix), (b) the file exists on disk, (c) the target file's frontmatter has `enriched: true` (not `merged`, `failed`, or any other state), and (d) the target file's `thread_dedup_key` matches the merged file's `thread_dedup_key` (identity check — prevents a stale or wrong pointer from silently rewriting references to an unrelated file). Merged files store their `thread_dedup_key` during Phase 0 dedup, so this check is always available.
   - **If invalid:** Log a warning naming the merged file and the invalid canonical. **Skip all cleanup for this merged file** — leave `_index.md`, `_sources.md`, and article `sources:` entries untouched. Do not set `needs_canonical_recompile`. Do not enqueue the canonical for Phase 2. Instead, add the **merged file itself** to the normal Phase 2 process list (step 1 exception) so it is extracted as a live fallback, preserving source coverage until the user fixes the canonical pointer.

   **b. If canonical is valid — set flag FIRST, then mutate:**
   - **First:** Set `needs_canonical_recompile: true` in the merged file's frontmatter (if not already set) and flush/write the file. This persists the requeue obligation BEFORE any cleanup mutations, so a crash between flag-write and cleanup cannot lose the obligation.
   - Then perform the three cleanup mutations:
     - If the merged file has an entry in `wiki/_index.md`: remove it.
     - If the merged file has an entry in `wiki/_sources.md`: remove it.
     - If any wiki article references the merged file in its frontmatter `sources:` array: replace with the canonical file reference. If canonical is already listed, simply drop the merged entry.
   - If any cleanup was performed: log in `wiki/_evolution.md`.

3. **Queue canonical for recompilation (one-shot, restart-safe):** For every `enriched: merged` file that has `needs_canonical_recompile: true` in frontmatter AND whose `canonical_file` passed validation, add the canonical to the Phase 2 "process" list (with process-list dedup). **Clear point:** `needs_canonical_recompile` is cleared from all merged files pointing to successfully recompiled canonicals as part of the same Phase 4 `git commit` that commits all wiki changes. The flag-clear is staged alongside wiki article writes, index updates, and other Phase 4 changes — there is no separate follow-up commit. This eliminates the crash window between "compile succeeded" and "flag cleared."

   **Crash behavior:** The `/kb compile` workflow operates on a git-tracked vault. During a compile run, all file modifications (raw frontmatter edits, wiki article writes, index updates) are working-tree changes that exist on disk but are not yet committed to git. A process crash (kill, OOM, power loss) preserves these on-disk working-tree changes — they are NOT lost. Only a deliberate `git checkout .` or `git restore .` would discard them.

   The `needs_canonical_recompile` flag is written/flushed to the merged file's frontmatter in step 2b BEFORE any cleanup mutations. Crash scenarios:
   - **Crash before flag write:** No state changed. Clean restart, Phase 1 retries from scratch. Safe.
   - **Crash after flag write, before/during cleanup:** Flag is on disk. Next run sees it, re-enqueues canonical. Idempotent cleanup re-checks and re-applies. Safe.
   - **Crash after cleanup, before Phase 4 commit:** Flag is on disk, cleanup mutations are on disk. Next run sees flag, re-enqueues canonical (cleanup already done — idempotent re-check finds nothing new). Safe.
   - **Phase 4 commit succeeds:** Flag cleared in same commit. Done. No future requeue.

This approach makes cleanup a **state-derived operation** that runs idempotently on every compile. The `needs_canonical_recompile` flag is written before mutations and bridges the crash window between Phase 1 cleanup and the final `git commit` (end of Phase 4). No in-memory handoff is required.

**Important:** Media files are stored in `media/x/` at the vault root (a sibling of `raw/`, NOT inside `raw/`). This prevents the compile pipeline's recursive `raw/` glob from picking up binary files as source candidates.

### What Phase 0 Does

1. **Config check (first — zero side effects):**
   - Check `kb.yaml` for `integrations.x.enabled` and `integrations.x.enrich`. If missing → skip Phase 0.
   - **Path 0 early exit:** If both `enrich.threads: false` AND `enrich.media: false`, log "X enrichment: both threads and media disabled — skipping" and exit Phase 0 immediately. No bird CLI check, no auth check, no file scanning.

2. **Guards (only reached if at least one enrich toggle is true):**
   - Check bird CLI is available: `bird --version`
   - **Build Bird args:** Construct the shared auth flags from config: `--cookie-source <browser>` plus `--chrome-profile "<profile>"` or `--firefox-profile "<profile>"` if `browser_profile` is set. All bird commands in Phase 0 use these same flags. Referred to as `<bird-auth>` below.
   - **Auth preflight:** Run `bird whoami <bird-auth>`. If this fails, log "X auth expired — skipping enrichment" and short-circuit Phase 0 entirely. Do not attempt per-file calls with broken auth.

3. **Scan and cap:**
   - Scan `raw/articles/x/` for enrichment candidates (see Enrichment Tracking for eligibility rules)
   - Apply two-stage eligibility (see Enrichment Tracking): state check, then URL check. Files without parseable tweet URLs are marked `enriched: skipped` and removed from the candidate list.
   - **Apply `max_files_per_run` cap here** (default: 20). **Scheduling priority:** new candidates (no `enriched` field) are processed before retries (`enriched: failed` or `enriched: false`). Within each group, take the oldest by file mtime. If more exist, log "M files deferred to next compile run." This prevents permanent failures (deleted tweets, 404s) from monopolizing the cap and starving fresh work. The cap applies BEFORE any bird API calls, preventing unbounded network work.

4. **Branch by mode:**


   **Path A: Threads enabled** (`enrich.threads: true`, the default)

   Fetches thread data, dedup groups, and stitches:

   a. For each candidate (up to the cap), fetch thread data: `bird thread <tweet-id> --json --all <bird-auth>`
   b. **Walk chain and compute dedup key:** Walk `inReplyToStatusId` UP and DOWN (branch-safe) filtered by `authorId` to produce the stitched chain. Compute `thread_dedup_key` = `<root_id>:<leaf_id>`. This composite key uniquely identifies the stitched path.
   c. **Cross-run dedup:** Scan already-enriched files (`enriched: true`) for their `thread_dedup_key` field. If a selected candidate's key matches, mark it `enriched: merged` pointing to that existing file. (Safe — the canonical already succeeded on a prior run.)
   d. **Within-run dedup:** Group remaining selected candidates by `thread_dedup_key`. Both fresh candidates (no `enriched` field) and retries (`enriched: failed`/`false`) participate in dedup equally — a retry can be merged if another candidate in the same group becomes canonical. If multiple share a key (same stitched path), select the canonical file (matching the chain root tweet ID, or earliest). **Do NOT mark others `enriched: merged` yet** — the canonical hasn't been enriched.
   e. **Enrich each canonical:** Stitch self-thread (see Thread Stitching). If `enrich.media: true`, also download media from all thread tweets. Mark `enriched: true` with `enriched_at`.
   f. **Finalize dedup (only after canonical succeeds):** For each within-run dedup group, mark the non-canonical files `enriched: merged` ONLY if the canonical was successfully marked `enriched: true` in step (e). If the canonical failed (`enriched: failed`), leave all duplicates in their current state (eligible for retry next run). This prevents losing source coverage when the canonical's enrichment fails.

   **Path B: Media only** (`enrich.threads: false` AND `enrich.media: true`)

   Skips thread fetching and dedup entirely — each file is independent:

   a. For each candidate (up to the cap), fetch single tweet: `bird read <tweet-id> --json <bird-auth>`
   b. No thread stitching, no chain-root computation, no dedup grouping
   c. **Write identity fields:** Set `thread_dedup_key: "<tweet_id>:<tweet_id>"`, `thread_root_id: "<tweet_id>"`, `thread_leaf_id: "<tweet_id>"` using the bookmarked tweet ID. This maintains the invariant that every `enriched: true` file has these fields, enabling consistent cross-run dedup and Phase 1 canonical identity validation if the user later enables threads.
   d. Download media from the bookmarked tweet only (not from thread). PDF detection uses `links` from the `bird read` JSON response (bird exposes expanded URL entities).
   e. Mark `enriched: true` with `enriched_at` timestamp

5. **Rate limiting:**
   - Insert a configurable delay between bird API calls (`api_delay_ms`, default: 1000ms)
   - The `max_files_per_run` cap is applied in step 3 (Scan), before any network calls

### Execution Model

- **Opus** orchestrates the enrichment phase
- **Haiku subagents** handle mechanical scanning (find unenriched files, extract tweet IDs, parse JSON)
- **Bird CLI and curl** run directly for fetching thread data and downloading media
- **No sonnet needed** — this is API calls and file manipulation, not content generation

### Opt-In Behavior

The enrichment phase only runs if `integrations.x.enrich` exists in `kb.yaml`. KBs without X integration are completely unaffected. If bird CLI is not installed, the phase logs a warning and skips — compile proceeds without enrichment rather than failing.

---

## Thread Stitching

### Flow

For each canonical unenriched raw file in `raw/articles/x/`:

1. **Extract tweet ID** from frontmatter. Smaug's output files include the tweet URL (e.g., `source: "https://x.com/omarsar0/status/2042724343466295307"`). Parse the numeric ID from the URL.

2. **Fetch full thread with pagination:**
   ```bash
   bird thread <tweet-id> --json --all <bird-auth>
   ```
   The `--all` flag ensures full pagination. `<bird-auth>` is the shared auth flags built in the Guards step (includes `--cookie-source` and optional profile flags). This returns all tweets in the conversation — replies from the author AND other people.

3. **Walk the self-thread chain using `inReplyToStatusId`:**

   Do NOT simply filter by `author.username` — usernames are mutable handles and filtering by username alone captures same-author replies to other people's branches within the conversation.

   Instead, use `authorId` (stable numeric ID) and walk the `inReplyToStatusId` chain:

   a. Start from the bookmarked tweet. Record the bookmarked tweet's `authorId` as the target author.
   b. **Walk UP:** Follow `inReplyToStatusId` links from the bookmarked tweet, collecting tweets where `authorId` matches the target author. Stop when you hit a tweet by a different author or the conversation root. Call the result the "ancestor chain."
   c. **Walk DOWN (branch-safe, from bookmarked tweet only):** Starting from the **bookmarked tweet** (NOT from ancestors), iteratively find the next node:
      - Look for tweets in the thread response whose `inReplyToStatusId` equals the **current node's ID** AND whose `authorId` matches the target author.
      - If exactly one such tweet exists: add it to the chain, advance to it, and repeat.
      - If zero or multiple such tweets exist: stop. (Zero = end of chain. Multiple = branch split — following either would be arbitrary.)
      - **Important:** The search at each step checks only `inReplyToStatusId == current_node.id`, NOT "any tweet in the ancestor chain." This prevents a sibling branch off an ancestor above the bookmarked tweet from blocking or interfering with descent below the bookmarked tweet.
   d. **Merge:** Combine the ancestor chain + bookmarked tweet + descendant chain. Sort chronologically. This is the final stitched chain.

4. **Compute `thread_dedup_key` (always, even for single tweets):**
   - `thread_dedup_key` = `"<root_id>:<leaf_id>"` — for a single tweet, root and leaf are the same ID (e.g., `"12345:12345"`). This ensures every enriched file has a `thread_dedup_key` for cross-run dedup and Phase 1 canonical identity validation.

5. **Decide: is this a self-thread?**
   - If only 1 tweet in the chain: not a thread, skip stitching (but still set `thread_dedup_key` above)
   - If 2+ tweets in the chain: self-thread, stitch

6. **Stitch into the raw file** using fenced markers for idempotent mutation:

   ```markdown
   ---
   title: "Neural Computers"
   type: article
   source: "https://x.com/omarsar0/status/2042724343466295307"
   thread_dedup_key: "2042724343466295301:2042724343466295307"
   thread_root_id: "2042724343466295301"
   thread_leaf_id: "2042724343466295307"
   conversation_id: "2042724343466295301"
   thread_length: 4
   enriched: true
   enriched_at: "2026-04-12T05:00:00Z"
   ---

   <!-- enrich:thread -->
   > **Thread by @omarsar0** (4 tweets):
   >
   > [1/4] Excited to share our new paper on Neural Computers...
   >
   > [2/4] Unlike traditional architectures, Neural Computers can learn...
   >
   > [3/4] Key results: 94.2% accuracy on compositional reasoning...
   >
   > [4/4] This opens up wild possibilities for AI agents...
   <!-- /enrich:thread -->

   <!-- enrich:media -->
   <!-- /enrich:media -->

   # Neural Computers: A New Computing Paradigm

   [... existing Smaug-generated article content ...]
   ```

   The `<!-- enrich:thread -->` and `<!-- enrich:media -->` fenced markers allow re-enrichment to replace blocks cleanly without duplicating content. On re-run, everything between matching markers is replaced.

### Frontmatter Additions

- `thread_dedup_key` — composite key `"<root_id>:<leaf_id>"` that uniquely identifies the stitched path. This is the single authoritative dedup key used everywhere (cross-run, within-run, compile skip). NOT `conversationId` (too coarse — groups unrelated branches) and not `thread_root_id` alone (fails when same author has multiple branches from the same root).
- `thread_root_id` — the tweet ID of the self-thread chain root (component of dedup key)
- `thread_leaf_id` — the tweet ID of the last tweet in the stitched chain (component of dedup key)
- `conversation_id` — Bird's `conversationId` field, stored for reference only
- `thread_length` — number of tweets by the same author in the self-thread chain
- `enriched: true` — marks enrichment complete
- `enriched_at` — ISO 8601 timestamp of when enrichment ran

### Edge Cases

- **Plain tweets in `bookmarks.md`:** Enrichment only processes files in `raw/articles/x/`. Tweets without links that Smaug filed to `bookmarks.md` are not touched.
- **Bird failure (auth expired, tweet deleted):** Caught by the session-level auth preflight. If auth fails, Phase 0 short-circuits before any per-file work. If a specific tweet is deleted (auth works but tweet 404s), mark that file `enriched: failed`.
- **Additional links in thread:** If other tweets in the thread contain links not in the original file, note them in the thread block but don't create new raw files — that's Smaug's job.
- **No tweet ID in file:** If the raw file has no parseable tweet URL in its frontmatter `source` field, mark `enriched: skipped`.
- **Partial thread / fetch failure:** The `--all` flag on `bird thread` requests full pagination. Mark the file `enriched: failed` (retry next compile) if ANY of these concrete failure predicates are true:
  1. Bird CLI exits with non-zero status code
  2. The bookmarked tweet ID is not present in the returned thread data
  3. During `inReplyToStatusId` chain walk, a required parent tweet (same `authorId`) is referenced but missing from the response
  Do NOT mark partial or failed results as `enriched: true`.
- **Files not from Smaug:** Some files in `raw/articles/x/` may be manually placed. If a file lacks a tweet URL in frontmatter, it gets `enriched: skipped` — defensive parsing, no assumptions about file origin.

---

## Media Download

### Purpose

Media download serves **vault-level preservation for human readers in Obsidian**. Downloaded images, videos, and PDFs are stored as vault attachments. The compile pipeline (Phases 1-4) does not semantically process binary media files.

**How enrichment blocks interact with compilation:**

The compile pipeline (Phases 1-4) extracts structured concepts from raw sources and rewrites wiki articles — it does NOT preserve raw markdown verbatim. Therefore:

- **Thread context** (`> Thread by @author ...`) becomes additional source material for the sonnet extractor. The extractor reads it as part of the source content and incorporates the thread's information into its concept extraction. Whether the thread blockquote appears verbatim in the wiki article depends on the extractor's judgment — this is by design, not a bug.
- **Media embeds** (`![[image.jpg]]`) are Obsidian syntax in the raw file. The extractor may or may not preserve them. **For v1, media preservation is at the raw-source level** — users browse raw files in Obsidian to see media attachments. Wiki articles may reference media if the extractor includes the embeds, but this is not guaranteed.
- **Failed-download text links** are treated as regular source text by the extractor.
- **HTML comment markers** (`<!-- enrich:thread -->`) are invisible to extraction.

**v1 contract:** Enrichment enriches raw sources. Media and thread context are visible when browsing `raw/articles/x/` in Obsidian. The wiki compilation benefits from richer source content (thread context = more information for extraction), but wiki articles are not guaranteed to display media embeds or thread blocks verbatim. Future versions could add explicit extractor rules to preserve media embeds, but that is out of scope for v1.

### Flow

For each canonical unenriched raw file, after thread stitching:

1. **Get media metadata** from the `bird thread` response (already fetched for thread stitching). Each tweet object includes a `media[]` array with `type`, `url`, `videoUrl`, `width`, `height`.

2. **Collect media from all self-thread tweets** (not just the bookmarked one). If this is a 4-tweet self-thread, media from all 4 tweets is downloaded. **Deduplicate by URL:** the first chronological occurrence of a URL determines the filename (using that tweet's ID and index). If the same URL appears in a later thread tweet, it is not re-downloaded — the embed references the filename from the first occurrence.

3. **Download by type with validation:**

   | Type | Source field | Filename |
   |------|-------------|----------|
   | Photo | `media.url` | `<source_tweet_id>-<n>.<detected_ext>` |
   | Video | `media.videoUrl` | `<source_tweet_id>-<n>.mp4` |
   | Animated GIF | `media.videoUrl` | `<source_tweet_id>-<n>.mp4` |
   | PDF (linked) | URL from tweet links | `<source_tweet_id>-<n>.pdf` |

   **Filename notes:**
   - `<source_tweet_id>` is the ID of the tweet that contains the media (not necessarily the bookmarked tweet — could be another tweet in the self-thread). This prevents filename collisions when collecting media across multiple thread tweets.
   - `<n>` is the media index within that specific tweet (1-indexed, matching the embed examples: `-1`, `-2`, etc.).
   - `<detected_ext>` for photos: detect from the URL path (Twitter media URLs typically end in `.jpg` or `.png`) or from magic bytes after download (JPEG → `.jpg`, PNG → `.png`). Do not hardcode `.jpg` — PNGs are common for screenshots and infographics.

   **Download command (safe curl):**
   ```bash
   curl -sfL --max-time 30 -o <file> <url>
   ```
   - `-f` (`--fail`): return error on HTTP errors instead of saving error pages
   - `-s`: silent
   - `-L`: follow redirects
   - `--max-time 30`: timeout per download

   **Post-download validation:**
   - Check file size > 1KB (reject trivially small files — likely error pages that slipped through)
   - For images: verify file starts with expected magic bytes (JPEG: `FF D8`, PNG: `89 50 4E 47`)
   - For videos: verify file size > 10KB
   - If validation fails: delete the downloaded file, log a warning, skip that media item

4. **Video size guard:** Before downloading videos, send a HEAD request to check `Content-Length`:
   ```bash
   curl -sfLI <url> | grep -i content-length
   ```
   If the response includes `Content-Length` exceeding `video_max_mb` (default: 100MB), skip the download and log the URL as a text link instead. If `Content-Length` is absent, proceed with download using `--max-filesize <video_max_mb_in_bytes>` (curl exits with code 63 if exceeded). **Post-download byte-size check:** After any video download completes, verify the file size on disk does not exceed `video_max_mb`. If it does (possible when `--max-filesize` is unsupported or a CDN streams without Content-Length), delete the file and log the URL as a text link. This makes the size cap deterministic regardless of HEAD behavior.

5. **Inject embeds** into the raw file within the media fenced marker:

   ```markdown
   <!-- enrich:media -->
   > **Media:**
   > ![[2042724343466295307-1.jpg]]
   > ![[2042724343466295307-2.mp4]]
   <!-- /enrich:media -->
   ```

### Storage

- **Location:** `media/x/` at the vault root — a sibling of `raw/`, NOT inside `raw/`
- **Naming:** `<source_tweet_id>-<n>.<detected_ext>` where `<source_tweet_id>` is the ID of the tweet containing the media (not necessarily the bookmarked tweet), `n` is the 1-indexed media position within that tweet, and `<detected_ext>` is the file extension detected from URL or magic bytes
- **Rationale:** Placing media outside `raw/` prevents the compile pipeline's recursive `raw/` glob from treating binary files as source candidates. Obsidian resolves `![[image.jpg]]` embeds by filename from anywhere in the vault, so the storage location doesn't affect rendering.

### PDF Detection

Scan tweet links for URLs ending in `.pdf` or matching known paper hosts:
- `arxiv.org/pdf/`
- `papers.ssrn.com`
- `openreview.net/pdf`
- Direct `.pdf` URLs

Download these as PDFs to `media/x/`.

### Edge Cases

- **No media in tweet:** Skip media download, still mark enriched.
- **Media URL 404 or timeout:** `curl -f` returns non-zero. Log warning, record the failed URL as a text link in the media block (e.g., `> Failed to download: <url>`). Continue with the rest.
- **Partial media success:** If some media downloads succeeded but others failed, the file is still marked `enriched: true` (thread stitching is complete and should not be re-done). Failed media items appear as text links in the media block. The user can set `enriched: false` to retry all media on next compile — the fenced markers ensure clean replacement.
- **Duplicate media across thread tweets:** Deduplicate by URL before downloading — same image shared across thread tweets is downloaded once. In the media block, duplicate URLs are embedded once (using the first-occurrence filename). They are not re-embedded at each occurrence.
- **CDN redirect to HTML:** Post-download validation catches this (size < 1KB or wrong magic bytes). File is deleted, URL recorded as text link.

---

## Enrichment Tracking

### Frontmatter States

```yaml
enriched: true           # successfully enriched (thread + media)
enriched: failed         # bird call failed for this specific file — retry next compile
enriched: skipped        # no tweet ID found or file not eligible — don't retry
enriched: merged         # duplicate of another file in the same thread — see canonical_file
needs_canonical_recompile: true   # (on merged files only) set by Phase 1 cleanup, cleared in same Phase 4 commit
```

### Eligibility for Processing

**Two-stage eligibility:**

**Stage 1 — State check** (determines if a file should be touched at all):
A file enters the enrichment pipeline if ALL of:
- It is in `raw/articles/x/`
- It has no `enriched` field in frontmatter, OR `enriched: failed`, OR `enriched: false`

Files with `enriched: true`, `enriched: skipped`, or `enriched: merged` are always skipped at this stage.

**Stage 2 — URL check** (determines if a file can actually be enriched):
For files passing Stage 1, attempt to parse a tweet URL from the frontmatter `source` field (frontmatter only — do NOT parse the body). If no parseable tweet URL is found, mark `enriched: skipped` immediately and remove from the candidate list. This is not an error — it means the file isn't a tweet-sourced article.

This two-stage approach ensures files without parseable URLs still get marked `skipped` (so they don't slow down future scans) while keeping the eligibility rules in one place.

### Staleness and Refresh

- `enriched_at` records when enrichment last ran (ISO 8601 timestamp)
- **v1 behavior:** Once `enriched: true`, the file is not re-enriched automatically. The `enriched_at` timestamp is informational.
- **Manual refresh:** User sets `enriched: false` to force re-enrichment on next compile. (Removing the field entirely also works — both make the file eligible.) The fenced markers (`<!-- enrich:thread -->`, `<!-- enrich:media -->`) ensure the old content is replaced cleanly, not duplicated.
- **Future:** A `enrich.staleness_days` config could trigger automatic re-enrichment for files older than N days. Not implemented in v1 but the `enriched_at` field enables it.

### Duplicate Thread Handling

When Smaug creates multiple raw files from tweets in the same self-thread (e.g., user bookmarked both tweet 1 and tweet 3 of a 4-tweet thread):

1. During Phase 0, after fetching thread data and walking the chain for each candidate, compute the `thread_dedup_key` (`"<root_id>:<leaf_id>"`) from the stitched chain. This uniquely identifies the stitched path.
2. **Within-run dedup:** Group selected candidates (both fresh and retries) by `thread_dedup_key`. If multiple produce the same key (they're on the same stitched path), select the canonical file: the one whose tweet ID matches the chain root, or the earliest tweet ID if none matches.
3. **Cross-run dedup:** Scan already-enriched files (`enriched: true`) for their `thread_dedup_key` field. If a selected candidate's key matches an existing file's, mark the candidate as merged pointing to that existing file. (Safe — the canonical already succeeded on a prior run.)
4. The canonical file gets full enrichment (thread stitching + media). Mark `enriched: true`.
5. **Finalize within-run dedup (after canonical succeeds):** Non-canonical files are marked merged ONLY after the canonical is confirmed `enriched: true`:
   ```yaml
   enriched: merged
   canonical_file: "raw/articles/x/<canonical-file>.md"   # vault-relative path
   thread_dedup_key: "<root_id>:<leaf_id>"                 # same key as canonical — required for Phase 1 identity validation
   ```
   If the canonical failed (`enriched: failed`), all duplicates in the group remain eligible for retry on the next run. This prevents losing source coverage when canonical enrichment fails.
6. **Phase 1 behavior:** Files with `enriched: merged` are skipped during Incremental Detection — UNLESS their `canonical_file` fails validation (in which case they are extracted normally as a live fallback).
7. **Pre-existing wiki articles:** Phase 1 validates `canonical_file` (structural + `thread_dedup_key` identity match), performs all-or-nothing cleanup, sets `needs_canonical_recompile: true` on the merged file, and enqueues the validated canonical. The flag is cleared in the same Phase 4 commit — a one-shot mechanism with no separate follow-up commit.

### Retry Behavior

- `enriched: failed` files are retried on the next `/kb compile` run
- Retries continue indefinitely — if auth is expired, the session-level preflight short-circuits all enrichment before any per-file work
- To permanently skip a file, the user manually sets `enriched: skipped` in its frontmatter
- Failure reasons are logged to console but not stored in frontmatter (keeps it clean)

---

## Configuration

### kb.yaml Additions

```yaml
integrations:
  smaug:
    path: /Users/dragon/smaug
  x:
    source: both
    raw_dir: raw/articles/x
    media_dir: media/x                   # NEW — outside raw/, prevents compile glob issues
    cron_interval: "0 */2 * * *"
    browser: chrome
    browser_profile: null                 # NEW — optional, for multi-profile Chrome/Firefox
    enabled: true
    enrich:                               # NEW — enrichment settings
      threads: true                       # stitch self-threads
      media: true                         # download all media types
      video_max_mb: 100                   # skip videos larger than this
      max_files_per_run: 20              # cap enrichment to avoid slow compiles
      api_delay_ms: 1000                 # delay between bird API calls
```

### Granular Control

Each enrichment type can be toggled independently:
- `enrich.threads: false` — skip thread stitching, still download media. When threads are disabled, media is downloaded only from the bookmarked tweet itself (not from other tweets in the thread, since the thread isn't fetched).
- `enrich.media: false` — skip media download, still stitch threads
- Both `false` — enrichment phase is effectively disabled

**Note:** When `enrich.threads: true` and `enrich.media: true` (default), the thread fetch (`bird thread`) provides both thread data and media metadata in one API call. When only media is enabled, a `bird read <tweet-id>` call (single tweet) suffices.

### Browser Profile Support

Bird CLI v0.8.0 supports `--chrome-profile`, `--chrome-profile-dir`, and `--firefox-profile` flags for machines with multiple browser profiles. The `browser_profile` config field maps to these:
- If `browser: chrome` and `browser_profile: "Profile 2"` → `--cookie-source chrome --chrome-profile "Profile 2"`
- If `browser: firefox` and `browser_profile: "work"` → `--cookie-source firefox --firefox-profile "work"`
- If `browser_profile: null` (default) → use the default profile (current behavior)

### Bird CLI Dependency

The enrichment phase requires bird CLI (`@steipete/bird`) installed globally. The `kb-x-setup` skill already installs it. If bird isn't available at compile time, the enrichment phase logs a warning and skips entirely — compile proceeds without enrichment.

---

## Compile Skill Modifications

The `kb` SKILL.md compile workflow gets a new phase inserted at the top:

```
Phase 0 (NEW): X Enrichment
  Config check (first, zero side effects):
    - Check kb.yaml for integrations.x.enabled && integrations.x.enrich
    - Path 0: if both threads and media false → exit immediately, no bird/auth/scan
  Guards (only if at least one toggle true):
    - Check bird CLI is available (bird --version)
    - Build <bird-auth> flags (--cookie-source + optional profile flags)
    - Auth preflight: bird whoami <bird-auth>. If fails → skip Phase 0 entirely.
  Scan:
    - Find enrichment candidates in raw/articles/x/ (frontmatter source URL only)
    - Apply max_files_per_run cap BEFORE any network calls (new files before retries)
  Path A (threads: true — default):
    - bird thread <id> --json --all <bird-auth> per candidate
    - Walk chain (UP + DOWN, branch-safe) → compute thread_dedup_key (root_id:leaf_id)
    - Cross-run dedup: compare thread_dedup_key to existing enriched files
    - Within-run dedup: group by thread_dedup_key, select canonicals (do NOT mark others merged yet)
    - Per canonical: stitch thread + download media + inject within fenced markers
    - Mark enriched: true with enriched_at. On failure → enriched: failed.
    - Finalize dedup: mark non-canonicals merged ONLY after canonical succeeds
  Path B (threads: false, media: true):
    - bird read <id> --json <bird-auth> per candidate (no thread fetch)
    - No dedup, no stitching — each file is independent
    - Write identity fields: thread_dedup_key, thread_root_id, thread_leaf_id (all = tweet ID)
    - Download media from bookmarked tweet only
    - Mark enriched: true with enriched_at
  Rate limit: api_delay_ms between calls
  mkdir -p media/x/ if any media downloaded

Phase 1: Incremental Detection (MODIFIED: state-derived merged cleanup)
    - Skip enriched:merged files from extraction
    - For each merged file: validate canonical_file (exists, enriched:true, under raw/articles/x/, thread_dedup_key match)
      - If invalid: warn, skip ALL cleanup, extract merged file normally as live fallback
      - If valid: set needs_canonical_recompile FIRST, then remove merged entries from _index.md, _sources.md, article sources:
    - Enqueue validated canonical for recompilation (process-list dedup)
    - Clear needs_canonical_recompile in same Phase 4 commit (one-shot, no separate follow-up)
Phase 2: Per-File Extraction (existing, unchanged)
Phase 3: Opus Orchestration (existing, unchanged)
Phase 4: Index Maintenance + commit (clears needs_canonical_recompile in same commit)
```

### Vault Cleanliness

Consistent with the existing vault cleanliness principle:
- `raw/articles/x/` — tweet markdown files (existing, unchanged)
- `media/x/` — downloaded media files (new, outside `raw/` to avoid compile glob)
- No scripts, logs, config, or state files in the KB directory
- All Smaug config/state stays in its own directory
- Bird CLI is a global install, not in the KB directory

---

## Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Scope | KB skill layer only | No Smaug fork maintenance burden |
| Media purpose | Vault preservation for humans | Compile pipeline is text-only; multimodal extraction is future work |
| Media types | Everything (images, videos, PDFs) | Maximum vault-level preservation |
| Media storage | `media/x/` (outside `raw/`) | Prevents compile glob from treating binaries as sources |
| Thread scope | Full self-thread (same author) | Captures complete thoughts across character-limit chains |
| Thread algorithm | `inReplyToStatusId` chain walk with `authorId` | Username filtering is broken for branched conversations; usernames are mutable |
| Thread pagination | `bird thread --all` | Default page size truncates longer threads |
| Trigger | Pre-compile (Phase 0) | Lazy — only runs when you compile. Phase 1 change: skip merged + synthetic deletion cleanup |
| Auth handling | Session-level `bird whoami` preflight + centralized `<bird-auth>` flags | Prevents N failing calls on expired auth; profile flags applied consistently |
| Mutation strategy | Fenced HTML comment markers (`<!-- enrich:thread -->`, `<!-- enrich:media -->`) | Enables idempotent re-enrichment without content duplication |
| Tracking | `enriched` field + `enriched_at` timestamp | `true`/`false`/`failed`/`skipped`/`merged` states; timestamp enables future staleness |
| Dedup key | Composite `root_id:leaf_id` (not `conversationId` or root alone) | Root alone fails on same-author branch splits; composite key identifies exact stitched path |
| Cross-run dedup | Check selected candidates' `thread_dedup_key` against existing files' | Prevents second canonical from same path across runs; retries participate equally |
| Two-path Phase 0 | Path A (threads) vs Path B (media-only) | Different API calls, dedup rules, and media scope per mode |
| `max_files_per_run` | Applied before any bird API calls | Prevents unbounded network work during large backlogs |
| Partial thread results | Mark `enriched: failed`, not `enriched: true` | Prevents permanently freezing truncated thread data |
| Partial media failure | Mark `enriched: true`, log failed URLs as text links | Thread work complete; user can `false` to retry media |
| Merged file wiki articles | State-derived cleanup + one-shot `needs_canonical_recompile` flag | Restart-safe; flag set before cleanup, cleared in same Phase 4 commit |
| Enrichment in wiki articles | v1: raw-source-level preservation only | Wiki articles benefit from richer source content but don't guarantee verbatim media/thread display |
| Rate limiting | Configurable delay + max 20 files/run | Avoids hammering X API and keeps compile responsive |
| Download safety | `curl -sfL` + magic-byte validation + detected extension | Prevents saving error pages; handles PNG/JPG correctly |
| Media naming | `<source_tweet_id>-<n>.<detected_ext>` | Per-tweet ID prevents collisions across thread; detected ext handles PNG |
| Browser profiles | Optional `browser_profile` config field | Supports multi-profile machines |
| URL parsing | Frontmatter `source` field only (no body parsing) | Prevents enriching manual files that merely mention tweet URLs |
| Failure mode | Non-blocking with preflight short-circuit | Never prevents compile from running |
| Merged after canonical | Mark duplicates `merged` only after canonical succeeds | Prevents losing source coverage when canonical enrichment fails |
| Downward walk scope | Walk down from bookmarked tweet only, not from ancestors | Prevents ancestor-level branches from interfering with descent below bookmarked tweet |
| `canonical_file` validity | Must exist under `raw/articles/x/` with `enriched: true` + matching `thread_dedup_key` | Structural + semantic check prevents both broken and wrong-target references |
