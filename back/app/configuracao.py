"""Configuração, log e autenticação — as três coisas que todo o resto usa.

Regra do projeto: nenhum segredo hardcoded em código. Tudo passa pelo
`Settings` daqui. Com FAKE_MODE=true o sistema roda inteiro localmente sem
nenhuma chave de API externa (LLM e pagamento usam implementações falsas
determinísticas).

O log e a checagem da chave de API moram no mesmo arquivo porque os dois só
existem em função da configuração: o nível do log sai do `debug`, e a chave
exigida no header sai do `admin_api_key`.
"""

from __future__ import annotations

import logging
import secrets
import sys
from decimal import Decimal
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Aplicação -----------------------------------------------------------
    app_name: str = "Mi Piace API"
    environment: str = "development"
    debug: bool = True
    public_base_url: str = "http://localhost:8000"

    # --- Banco ---------------------------------------------------------------
    database_url: str = "postgresql+psycopg://mipiace:mipiace@localhost:5432/mipiace"

    # --- Segurança -----------------------------------------------------------
    # Chave exigida no header X-API-Key para as rotas administrativas.
    admin_api_key: str = "dev-local-key"
    # NoDecode impede o pydantic-settings de tentar json.loads() no valor cru do
    # .env; queremos aceitar o formato simples "http://a,http://b".
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:8080"]
    )

    # --- Modo de desenvolvimento --------------------------------------------
    # true  -> LLM falso + pagamento falso, roda sem chave nenhuma
    # false -> OpenAI + Mercado Pago de verdade
    fake_mode: bool = True

    # --- LLM (OpenAI) --------------------------------------------------------
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    llm_max_tokens: int = 1024
    llm_timeout_seconds: float = 20.0

    # --- WhatsApp via Evolution API (gateway self-hosted): não exige app nem
    # número comercial aprovado, basta parear um QR code.
    evolution_api_url: str = "http://localhost:8081"
    evolution_api_key: str | None = None
    evolution_instance: str = "mipiace"
    # Evolution API não assina o corpo do webhook como a Meta faz; a validação
    # é um token compartilhado na query string da URL cadastrada em WEBHOOK_GLOBAL_URL.
    evolution_webhook_token: str | None = None

    # --- Trava de contatos ---------------------------------------------------
    # Lista de telefones autorizados a conversar com o agente. VAZIA = aberto,
    # que é o estado normal de produção. Com um número dentro, o sistema vira
    # uma sala fechada: mensagem de qualquer outro número é descartada e o bot
    # se recusa a enviar para fora da lista. É o modo de testar com a loja no
    # ar sem risco de atender cliente de verdade pela metade.
    allowed_phones: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # --- Ritmo de envio no WhatsApp (ver app/agent/pacing.py) ----------------
    # O cliente é não-oficial: o que protege o número é o bot não se comportar
    # como bot. Estes três números são o freio.
    #: Velocidade média de digitação simulada, em palavras por minuto.
    wa_typing_wpm: float = 45.0
    #: Intervalo mínimo entre duas mensagens para o MESMO contato.
    wa_min_seconds_between_messages: float = 3.0
    #: Teto da instância inteira, por minuto (a comunidade situa o risco a
    #: partir de ~20/min; ficamos abaixo de propósito).
    wa_max_messages_per_minute: int = 12
    #: Janela para juntar mensagens seguidas do mesmo cliente antes de pensar.
    #: Quem pede pelo WhatsApp escreve picado ("quero um pote" / "G" / "de
    #: pistache"); responder balão a balão gera três respostas e confunde a
    #: máquina de estados. 0 desliga o agrupamento (ver app/agent/inbox.py).
    wa_debounce_seconds: float = 3.0

    # --- Mercado Pago --------------------------------------------------------
    mp_access_token: str | None = None
    mp_webhook_secret: str | None = None

    # --- Regras de negócio ---------------------------------------------------
    delivery_fee: Decimal = Decimal("5.00")
    pix_expiration_minutes: int = 30
    session_ttl_minutes: int = 60
    #: Quanto tempo o bot fica mudo esperando alguém da loja assumir a conversa.
    #: Passado isso sem resposta humana, ele reassume em vez de deixar o cliente
    #: falando sozinho — escalar para humano só ajuda se houver humano.
    handoff_return_minutes: int = 15

    # --- Dados da loja -------------------------------------------------------
    # É AQUI que uma segunda empresa é configurada. A Mi Piace é o primeiro caso
    # de uso, não o sistema: nada de nome, emoji ou vocabulário de gelateria
    # deve estar escrito no código. Uma açaiteria sobe o mesmo binário com
    # STORE_NAME e STORE_EMOJI diferentes e um catálogo próprio.
    #
    # O desenho é um deploy por loja — sem `tenant_id`, sem tabela de
    # configuração. Para o tamanho deste produto, uma instância por cliente é
    # mais simples de operar e de entender do que multi-tenancy.

    # Os defaults são os da Mi Piace, e é de propósito: o que a generalização
    # trouxe foi a OPÇÃO de trocar, não a obrigação de configurar. Uma loja
    # nova sobrescreve estas quatro no `.env`; sem elas, o sistema continua
    # sendo o da casa que ele atende hoje — e não um genérico sem identidade.
    #: Como a loja se apresenta ao cliente no WhatsApp e no painel.
    store_name: str = "Mi Piace Gelateria"
    #: Emoji que abre o cardápio e a saudação. Vazio = nenhum.
    store_emoji: str = "🍨"
    #: O ramo, em uma palavra, para o prompt situar o modelo ("gelateria",
    #: "açaiteria", "doceria"). Não muda o que ele pode fazer, só o vocabulário.
    store_segment: str = "gelateria"
    #: Cidade do recebedor — o BR Code do Pix carrega esse campo.
    store_city: str = "SAO PAULO"

    # As quatro abaixo não são obrigatórias, e é de propósito: vazias, o agente
    # admite que não sabe em vez de inventar ("a gente abre às 10h" numa loja
    # fechada é pior do que "não tenho certeza"). Preenchidas, ele responde na
    # hora — são as perguntas que mais aparecem e que o catálogo não responde.
    #: "Seg a sáb, das 14h às 22h"
    store_hours: str | None = None
    #: "Rua das Flores, 123 — Centro"
    store_address: str | None = None
    #: "Centro, Jardim América e Vila Nova"
    store_delivery_area: str | None = None
    #: "40 a 60 minutos"
    store_delivery_estimate: str | None = None

    @field_validator("allowed_phones", mode="before")
    @classmethod
    def _split_phones(cls, value: object) -> object:
        """Aceita "5511...,5569..." do .env; guarda só os dígitos."""
        if isinstance(value, str):
            value = [p for p in value.split(",")]
        if isinstance(value, list):
            return [
                "".join(ch for ch in str(p) if ch.isdigit())
                for p in value
                if "".join(ch for ch in str(p) if ch.isdigit())
            ]
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Aceita "a,b" vindo do .env além de lista JSON."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


# ---------------------------------------------------------------------------
# Log
# ---------------------------------------------------------------------------
# Uma linha por evento, com o nome do módulo — o suficiente para depurar o
# agente e o webhook de pagamento sem trazer dependência de observabilidade.

_CONFIGURED = False

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s | %(message)s"


def setup_logging() -> None:
    """Idempotente: pode ser chamada no import e no startup sem duplicar handler."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    settings = get_settings()
    level = logging.DEBUG if settings.debug else logging.INFO

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [handler]

    # SQLAlchemy é falador demais em DEBUG e afoga o log do agente.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)


# ---------------------------------------------------------------------------
# Autenticação das rotas administrativas
# ---------------------------------------------------------------------------
# Uma chave estática no header `X-API-Key` é o suficiente para o MVP (o painel
# é interno), mas a comparação usa `secrets.compare_digest` para não vazar a
# chave por tempo de resposta.

API_KEY_HEADER = "X-API-Key"

# auto_error=False para devolvermos a mensagem em português no formato do projeto.
_api_key_scheme = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": API_KEY_HEADER},
    )


async def require_api_key(
    api_key: str | None = Depends(_api_key_scheme),
    settings: Settings = Depends(get_settings),
) -> str:
    """Dependência das rotas `/api/*` administrativas."""
    expected = settings.admin_api_key
    if not expected:
        # Sem chave configurada a API ficaria aberta; melhor falhar fechado.
        raise _unauthorized("ADMIN_API_KEY não configurada no servidor.")
    if not api_key:
        raise _unauthorized(f"Header {API_KEY_HEADER} ausente.")
    if not secrets.compare_digest(api_key, expected):
        raise _unauthorized("Chave de API inválida.")
    return api_key


__all__ = [
    "API_KEY_HEADER",
    "Settings",
    "get_logger",
    "get_settings",
    "require_api_key",
    "setup_logging",
]
