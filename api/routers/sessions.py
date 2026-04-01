from pathlib import Path
from typing import Any
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()
OUTPUTS_DIR = Path("outputs")

class FileItem(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: int | None = None
    extension: str | None = None

@router.get("/tree")
async def get_directory_tree(path: str = "") -> list[FileItem]:
    """Returns the contents of a directory within outputs/."""
    target_dir = OUTPUTS_DIR / path
    
    # Security check: prevent directory traversal
    try:
        target_dir = target_dir.resolve()
        outputs_resolved = OUTPUTS_DIR.resolve()
        if not target_dir.is_relative_to(outputs_resolved):
            raise HTTPException(status_code=403, detail="Access denied")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target_dir.exists() or not target_dir.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    items = []
    for entry in target_dir.iterdir():
        if entry.name.startswith("__"):
            continue
            
        items.append(FileItem(
            name=entry.name,
            path=str(entry.relative_to(outputs_resolved)),
            is_dir=entry.is_dir(),
            size=entry.stat().st_size if entry.is_file() else None,
            extension=entry.suffix.lower() if entry.is_file() else None
        ))
        
    # Sort: directories first, then alphabetical
    items.sort(key=lambda x: (not x.is_dir, x.name.lower()))
    return items

@router.get("/file")
async def get_file_content(path: str) -> dict[str, Any]:
    """Returns the text content of a file."""
    target_file = OUTPUTS_DIR / path
    
    try:
        target_file = target_file.resolve()
        if not target_file.is_relative_to(OUTPUTS_DIR.resolve()):
            raise HTTPException(status_code=403, detail="Access denied")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target_file.exists() or not target_file.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    # Only read text files
    text_exts = {".json", ".txt", ".md", ".py", ".csv", ".log", ".yaml", ".yml"}
    if target_file.suffix.lower() not in text_exts:
        raise HTTPException(status_code=400, detail="Not a text file")

    try:
        content = target_file.read_text(encoding="utf-8", errors="replace")
        return {"content": content, "path": path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
