---
name: notion-update
description: Update the LOCALI Engineering Command Center in Notion after work on a ticket (task status, Task Board, Command Center status, Daily Log). Use when asked to "update notion" or "update the board".
argument-hint: "[ticket IDs or commit hashes]"
disable-model-invocation: true
---

# Update the Notion board

Context from the maintainer: $ARGUMENTS

Command Center: https://app.notion.com/p/3af2eaabc801814fa11bf15e775c2b2b

## 1. Gather the facts first

- Run `git log --oneline -15` and `git status --short`. Note which tickets have commits and which are
  still uncommitted. A hash the maintainer gives in `$ARGUMENTS` is a commit to record.
- Check whether CI is green with `gh run list --limit 3`.
- Fetch the current Notion pages before editing, so edits match the real text.

## 2. Update, in this order

1. **LOCALI Tasks** (database), one row per ticket worked on:
   - Set Status, Commit (hash) and When Finished (date).
   - Mark a ticket **Done** only when its commit exists, and **In review** while it's uncommitted or CI is red.
   - Move tasks whose "Depends on" tickets are now all Done from **Backlog** to **Ready**.
2. **Task Board** (long page):
   - Tick the ticket's Steps and Acceptance criteria checkboxes that are really done.
   - Update the "Where we are" section: phase progress (for example "Phase 1: 6 of N done"), what's in
     review, and what's next.
   - Edits far down this page often fail with "no match" even when the text is identical. Retry once
     with the raw text. If it still fails, list the boxes for the maintainer to tick by hand.
3. **Command Center** status block: the current phase, the active priority and the next task. Its lines
   are separate blocks, so replace them one at a time.
4. **Daily Log**:
   - Add or update today's entry, titled `YYYY-MM-DD — <short summary>`, and link it to the tickets.
   - Fill in: what was done, commits, what was learned or decided (with the reasons), and the first
     items for the next session.
   - Leave **Hours** and **Energy** empty for the maintainer.
5. If the change affects architecture (new endpoints, entities, ADR-level decisions), update the
   matching 🏛️ Architecture entries too.

Use **Self-Test Log** rows only for measurements and self-test observations.

## 3. Report

Give a short list of what changed on each page, with links. Then add a **"Do by hand"** list (boxes
that didn't apply, rows to delete) and the first items for the next session. Never claim an edit that failed.
