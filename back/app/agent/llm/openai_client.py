"""Cliente de LLM (OpenAI), com function calling para saída estruturada.

Espelha `anthropic_client.py` no contrato e nas garantias — só troca o SDK:

* **tool call obrigatório** (`tool_choice`): o modelo é forçado a chamar
  `registrar_interpretacao`, cujo `parameters` espelha `NluResult`. Não sobra
  texto livre para parsear.
* **falha nunca sobe**: qualquer erro (timeout, rate limit, resposta sem tool
  call) vira `NluResult(intent=DESCONHECIDO)`. A máquina de estados já sabe
  repreguntar; derrubar a request do WhatsApp seria bem pior.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Sequence

from app.agent.llm.base import ExtractedAddress, NluResult, Turn
from app.agent.llm.prompts import TOOL_NAME, build_system_blocks, tool_schema
from app.core.config import Settings, get_settings
from app.domain.catalog import CatalogSnapshot
from app.domain.enums import ConversationState, Intent

logger = logging.getLogger(__name__)


def _function_tool() -> dict[str, Any]:
    """Converte o schema Anthropic (`input_schema`) para o formato OpenAI."""
    schema = tool_schema()
    return {
        "type": "function",
        "function": {
            "name": schema["name"],
            "description": schema["description"],
            "parameters": schema["input_schema"],
        },
    }


def _system_text(state: ConversationState, catalog: CatalogSnapshot) -> str:
    """OpenAI recebe uma única mensagem de sistema; junta os blocos do Anthropic."""
    return "\n\n".join(block["text"] for block in build_system_blocks(state, catalog))


class OpenAILLMClient:
    """Implementa `LLMClient` chamando a API de Chat Completions da OpenAI."""

    name = "openai"

    def __init__(self, settings: Settings | None = None, client: Any | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = client  # injetável em teste
        self._tool = _function_tool()

    # -- infraestrutura ----------------------------------------------------

    def _ensure_client(self) -> Any:
        if self._client is None:
            from openai import AsyncOpenAI  # noqa: PLC0415 (import tardio)

            if not self._settings.openai_api_key:
                raise RuntimeError("OPENAI_API_KEY não configurada")
            self._client = AsyncOpenAI(
                api_key=self._settings.openai_api_key,
                timeout=self._settings.llm_timeout_seconds,
            )
        return self._client

    @staticmethod
    def _messages(
        system_text: str, history: Sequence[Turn], message: str
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_text}]
        for turn in history[-8:]:
            role = "user" if turn.role == "cliente" else "assistant"
            messages.append({"role": role, "content": turn.content})
        messages.append({"role": "user", "content": message})
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
            response = await client.chat.completions.create(
                model=self._settings.openai_model,
                max_tokens=self._settings.llm_max_tokens,
                messages=self._messages(_system_text(state, catalog), history, message),
                tools=[self._tool],
                tool_choice={"type": "function", "function": {"name": TOOL_NAME}},
            )
        except Exception:
            # Timeout, rate limit, chave inválida: a conversa continua viva.
            logger.exception("falha ao chamar o LLM; caindo para DESCONHECIDO")
            return NluResult(intent=Intent.DESCONHECIDO, model=self._settings.openai_model)

        return self._to_result(response)

    # -- parsing -----------------------------------------------------------

    def _to_result(self, response: Any) -> NluResult:
        usage = self._usage(response)
        model = getattr(response, "model", self._settings.openai_model)

        payload = self._tool_input(response)
        if payload is None:
            logger.warning(
                "resposta do LLM sem tool call: %r", getattr(response, "id", None)
            )
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
        choices = getattr(response, "choices", None) or []
        if not choices:
            return None
        message = getattr(choices[0], "message", None)
        tool_calls = getattr(message, "tool_calls", None) or []
        for call in tool_calls:
            function = getattr(call, "function", None)
            if getattr(function, "name", None) != TOOL_NAME:
                continue
            raw_args = getattr(function, "arguments", None)
            if not raw_args:
                continue
            try:
                payload = json.loads(raw_args)
            except json.JSONDecodeError:
                logger.warning("arguments da tool não são JSON válido: %r", raw_args)
                return None
            return payload if isinstance(payload, dict) else None
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
        """Tokens gastos, inclusive os de cache automático da OpenAI."""
        usage = getattr(response, "usage", None)
        if usage is None:
            return None
        data = {
            "input_tokens": getattr(usage, "prompt_tokens", None),
            "output_tokens": getattr(usage, "completion_tokens", None),
        }
        details = getattr(usage, "prompt_tokens_details", None)
        cached = getattr(details, "cached_tokens", None) if details else None
        if cached:
            data["cache_read_input_tokens"] = cached
        return {k: v for k, v in data.items() if v is not None}
