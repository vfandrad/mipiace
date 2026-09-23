"""Agrupamento de mensagens seguidas (app/agent/inbox.py).

Cobre o comportamento que o cliente percebe: escrever picado deve render uma
resposta só, considerando tudo o que ele escreveu.
"""

from __future__ import annotations

import asyncio

import pytest

from app.agent import inbox
from app.agent.whatsapp import InboundMessage
from app.core.config import get_settings


def msg(text: str, *, phone: str = "5511999990000", id_: str = "m1") -> InboundMessage:
    return InboundMessage(phone=phone, text=text, provider_message_id=id_)


@pytest.fixture
def janela_curta(monkeypatch):
    """Mesma lógica, prazo de teste — ninguém espera 3s numa suíte."""
    monkeypatch.setattr(get_settings(), "wa_debounce_seconds", 0.05)
    yield
    inbox._buffers.clear()


@pytest.mark.asyncio
async def test_baloes_seguidos_viram_um_turno_so(janela_curta) -> None:
    turnos: list[InboundMessage] = []

    async def handler(message: InboundMessage) -> None:
        turnos.append(message)

    await inbox.submit(msg("quero um pote", id_="m1"), handler)
    await inbox.submit(msg("G", id_="m2"), handler)
    await inbox.submit(msg("de pistache e morango", id_="m3"), handler)
    await inbox.drain()

    assert len(turnos) == 1
    assert turnos[0].text == "quero um pote\nG\nde pistache e morango"
    # O id do turno é o da última mensagem: é ele que o runner usa para
    # reconhecer a reentrega do mesmo turno.
    assert turnos[0].provider_message_id == "m3"


@pytest.mark.asyncio
async def test_clientes_diferentes_nao_se_misturam(janela_curta) -> None:
    turnos: list[InboundMessage] = []

    async def handler(message: InboundMessage) -> None:
        turnos.append(message)

    await inbox.submit(msg("oi", phone="551199990001", id_="a"), handler)
    await inbox.submit(msg("oi", phone="551199990002", id_="b"), handler)
    await inbox.drain()

    assert sorted(t.phone for t in turnos) == ["551199990001", "551199990002"]


@pytest.mark.asyncio
async def test_mensagem_depois_do_prazo_e_outro_turno(janela_curta) -> None:
    turnos: list[InboundMessage] = []

    async def handler(message: InboundMessage) -> None:
        turnos.append(message)

    await inbox.submit(msg("oi", id_="m1"), handler)
    await inbox.drain()
    await inbox.submit(msg("quero um pote G", id_="m2"), handler)
    await inbox.drain()

    assert [t.text for t in turnos] == ["oi", "quero um pote G"]


@pytest.mark.asyncio
async def test_handler_que_explode_nao_derruba_o_proximo(janela_curta) -> None:
    turnos: list[str] = []

    async def handler(message: InboundMessage) -> None:
        turnos.append(message.text)
        raise RuntimeError("banco fora do ar")

    await inbox.submit(msg("oi", id_="m1"), handler)
    await inbox.drain()
    await inbox.submit(msg("oi de novo", id_="m2"), handler)
    await inbox.drain()

    assert turnos == ["oi", "oi de novo"]


@pytest.mark.asyncio
async def test_janela_zero_processa_na_hora(monkeypatch) -> None:
    """Desligar o agrupamento tem que devolver o comportamento antigo."""
    monkeypatch.setattr(get_settings(), "wa_debounce_seconds", 0.0)
    turnos: list[str] = []

    async def handler(message: InboundMessage) -> None:
        turnos.append(message.text)

    await inbox.submit(msg("oi"), handler)
    assert turnos == ["oi"]  # sem drain: já rodou
    assert not asyncio.all_tasks() - {asyncio.current_task()}
