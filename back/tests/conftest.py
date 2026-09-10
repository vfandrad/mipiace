"""Infra dos testes do Agente 1.

Regra: nenhum teste daqui exige Postgres no ar. O que precisa de banco usa uma
sessão de mentira e a dependência `get_session` sobrescrita — o objetivo é
cobrir contrato de API e regra de negócio, não o driver.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

# `pytest` roda de dentro de back/, mas garantir o path evita depender do CWD.
BACK_DIR = Path(__file__).resolve().parents[1]
if str(BACK_DIR) not in sys.path:
    sys.path.insert(0, str(BACK_DIR))

# Configuração previsível: os testes nunca podem falar com serviço externo.
os.environ.setdefault("FAKE_MODE", "true")
os.environ.setdefault("ADMIN_API_KEY", "test-key")

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.session import get_session  # noqa: E402
from app.main import app  # noqa: E402


class FakeSession:
    """Sessão que só registra o que foi chamado — não fala com banco nenhum."""

    def __init__(self) -> None:
        self.committed = 0
        self.added: list[Any] = []

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:  # pragma: no cover - só para simetria
        pass

    async def flush(self) -> None:
        pass

    async def refresh(self, obj: Any) -> None:
        pass

    def add(self, obj: Any) -> None:
        self.added.append(obj)


@pytest.fixture
def fake_session() -> FakeSession:
    return FakeSession()


@pytest.fixture
def api_key() -> str:
    return get_settings().admin_api_key


@pytest.fixture
def client(fake_session: FakeSession):
    """TestClient com a dependência de banco sobrescrita."""

    async def _override():
        yield fake_session

    app.dependency_overrides[get_session] = _override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
