"""Catalog use cases: scan a project's folders into its catalog as a `catalog` background job, and list
what the catalog holds.

A scan reads every file first and then saves all changes in one transaction, so a cancelled or failed
scan leaves the previous catalog as it was. Jobs run per project (the job's project is the project id),
so two scans of one project never run at once. The catalog is deleted with its project.

Importing this module registers the `catalog` job kind; app/api/main.py imports it through the routers.
"""

import time

from app.catalog import scanner
from app.db import database
from app.jobs import worker

CATALOG_KIND = "catalog"


def start_scan(project_id):
    """Queues a catalog scan and returns the job, or None if the project doesn't exist."""
    if database.get_project(project_id) is None:
        return None
    return database.get_job(worker.submit(CATALOG_KIND, {"project_id": project_id}, project=project_id))


def catalog_project(project, report=None):
    """Scans the project's folders, saves the changes and returns the counts. `report` goes to scanner.scan."""
    started = time.perf_counter()
    records = database.list_catalog_records(project["id"])
    scan = scanner.scan([folder["path"] for folder in project["folders"]], report)
    updates, inserts, delete_ids, renamed = scanner.match(records, scan)
    database.save_catalog_scan(project["id"], updates, inserts, delete_ids)
    return {
        "files": len(updates) + len(inserts),
        "added": len(inserts),
        "renamed": renamed,
        "removed": len(delete_ids),
        "unreadable_folders": scan.unreadable,
        "seconds": round(time.perf_counter() - started, 2),
    }


@worker.handler(CATALOG_KIND)
def run_catalog_job(params, ctx):
    project = database.get_project(params["project_id"])
    if project is None:
        raise ValueError("This project no longer exists.")

    def report(count, folder):
        ctx.check_cancelled()
        ctx.progress(count, None, f"Cataloguing {folder}")

    return catalog_project(project, report)
