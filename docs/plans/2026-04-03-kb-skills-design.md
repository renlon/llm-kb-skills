# LLM Knowledge Base Skills -- Design Document

**Date:** 2026-04-03

**Goal:** Build two Claude Code skills that turn a directory of raw source documents into a living, LLM-maintained Obsidian wiki with Q&A, health checks, and self-improvement capabilities.

**Architecture:** Two skills -- `kb-init` for one-time setup, `kb` for four ongoing workflows (compile, query, lint, evolve). All workflows are opus-orchestrated with model-aware subagent dispatch. The wiki is an Obsidian vault with native formatting.

---

## Skill 1: `kb-init`

**Purpose:** One-time (or re-runnable) setup that bootstraps a knowledge base project as an Obsidian vault.

### Flow

1. **Prerequisites check** -- Inform user Obsidian must be installed. Ask if creating a new vault or using an existing one.

2. **Source gathering** -- Ask: "How do you want to get raw data in?"
   - **Self-serve** -- User drops files in `raw/`. Skill provides per-type guidance (Web Clipper setup for articles, PDF downloads, repo snapshots, YouTube transcripts, dataset placement, image downloads).
   - **Assisted** -- Claude fetches via `WebFetch`, `Bash` (clone repos, download PDFs, pull transcripts).
   - **Mixed** -- Some of each.
   - Supported source types: web articles, academic papers (PDF), GitHub repos/code, local markdown/text files, images/diagrams, YouTube transcripts, datasets (CSV, JSON, etc.).

3. **Output preferences** -- Ask which output formats the user wants: markdown, Marp slides, matplotlib charts, HTML, CSV, Excalidraw, or others. Extensible -- the skill teaches Claude the pattern for rendering into any format.

4. **Maintenance cadence** -- Inform user about health check scheduling:
   - For daily/hourly: use `/loop` (e.g. `/loop 1d /kb lint`)
   - For weekly/monthly: use `/schedule`
   - Or run manually anytime

5. **Generate `kb.yaml`** at project root:
   ```yaml
   name: "My Knowledge Base"
   paths:
     raw: raw/
     wiki: wiki/
     output: output/
   output_formats:
     - markdown
     - marp
   obsidian:
     wikilinks: true
     recommended_plugins:
       - obsidian-web-clipper
       - obsidian-marp-slides
       - dataview
   ```

6. **Scaffold directories** + `.obsidian/` config if new vault.

7. **Write project-level `CLAUDE.md`** so future Claude sessions know this is a KB repo and how to operate on it.

8. **Write `README.md`** -- Proper repo README explaining the project, setup, prerequisites, and usage.

9. **Next steps guidance** -- After scaffolding, inform the user:
   - How to add raw sources (drop files in `raw/`, use Web Clipper, or ask Claude to fetch)
   - "Once you have sources in `raw/`, ask me to compile the wiki" (invoke the `kb` skill)
   - Remind about the four workflows: **compile**, **query**, **lint**, **evolve**
   - If maintenance cadence was set, confirm it's active

---

## Skill 2: `kb`

**Purpose:** The main operating skill with four workflows for maintaining and querying the knowledge base.

### Obsidian-Native Formatting

All wiki output must use Obsidian-compatible syntax:
- YAML frontmatter delimited by `---`
- `[[wikilinks]]` for all internal links (not markdown-style links)
- `[[wikilinks|display text]]` when the display name differs
- Tags as `tags: [concept, topic]` in frontmatter (Obsidian reads these)
- Aliases in frontmatter so alternate names resolve to the same article
- Embeds for images: `![[image-name.png]]`
- Standard markdown for everything else (headings, lists, code blocks)

### Model Strategy

Opus orchestrates every workflow, delegates volume work to cheaper models, and always verifies before anything gets written to the wiki.

| Task | Executor | Verifier |
|------|----------|----------|
| Index scanning, link checking, file diffing | **haiku** subagents | -- (mechanical) |
| Summarizing individual sources | **haiku** subagents | **opus** spot-checks |
| Wiki article writing | **sonnet** subagents | **opus** reviews before committing |
| Deep research (`/research-deep`) | **sonnet** subagents | **opus** orchestrates + verifies |
| Research synthesis / final reports | **opus** | -- |
| Lint issue detection | **sonnet** subagents | **opus** prioritizes + filters false positives |
| Query answering | **opus** | -- |
| Consistency checks across articles | **sonnet** subagents | **opus** makes final judgment |

### Workflow 1: Compile

**Trigger:** User adds new files to `raw/` and asks to compile, or says "update the wiki."

**Incremental detection:**
- The skill maintains `wiki/_index.md` listing every raw source and its last-compiled hash/timestamp.
- On compile, Claude diffs `raw/` against the index to find new/changed/deleted files.
- Only processes what's changed.

**Per-file compilation:**
1. Read the raw source
2. Determine type (article, paper, repo, dataset, image, transcript, etc.)
3. Extract key concepts, claims, entities, relationships
4. For each new concept -- create a wiki article
5. For each existing concept -- update/enrich with new information
6. Add source backlinks (`[[Sources/source-name]]`)
7. Auto-categorize into folder structure (Claude decides and evolves categories organically)

**Wiki article format:**
```markdown
---
title: Attention Mechanisms
aliases: [self-attention, multi-head attention]
tags: [concept]
sources: [raw/papers/vaswani-2017.pdf, raw/articles/attention-explained.md]
last_updated: 2026-04-03
---

# Attention Mechanisms

Article body with [[wikilinks]] to related concepts...

## Sources
- [[Sources/vaswani-2017]] - Original transformer paper
- [[Sources/attention-explained]] - Blog walkthrough
```

**Index maintenance:**
- `wiki/_index.md` -- master list of all articles with one-line summaries (Claude reads this first for Q&A)
- `wiki/_sources.md` -- all raw sources and which articles they contributed to
- `wiki/_categories.md` -- auto-maintained category tree

### Workflow 2: Query

**Trigger:** User asks a question against the wiki.

**Step 1: Ask query depth:**
- **Quick** -- Wiki-only. Read indexes, find relevant articles, synthesize answer. Fast, no external calls.
- **Standard** -- Wiki + web search. Read wiki first, supplement gaps with `WebSearch`/`WebFetch`.
- **Deep** -- Full research pipeline. Invoke `/research` skill to generate outline, then `/research-deep` dispatches sonnet subagents for comprehensive structured research, opus orchestrates and verifies. Best for big open-ended questions.

**Step 2:** Execute at chosen depth.

**Step 3:** Render output in user's preferred format from `kb.yaml` (markdown, Marp, matplotlib, etc.), saved to `output/`.

**Step 4: Smart suggest filing** -- If the output contains genuinely new knowledge (especially from Standard/Deep searches that pulled in external data), suggest filing it back into the wiki. If yes, run the compile workflow on the new material.

### Workflow 3: Lint

**Trigger:** User says "health check," "lint the wiki," or runs via `/loop`/`/schedule`.

**Checks (via sonnet subagents, opus-verified):**
1. **Broken links** -- `[[wikilinks]]` pointing to non-existent articles
2. **Orphan articles** -- Articles with no inbound links
3. **Orphan sources** -- Files in `raw/` never compiled into the wiki
4. **Stale articles** -- Source material changed since last compile
5. **Consistency** -- Conflicting claims across articles
6. **Missing backlinks** -- References that should be bidirectional but aren't
7. **Sparse articles** -- Articles below a content threshold

**Output:** Markdown report at `output/lint-YYYY-MM-DD.md`, issues grouped by severity. Suggests specific fixes Claude can make if user approves.

### Workflow 4: Evolve

**Trigger:** User says "evolve the wiki," "suggest improvements," or "what's missing."

**Flow (opus-orchestrated):**
1. Read wiki indexes and category structure
2. Dispatch sonnet subagents to analyze article clusters for:
   - **Gaps** -- concepts referenced but never given their own article
   - **Connections** -- articles in different categories with unexplored relationships
   - **Missing data** -- claims that could be filled/verified with web search
   - **Questions** -- interesting questions the wiki could answer but doesn't yet
3. Opus collates, deduplicates, ranks by value
4. Present ranked suggestions to user
5. User picks which to pursue -- Claude executes (compile new articles, run queries, fill gaps)

---

## Research Skills Integration

The `/research`, `/research-deep`, `/research-add-fields`, `/research-add-items`, and `/research-report` skills are copied into this repo to power the Deep query workflow. These skills are used with attribution to their original author (see README).

---

## Config File: `kb.yaml`

Lives at project root. Generated by `kb-init`, read by `kb`.

```yaml
name: "My Knowledge Base"
paths:
  raw: raw/
  wiki: wiki/
  output: output/
output_formats:
  - markdown
  - marp
obsidian:
  wikilinks: true
  recommended_plugins:
    - obsidian-web-clipper
    - obsidian-marp-slides
    - dataview
```

---

## Repository Structure

```
llm-knowledge-bases/
  kb.yaml                  # Config (generated by kb-init)
  README.md                # Repo documentation
  CLAUDE.md                # Project-level Claude instructions
  .obsidian/               # Obsidian vault config
  raw/                     # Raw source documents
  wiki/                    # Compiled wiki (Obsidian vault content)
    _index.md              # Master article index
    _sources.md            # Source tracking
    _categories.md         # Category tree
  output/                  # Query results, reports, visualizations
  skills/                  # Claude Code skills
    kb-init/
      SKILL.md
    kb/
      SKILL.md
    research/              # Copied research skills (with attribution)
      ...
  docs/
    plans/                 # Design and implementation plans
```
