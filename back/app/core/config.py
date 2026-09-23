"""Configuração central via variáveis de ambiente.

Regra do projeto: nenhum segredo hardcoded em código. Tudo passa por aqui.
Com FAKE_MODE=true o sistema roda inteiro localmente sem nenhuma chave de API
externa (LLM e pagamento usam implementações falsas determinísticas).
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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
    max_nlu_failures: int = 3  # depois disso, cai para atendimento humano
    #: Quanto tempo o bot fica mudo esperando alguém da loja assumir a conversa.
    #: Passado isso sem resposta humana, ele reassume em vez de deixar o cliente
    #: falando sozinho — escalar para humano só ajuda se houver humano.
    handoff_return_minutes: int = 15

    # --- Dados da loja -------------------------------------------------------
    # Nada aqui é obrigatório, e é de propósito: vazio, o agente admite que não
    # sabe em vez de inventar ("a gente abre às 10h" numa loja fechada é pior
    # do que "não tenho certeza"). Preenchido, ele responde na hora — são as
    # quatro perguntas que mais aparecem e que o catálogo não responde.
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
