# LLM Knowledge Bases

A Claude Code plugin that turns raw research material into an LLM-maintained Obsidian wiki -- inspired by [Andrej Karpathy's description](https://x.com/karpathy/status/2039805659525644595) of using LLMs as knowledge compilers rather than just code manipulators.

You drop source material into `raw/`, run a single command, and Claude handles the rest: compiling interlinked wiki articles, maintaining indexes and backlinks, answering complex questions at multiple depth levels, and continuously improving the knowledge base over time.

The LLM owns the wiki. You rarely edit it manually -- just explore in Obsidian and keep feeding it raw data.

## How It Works

1. **Ingest** -- Raw documents (articles, papers, repos, YouTube transcripts, images, datasets) go into `raw/`
2. **Compile** -- Claude builds a structured Obsidian vault with summaries, backlinks, concept articles, and auto-generated indexes
3. **Query** -- Three depth levels:
   - **Quick** -- Answers from wiki indexes and summaries alone
   - **Standard** -- Cross-references the full wiki, supplements with web search
   - **Deep** -- Multi-agent research pipeline with parallel web search agents
4. **Output** -- Markdown reports, Marp slides, matplotlib charts -- saved to `output/` and optionally filed back into the wiki
5. **Maintain** -- Automated health checks (broken links, orphans, inconsistencies) and suggestions for new articles and connections

## Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (CLI), installed and authenticated
- [Obsidian](https://obsidian.md)

Obsidian plugins (Dataview, Obsidian Git, etc.) are installed automatically by the setup script during `/kb-init`.

## Installation

In Claude Code, run:

```
/plugin marketplace add renlon/llm-kb-skills
/plugin install kb@llm-kb-skills
```

All skills are installed as a single plugin.

## Quick Start

```bash
# Initialize a new knowledge base
/kb-init

# Add sources to raw/, then compile the wiki
/kb compile

# Query the knowledge base
/kb query

# Run a health check
/kb lint

# Deep multi-agent research on a topic
/research <topic>
/research-deep
```

## Available Skills

| Skill | Purpose |
|-------|---------|
| `kb-init` | One-time setup: scaffolds directories, generates config, installs Obsidian plugins |
| `kb` | Main skill — compile raw sources into wiki articles, query the KB at three depth levels, lint for health issues, evolve with improvement suggestions |
| `kb-arc` | Archive session Q&A into lesson files with intelligent merge, date rotation, and auto git-push |
| `kb-notebooklm` | Bridge KB with Google NotebookLM — generate podcasts, quizzes, digests, reports, and research audio from lessons and wiki |
| `research` | Generate a structured research outline (items + fields) for a topic, supplemented by web search |
| `research-deep` | Launch parallel agents for deep per-item research, outputting validated JSON results |
| `research-add-fields` | Add field definitions to an existing research outline |
| `research-add-items` | Add research targets to an existing outline |
| `research-report` | Compile deep research JSON results into a formatted markdown report |

## Prompt Templates

Each skill stores its prompt templates as separate files under a co-located `prompts/` directory, version-controlled alongside the skill.

| Skill | Prompt File | Description |
|-------|-------------|-------------|
| `kb` | `prompts/article-default.md` | Reference-style wiki article structure |
| `kb` | `prompts/article-tutorial.md` | Tutorial-style wiki article with easy-to-hard hierarchy |
| `kb-arc` | `prompts/lesson-format.md` | Session lesson file with technical summary and Q&A transcript |
| `kb-notebooklm` | `prompts/podcast-tutor.md` | Podcast audio instructions — "Technical Lead & Mentor" teaching methodology |
| `research` | `prompts/web-search-agent.md` | Web search agent prompt for supplementing research items and fields |
| `research` | `prompts/web-search-agent-example.md` | One-shot example for web search agent (AI Coding topic) |
| `research-deep` | `prompts/deep-research-agent.md` | Deep research agent prompt for per-item JSON output |
| `research-deep` | `prompts/deep-research-agent-example.md` | One-shot example for deep research agent (GitHub Copilot) |

All prompt files live under `plugins/kb/skills/<skill-name>/prompts/`.

## Directory Structure (after `/kb-init`)

```
raw/           -- Raw source documents
wiki/          -- LLM-compiled Obsidian vault
output/        -- Query results, slides, charts, reports
kb.yaml        -- Configuration
CLAUDE.md      -- Project instructions for Claude
```

## X/Twitter Integration (Optional)

To ingest tweets, threads, and bookmarks from X, install [Smaug](https://github.com/alexknowshtml/smaug):

```bash
npm install -g @steipete/bird
git clone https://github.com/alexknowshtml/smaug && cd smaug && npm install
npx smaug setup  # configures X session cookies
```

Once configured, paste any `x.com` link and the kb skill will fetch and compile it automatically. Without Smaug, you can still add X content by pasting tweet text directly or using [Thread Reader App](https://threadreaderapp.com) for threads.

**Note:** Smaug uses X session cookies for read-only access to your own data. This is not officially supported by X's TOS. Practical risk for personal use is very low, but be aware.

## Attribution

- [rvk7895](https://github.com/rvk7895/llm-knowledge-bases) -- Original codebase this project was forked from
- [Andrej Karpathy](https://x.com/karpathy/status/2039805659525644595) -- Original vision for LLM-maintained knowledge bases
- [Weizhena](https://github.com/Weizhena/Deep-Research-skills) -- Deep Research skills adapted for the research pipeline
