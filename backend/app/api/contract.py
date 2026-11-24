"""合同上传与任务创建。"""
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import require_perm
from app.models.domain import AuditLog, Contract, ReviewTask, User

router = APIRouter(prefix="/contract", tags=["合同接入"])

ALLOWED_TYPES = {".pdf": "pdf", ".docx": "docx", ".txt": "txt"}


def ok(data):
    return {"code": 0, "message": "ok", "data": data}


@router.post("/upload")
async def upload(
    file: UploadFile,
    db: Session = Depends(get_db),
    user: User = Depends(require_perm("contract:upload")),
):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_TYPES:
        raise HTTPException(400, "仅支持 PDF / DOCX / TXT 格式")

    content = await file.read()
    if len(content) > settings.UPLOAD_MAX_MB * 1024 * 1024:
        raise HTTPException(400, f"文件大小超过限制（{settings.UPLOAD_MAX_MB}MB）")
    if not content:
        raise HTTPException(400, "文件内容为空")

    save_dir = settings.STORAGE_DIR / "contracts"
    save_dir.mkdir(parents=True, exist_ok=True)
    file_path = save_dir / f"{uuid.uuid4().hex}{suffix}"
    file_path.write_bytes(content)

    contract = Contract(
        name=file.filename, file_path=str(file_path),
        file_type=ALLOWED_TYPES[suffix], uploader_id=user.id,
    )
    db.add(contract)
    db.flush()

    task = ReviewTask(contract_id=contract.id, thread_id=uuid.uuid4().hex, creator_id=user.id)
    db.add(task)
    db.flush()  # 先落库拿到 task.id，审计详情可追溯
    db.add(AuditLog(operator_id=user.id, action="upload", target=file.filename, detail=f"task_id={task.id}"))
    db.commit()

    return ok({"contract_id": contract.id, "task_id": task.id, "thread_id": task.thread_id})
