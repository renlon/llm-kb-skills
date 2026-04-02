# LLM Knowledge Bases

A system of Claude Code skills that turn raw source documents into a living, LLM-maintained personal knowledge base, viewable as an Obsidian wiki.

Raw data from various sources is collected, compiled by an LLM into a `.md` wiki, then operated on by various workflows to do Q&A, health checks, and self-improvement. You rarely edit the wiki manually -- it's the domain of the LLM.

## Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (CLI)
- [Obsidian](https://obsidian.md)
- Recommended Obsidian plugins: Web Clipper, Marp Slides, Dataview

## Installation

In Claude Code, run:

```
/plugin marketplace add rvk7895/llm-knowledge-bases
/plugin install kb@llm-knowledge-bases
```

That's it. All skills (`kb-init`, `kb`, `research`, `research-deep`, etc.) are installed as a single plugin.

## Quick Start

1. Install the skills using one of the methods above.
2. Run `/kb-init` to bootstrap a new knowledge base.
3. Add raw sources to `raw/`.
4. Ask Claude to "compile the wiki".

## Available Workflows

- **Compile** -- Incrementally turns raw sources into wiki articles. Processes each source, extracts key information, and produces interlinked Obsidian-compatible markdown.
- **Query** -- Q&A at three depth levels: Quick (instant lookup), Standard (cross-referenced answer), and Deep (multi-agent research pipeline).
- **Lint** -- Health checks for broken links, orphan pages, tag consistency, and structural issues across the wiki.
- **Evolve** -- Suggests improvements to existing articles, finds gaps in coverage, and surfaces new connections between topics.

## Supported Source Types

Web articles, academic papers, GitHub repos, local markdown, images, YouTube transcripts, datasets.

## Directory Structure (after running kb-init)

```
raw/           -- Raw source documents
wiki/          -- Compiled wiki (Obsidian vault)
output/        -- Query results, reports, visualizations
kb.yaml        -- Configuration
CLAUDE.md      -- Project instructions for Claude
```

## Research Skills Attribution

The deep research pipeline (used for Deep query depth) is based on skills originally authored by [Weizhena](https://github.com/Weizhena/Deep-Research-skills).
