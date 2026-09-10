"""REPL de terminal para conversar com o agente.

    cd back && python -m app.cli.chat

É a forma mais rápida de ver a máquina de estados funcionando: além das
respostas, imprime o estado a cada turno, que é justamente o que se quer olhar
quando o fluxo trava.

Comandos: /reset (recomeça), /estado (mostra o estado e o carrinho),
/sair (encerra).
"""

from __future__ import annotations

import asyncio
import logging
import sys

from app.agent.channels.base import InboundMessage
from app.agent.renderer import money
from app.agent.runner import handle_inbound, settings_snapshot
from app.agent.session import load_or_create, reset_session
from app.core.config import get_settings

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
        f"subtotal={money(cart.subtotal)} falhas={conversation.fail_count} "
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
        from app.db.session import get_sessionmaker
    except Exception as exc:  # o Agente 1 é dono desta camada
        print(f"{_ERR}Não consegui carregar app.db.session: {exc}{_OFF}")
        return 1

    sessionmaker = get_sessionmaker()
    info = settings_snapshot()

    print("=" * 60)
    print(" Mi Piace — simulador de WhatsApp no terminal")
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
