"""Aplicação FastAPI do Mi Piace.

Monta três grupos de rotas:
  - públicas: `/health` e os webhooks (que validam o próprio remetente);
  - administrativas: tudo em `/api`, protegido por `X-API-Key`;
  - simulador: ferramenta de desenvolvimento, só responde com FAKE_MODE=true.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.deps import ADMIN_DEPS
from app.api.routes import (
    conversations,
    health,
    metrics,
    orders,
    products,
    simulator,
    webhooks,
)
from app.api.routes.health import API_VERSION
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logger.info(
        "Subindo %s (%s) fake_mode=%s",
        settings.app_name,
        settings.environment,
        settings.fake_mode,
    )
    yield
    from app.db.session import dispose_engine

    await dispose_engine()


def create_app() -> FastAPI:
    setup_logging()
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=API_VERSION,
        description="Backend do MVP Mi Piace: catálogo, pedidos, Pix e agente de WhatsApp.",
        lifespan=lifespan,
    )

    # CORS restrito à lista do .env — nunca "*", porque a API leva chave no header.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-API-Key", "Authorization"],
    )

    # Públicas: health e webhooks (Mercado Pago e Evolution validam o remetente).
    app.include_router(health.router)
    app.include_router(webhooks.router)

    # Administrativas: exigem X-API-Key.
    for router in (
        products.router,
        orders.router,
        metrics.router,
        conversations.router,
        simulator.router,
    ):
        app.include_router(router, dependencies=ADMIN_DEPS)

    return app


app = create_app()
