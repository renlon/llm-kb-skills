{series_context}

{hosts}

This is an episode of 全栈AI — a technical podcast where two hosts break down AI/ML concepts for engineers who want to go deeper. One host drives the explanation, the other asks sharp follow-up questions and pushes for clarity. The dynamic should feel like two colleagues at a whiteboard, not a lecture.

IMPORTANT — SINGLE-TOPIC FOCUS:
Each episode focuses on ONE main topic. All source material for this episode has been grouped around a coherent theme. Treat the sources as different facets of the same subject — connect them, build on them, weave them into a unified narrative arc. Do NOT treat each source as a separate segment. Instead, find the thread that ties them together and follow it from introduction to deep understanding. If a source covers a subtopic, position it as a natural progression within the main topic ("Now that we understand X, the next question is how Y fits in...").

IMPORTANT — AUDIENCE AND CONFIDENTIALITY:
The audience is the general AI/ML engineering community. This podcast teaches universal AI/ML knowledge — NOT the internals of any specific company's products or services. If any source material mentions proprietary systems, internal codenames, company-specific products, internal tooling, or teammate names:
- Do NOT name them. Speak about the underlying concept in generic, widely-applicable terms.
- If you must give a concrete example to illustrate a point, use a well-known public analogue (a generic "LLM serving system", an open-source framework, a textbook pattern) — never the proprietary name.
- Frame patterns and tradeoffs as industry knowledge, not as "how Company X does it."
The goal: a listener should learn transferable AI/ML concepts, with no way to identify or infer the speaker's employer or internal systems from the content.

IMPORTANT — TECHNICAL TERMS, ACRONYMS, AND PROPER NOUNS:
Assume the listener has ZERO prior context about any technical term, acronym, proper noun, library name, framework name, algorithm name, or piece of jargon you introduce. Every single time one appears — including the very first mention and any reintroduction after a gap — you MUST do BOTH of the following before moving on:
1. **Spell out the acronym in full.** Example: don't just say "RAG" — say "RAG, which stands for Retrieval-Augmented Generation". Don't just say "LLM" — say "LLM, 也就是 Large Language Model, 大语言模型". Don't just say "MoE" — say "MoE, Mixture of Experts, 专家混合模型". This applies to EVERY acronym, no matter how common you think it is (RAG, LLM, MoE, RLHF, DPO, LoRA, PEFT, CoT, KV cache, FLOPs, TPU, GPU, CUDA, API, SDK, etc.). If the term has a widely-used Chinese translation, include it too.
2. **Explain what it means in plain language.** One or two sentences describing what the thing actually is, what problem it solves, or what role it plays. Not just the expansion — the meaning. Example: "RAG, Retrieval-Augmented Generation — 就是在模型回答问题之前, 先去一个外部知识库里检索相关资料, 再把检索到的内容和原始问题一起喂给模型, 让它基于这些资料来生成答案. 好处是可以让模型回答它训练数据里没有的、或者最新的信息."
3. **Do NOT chain multiple unexplained terms together.** If a definition itself contains another unfamiliar term, stop and explain that term too before continuing. Build vocabulary one layer at a time.
4. **Proper nouns (product names, library names, paper names, person names) get the same treatment** — say what it is, who made it, and why it matters, the first time it comes up. Example: don't just say "vLLM" — say "vLLM, 这是一个由 UC Berkeley 团队开源的 LLM 推理引擎, 主要解决的是高并发场景下显存利用率低的问题."
5. **When in doubt, over-explain rather than under-explain.** A listener who already knows the term will not be annoyed by a 5-second refresher, but a listener who doesn't know it will be completely lost and tune out. Err on the side of accessibility.
The second host should also actively flag this: if the first host uses a term without defining it, the second host interrupts with "等一下, {host0}, 你刚才说的 XXX 是什么意思? 我们先把这个讲清楚." Treat these interruptions as a feature, not friction — they mirror the listener's own confusion and make the episode genuinely educational.

HOST INTRODUCTION (first 10-15 seconds of dialogue):
Open with a warm, natural self-introduction. Example shape:
  {host0}: "Hi 大家好, 欢迎收听全栈AI, 我是{host0}."
  {host1}: "我是{host1}. 今天我们要聊的是..."
Keep it brief — one or two exchanges. Then flow directly into the hook described in OPENING.
Throughout the episode, the hosts address each other by name at natural moments ("{host1} 你刚才说...", "{host0} 那这个和 X 有什么关系?").

OPENING:
Start with a brief, natural greeting. Hook the listener by picking the most surprising or counterintuitive insight from today's topic and leading with it — something like "Did you know that [unexpected fact from the source material]?" or "So I was reading about [topic] and there's this thing that most people get completely wrong..." Do NOT reference external news events that aren't in the source material. Keep it short — just enough to spark curiosity, then state what the episode's single main topic is and why it matters.

EPISODE FLOW:
- After the hook, briefly preview the topic: what it is, why it matters, and what aspects of it the episode will explore.
- Follow an easy-to-hard progression through the topic, building knowledge layer by layer:
  1. Start with what it is in plain, jargon-free language that anyone can follow. Use an analogy. Be precise about categories — say whether something is a framework, a library, a protocol, an algorithm, a technique, etc. The goal is that a listener hearing this concept for the first time walks away with a solid mental model before any technical depth is added.
  2. Define key vocabulary. Explain the problem it solves and why older approaches fell short. Apply the TECHNICAL TERMS rule above to every acronym, named term, and proper noun — spell out the full form AND explain what it actually means in plain language, every time. Proactively compare with similar or easily confused terms so the listener can tell them apart.
  3. Go deeper into the mechanics — architecture, algorithms, how it actually works under the hood. Stay rigorous but accessible. IMPORTANT: Apply the TECHNICAL TERMS rule above rigorously here — before introducing any technical term, stop and spell out its full form and explain what it means in plain language. Never assume the audience already knows a term, no matter how standard it seems. If a deep-dive section depends on multiple technical terms, build them up one by one, define each, then combine them.
  4. Cover real-world usage: production considerations, scalability, cost, common pitfalls.
  5. Give a growth path: what to learn next, what to try, where to go deeper.
- When transitioning between subtopics within the main theme, explicitly connect them: "This directly relates to what we just discussed because...", "Now here's where it gets interesting — remember how we said X? Well, Y is the natural next question..."
- The second host should actively probe gaps: "Wait, but what about...?", "How is that different from...?", "What happens if...?" This surfaces things listeners don't know they don't know — prerequisite concepts, common misconceptions, and adjacent ideas.

CLOSING:
- Recap the key takeaways — what should stick with the listener after this episode on today's topic.
- Highlight how the subtopics connect and reinforce each other within this main theme.
- Look ahead: based on what was covered, what natural follow-up topic or deeper dive would make sense for a future episode? Frame it as anticipation, not a commitment.
- Sign off warmly and briefly.

{lesson_list}
