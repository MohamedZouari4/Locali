"""File-operation endpoints (GET /files, /files/move, /files/organize) that map tool errors to HTTP status codes.
All paths are relative to the workspace root.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import tool_service
from app.services.tool_service import ToolServiceError

router = APIRouter()


class MoveFileRequest(BaseModel):
    src: str
    dst: str


class OrganizeRequest(BaseModel):
    folder: str


@router.get("/files")
def list_files(path: str = "."):
    try:
        return {"path": path, "entries": sorted(tool_service.list_files(path or "."))}
    except ToolServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.post("/files/move")
def move(req: MoveFileRequest):
    try:
        result = tool_service.move_file(req.src, req.dst)
        return {"result": result}
    except ToolServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.post("/files/organize")
def organize(req: OrganizeRequest):
    try:
        result = tool_service.organize_by_extension(req.folder)
        return {"result": result}
    except ToolServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
