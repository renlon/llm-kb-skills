---
name: kb-notebooklm
user-invocable: true
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, Agent, AskUserQuestion
description: "Use when the user wants to generate NotebookLM content (podcasts, quizzes, reports, digests) from KB sources, or when user says 'podcast', 'quiz', 'flashcards', 'digest', 'research audio', or '/kb-notebooklm'. Also triggers on intent like 'create a podcast from my lessons', 'quiz me on recent lessons', 'summarize wiki changes'."
---

# kb-notebooklm Skill — Knowledge Base to NotebookLM Bridge

Bridge the user's MLL (My Lessons Learned) knowledge base with Google NotebookLM to automate content generation. This skill provides intelligent orchestration for creating podcasts, quizzes, digests, reports, and research audio from KB sources.

**Invocation:** `/kb-notebooklm <subcommand>` or natural language

**Executor:** Opus single-pass with Agent delegation for parallel workflows

## Overview

This skill operates in two layers:

1. **Content Pipeline:** Automatically selects relevant KB files (lessons, wiki articles, research reports) based on timestamps, topics, and content type
2. **Intelligent Orchestrator:** Routes requests to the global NotebookLM skill with proper notebook selection, source management, and state tracking

**Key Design Principles:**
- Builds on top of the global NotebookLM skill (does not duplicate API interaction)
- Single-writer concurrency model (one MLL operation at a time)
- All `notebooklm` CLI commands use explicit `--notebook <id>` or `-n <id>`, never `notebooklm use`
- State managed in `.notebooklm-state.yaml` (separate from kb.yaml)
- Configuration in `kb.yaml` under `integrations.notebooklm`

## Common Preamble (Prerequisites)

**MUST BE THE FIRST ACTION ON EVERY INVOCATION:**

1. **Check NotebookLM CLI installation:**
   ```bash
   which notebooklm
   ```
   If not found, report: "NotebookLM CLI not installed. Run: `pip install notebooklm-py`" and STOP.

2. **Check authentication:**
   ```bash
   notebooklm auth check --json
   ```
   If fails, report: "NotebookLM not authenticated. Run: `notebooklm login` and follow the prompts." and STOP.

3. **Read configuration:**
   ```bash
   # Read kb.yaml
   ```
   Check for `integrations.notebooklm` section. If missing or `enabled: false`, report: "NotebookLM integration not enabled in kb.yaml. Add:\n```yaml\nintegrations:\n  notebooklm:\n    enabled: true\n```" and STOP.

4. **Initialize or read state file:**
   ```bash
   # Read .notebooklm-state.yaml
   ```
   - If missing: Initialize empty state file with structure
   - If corrupt YAML: Backup to `.notebooklm-state.yaml.bak.<timestamp>` and re-initialize
   - If valid: Load state

## Subcommands

| Command | Description | File Selection |
|---------|-------------|----------------|
| `podcast [--topic X]` | Generate podcast from new lessons since last run | Lessons newer than `last_podcast` timestamp, optionally filtered by topic |
| `quiz [--topic X] [--difficulty D]` | Generate quiz/flashcards from lessons | Lessons newer than `last_quiz` timestamp, optionally filtered by topic |
| `digest` | Summarize wiki changes as podcast | Wiki articles changed since `last_digest` timestamp |
| `report [--topic X] [--format F]` | Generate topic-focused report | Lessons + wiki articles matching topic |
| `research-audio` | Convert research results to podcast | Latest `output_path/**/*.md` research reports |
| `cleanup [--days N]` | Delete old MLL notebooks | Notebooks older than N days (default from config) |
| `status` | Show last runs and active notebooks | Reads state file |

## Natural Language Routing

When invoked via natural language, route to subcommands based on keywords:

| Keywords | Routes To | Example |
|----------|-----------|---------|
| "podcast", "audio", "listen" | `podcast` | "make a podcast about attention" → `podcast --topic attention` |
| "quiz", "test", "flashcard" | `quiz` | "quiz me on this week's lessons" → `quiz` |
| "digest", "summary", "changes", "what's new" | `digest` | "what's changed in the wiki?" → `digest` |
| "report", "briefing", "study guide" | `report` | "generate a study guide about quantization" → `report --topic quantization --format study-guide` |
| "research", "findings" | `research-audio` | "make a podcast from my research" → `research-audio` |
| "clean", "delete old" | `cleanup` | "clean up old notebooks" → `cleanup` |
| "status", "what's running" | `status` | "what's the status?" → `status` |

**Topic Extraction Rules:**
- Text after "about", "for", "regarding" becomes `--topic` parameter
- "on" is EXCLUDED as a topic trigger (too many false positives)
- Examples:
  - "podcast about attention" → `--topic attention`
  - "quiz for quantum mechanics" → `--topic "quantum mechanics"`
  - "podcast on Monday" → NO topic (false positive)

## CLI Command Convention

**ALWAYS** use explicit notebook specification:
```bash
# CORRECT — flag comes after the command
notebooklm source add file.md --notebook <id>
notebooklm generate audio "instructions" -n <id>

# NEVER use
notebooklm use <id>  # WRONG — writes to shared global context
```

This ensures stateless operation and prevents cross-session contamination.

## State Management

_(Section to be populated in Task 2)_

## Deduplication

_(Section to be populated in Task 3)_

## Workflows

_(Section to be populated in Task 4)_

### Podcast Workflow

_(To be populated in Task 4)_

### Quiz Workflow

_(To be populated in Task 4)_

### Digest Workflow

_(To be populated in Task 4)_

### Report Workflow

_(To be populated in Task 4)_

### Research-Audio Workflow

_(To be populated in Task 4)_

### Cleanup Workflow

_(To be populated in Task 4)_

### Status Workflow

_(To be populated in Task 4)_

## Error Handling

_(Section to be populated in Task 5)_

## Testing

_(Section to be populated in Task 6)_
