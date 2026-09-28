"""Aplicação FastAPI do atendimento por WhatsApp.

Monta três grupos de rotas:
  - públicas: `/health` e os webhooks (que validam o próprio remetente);
  - administrativas: tudo em `/api`, protegido por `X-API-Key`;
  - simulador: ferramenta de desenvolvimento, só responde com FAKE_MODE=true.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.api import (
    ADMIN_DEPS,
    API_VERSION,
    rotas_conversas,
    rotas_metricas,
    rotas_pedidos,
    rotas_produtos,
    rotas_saude,
    rotas_simulador,
    rotas_webhooks,
)
from app.configuracao import get_logger, get_settings, setup_logging

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
    from app.banco import dispose_engine  # noqa: PLC0415

    await dispose_engine()


def create_app() -> FastAPI:
    setup_logging()
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=API_VERSION,
        description="Catálogo, pedidos, Pix e o agente de WhatsApp.",
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

    @app.middleware("http")
    async def _security_headers(request: Request, call_next: Any) -> Response:
        """Headers básicos que toda API atrás de HTTPS deveria mandar.

        Não substituem nada (a API não serve HTML, então CSP não se aplica
        aqui) — só fecham brechas baratas: navegador tentando adivinhar
        Content-Type, e a resposta sendo aceita por HTTP puro se alguém
        contornar o redirect do proxy.
        """
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
        return response

    # Públicas: health e webhooks (Mercado Pago e Evolution validam o remetente).
    app.include_router(rotas_saude)
    app.include_router(rotas_webhooks)

    # Administrativas: exigem X-API-Key.
    for rotas in (
        rotas_produtos,
        rotas_pedidos,
        rotas_metricas,
        rotas_conversas,
        rotas_simulador,
    ):
        app.include_router(rotas, dependencies=ADMIN_DEPS)

    @app.exception_handler(IntegrityError)
    async def _integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
        """Restrição do banco barrou a operação — normalmente apagar algo com pedido.

        `product_id`/`complement_id` em `order_items`/`order_item_complements`
        são `ON DELETE RESTRICT` de propósito: apagar um sabor ou produto que
        já foi vendido perderia o histórico daquele pedido. Sem este handler,
        o painel travava com um erro de banco cru (500) em vez de uma
        mensagem que o lojista entende.
        """
        logger.warning("Restrição do banco barrou a operação: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": (
                    "Não dá pra apagar: esse item já foi usado em algum pedido. "
                    "Desative em vez de apagar."
                )
            },
        )

    return app


app = create_app()
