---
name: ticket
description: Plan a Locali ticket (IDs like P1-E1-T6) as numbered steps the maintainer applies by hand. Use when a ticket with Steps and Acceptance criteria is pasted, or when asked "how do I do this" or "what do I need to change".
argument-hint: <pasted ticket>
model: sonnet
---

# Plan a ticket as hand-applied steps

The ticket: $ARGUMENTS

The maintainer makes the edits by hand. **Don't edit project files** unless the message also says
"do it", "do it yourself" or "do step N". If it does, do only what was asked.

## 1. Understand before planning

- Read the ticket's Steps, Acceptance criteria and "Depends on". Check with `git log --oneline -20`
  that the dependencies are done. If one isn't, say so first.
- Find the code the change touches with Grep, then read only those functions and the lines around
  them (Read with offset/limit). Read a whole file only when it is short or the step rewrites most
  of it. Read just the test file for the code you change, not every test. Follow the layering:
  `api/routers` (thin) → `services` (rules) → `ai/`, `db/`, `tools/`.
- Check what the ticket implies elsewhere:
  - **A schema change** needs a new migration in `app/db/migrations.py` and a test in `tests/test_migrations.py`.
  - **A route change** needs the OpenAPI export, `npm run generate:api`, and both generated files committed.
  - **A path that comes from the user** must go through `services/project_boundary.py`.
  - **A new setting** goes in its `config.py` dataclass, gets a flat alias, and gets a row in the README.
  - **Visible behavior** needs a desktop change and a README update.

## 2. Write the plan

Start with 2–4 sentences on what the ticket means in this codebase and the approach, plus identify
whether the ticket contains incorrect information or is missing details regarding its requirements or
implementation. Then give numbered steps:

```
### Step N — <what this step achieves>  (`backend/app/services/x.py`)
Find: <the existing line or function, quoted, with its line number>
Replace with / Add after:
<exact code, ready to paste, with the file's indentation>
Why: <one sentence>
```

- One file per step, small enough to paste in one go. Backend first, then tests, then OpenAPI and the
  desktop, then README and docs.
- Give complete code for what changes, never "...". Don't repeat unchanged lines; say which lines stay.
- Skip the "Why" line when the step title already says it.
- New files start with a header comment explaining what the file does, like every other file.
- Write the tests as their own step, one test per acceptance criterion where possible.
- End with a **Verify** step: the exact `uv run` and `npm` commands from AGENTS.md that cover this
  change, and what passing looks like.

## 3. Close

- Say whether the desktop needs to change for the feature to be visible.
- End with a ready-to-paste commit message: a short imperative subject, at most 2–3 body lines, and
  the Co-Authored-By trailer.
