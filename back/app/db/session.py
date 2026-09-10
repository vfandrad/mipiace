"""Engine e sessão assíncrona (SQLAlchemy 2.0 + driver psycopg 3).

O engine é criado sob demanda (lru_cache) e não no import: assim `import
app.main` funciona sem Postgres no ar — útil para testes e para o build da
imagem Docker.
"""

from __future__ import annotations

import asyncio
import sys
import warnings
from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


def _ensure_selector_event_loop() -> None:
    """No Windows, psycopg async não roda no ProactorEventLoop (o padrão).

    Sem isso, todo `asyncio.run(...)` que toque o banco — o simulador de
    terminal, os scripts de manutenção — morre com InterfaceError. Uvicorn
    escolhe o loop por conta própria (com `--reload` já usa o selector), então
    isto só afeta quem cria o loop na mão.
    """
    if sys.platform != "win32":
        return
    with warnings.catch_warnings():
        # A API de policy está deprecada no 3.14, mas ainda é a única forma
        # de trocar o loop padrão para quem chama asyncio.run().
        warnings.simplefilter("ignore", DeprecationWarning)
        policy = asyncio.get_event_loop_policy()
        selector_policy = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
        if selector_policy is not None and not isinstance(policy, selector_policy):
            asyncio.set_event_loop_policy(selector_policy())


_ensure_selector_event_loop()


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=True,   # conexão morta depois do container do banco reiniciar
        pool_size=5,
        max_overflow=10,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Fábrica de sessões compartilhada pela API e pelo agente."""
    return async_sessionmaker(
        bind=get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,  # ler atributos depois do commit sem novo SELECT
        autoflush=False,
    )


async def get_session() -> AsyncIterator[AsyncSession]:
    """Dependência FastAPI: uma sessão por request, com rollback em erro."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Fecha o pool no shutdown da aplicação."""
    if get_engine.cache_info().currsize:
        await get_engine().dispose()


__all__ = [
    "dispose_engine",
    "get_engine",
    "get_session",
    "get_sessionmaker",
]
