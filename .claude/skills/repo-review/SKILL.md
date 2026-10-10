---
name: repo-review
description: Review an outside GitHub repo (often a Personal OS Resources link) for what Locali can learn from it, map the maintainer's idea list onto the Task Board, and record the result in Notion after approval. Use when a repo or Resources link is pasted with "what do you think" or a list of ideas.
argument-hint: <repo or Notion Resources link> [maintainer's ideas]
---

# Review a repo for Locali

Input: $ARGUMENTS

## 1. Gather the facts

- If the link is a Notion Resources entry, fetch it for the repo URL and the maintainer's notes.
- Read the repo's README (WebFetch). Note: licence, stack, whether it runs fully offline, which model
  providers it calls by default, hardware needs, maturity (stars, commits, maintainers, releases),
  and benchmark claims with or without a method.
- Search the LOCALI Task Board (https://app.notion.com/p/c342eaabc8018339a48f81d4c0fb0eee) and the
  Architecture Guide for every idea before calling it new. Most ideas are already planned.
- Check claims about Locali's code in the code itself (Grep/Read), not from memory.

## 2. Judge it against Locali's rules

- **Licence:** AGPL/GPL means ideas only, never code. MIT/Apache allows borrowing with a notice (X-DOC-T5).
- **Local-first:** anything that calls a cloud API or downloads at runtime is out, or opt-in and packaged.
- **Small local model:** a 4B model on CPU needs few tools per step, few agents, code-built structure
  over model-built structure, and caps on what goes into the prompt.
- **Security:** content from files is untrusted (P5-E3). Memory, wikis and graphs built from files must
  keep their sources, follow the project boundary, and never act as a source of truth on their own.
- **Phase discipline:** new ideas go to the Backlog in a later phase. Only bugs or small unblockers
  are proposed for the current phase.

## 3. Report (no Notion writes yet)

- What the repo is, in 3–5 bullets, separating verifiable facts from marketing.
- Integrate or not, with the reasons.
- A table of the maintainer's ideas: idea · already on the board? (ticket IDs) · what is really missing.
- Your own ideas, each with where it fits (after which ticket).
- End with the exact list of Notion changes you propose, and ask before writing.

## 4. When told to add

1. **Knowledge Library** (data source `collection://f45c6901-4500-4c7f-ae5f-ebc858c725bb`): one page with
   Status Studied, Kind, LOCALI Relevance, Key Insight, Topic, Date, and sections What it is · How it
   works · Assessment (date) · Review of the ideas (table) · Source (repo link + mention of the Resources entry).
2. **Resources entry** (`collection://ace1ef2a-444f-46ed-9a0f-c775e7632c46`): Status Reference, Notes with
   the date, the decision and the tickets it led to.
3. **LOCALI Tasks** (`collection://3e22eaab-c801-806a-83d1-000b2cd00313`): check new IDs are free with a
   SQL query, then create rows with every property filled. Existing rows: append steps, keep the old ones.
4. **Task Board**: insert each new ticket section after the last ticket of its epic, in the same format,
   with a `**Source:**` line. Add the same steps to existing sections. Add one "Added <date> (<repo> review)"
   line under "Where we are". Anchor edits on unique text; retry once if an edit reports no match.
5. Report what changed with links, and anything that failed.
