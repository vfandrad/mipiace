"""Nota de voz do cliente: reconhecer, baixar e transcrever.

O WhatsApp entrega áudio como `audioMessage` no webhook, sem o conteúdo — só
os metadados e a chave da mensagem. Estes testes cobrem os três degraus:
reconhecer que é áudio (`_to_inbound`), baixar o conteúdo pela Evolution API
(`fetch_media_base64`) e transcrever (`resolve_audio_message`) — sempre sem
rede de verdade.
"""

from __future__ import annotations

import base64
from typing import Any
from uuid import uuid4

import pytest

from app.agente import (
    EvolutionAdapter,
    FakeAudioTranscriber,
    InboundMessage,
    OpenAIAudioTranscriber,
    get_audio_transcriber,
    resolve_audio_message,
)
from app.configuracao import get_settings


def _raw_audio_message(*, seconds: int | None = 5, message_id: str = "AUDIO1") -> dict[str, Any]:
    return {
        "key": {
            "id": message_id,
            "remoteJid": "5511999998888@s.whatsapp.net",
            "fromMe": False,
        },
        "pushName": "Cliente",
        "message": {
            "audioMessage": {
                "mimetype": "audio/ogg; codecs=opus",
                "seconds": seconds,
                "ptt": True,
            }
        },
    }


# ---------------------------------------------------------------------------
# Reconhecer o áudio no webhook
# ---------------------------------------------------------------------------

def test_to_inbound_reconhece_audio_sem_texto() -> None:
    message = EvolutionAdapter._to_inbound(_raw_audio_message())
    assert message is not None
    assert message.media_type == "audio"
    assert message.text == ""
    assert message.provider_message_id == "AUDIO1"


def test_parse_webhook_de_audio_devolve_a_mensagem() -> None:
    payload = {"event": "messages.upsert", "data": _raw_audio_message()}
    messages = EvolutionAdapter(get_settings()).parse_webhook(payload)
    assert len(messages) == 1
    assert messages[0].media_type == "audio"


def test_outro_tipo_de_midia_sem_texto_continua_ignorado() -> None:
    """Imagem, figurinha etc. seguem descartadas — só áudio ganhou tratamento."""
    raw = {
        "key": {"id": "IMG1", "remoteJid": "5511999998888@s.whatsapp.net", "fromMe": False},
        "message": {"imageMessage": {"mimetype": "image/jpeg"}},
    }
    assert EvolutionAdapter._to_inbound(raw) is None


# ---------------------------------------------------------------------------
# Baixar o conteúdo pela Evolution API
# ---------------------------------------------------------------------------

class _RespostaFalsa:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _ClienteFalso:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.chamadas = 0

    async def post(self, *args: Any, **kwargs: Any) -> _RespostaFalsa:
        self.chamadas += 1
        return _RespostaFalsa(self._payload)


class _ClienteQueFalhaUmaVez:
    """A primeira chamada explode; a segunda funciona — cobre a retentativa."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.chamadas = 0

    async def post(self, *args: Any, **kwargs: Any) -> _RespostaFalsa:
        self.chamadas += 1
        if self.chamadas == 1:
            raise ConnectionError("Evolution instável")
        return _RespostaFalsa(self._payload)


@pytest.fixture
def com_chave(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "evolution_api_key", "chave-de-teste")
    return settings


@pytest.mark.asyncio
async def test_fetch_media_base64_baixa_e_decodifica(com_chave) -> None:
    conteudo = base64.b64encode(b"conteudo do audio").decode()
    cliente = _ClienteFalso({"base64": conteudo, "mimetype": "audio/ogg; codecs=opus"})
    adapter = EvolutionAdapter(com_chave, client=cliente)

    resultado = await adapter.fetch_media_base64({"id": "AUDIO1"})

    assert resultado == (b"conteudo do audio", "audio/ogg; codecs=opus")
    assert cliente.chamadas == 1


@pytest.mark.asyncio
async def test_fetch_media_base64_tenta_de_novo_apos_falha(com_chave) -> None:
    conteudo = base64.b64encode(b"oi").decode()
    cliente = _ClienteQueFalhaUmaVez({"base64": conteudo, "mimetype": "audio/ogg"})
    adapter = EvolutionAdapter(com_chave, client=cliente)

    resultado = await adapter.fetch_media_base64({"id": "AUDIO1"})

    assert resultado == (b"oi", "audio/ogg")
    assert cliente.chamadas == 2


@pytest.mark.asyncio
async def test_fetch_media_base64_sem_chave_devolve_none(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "evolution_api_key", None)
    adapter = EvolutionAdapter(settings, client=_ClienteFalso({}))
    assert await adapter.fetch_media_base64({"id": "AUDIO1"}) is None


@pytest.mark.asyncio
async def test_fetch_media_base64_sem_base64_na_resposta_devolve_none(com_chave) -> None:
    adapter = EvolutionAdapter(com_chave, client=_ClienteFalso({"mimetype": "audio/ogg"}))
    assert await adapter.fetch_media_base64({"id": "AUDIO1"}) is None


# ---------------------------------------------------------------------------
# Transcrição
# ---------------------------------------------------------------------------

class _TranscricaoFalsa:
    def __init__(self, texto: str) -> None:
        self.text = texto


class _ClienteOpenAIQueFalhaUmaVez:
    """Mesma ideia de `_ClienteQueFalhaUmaVez` do download: 1ª chamada explode."""

    def __init__(self, texto: str) -> None:
        self.chamadas = 0
        self._texto = texto
        self.audio = self
        self.transcriptions = self

    async def create(self, **kwargs: Any) -> _TranscricaoFalsa:
        self.chamadas += 1
        if self.chamadas == 1:
            raise ConnectionError("OpenAI instável")
        return _TranscricaoFalsa(self._texto)


@pytest.mark.asyncio
async def test_transcricao_tenta_de_novo_apos_falha_passageira() -> None:
    """Mesmo padrão de `fetch_media_base64`: 1ª chamada falha, 2ª funciona."""
    settings = get_settings()
    cliente = _ClienteOpenAIQueFalhaUmaVez("quero um pote grande")
    transcriber = OpenAIAudioTranscriber(settings, client=cliente)

    texto = await transcriber.transcribe(audio=b"...", mimetype="audio/ogg")

    assert texto == "quero um pote grande"
    assert cliente.chamadas == 2


@pytest.mark.asyncio
async def test_fake_transcriber_decodifica_os_bytes_como_texto() -> None:
    texto = await FakeAudioTranscriber().transcribe(
        audio=b"quero um pote grande de pistache", mimetype="audio/ogg"
    )
    assert texto == "quero um pote grande de pistache"


@pytest.mark.asyncio
async def test_fake_transcriber_bytes_invalidos_devolve_none() -> None:
    texto = await FakeAudioTranscriber().transcribe(audio=b"\xff\xfe", mimetype="audio/ogg")
    assert texto is None


def test_get_audio_transcriber_fake_mode_usa_o_falso() -> None:
    get_audio_transcriber.cache_clear()
    settings = get_settings()
    assert settings.fake_mode is True
    try:
        transcriber = get_audio_transcriber()
        assert isinstance(transcriber, FakeAudioTranscriber)
    finally:
        get_audio_transcriber.cache_clear()


def test_get_audio_transcriber_sem_chave_em_producao_devolve_none(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "fake_mode", False)
    monkeypatch.setattr(settings, "openai_api_key", None)
    get_audio_transcriber.cache_clear()
    try:
        assert get_audio_transcriber() is None
    finally:
        get_audio_transcriber.cache_clear()


# ---------------------------------------------------------------------------
# resolve_audio_message: a orquestração
# ---------------------------------------------------------------------------

class _AdapterFalso:
    def __init__(self, resultado: tuple[bytes, str] | None) -> None:
        self._resultado = resultado
        self.chamado_com: dict[str, Any] | None = None

    async def fetch_media_base64(self, message_key: dict[str, Any]):
        self.chamado_com = message_key
        return self._resultado


@pytest.mark.asyncio
async def test_resolve_audio_message_transcreve_com_sucesso() -> None:
    message = InboundMessage(
        phone="5511999998888",
        text="",
        media_type="audio",
        raw=_raw_audio_message(),
    )
    adapter = _AdapterFalso((b"quero um pote grande", "audio/ogg"))

    resolvida = await resolve_audio_message(
        message, adapter=adapter, transcriber=FakeAudioTranscriber()
    )

    assert resolvida.text == "quero um pote grande"
    assert adapter.chamado_com == message.raw["key"]


@pytest.mark.asyncio
async def test_resolve_audio_message_sem_transcritor_devolve_texto_vazio() -> None:
    message = InboundMessage(
        phone="5511999998888", text="", media_type="audio", raw=_raw_audio_message()
    )
    resolvida = await resolve_audio_message(
        message, adapter=_AdapterFalso((b"x", "audio/ogg")), transcriber=None
    )
    assert resolvida.text == ""


@pytest.mark.asyncio
async def test_resolve_audio_message_evolution_fora_do_ar_devolve_texto_vazio() -> None:
    message = InboundMessage(
        phone="5511999998888", text="", media_type="audio", raw=_raw_audio_message()
    )
    resolvida = await resolve_audio_message(
        message, adapter=_AdapterFalso(None), transcriber=FakeAudioTranscriber()
    )
    assert resolvida.text == ""


@pytest.mark.asyncio
async def test_resolve_audio_message_acima_do_limite_nao_baixa(monkeypatch) -> None:
    """Áudio longo demais nem chega a custar a chamada de download."""
    settings = get_settings()
    monkeypatch.setattr(settings, "audio_max_seconds", 60)
    message = InboundMessage(
        phone="5511999998888",
        text="",
        media_type="audio",
        raw=_raw_audio_message(seconds=600),
    )
    adapter = _AdapterFalso((b"nao deveria ser usado", "audio/ogg"))

    resolvida = await resolve_audio_message(
        message, adapter=adapter, transcriber=FakeAudioTranscriber()
    )

    assert resolvida.text == ""
    assert adapter.chamado_com is None


# ---------------------------------------------------------------------------
# handle_inbound: falha na transcrição não conta como "não entendi"
# ---------------------------------------------------------------------------

class _BancoDeAudio:
    """Fake mínimo: conversa nova, sem mensagem prévia, registra os inserts."""

    def __init__(self) -> None:
        self.id = uuid4()
        self.mensagens: list[dict[str, Any]] = []

    async def execute(self, statement: Any, params: Any = None):
        sql = str(statement)

        class _Resultado:
            def __init__(self, valor: Any) -> None:
                self._valor = valor

            def first(self) -> Any:
                return self._valor

            def scalar_one(self) -> Any:
                return self._valor

        if "conversation_messages" in sql and "INSERT" in sql.upper():
            self.mensagens.append(params or {})
            return _Resultado(None)
        if "provider_message_id" in sql and "SELECT" in sql.upper():
            return _Resultado(None)
        if "FROM conversations" in sql and "WHERE phone" in sql:
            return _Resultado(None)
        if "INSERT INTO conversations" in sql:
            return _Resultado(self.id)
        raise AssertionError(f"consulta inesperada no fake de áudio: {sql}")


@pytest.mark.asyncio
async def test_handle_inbound_audio_sem_transcricao_nao_chama_a_ia(monkeypatch) -> None:
    from app import agente

    async def transcritor_indisponivel(message, *, adapter, transcriber):
        return message.model_copy(update={"text": ""})

    monkeypatch.setattr(agente, "resolve_audio_message", transcritor_indisponivel)

    chamou_llm = False

    async def _interpret_nao_deveria_rodar(*args, **kwargs):
        nonlocal chamou_llm
        chamou_llm = True
        raise AssertionError("não deveria chamar a IA com áudio não transcrito")

    monkeypatch.setattr(agente, "_interpret", _interpret_nao_deveria_rodar)

    db = _BancoDeAudio()
    message = InboundMessage(
        phone="5511999998888",
        text="",
        media_type="audio",
        provider_message_id="AUDIO1",
        raw=_raw_audio_message(),
    )

    replies = await agente.handle_inbound(db, message)

    assert not chamou_llm
    assert replies == [agente.r.audio_nao_transcrito()]
    assert any("[áudio não transcrito]" in m.get("content", "") for m in db.mensagens)
