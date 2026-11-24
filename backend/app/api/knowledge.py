"""知识库管理：文档上传向量化（历史合同 / 标准模板）+ 相似检索验证。"""
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import require_perm
from app.models.domain import AuditLog, KnowledgeDoc, User
from app.services import docparse, rag

router = APIRouter(prefix="/knowledge", tags=["知识库"])

ALLOWED_TYPES = {".pdf": "pdf", ".docx": "docx", ".txt": "txt"}


def ok(data):
    return {"code": 0, "message": "ok", "data": data}


def _to_out(d: KnowledgeDoc) -> dict:
    return {
        "id": d.id, "lib_type": d.lib_type, "title": d.title,
        "vector_status": d.vector_status, "create_time": d.create_time,
    }


class SearchOut(BaseModel):
    pass


@router.post("/upload")
async def upload(
    file: UploadFile,
    lib_type: str = Query(..., description="库类型：history / template"),
    db: Session = Depends(get_db),
    user: User = Depends(require_perm("knowledge:manage")),
):
    if lib_type not in ("history", "template"):
        raise HTTPException(400, "lib_type 仅支持 history / template（规则请走 /api/rule）")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_TYPES:
        raise HTTPException(400, "仅支持 PDF / DOCX / TXT 格式")
    content = await file.read()
    if not content:
        raise HTTPException(400, "文件内容为空")

    save_dir = settings.STORAGE_DIR / "knowledge"
    save_dir.mkdir(parents=True, exist_ok=True)
    file_path = save_dir / f"{uuid.uuid4().hex}{suffix}"
    file_path.write_bytes(content)

    doc = KnowledgeDoc(lib_type=lib_type, title=file.filename,
                       file_path=str(file_path), uploader_id=user.id)
    db.add(doc)
    db.flush()

    try:
        text = docparse.extract_text(str(file_path), ALLOWED_TYPES[suffix])
        chunk_count = rag.index_document(doc.id, lib_type, doc.title, text)
        doc.vector_status = "done" if chunk_count else "failed:无有效文本"
    except Exception as exc:
        doc.vector_status = f"failed:{exc}"[:200]

    db.add(AuditLog(operator_id=user.id, action="knowledge:upload",
                    target=file.filename, detail=f"lib_type={lib_type}"))
    db.commit()
    return ok({**_to_out(doc), "chunk_count": chunk_count if doc.vector_status == "done" else 0})


@router.get("/list")
def list_docs(lib_type: str | None = None, db: Session = Depends(get_db),
              user: User = Depends(require_perm("knowledge:view"))):
    stmt = select(KnowledgeDoc).order_by(KnowledgeDoc.id.desc())
    if lib_type:
        stmt = stmt.where(KnowledgeDoc.lib_type == lib_type)
    return ok([_to_out(d) for d in db.scalars(stmt).all()])


@router.get("/search")
def search(q: str = Query(..., min_length=1), lib_type: str = "template",
           top_k: int = Query(3, ge=1, le=20),
           user: User = Depends(require_perm("knowledge:view"))):
    """相似检索验证：返回 Top-K 命中片段与相似度分数。"""
    if lib_type == "rule":
        hits = rag.search_rules(q, top_k=top_k, threshold=0.0)
    else:
        hits = rag.search_knowledge(lib_type, q, top_k=top_k, threshold=0.0)
    return ok({"query": q, "lib_type": lib_type, "hits": hits})
