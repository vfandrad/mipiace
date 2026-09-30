"""Aplicação FastAPI do atendimento por WhatsApp.

Monta três grupos de rotas:
  - públicas: `/health` e os webhooks (que validam o próprio remetente);
  - administrativas: tudo em `/api`, protegido por `X-API-Key`;
  - simulador: ferramenta de desenvolvimento, só responde com FAKE_MODE=true.

E as duas formas de subir o sistema: o servidor web (`app` lá embaixo, que é
o que o uvicorn carrega) e a conversa pelo terminal, no fim do arquivo:

    python -m app.main
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.agente import (
    InboundMessage,
    handle_inbound,
    load_or_create,
    reset_session,
    send_pending_pix_reminders,
    settings_snapshot,
)
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
from app.textos import em_reais

logger = get_logger(__name__)


async def _pix_reminder_loop(settings: Any) -> None:
    """Confere pedidos com Pix pendente e manda lembrete, de tempos em tempos.

    Roda até ser cancelada no shutdown. Erro de uma volta não pode matar as
    seguintes — o cliente perder um lembrete é bem menos grave que o laço
    parar de rodar pro resto dos clientes.
    """
    from app.banco import get_sessionmaker  # noqa: PLC0415

    sessionmaker = get_sessionmaker()
    while True:
        await asyncio.sleep(settings.pix_reminder_check_seconds)
        try:
            async with sessionmaker() as db:
                await send_pending_pix_reminders(db)
        except Exception:
            logger.exception("falha na varredura de lembretes de Pix pendente")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logger.info(
        "Subindo %s (%s) fake_mode=%s",
        settings.app_name,
        settings.environment,
        settings.fake_mode,
    )
    reminder_task = asyncio.create_task(_pix_reminder_loop(settings))
    yield
    reminder_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await reminder_task

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


# ---------------------------------------------------------------------------
# Conversa pelo terminal (desenvolvimento)
# ---------------------------------------------------------------------------
# A forma mais rápida de ver a máquina de estados funcionando: além das
# respostas, imprime o estado a cada turno, que é justamente o que se quer
# olhar quando o fluxo trava. Comandos: /reset, /estado, /sair.

CHANNEL = "simulador"
DEFAULT_PHONE = "5511999990000"

# Cores só quando o terminal aguenta.
_BOT = "\033[36m"
_INFO = "\033[90m"
_ERR = "\033[31m"
_OFF = "\033[0m"


def _print_bot(text: str) -> None:
    print(f"{_BOT}bot >{_OFF} " + text.replace("\n", "\n      "))


def _print_info(text: str) -> None:
    print(f"{_INFO}{text}{_OFF}")


async def _show_state(sessionmaker, phone: str) -> None:
    """Estado + carrinho a cada turno: é o que se olha quando o fluxo trava."""
    try:
        async with sessionmaker() as db:
            conversation = await load_or_create(db, phone, CHANNEL)
            await db.commit()
    except Exception as exc:
        _print_info(f"[não consegui ler o estado: {exc}]")
        return
    cart = conversation.cart
    _print_info(
        f"[estado={conversation.state.value} itens={len(cart.items)} "
        f"subtotal={em_reais(cart.subtotal)} falhas={conversation.fail_count} "
        f"handoff={conversation.handoff}]"
    )
    for item in cart.items:
        extras = ", ".join(c.name for c in item.complements)
        _print_info(f"   - {item.quantity}x {item.product_name} {extras}")


def _prepare_console() -> None:
    """O terminal do Windows nasce em cp1252 e engasga com os emoji das mensagens."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


async def main(phone: str = DEFAULT_PHONE) -> int:
    logging.basicConfig(level=logging.WARNING)
    _prepare_console()
    settings = get_settings()

    try:
        from app.banco import get_sessionmaker  # noqa: PLC0415
    except Exception as exc:  # sem banco no ar a CLI avisa em vez de estourar
        print(f"{_ERR}Não consegui carregar app.banco: {exc}{_OFF}")
        return 1

    sessionmaker = get_sessionmaker()
    info = settings_snapshot()

    print("=" * 60)
    print(f" {settings.store_name} — simulador de WhatsApp no terminal")
    print(f" LLM: {info['llm']} | fake_mode: {info['fake_mode']} | telefone: {phone}")
    print(" Comandos: /reset  /estado  /sair")
    print("=" * 60)
    if not settings.fake_mode:
        _print_info("Atenção: FAKE_MODE=false — este chat usa o LLM real e gasta tokens.")

    while True:
        try:
            text = input("\nvocê > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not text:
            continue
        if text in {"/sair", "/quit", "/exit"}:
            return 0
        if text == "/estado":
            await _show_state(sessionmaker, phone)
            continue
        if text == "/reset":
            try:
                async with sessionmaker() as db:
                    await reset_session(db, phone, CHANNEL)
                    await db.commit()
                _print_info("[conversa reiniciada]")
            except Exception as exc:
                print(f"{_ERR}erro ao reiniciar: {exc}{_OFF}")
            continue

        try:
            async with sessionmaker() as db:
                replies = await handle_inbound(
                    db, InboundMessage(phone=phone, text=text), channel_name=CHANNEL
                )
                await db.commit()
        except Exception as exc:
            print(f"{_ERR}erro ao processar: {exc}{_OFF}")
            continue

        if not replies:
            _print_info("[sem resposta — conversa em atendimento humano]")
        for reply in replies:
            _print_bot(reply)

        await _show_state(sessionmaker, phone)


def _run(coro) -> int:
    """No Windows o psycopg async não funciona no ProactorEventLoop (o padrão).

    Sem isto, toda query levanta `Psycopg cannot use the 'ProactorEventLoop'`.
    """
    if sys.platform == "win32":
        return asyncio.run(coro, loop_factory=asyncio.SelectorEventLoop)
    return asyncio.run(coro)


if __name__ == "__main__":
    argv_phone = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PHONE
    raise SystemExit(_run(main(argv_phone)))
