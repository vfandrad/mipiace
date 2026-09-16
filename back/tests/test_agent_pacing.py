"""O freio de envio do WhatsApp: demora como gente e respeita um teto."""

from __future__ import annotations

import asyncio

import pytest

from app.agent.pacing import MAX_TYPING_MS, MIN_TYPING_MS, Throttle, typing_delay_ms
from app.core.config import get_settings


def test_delay_nunca_e_instantaneo_nem_eterno():
    for texto in ("oi", "x" * 5_000, "Seu pedido saiu para entrega!"):
        assert MIN_TYPING_MS <= typing_delay_ms(texto) <= MAX_TYPING_MS


def test_delay_cresce_com_o_tamanho_do_texto():
    curto = sum(typing_delay_ms("ok") for _ in range(50)) / 50
    longo = sum(typing_delay_ms("palavra " * 60) for _ in range(50)) / 50
    assert longo > curto


def test_delay_varia_entre_chamadas_iguais():
    """Cadência constante é assinatura de robô; dois envios iguais diferem."""
    amostras = {typing_delay_ms("mesma mensagem de sempre") for _ in range(30)}
    assert len(amostras) > 1


@pytest.mark.asyncio
async def test_mensagens_seguidas_para_o_mesmo_contato_sao_espacadas(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "wa_min_seconds_between_messages", 0.3)
    monkeypatch.setattr(settings, "wa_max_messages_per_minute", 100)

    throttle = Throttle()
    inicio = asyncio.get_running_loop().time()
    for _ in range(3):
        await throttle.acquire("5511999998888")
    decorrido = asyncio.get_running_loop().time() - inicio

    assert decorrido >= 0.6  # dois intervalos entre três envios


@pytest.mark.asyncio
async def test_contatos_diferentes_nao_esperam_um_pelo_outro(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "wa_min_seconds_between_messages", 5.0)
    monkeypatch.setattr(settings, "wa_max_messages_per_minute", 100)

    throttle = Throttle()
    inicio = asyncio.get_running_loop().time()
    await throttle.acquire("5511900000001")
    await throttle.acquire("5511900000002")
    assert asyncio.get_running_loop().time() - inicio < 0.5


@pytest.mark.asyncio
async def test_teto_por_minuto_segura_a_rajada(monkeypatch):
    """O caso que mata o número: laço ou tempestade de webhooks."""
    settings = get_settings()
    monkeypatch.setattr(settings, "wa_min_seconds_between_messages", 0.0)
    monkeypatch.setattr(settings, "wa_max_messages_per_minute", 3)

    throttle = Throttle()
    for i in range(3):
        await throttle.acquire(f"55119000000{i:02d}")

    # O quarto envio dentro do mesmo minuto não passa.
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(throttle.acquire("5511900000099"), timeout=0.5)
