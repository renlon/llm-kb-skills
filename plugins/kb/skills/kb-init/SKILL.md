---
name: kb-init
description: "Use when setting up a new knowledge base, bootstrapping an Obsidian vault, or when user says 'init kb', 'new knowledge base', 'create kb', or 'setup vault'. Triggers on any request to initialize or scaffold a knowledge base project."
---

## Overview

One-time (or re-runnable) setup that bootstraps a knowledge base project as an Obsidian vault.

## Prerequisites

Obsidian must be installed. Recommended plugins: **Web Clipper**, **Marp Slides**, **Dataview**.

## Flow

### 1. Vault Setup

Ask: create a new vault or use an existing directory? If new, scaffold `.obsidian/`. If existing, verify it exists.

### 2. Source Gathering Strategy

Ask how the user wants to get raw data in:

- **Self-serve** -- User drops files in `raw/`. Per-type guidance:
  - Web articles: Obsidian Web Clipper extension -> `raw/articles/`
  - Academic papers (PDF): Download to `raw/papers/`
  - GitHub repos: Clone/snapshot to `raw/repos/`
  - Local markdown/text: Copy to `raw/notes/`
  - Images/diagrams: Place in `raw/images/`
  - YouTube transcripts: Transcript tool -> `raw/transcripts/`
  - Datasets (CSV, JSON): Place in `raw/datasets/`
- **Assisted** -- Claude fetches via WebFetch, Bash (clone repos, download PDFs, pull transcripts)
- **Mixed** -- Some of each

### 3. Output Format Preferences

Ask which formats the user wants: markdown (always on), Marp slides, matplotlib charts, HTML, CSV, Excalidraw, other. Use an extensible pattern so new formats can be added later.

### 4. Maintenance Cadence

Inform about options:
- Daily/hourly: `/loop` (e.g., `/loop 1d kb lint`)
- Weekly/monthly: `/schedule`
- Manual: just ask anytime

### 5. Generate `kb.yaml`

Write `kb.yaml` at project root with paths, `output_formats`, and obsidian config.

### 6. Scaffold Directories

Create: `raw/articles/`, `raw/papers/`, `raw/repos/`, `raw/notes/`, `raw/images/`, `raw/transcripts/`, `raw/datasets/`, `wiki/`, `output/`. Plus `.obsidian/` if new vault.

### 7. Write Project Files

- `CLAUDE.md` -- project instructions for future sessions
- `README.md` -- repo docs with prerequisites, setup, workflows, directory structure, and attribution for research skills

### 8. Next Steps Guidance

Tell user what to do next: add sources, compile, and list available workflows (`compile`, `query`, `lint`, `evolve`).

## Common Mistakes

- Do not overwrite an existing `kb.yaml` without confirming with the user first.
- Do not skip the source-gathering strategy question -- it determines the entire workflow.
- Do not create `.obsidian/` inside a directory that is already an Obsidian vault.
- Do not assume output formats -- always ask the user.
