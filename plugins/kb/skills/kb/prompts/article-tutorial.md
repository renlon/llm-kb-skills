---
title: "Concept Name"
aliases: [alternate name, abbreviation]
tags: [domain, topic]
article_format: tutorial
diagram: false
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

**Technical terms, acronyms, and proper nouns — MANDATORY treatment:** Assume the reader has ZERO prior context about any acronym, proper noun, library name, framework name, algorithm name, or piece of jargon you introduce. Every single time one appears -- including the first mention AND any reintroduction after a gap -- do BOTH of the following before moving on:

1. **Spell out the acronym in full.** Don't just write "RAG" -- write "RAG (Retrieval-Augmented Generation)". Don't just write "LLM" -- write "LLM (Large Language Model, 大语言模型)". This applies to every acronym no matter how common (LLM, RAG, MoE, RLHF, DPO, LoRA, PEFT, CoT, KV cache, TPU, GPU, CUDA, API, SDK, etc.). Include the Chinese translation when one is in common use.
2. **Explain what it means in plain language.** One or two sentences on what the thing actually is, what problem it solves, or what role it plays -- not just the expansion, the meaning.
3. **Do not chain unexplained terms.** If a definition itself references another unfamiliar term, define that term too before continuing. Build vocabulary one layer at a time.
4. **Proper nouns (product names, library names, paper titles, people) get the same treatment** -- say what it is, who made it, and why it matters on first mention.
5. **When in doubt, over-explain rather than under-explain.** A reader who already knows the term is not harmed by one extra line of refresher; a reader who doesn't know it is lost without it.

## Technical Deep-Dive

Transition into mechanics: architecture, algorithms, implementation details. Keep it accessible but rigorous. Use code blocks, diagrams (via `![[image.png]]`), and worked examples where appropriate.

Apply the technical-terms rule from Foundational Context rigorously in this section as well -- before introducing any new technical term, stop and spell out its full form and explain what it means. Never assume the reader already knows a term, no matter how standard it seems in the domain. If a deep-dive depends on multiple technical terms, build them up one by one, define each, then combine them.

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
