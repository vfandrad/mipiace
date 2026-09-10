"""Dependências compartilhadas pelas rotas."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import require_api_key
from app.db.session import get_session

#: Sessão de banco por request.
SessionDep = Annotated[AsyncSession, Depends(get_session)]

#: Configuração da aplicação.
SettingsDep = Annotated[Settings, Depends(get_settings)]

#: Proteção das rotas administrativas — aplicada no `include_router`.
ADMIN_DEPS = [Depends(require_api_key)]


async def require_fake_mode(settings: SettingsDep) -> None:
    """Bloqueia rotas de desenvolvimento quando o sistema roda pra valer."""
    if not settings.fake_mode:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rota disponível apenas com FAKE_MODE=true.",
        )


def not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


__all__ = [
    "ADMIN_DEPS",
    "SessionDep",
    "SettingsDep",
    "bad_request",
    "conflict",
    "not_found",
    "require_fake_mode",
]
