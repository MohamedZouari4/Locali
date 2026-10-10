# CLAUDE.md

@AGENTS.md

The rest of this file is specific to Claude Code and to how the maintainer works with it.

## How to help on a ticket

The maintainer pastes a ticket (for example `P1-E1-T6 — Scope chats to projects`) and wants to learn by
making the changes by hand.

- **By default, explain and don't edit.** Use the `ticket` skill to give numbered steps (file, line,
  exact code to paste).
- **Only edit project files when the current message says so** ("do it", "do it yourself", "fix it",
  "do step 4"). That permission covers that request only. "Do step N" means only that step.
- Reading files, running tests, ruff and type checks, and trying snippets in the scratchpad are always fine.
- "Check step N" uses the `check-step` skill: review the edit and report what's wrong, without fixing it.
- If backend work changes something the desktop should show, say so and offer the frontend steps.

## Finishing a change

- **Always end with a ready-to-paste commit message** in a code block, even when not committing: a short
  imperative subject, at most 2–3 short body lines, then the Co-Authored-By trailer.
- Before calling something done, run the checks the change touches (the `ci` skill runs all of them).
  Report failures with their output.
- Don't `git commit` or `git push` unless asked.

## Skills in `.claude/skills/`

| Skill | Use |
| --- | --- |
| `/ticket` | Plan a pasted ticket as hand-applied steps |
| `/check-step N` | Review the maintainer's edit for a step |
| `/ci` | Run every CI check locally |
| `/notion-update` | Update the Notion Command Center after a ticket |
| `/update-docs` | Bring the Architecture, RAG Pipeline and Project Documentation pages and the README in line with the code |

## Environment notes

- Windows 11, PowerShell. The repo is at `D:\DEV\Locali`. Use `npm.cmd` if `npm` is blocked.
- Ollama must be running for chat and the integration test. Set `LOCALI_DEMO_JOBS=1` to enable the
  demo job kind when testing job progress.
- The developer's own `assistant.db` holds real data. Back it up or use a temporary database in tests,
  and never delete or reset it.
- Tracked docs go in `docs/`; private notes go in `docs/private/` (gitignored).
