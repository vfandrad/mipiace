"""A trava de contatos: com a loja no ar, só quem está na lista conversa."""

from __future__ import annotations

import pytest

from app.agent.whatsapp import phone_allowed
from app.core.config import get_settings

DONO = "5569993061196"


@pytest.fixture
def travado(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "allowed_phones", [DONO])
    return settings


def test_lista_vazia_libera_todo_mundo():
    """É o estado normal de produção: a gelateria atende quem chegar."""
    settings = get_settings()
    assert settings.allowed_phones == []
    assert phone_allowed("5511999998888") is True


def test_numero_da_lista_passa(travado):
    assert phone_allowed(DONO, travado) is True


def test_qualquer_outro_numero_e_barrado(travado):
    for outro in ("5511999998888", "5569993061197", "554199990000"):
        assert phone_allowed(outro, travado) is False


def test_aceita_o_mesmo_numero_escrito_de_outro_jeito(travado):
    """O WhatsApp entrega o celular brasileiro com e sem o nono dígito."""
    assert phone_allowed("+55 69 99306-1196", travado) is True
    assert phone_allowed("556993061196", travado) is True  # sem o nono dígito


def test_mesmo_final_em_outro_ddd_nao_passa(travado):
    """O que identifica a linha é DDI + DDD + os 8 finais, não só os 8 finais."""
    assert phone_allowed("5511993061196", travado) is False


def test_numero_curto_demais_nao_passa_por_sufixo(travado):
    """Sem piso de dígitos, "1196" casaria com o dono por coincidência."""
    assert phone_allowed("1196", travado) is False
    assert phone_allowed("", travado) is False


@pytest.mark.asyncio
async def test_adapter_recusa_enviar_para_fora_da_lista(travado, monkeypatch):
    from app.agent.whatsapp import EvolutionAdapter

    monkeypatch.setattr(travado, "evolution_api_key", "chave-de-teste")
    enviados: list[str] = []

    class ClientQueNuncaDeveriaSerUsado:
        async def post(self, *a, **kw):  # pragma: no cover - o teste falha antes
            enviados.append("post")
            raise AssertionError("não deveria ter enviado")

    adapter = EvolutionAdapter(travado, client=ClientQueNuncaDeveriaSerUsado())
    assert await adapter.send_text("5511999998888", "oi") is None
    assert enviados == []
