import json
import re
import secrets
from dataclasses import dataclass
from functools import lru_cache
from typing import Generator

from fastapi import Header, HTTPException, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.base import SessionLocal
from app.llm.providers import build_llm
from app.services.retrieval import LocalKnowledgeRetriever


_TENANT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,63}$")


@dataclass(frozen=True)
class AuthContext:
    tenant_id: str
    user_id: str = "workspace-user"


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def require_auth(
    x_api_key: str = Header(..., alias="X-API-Key"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_user_id: str = Header("workspace-user", alias="X-User-ID"),
) -> AuthContext:
    if not _TENANT_PATTERN.fullmatch(x_tenant_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid tenant ID")
    if not _TENANT_PATTERN.fullmatch(x_user_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid user ID")
    settings = get_settings()
    if settings.tenant_api_keys_json:
        try:
            tenant_keys = json.loads(settings.tenant_api_keys_json.get_secret_value())
            expected = tenant_keys.get(x_tenant_id, "")
        except (json.JSONDecodeError, AttributeError):
            raise HTTPException(status_code=500, detail="tenant authentication is misconfigured")
    else:
        expected = settings.app_api_key.get_secret_value()
    if not expected or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid API key")
    return AuthContext(tenant_id=x_tenant_id, user_id=x_user_id)


@lru_cache
def get_llm():
    return build_llm(get_settings())


@lru_cache
def get_retriever() -> LocalKnowledgeRetriever:
    return LocalKnowledgeRetriever(get_settings().knowledge_dir)
