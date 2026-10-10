---
name: ci
description: Run every check Locali's GitHub CI runs (ruff, pytest, OpenAPI sync, desktop lint and typecheck) locally and report what fails. Use before committing, or when asked "will CI pass" or "why is CI red".
argument-hint: "[backend|desktop]"
---

# Run the CI checks locally

Scope: $ARGUMENTS (empty means both).

These checks mirror `.github/workflows/ci.yml`. If the workflow file changed, follow the workflow instead.
Run every check even after one fails, so the report is complete. **Don't fix anything** unless asked.

## Backend (from `backend/`)

```powershell
uv sync --locked
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest -q
uv run --locked python -m scripts.export_openapi --check
```

- If `uv sync --locked` fails, `uv.lock` is out of date with `pyproject.toml`. Running `uv lock` fixes
  it, and both files must be committed.
- If the OpenAPI check fails, run `uv run python -m scripts.export_openapi`, then
  `npm run generate:api` in `desktop/`, and commit both generated files.
- Integration tests skip without Ollama. That's expected. Report them as skipped, not failed.
- The boundary tests also run on Windows CI, and this machine is Windows, so a failure in
  `tests/test_project_boundary.py` is a real failure.

## Desktop (from `desktop/`, using `npm.cmd` if PowerShell blocks `npm`)

```powershell
npm ci            # only if node_modules is missing or package-lock.json changed
npm run lint
npm run generate:api
git diff --exit-code electron/api/schema.d.ts
npm run typecheck
```

## Report

Show a table with one row per check: ✅ pass, ❌ fail or ⏭ skipped, and a short note. Under it, list
each failure with the relevant output lines (not the whole log) and the exact fix to apply by hand.
If everything passed, say so in one line.

To see why CI on GitHub is red, run `gh run list --limit 5` and then `gh run view <id> --log-failed`,
and compare the result with the local run.
