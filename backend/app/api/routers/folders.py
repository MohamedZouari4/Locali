"""Indexed-folder routes: list the folders ingestion walks, add one, remove one. Indexing itself is
started with POST /ingest. See app/services/folder_service.py for the checks a folder must pass.
"""

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from app.services import folder_service

router = APIRouter(prefix="/folders")


class IndexedFolder(BaseModel):
    id: int
    path: str
    added_at: str


class AddFolderRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1000, description="Full path of an existing folder.")


@router.get("", response_model=list[IndexedFolder])
def list_folders():
    return folder_service.list_folders()


@router.post("", status_code=201, response_model=IndexedFolder)
def add_folder(req: AddFolderRequest):
    """Adds a folder to index. 422 with the reason if it doesn't exist, is a system, privacy or
    ignored folder, or is already covered by another indexed folder."""
    try:
        return folder_service.add_folder(req.path)
    except folder_service.FolderRefused as error:
        raise HTTPException(status_code=422, detail=str(error)) from None


@router.delete("/{folder_id}", status_code=204)
def remove_folder(folder_id: int):
    """Removes the folder from the list; a background job then removes its files from the index."""
    if not folder_service.remove_folder(folder_id):
        raise HTTPException(status_code=404, detail="Folder not found")
    return Response(status_code=204)
