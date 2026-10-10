---
name: check-step
description: Review the maintainer's hand-made edit for one step of the current ticket plan, without fixing it. Use when asked "check step N" or "did I do it right".
argument-hint: <step number(s)>
---

# Check the maintainer's edit for a step

Steps to check: $ARGUMENTS

This is a review, so **don't edit project files**. Fix something only if the maintainer then says "fix it".

1. Find the step(s) in the plan from earlier in this conversation. If there's no plan in context, ask
   which change to check, or read the ticket from the message.
2. Run `git diff` (and `git diff --staged`) on the step's files. Compare the edit with the plan and
   with what the step was meant to achieve. An edit that differs from the plan but is correct is fine.
3. Look for:
   - missing or wrong pieces: imports, indentation, names, a changed signature whose callers weren't updated
   - paste mistakes: duplicated blocks, leftover old code, code in the wrong function
   - the AGENTS.md rules: header comment, thin routers, migrations appended only, boundary checks on user paths
4. Run the cheapest checks that cover the step, from `backend/`:
   - `uv run ruff check <files>` and `uv run ruff format --check <files>`
   - `uv run pytest -q <related tests>`
   - for a route change, also `uv run python -m scripts.export_openapi --check`

   For a desktop step, run `npm run lint` and `npm run typecheck` from `desktop/`.
5. Report:
   - start with a verdict: **OK**, or **Needs changes**
   - for each problem: file:line, what's wrong, and the exact correction to make by hand
   - quote any failing command's output
   - end with what comes next: the next step number, or "ticket complete" plus a commit message
