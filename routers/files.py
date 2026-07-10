from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import tools

router = APIRouter()

class MoveFileRequest(BaseModel):
    src: str
    dst: str

class OrganizeRequest(BaseModel):
    folder: str

@router.post("/files/move")
def move(req: MoveFileRequest):
    try:
        result = tools.move_file(req.src, req.dst)
        return {"result": result}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/files/organize")
def organize(req: OrganizeRequest):
    try:
        result = tools.organize_by_extension(req.folder)
        return {"result": result}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
