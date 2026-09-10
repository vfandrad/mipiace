"""Autenticação das rotas administrativas.

Uma chave estática no header `X-API-Key` é o suficiente para o MVP (o painel é
interno), mas a comparação é feita com `secrets.compare_digest` para não vazar
a chave por tempo de resposta, e a chave nunca aparece em código — vem de
`settings.admin_api_key`.
"""

from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader

from app.core.config import Settings, get_settings

API_KEY_HEADER = "X-API-Key"

# auto_error=False para devolvermos a mensagem em português no formato do projeto.
_api_key_scheme = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": API_KEY_HEADER},
    )


async def require_api_key(
    api_key: str | None = Depends(_api_key_scheme),
    settings: Settings = Depends(get_settings),
) -> str:
    """Dependência das rotas `/api/*` administrativas."""
    expected = settings.admin_api_key
    if not expected:
        # Sem chave configurada a API ficaria aberta; melhor falhar fechado.
        raise _unauthorized("ADMIN_API_KEY não configurada no servidor.")
    if not api_key:
        raise _unauthorized(f"Header {API_KEY_HEADER} ausente.")
    if not secrets.compare_digest(api_key, expected):
        raise _unauthorized("Chave de API inválida.")
    return api_key


__all__ = ["API_KEY_HEADER", "require_api_key"]
