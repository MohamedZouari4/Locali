"""Catalog use cases: scan a project's folders into its catalog as a `catalog` background job, and list
what the catalog holds.

A scan reads every file first and then saves all changes in one transaction, so a cancelled or failed
scan leaves the previous catalog as it was. Jobs run per project (the job's project is the project id),
so two scans of one project never run at once. The file watcher updates the catalog between scans
(apply_changes); a lock keeps it and a scan from saving at the same time. The catalog is deleted with its project.
After a full scan, cached text that no catalog file was last read from is pruned (text_cache_service).

Importing this module registers the `catalog` job kind; app/api/main.py imports it through the routers.
"""

import fnmatch
import threading
import time
from datetime import UTC, datetime, timedelta

from app.catalog import scanner
from app.db import database
from app.jobs import worker

CATALOG_KIND = "catalog"
# find_files returns at most this many files, with the total count, so a broad search stays short for the model.
MAX_FOUND_FILES = 20
# The periods find_files can limit a search to, on the user's local clock.
CHANGED_PERIODS = ("today", "this_week", "this_month", "this_year", "last_7_days", "last_30_days")


# Held from reading the records to saving the changes, so a scan and the watcher never match against
# records the other is about to change.
_lock = threading.Lock()


def start_scan(project_id):
    """Queues a catalog scan and returns the job, or None if the project doesn't exist."""
    if database.get_project(project_id) is None:
        return None
    return database.get_job(worker.submit(CATALOG_KIND, {"project_id": project_id}, project=project_id))


def catalog_project(project, report=None):
    """Scans the project's folders, saves the changes and returns the counts. `report` goes to scanner.scan."""
    started = time.perf_counter()
    with _lock:
        records = database.list_catalog_records(project["id"])
        rules = scanner.IgnoreRules([folder["path"] for folder in project["folders"]], project["ignore_patterns"])
        scan = scanner.scan(rules, report)
        updates, inserts, delete_ids, renamed = scanner.match(records, scan)
        database.save_catalog_scan(project["id"], updates, inserts, delete_ids, scan.skipped)
        database.prune_text_cache()
    return {
        "files": len(updates) + len(inserts),
        "skipped": scan.skipped,
        "added": len(inserts),
        "renamed": renamed,
        "removed": len(delete_ids),
        "unreadable_folders": scan.unreadable,
        "seconds": round(time.perf_counter() - started, 2),
    }


def project_overview(project_id, max_files=100, recent_limit=10):
    """Returns a compact overview of one project's catalog, or None if the project does not exist."""
    project = database.get_project(project_id)
    if project is None:
        return None

    overview = database.get_catalog_overview(
        project_id,
        max_files=max_files,
        recent_limit=recent_limit,
    )

    return {
        "project": project["name"],
        "folders": [folder["path"] for folder in project["folders"]],
        **overview,
    }


def find_files(project_id, name=None, extensions=None, min_size=None, max_size=None, changed=None, now=None):
    """The project's catalogued files matching every filter given, as {"total", "files"}: at most
    MAX_FOUND_FILES rows, most recently modified first, or None if the project doesn't exist.

    `name` matches the file name, ignoring case in any script: a pattern with * or ? must match the whole name,
    anything else is found anywhere in it. `changed` is one of CHANGED_PERIODS; `now` is for tests.
    """
    if database.get_project(project_id) is None:
        return None
    since = _period_start(changed, now or datetime.now()) if changed else None
    rows = database.find_catalog_files(project_id, extensions, min_size, max_size, since)
    if name:
        pattern = name.casefold() if any(char in name for char in "*?[") else f"*{name.casefold()}*"
        rows = [row for row in rows if fnmatch.fnmatchcase(row["name"].casefold(), pattern)]
    return {"total": len(rows), "files": rows[:MAX_FOUND_FILES]}


def _period_start(period, now):
    # The period's start on the local clock (now is naive local time), as UTC in the catalog's timestamp format.
    # Naive datetimes are read as local time by astimezone, so a month that starts in another daylight-saving
    # offset still starts at local midnight.
    today = datetime(now.year, now.month, now.day)
    starts = {
        "today": today,
        "this_week": today - timedelta(days=today.weekday()),
        "this_month": today.replace(day=1),
        "this_year": today.replace(month=1, day=1),
        "last_7_days": now - timedelta(days=7),
        "last_30_days": now - timedelta(days=30),
    }
    return starts[period].astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def apply_changes(project, paths):
    """Updates the project's catalog for the paths the file watcher reported, and returns the counts.
    The skipped counts stay those of the last full scan."""
    with _lock:
        rules = scanner.IgnoreRules([folder["path"] for folder in project["folders"]], project["ignore_patterns"])
        scan, scope = scanner.scan_changes(paths, rules)
        if not scope:
            return {"added": 0, "updated": 0, "removed": 0}
        updates, inserts, delete_ids, _ = scanner.match(database.list_catalog_records(project["id"]), scan, scope)
        database.save_catalog_scan(project["id"], updates, inserts, delete_ids)
    return {"added": len(inserts), "updated": len(updates), "removed": len(delete_ids)}


@worker.handler(CATALOG_KIND)
def run_catalog_job(params, ctx):
    project = database.get_project(params["project_id"])
    if project is None:
        raise ValueError("This project no longer exists.")

    def report(count, folder):
        ctx.check_cancelled()
        ctx.progress(count, None, f"Cataloguing {folder}")

    return catalog_project(project, report)
