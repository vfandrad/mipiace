"""Health check — rota pública, usada pelo docker-compose e pelo front."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import SettingsDep

router = APIRouter(tags=["saúde"])

#: Versão do MVP; sobe junto com o contrato da API.
API_VERSION = "1.0.0"


class HealthResponse(BaseModel):
    status: str
    version: str
    fake_mode: bool
    environment: str


@router.get("/health", response_model=HealthResponse)
async def health(settings: SettingsDep) -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=API_VERSION,
        fake_mode=settings.fake_mode,
        environment=settings.environment,
    )
