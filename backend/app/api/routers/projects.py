"""Project routes: create, list, open, update and delete projects, and add, change and remove their
folders. See app/services/project_service.py for the checks and what deleting a project removes.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field, StringConstraints

from app.db import database
from app.services import project_service
from app.services.folder_service import FolderRefused

router = APIRouter(prefix="/projects")

Permission = Literal["read", "act"]
ProjectName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Instructions = Annotated[str, Field(max_length=20000, description="Instructions the assistant follows in this project's chats.")]


class ProjectFolder(BaseModel):
    id: int
    path: str
    permission: Permission = Field(description="read: the assistant may search the folder. act: its tools may also change files there.")
    added_at: str


class ProjectSummary(BaseModel):
    id: str
    name: str
    instructions: str
    created_at: str


class Project(ProjectSummary):
    folders: list[ProjectFolder]


class CreateProjectRequest(BaseModel):
    name: ProjectName
    instructions: Instructions = ""


class UpdateProjectRequest(BaseModel):
    name: ProjectName | None = None
    instructions: Instructions | None = None


class AddProjectFolderRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1000, description="Full path of an existing folder.")
    permission: Permission = "read"


class FolderPermissionRequest(BaseModel):
    permission: Permission


def _project_not_found():
    return HTTPException(status_code=404, detail="Project not found")


def _folder_not_found():
    return HTTPException(status_code=404, detail="Folder not found in this project")


@router.get("", response_model=list[ProjectSummary])
def list_projects():
    return database.list_projects()


@router.post("", status_code=201, response_model=Project)
def create_project(req: CreateProjectRequest):
    """Creates a project without folders. 409 if another project has the same name, ignoring case."""
    try:
        return project_service.create_project(req.name, req.instructions)
    except project_service.ProjectNameTaken as error:
        raise HTTPException(status_code=409, detail=str(error)) from None


@router.get("/{project_id}", response_model=Project)
def open_project(project_id: str):
    project = database.get_project(project_id)
    if project is None:
        raise _project_not_found()
    return project


@router.patch("/{project_id}", response_model=Project)
def update_project(project_id: str, req: UpdateProjectRequest):
    """Renames the project or edits its instructions; fields left out are kept."""
    try:
        project = project_service.update_project(project_id, req.name, req.instructions)
    except project_service.ProjectNameTaken as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    if project is None:
        raise _project_not_found()
    return project


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: str):
    """Deletes the project, its folder list and its chats. Files in its folders are never touched."""
    if not database.delete_project(project_id):
        raise _project_not_found()
    return Response(status_code=204)


@router.post("/{project_id}/folders", status_code=201, response_model=ProjectFolder)
def add_project_folder(project_id: str, req: AddProjectFolderRequest):
    """Adds a folder. 422 with the reason if it doesn't exist, is a system, privacy or ignored folder,
    or is already in the project."""
    try:
        folder = project_service.add_folder(project_id, req.path, req.permission)
    except FolderRefused as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    if folder is None:
        raise _project_not_found()
    return folder


@router.patch("/{project_id}/folders/{folder_id}", response_model=ProjectFolder)
def set_folder_permission(project_id: str, folder_id: int, req: FolderPermissionRequest):
    folder = database.set_project_folder_permission(project_id, folder_id, req.permission)
    if folder is None:
        raise _folder_not_found()
    return folder


@router.delete("/{project_id}/folders/{folder_id}", status_code=204)
def remove_project_folder(project_id: str, folder_id: int):
    """Takes the folder off the project. Its files are never touched."""
    if not database.remove_project_folder(project_id, folder_id):
        raise _folder_not_found()
    return Response(status_code=204)
