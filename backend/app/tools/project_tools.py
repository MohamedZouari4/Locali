"""Read-only tools that summarize a project's catalog without accessing the filesystem directly."""

from app.services import catalog_service


def project_overview(project_id):
    """Summarize the structure, file types and recent catalog changes of one project."""
    overview = catalog_service.project_overview(project_id)
    if overview is None:
        raise ValueError("This project does not exist.")
    return overview