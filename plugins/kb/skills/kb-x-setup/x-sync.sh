#!/bin/bash
set -euo pipefail

# ──────────────────────────────────────────────────────
# x-sync.sh — KB X/Twitter Bridge Script
# Fetches likes/bookmarks via Smaug, normalizes output,
# and syncs to raw/articles/x/ for kb compile.
#
# Runs on cron. Reads config from kb.yaml at runtime.
# Installed by /kb-x-setup skill.
# ──────────────────────────────────────────────────────

KB_ROOT="$(cd "$(dirname "$0")" && pwd)"
KBYAML="$KB_ROOT/kb.yaml"
LOG_DIR="$KB_ROOT/logs"
LOG_FILE="$LOG_DIR/x-sync.log"
STATUS_FILE="$KB_ROOT/x-sync-status.json"

mkdir -p "$LOG_DIR"

# ── Logging ─────────────────────────────────────────

log() {
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" >> "$LOG_FILE"
}

# ── YAML helpers (flat key extraction, no parser needed) ─

yaml_get() {
  local file="$1" key="$2"
  grep -E "^[[:space:]]+${key}:" "$file" 2>/dev/null \
    | head -1 \
    | sed 's/^[^:]*:[[:space:]]*//' \
    | tr -d '"' \
    | tr -d "'" \
    | sed 's/[[:space:]]*#.*//' \
    | sed 's/[[:space:]]*$//'
}

# ── Config ──────────────────────────────────────────

if [ ! -f "$KBYAML" ]; then
  log "ERROR: kb.yaml not found at $KBYAML"
  exit 1
fi

ENABLED=$(yaml_get "$KBYAML" "enabled")
if [ "$ENABLED" = "false" ]; then
  log "X sync disabled, exiting"
  exit 0
fi

SMAUG_PATH=$(yaml_get "$KBYAML" "path")
SOURCE=$(yaml_get "$KBYAML" "source")
RAW_DIR=$(yaml_get "$KBYAML" "raw_dir")

if [ -z "$SMAUG_PATH" ] || [ ! -d "$SMAUG_PATH" ]; then
  log "ERROR: Smaug path not configured or missing: $SMAUG_PATH"
  exit 1
fi

TARGET_DIR="$KB_ROOT/$RAW_DIR"
mkdir -p "$TARGET_DIR"

# ── Fetch via Smaug ────────────────────────────────

log "Starting fetch (source=$SOURCE)"
cd "$SMAUG_PATH"

if ! npx smaug fetch --source "$SOURCE" 2>> "$LOG_FILE"; then
  log "ERROR: Smaug fetch failed (likely auth)"
  cat > "$STATUS_FILE" <<EOJSON
{"status": "auth_error", "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"}
EOJSON
  exit 1
fi

# Process fetched tweets (AI categorization, link expansion)
npx smaug process 2>> "$LOG_FILE" || true

# ── Slug generation ─────────────────────────────────

make_slug() {
  local text="$1"
  echo "$text" \
    | tr '[:upper:]' '[:lower:]' \
    | sed 's|https\{0,1\}://[^ ]*||g' \
    | sed 's/@[A-Za-z0-9_]*//g' \
    | sed 's/[^a-z0-9 ]//g' \
    | tr -s ' ' \
    | sed 's/^ //' \
    | awk '{for(i=1;i<=8&&i<=NF;i++) printf "%s-",$i; print ""}' \
    | sed 's/-$//' \
    | cut -c1-60
}

# ── Process Smaug output ───────────────────────────

SYNCED=0
SKIPPED=0

process_file() {
  local file="$1"

  # Extract tweet URL — look for x.com or twitter.com status URLs
  local tweet_url
  tweet_url=$(grep -oE 'https://(x\.com|twitter\.com)/[^/]+/status/[0-9]+' "$file" | head -1)
  if [ -z "$tweet_url" ]; then
    log "SKIP: No tweet URL found in $(basename "$file")"
    return
  fi

  # Extract tweet ID from URL
  local tweet_id
  tweet_id=$(echo "$tweet_url" | grep -oE '[0-9]+$')

  # Primary dedup: check if this tweet ID already exists in target dir
  if grep -rql "tweet_id: \"$tweet_id\"" "$TARGET_DIR" 2>/dev/null; then
    SKIPPED=$((SKIPPED + 1))
    return
  fi
  if ls "$TARGET_DIR"/*-"$tweet_id".md 2>/dev/null | grep -q .; then
    SKIPPED=$((SKIPPED + 1))
    return
  fi

  # Extract author from URL
  local author
  author=$(echo "$tweet_url" | sed 's|.*/\([^/]*\)/status/.*|\1|' | tr '[:upper:]' '[:lower:]')

  # Extract tweet date from frontmatter or file content
  # Try frontmatter date fields first, fall back to today
  local tweet_date
  tweet_date=$(grep -E '^(date|created|tweet_date):' "$file" 2>/dev/null \
    | head -1 \
    | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}' \
    | head -1)
  if [ -z "$tweet_date" ]; then
    tweet_date=$(date +%Y-%m-%d)
  fi

  # Extract title/text for slug — try frontmatter title, then first heading, then first text line
  local tweet_text
  tweet_text=$(grep -E '^title:' "$file" 2>/dev/null | head -1 | sed 's/^title:[[:space:]]*//' | tr -d '"' | tr -d "'")
  if [ -z "$tweet_text" ]; then
    tweet_text=$(grep -E '^#' "$file" 2>/dev/null | head -1 | sed 's/^#* *//')
  fi
  if [ -z "$tweet_text" ]; then
    tweet_text=$(grep -E '^>' "$file" 2>/dev/null | head -1 | sed 's/^> *//')
  fi
  if [ -z "$tweet_text" ]; then
    tweet_text="tweet-$tweet_id"
  fi

  # Determine capture type from Smaug metadata or default to "like"
  local capture_type="like"
  if grep -qi 'bookmark' "$file" 2>/dev/null; then
    capture_type="bm"
  fi
  local tag_type="x-$capture_type"

  # Extract existing tags from Smaug's frontmatter (if any)
  local smaug_tags
  smaug_tags=$(grep -E '^tags:' "$file" 2>/dev/null | head -1 | sed 's/^tags:[[:space:]]*//' | tr -d '[]"' | tr -d "'")

  # Build tags list
  local tags="$tag_type"
  if [ -n "$smaug_tags" ]; then
    tags="$tag_type, $smaug_tags"
  fi

  # Generate slug
  local slug
  slug=$(make_slug "$tweet_text")
  if [ -z "$slug" ]; then
    slug="tweet"
  fi

  # Build filename
  local filename="${tweet_date}-x-${capture_type}-@${author}-${slug}.md"

  # Handle slug collision (different tweet, same slug)
  if [ -f "$TARGET_DIR/$filename" ]; then
    filename="${tweet_date}-x-${capture_type}-@${author}-${slug}-${tweet_id}.md"
  fi

  # Build title
  local title="@${author} - $(echo "$tweet_text" | cut -c1-80)"

  # Extract body content (everything after frontmatter)
  local body=""
  local in_frontmatter=false
  local frontmatter_done=false
  while IFS= read -r line; do
    if [ "$frontmatter_done" = true ]; then
      body="${body}${line}
"
    elif [ "$line" = "---" ] && [ "$in_frontmatter" = false ]; then
      in_frontmatter=true
    elif [ "$line" = "---" ] && [ "$in_frontmatter" = true ]; then
      frontmatter_done=true
    fi
  done < "$file"

  # If no frontmatter found, use entire file as body
  if [ "$frontmatter_done" = false ]; then
    body=$(cat "$file")
  fi

  # Write normalized file
  cat > "$TARGET_DIR/$filename" <<EOMD
---
title: "$title"
aliases: []
tags: [$tags]
author: "$author"
tweet_id: "$tweet_id"
tweet_date: $tweet_date
capture_type: $capture_type
source_url: "$tweet_url"
created: $tweet_date
updated: $(date +%Y-%m-%d)
---

# $title

$body
EOMD

  SYNCED=$((SYNCED + 1))
  log "Synced: $filename"
}

# Process all files from Smaug's knowledge output
for src_dir in "$SMAUG_PATH/knowledge/articles" "$SMAUG_PATH/knowledge/tools"; do
  [ -d "$src_dir" ] || continue

  for file in "$src_dir"/*.md; do
    [ -f "$file" ] || continue
    process_file "$file"
  done
done

# Move processed files to prevent re-processing on next run
ARCHIVE_DIR="$SMAUG_PATH/knowledge/.processed"
mkdir -p "$ARCHIVE_DIR"
for src_dir in "$SMAUG_PATH/knowledge/articles" "$SMAUG_PATH/knowledge/tools"; do
  [ -d "$src_dir" ] || continue
  for file in "$src_dir"/*.md; do
    [ -f "$file" ] || continue
    mv "$file" "$ARCHIVE_DIR/" 2>/dev/null || true
  done
done

# ── Status update ───────────────────────────────────

cat > "$STATUS_FILE" <<EOJSON
{"status": "ok", "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)", "tweets_synced": $SYNCED, "tweets_skipped": $SKIPPED}
EOJSON

log "Done: synced=$SYNCED skipped=$SKIPPED"
