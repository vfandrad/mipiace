"""Aplicação FastAPI do Mi Piace.

Monta as rotas administrativas (protegidas por X-API-Key), os webhooks
(protegidos pela assinatura do provedor) e — se já existirem — as rotas do
agente de WhatsApp. Os imports do agente são tolerantes a ausência de
propósito: o backend precisa subir mesmo com aquela parte ainda em construção.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.deps import ADMIN_DEPS
from app.api.routes import conversations, dev, health, metrics, orders, products, webhooks
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


def _include_agent_routers(app: FastAPI) -> None:
    """Rotas do agente (Agente 2). Ausentes = app sobe igual, só sem WhatsApp."""
    for module_name, label in (
        ("app.api.routes.whatsapp", "WhatsApp"),
        ("app.api.routes.evolution", "Evolution API"),
        ("app.api.routes.evolution_client", "cliente Evolution"),
        ("app.api.routes.simulator", "simulador"),
    ):
        try:
            module = __import__(module_name, fromlist=["router"])
            app.include_router(module.router)
            logger.info("Rotas do %s montadas.", label)
        except ImportError:
            logger.warning("Rotas do %s indisponíveis (módulo ainda não existe).", label)
        except AttributeError:
            logger.warning("Módulo %s não expõe `router`.", module_name)


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

    # Públicas: health e webhooks (estes validam a assinatura do provedor).
    app.include_router(health.router)
    app.include_router(webhooks.router)

    # Administrativas: exigem X-API-Key.
    for router in (products.router, orders.router, metrics.router, conversations.router):
        app.include_router(router, dependencies=ADMIN_DEPS)

    # Ferramenta de desenvolvimento: só responde com FAKE_MODE=true.
    app.include_router(dev.router, dependencies=ADMIN_DEPS)

    _include_agent_routers(app)
    return app


app = create_app()
