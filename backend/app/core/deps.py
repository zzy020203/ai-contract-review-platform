"""FastAPI 依赖注入：当前用户解析与 RBAC 权限码校验。"""
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_token
from app.models.domain import User

bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    token: str | None = Query(default=None),  # EventSource 无法携带 Header，SSE 场景用 query token
    db: Session = Depends(get_db),
) -> User:
    raw = credentials.credentials if credentials else token
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未登录")
    payload = decode_token(raw)
    if payload is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token 无效或已过期")
    user = db.get(User, int(payload["sub"]))
    if user is None or user.status != 1:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在或已禁用")
    return user


def user_permissions(user: User) -> set[str]:
    """汇总用户全部角色的权限码。"""
    codes: set[str] = set()
    for role in user.roles:
        codes.update(c for c in role.permission_codes.split(",") if c)
    return codes


def require_perm(perm_code: str):
    """RBAC 权限码校验依赖，用法：Depends(require_perm('review:start'))"""

    def checker(user: User = Depends(get_current_user)) -> User:
        if perm_code not in user_permissions(user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"缺少权限：{perm_code}")
        return user

    return checker
