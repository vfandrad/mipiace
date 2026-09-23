"""Cliente de LLM (OpenAI), com function calling para saída estruturada.

Contrato e garantias:

* **tool call obrigatório** (`tool_choice`): o modelo é forçado a chamar
  `registrar_operacoes`, cujo `parameters` espelha `AgentPlan`. Não sobra
  texto livre para parsear.
* **falha nunca sobe**: qualquer erro (timeout, rate limit, resposta sem tool
  call) vira um plano vazio. O executor responde pedindo para repetir; derrubar
  a request do WhatsApp seria bem pior.
* **nada do modelo entra sem passar pelo enum**: ação desconhecida vira
  `no_action`, tópico de pergunta fora da lista vira "outro".
"""

from __future__ import annotations

import json
import logging
from typing import Any, Sequence

from app.agent.llm import Turn
from app.agent.plan import QUESTION_TOPICS, Action, Address, AgentPlan, Operation
from app.agent.prompts import TOOL_NAME, build_system_blocks, tool_schema
from app.core.config import Settings, get_settings
from app.domain.catalog import CatalogSnapshot

logger = logging.getLogger(__name__)


def _function_tool() -> dict[str, Any]:
    """Converte o schema da tool (`input_schema`) para o formato OpenAI."""
    schema = tool_schema()
    return {
        "type": "function",
        "function": {
            "name": schema["name"],
            "description": schema["description"],
            "parameters": schema["input_schema"],
            # Structured outputs: a OpenAI passa a GARANTIR o formato. Sem
            # isto o modelo devolvia operação sem `action` e o pedido virava
            # "não entendi".
            "strict": True,
        },
    }


def _system_text(catalog: CatalogSnapshot, situation: str) -> str:
    """OpenAI recebe uma única mensagem de sistema; junta os blocos em um."""
    return "\n\n".join(
        block["text"] for block in build_system_blocks(catalog, situation)
    )


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

    async def interpret(
        self,
        *,
        catalog: CatalogSnapshot,
        history: Sequence[Turn],
        message: str,
        situation: str = "",
    ) -> AgentPlan:
        try:
            client = self._ensure_client()
            response = await client.chat.completions.create(
                model=self._settings.openai_model,
                max_tokens=self._settings.llm_max_tokens,
                messages=self._messages(
                    _system_text(catalog, situation), history, message
                ),
                tools=[self._tool],
                tool_choice={"type": "function", "function": {"name": TOOL_NAME}},
            )
        except Exception:
            # Timeout, rate limit, chave inválida: a conversa continua viva.
            logger.exception("falha ao chamar o LLM; plano vazio")
            return AgentPlan(model=self._settings.openai_model)

        return self._to_plan(response)

    # -- parsing -----------------------------------------------------------

    def _to_plan(self, response: Any) -> AgentPlan:
        usage = self._usage(response)
        model = getattr(response, "model", self._settings.openai_model)

        payload = self._tool_input(response)
        if payload is None:
            logger.warning(
                "resposta do LLM sem tool call: %r", getattr(response, "id", None)
            )
            return AgentPlan(model=model, usage=usage)

        try:
            operations = [
                self._operation(raw)
                for raw in (payload.get("operations") or [])
                if isinstance(raw, dict)
            ]
            plan = AgentPlan(
                operations=operations,
                confidence=float(payload.get("confidence") or 0.0),
                customer_name=payload.get("customer_name") or None,
            )
        except Exception:
            logger.exception("input da tool fora do contrato: %r", payload)
            return AgentPlan(model=model, usage=usage)

        plan.model = model
        plan.usage = usage
        return plan

    @classmethod
    def _operation(cls, raw: dict[str, Any]) -> Operation:
        return Operation(
            action=cls._action(raw.get("action")),
            item_index=cls._positive(raw.get("item_index")),
            product_name=raw.get("product_name") or None,
            quantity=cls._positive(raw.get("quantity")),
            add_flavors=cls._names(raw.get("add_flavors")),
            remove_flavors=cls._names(raw.get("remove_flavors")),
            fulfillment=cls._fulfillment(raw.get("fulfillment")),
            address=cls._address(raw.get("address")),
            question_topic=cls._topic(raw.get("question_topic")),
            question_text=raw.get("question_text") or None,
            raw_text=raw.get("raw_text") or None,
            clarification=raw.get("clarification") or None,
        )

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
    def _action(raw: Any) -> Action:
        try:
            return Action(str(raw))
        except ValueError:
            logger.warning("ação fora do enum: %r", raw)
            return Action.NO_ACTION

    @staticmethod
    def _names(raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []
        return [str(name).strip() for name in raw if str(name).strip()]

    @staticmethod
    def _positive(raw: Any) -> int | None:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    @staticmethod
    def _fulfillment(raw: Any) -> str | None:
        """Só "entrega" ou "retirada" passam; o resto é ruído do modelo."""
        value = str(raw).strip().lower() if raw else ""
        return value if value in {"entrega", "retirada"} else None

    @staticmethod
    def _topic(raw: Any) -> str | None:
        value = str(raw).strip().lower() if raw else ""
        if not value:
            return None
        return value if value in QUESTION_TOPICS else "outro"

    @staticmethod
    def _address(raw: Any) -> Address | None:
        if not isinstance(raw, dict):
            return None
        address = Address(**{k: v for k, v in raw.items() if v})
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
