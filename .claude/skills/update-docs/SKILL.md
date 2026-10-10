---
name: update-docs
description: Bring Locali's living documentation pages (Architecture, RAG Pipeline, Project Documentation) and the README in line with the current code. Use when asked to "update the docs", "update the architecture" or "update the artifact".
argument-hint: "[which doc]"
disable-model-invocation: true
---

# Update the living docs

Which docs: $ARGUMENTS (empty means check all of them).

| Page | URL |
| --- | --- |
| Locali Architecture | https://claude.ai/artifact/SENgTw488cuQ8jXXLWbBQ1 |
| Locali RAG Pipeline | https://claude.ai/artifact/KZyQZo9rT2GscN2iYPBtqn |
| Locali — Project Documentation | https://claude.ai/code/artifact/91610ba7-3635-40a4-998c-1996b3785295 |

**Always update these in place: read each page with the Artifact tool, edit it, and republish to the
same URL.** Never create a new page.

## Steps

1. Read each page, then find the commit its footer says it matches. Use
   `git log --oneline <that commit>..HEAD` and `git diff --stat <that commit>..HEAD` to see what has changed since.
2. Check the page against the code, not against memory:
   - routes in `backend/app/api/routers/`
   - entities and migrations in `backend/app/db/`
   - jobs in `backend/app/jobs/`
   - settings in `backend/app/core/config.py`
   - the retrieval and ingestion flow in `backend/app/ai/`
   - desktop features in `desktop/src/`
   - event contracts in `docs/CHAT_EVENTS.md` and `docs/JOB_EVENTS.md`
3. Fix what's wrong or missing, and remove what no longer exists. Keep each page's existing structure,
   design and diagrams, and change only what the code requires. Update the as-of date and the
   "matches commit `<hash>`" footer.
4. Check that README.md (layout, configuration tables, API reference, commands) and `desktop/README.md`
   agree with the code. These are project files, so give the README fixes as steps unless the
   maintainer said "do it".

## Report

For each page, give its link and a few bullets on what changed. Then list the README edits that are
still needed, if any. If a README file was edited, end with a commit message.
