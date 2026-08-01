from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from services import tool_service
from services.tool_service import ToolServiceError

router = APIRouter()

class MoveFileRequest(BaseModel):
    src: str
    dst: str

class OrganizeRequest(BaseModel):
    folder: str

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
