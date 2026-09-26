"""Health check — rota pública, usada pelo Docker (HEALTHCHECK) e pelo front."""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import text

from app.api.deps import SessionDep, SettingsDep

router = APIRouter(tags=["saúde"])

#: Versão do MVP; sobe junto com o contrato da API.
API_VERSION = "1.0.0"


class HealthResponse(BaseModel):
    status: str
    version: str
    fake_mode: bool
    environment: str
    database: str


@router.get("/health", response_model=HealthResponse)
async def health(
    settings: SettingsDep, session: SessionDep, response: Response
) -> HealthResponse:
    """"ok" só se a request REALMENTE alcançar o banco.

    Antes só ecoava `Settings` — o processo respondia "ok" mesmo com o banco
    fora do ar ou com o schema desatualizado. Foi assim que um 503 real em
    `/api/products` (schema sem a tabela `product_groups`) passou despercebido:
    o `HEALTHCHECK` do Docker batia aqui, via "ok" e marcava o container
    saudável o tempo todo. Um `SELECT 1` é a checagem mais barata que ainda
    prova que a conexão funciona de verdade.
    """
    try:
        await session.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "erro"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status="ok" if db_status == "ok" else "degradado",
        version=API_VERSION,
        fake_mode=settings.fake_mode,
        environment=settings.environment,
        database=db_status,
    )
