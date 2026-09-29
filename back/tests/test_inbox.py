"""Agrupamento de mensagens seguidas (app/agent/inbox.py).

Cobre o comportamento que o cliente percebe: escrever picado deve render uma
resposta só, considerando tudo o que ele escreveu.
"""

from __future__ import annotations

import asyncio

import pytest

from app import agente as inbox
from app.agente import InboundMessage
from app.configuracao import get_settings


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
async def test_reentrega_dentro_da_janela_nao_duplica_texto(janela_curta) -> None:
    """Retry de webhook do gateway, ainda dentro do agrupamento, não conta duas vezes.

    Sem checar o id antes de somar ao buffer, a reentrega de um balão que já
    está NESTA janela duplicava o texto — o LLM lia "quero um pote" duas
    vezes na mesma mensagem, como se o cliente tivesse pedido dois.
    """
    turnos: list[InboundMessage] = []

    async def handler(message: InboundMessage) -> None:
        turnos.append(message)

    await inbox.submit(msg("quero um pote", id_="m1"), handler)
    await inbox.submit(msg("quero um pote", id_="m1"), handler)  # reentrega do m1
    await inbox.submit(msg("de pistache", id_="m2"), handler)
    await inbox.drain()

    assert len(turnos) == 1
    assert turnos[0].text == "quero um pote\nde pistache"


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


@pytest.mark.asyncio
async def test_mesmo_telefone_nao_roda_dois_turnos_ao_mesmo_tempo(janela_curta) -> None:
    """Um turno lento (LLM, ritmo de envio) não pode ser pisado por outro.

    Sem a trava por telefone, uma mensagem que chega depois que a janela de
    agrupamento fechou mas antes do turno anterior salvar o estado dispararia
    um segundo `handle_inbound` sobre a MESMA conversa — os dois leriam o
    mesmo estado do banco, e quem salvasse por último apagaria o que o outro
    mudou.
    """
    em_andamento = 0
    pico_de_concorrencia = 0
    ordem: list[str] = []

    async def handler(message: InboundMessage) -> None:
        nonlocal em_andamento, pico_de_concorrencia
        em_andamento += 1
        pico_de_concorrencia = max(pico_de_concorrencia, em_andamento)
        try:
            await asyncio.sleep(0.1)  # mais lento que a janela de debounce (0.05s)
            ordem.append(message.text)
        finally:
            em_andamento -= 1

    await inbox.submit(msg("primeiro turno", id_="m1"), handler)
    await asyncio.sleep(0.08)  # a janela do primeiro turno já fechou, ele está rodando
    await inbox.submit(msg("segundo turno", id_="m2"), handler)
    await inbox.drain()

    assert pico_de_concorrencia == 1
    assert ordem == ["primeiro turno", "segundo turno"]
