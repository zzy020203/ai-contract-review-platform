"""登录认证接口。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, user_permissions
from app.core.security import create_token, verify_password
from app.models.domain import AuditLog, User
from app.schemas.auth import LoginRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["认证"])


def ok(data):
    return {"code": 0, "message": "ok", "data": data}


@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(400, "用户名或密码错误")
    if user.status != 1:
        raise HTTPException(403, "账号已被禁用")

    db.add(AuditLog(operator_id=user.id, action="login", target=user.username))
    db.commit()

    token = create_token(user.id, user.username)
    return ok(TokenResponse(
        token=token,
        username=user.username,
        real_name=user.real_name,
        permissions=sorted(user_permissions(user)),
    ).model_dump())


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return ok({
        "username": user.username,
        "real_name": user.real_name,
        "permissions": sorted(user_permissions(user)),
    })
