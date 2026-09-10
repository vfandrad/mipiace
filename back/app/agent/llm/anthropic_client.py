"""Cliente real de LLM (Anthropic), com tool use para saída estruturada.

Duas decisões que valem explicação:

* **tool use obrigatório** (`tool_choice`): em vez de pedir JSON no texto e
  torcer, o modelo é forçado a chamar `registrar_interpretacao`, cujo
  input_schema espelha `NluResult`. Não sobra formato livre para parsear.
* **falha nunca sobe**: qualquer erro (timeout, rate limit, resposta
  inesperada) vira `NluResult(intent=DESCONHECIDO)`. A máquina de estados já
  sabe repreguntar; derrubar a request do WhatsApp seria bem pior.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

from app.agent.llm.base import ExtractedAddress, NluResult, Turn
from app.agent.llm.prompts import TOOL_NAME, build_system_blocks, tool_schema
from app.core.config import Settings, get_settings
from app.domain.catalog import CatalogSnapshot
from app.domain.enums import ConversationState, Intent

logger = logging.getLogger(__name__)


class AnthropicLLMClient:
    """Implementa `LLMClient` chamando a API de Mensagens da Anthropic."""

    name = "anthropic"

    def __init__(self, settings: Settings | None = None, client: Any | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = client  # injetável em teste
        self._tool = tool_schema()

    # -- infraestrutura ----------------------------------------------------

    def _ensure_client(self) -> Any:
        if self._client is None:
            from anthropic import AsyncAnthropic  # noqa: PLC0415 (import tardio)

            if not self._settings.anthropic_api_key:
                raise RuntimeError("ANTHROPIC_API_KEY não configurada")
            self._client = AsyncAnthropic(
                api_key=self._settings.anthropic_api_key,
                timeout=self._settings.llm_timeout_seconds,
            )
        return self._client

    @staticmethod
    def _messages(history: Sequence[Turn], message: str) -> list[dict[str, Any]]:
        """Histórico recente + a mensagem atual, alternando papéis."""
        messages: list[dict[str, Any]] = []
        for turn in history[-8:]:
            role = "user" if turn.role == "cliente" else "assistant"
            if messages and messages[-1]["role"] == role:
                messages[-1]["content"] += f"\n{turn.content}"
                continue
            messages.append({"role": role, "content": turn.content})
        if not messages or messages[-1]["role"] != "user":
            messages.append({"role": "user", "content": message})
        else:
            messages[-1]["content"] += f"\n{message}"
        # A API exige que a conversa comece com o cliente.
        while messages and messages[0]["role"] != "user":
            messages.pop(0)
        return messages

    # -- contrato ----------------------------------------------------------

    async def extract(
        self,
        *,
        state: ConversationState,
        catalog: CatalogSnapshot,
        history: Sequence[Turn],
        message: str,
    ) -> NluResult:
        try:
            client = self._ensure_client()
            response = await client.messages.create(
                model=self._settings.llm_model,
                max_tokens=self._settings.llm_max_tokens,
                system=build_system_blocks(state, catalog),
                tools=[self._tool],
                tool_choice={"type": "tool", "name": TOOL_NAME},
                messages=self._messages(history, message),
            )
        except Exception:
            # Timeout, rate limit, chave inválida: a conversa continua viva.
            logger.exception("falha ao chamar o LLM; caindo para DESCONHECIDO")
            return NluResult(intent=Intent.DESCONHECIDO, model=self._settings.llm_model)

        return self._to_result(response)

    # -- parsing -----------------------------------------------------------

    def _to_result(self, response: Any) -> NluResult:
        usage = self._usage(response)
        model = getattr(response, "model", self._settings.llm_model)

        payload = self._tool_input(response)
        if payload is None:
            logger.warning("resposta do LLM sem tool_use: %r", getattr(response, "id", None))
            return NluResult(intent=Intent.DESCONHECIDO, model=model, usage=usage)

        try:
            result = NluResult(
                intent=self._intent(payload.get("intent")),
                confidence=float(payload.get("confidence") or 0.0),
                product_query=payload.get("product_query") or None,
                complement_queries=[
                    str(q) for q in (payload.get("complement_queries") or []) if q
                ],
                quantity=self._quantity(payload.get("quantity")),
                address=self._address(payload.get("address")),
                customer_name=payload.get("customer_name") or None,
                note=payload.get("note") or None,
            )
        except Exception:
            logger.exception("input da tool fora do contrato: %r", payload)
            return NluResult(intent=Intent.DESCONHECIDO, model=model, usage=usage)

        result.model = model
        result.usage = usage
        return result

    @staticmethod
    def _tool_input(response: Any) -> dict[str, Any] | None:
        for block in getattr(response, "content", []) or []:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == TOOL_NAME:
                payload = getattr(block, "input", None)
                if isinstance(payload, dict):
                    return payload
        return None

    @staticmethod
    def _intent(raw: Any) -> Intent:
        try:
            return Intent(str(raw))
        except ValueError:
            logger.warning("intenção fora do enum: %r", raw)
            return Intent.DESCONHECIDO

    @staticmethod
    def _quantity(raw: Any) -> int | None:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    @staticmethod
    def _address(raw: Any) -> ExtractedAddress | None:
        if not isinstance(raw, dict):
            return None
        address = ExtractedAddress(**{k: v for k, v in raw.items() if v})
        return address if address.model_dump(exclude_none=True) else None

    @staticmethod
    def _usage(response: Any) -> dict[str, Any] | None:
        """Tokens gastos — inclusive os de cache, para auditar o custo real."""
        usage = getattr(response, "usage", None)
        if usage is None:
            return None
        fields = (
            "input_tokens",
            "output_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        )
        data = {f: getattr(usage, f, None) for f in fields}
        return {k: v for k, v in data.items() if v is not None}

