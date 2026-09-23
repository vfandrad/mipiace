"""Agrupa as mensagens seguidas do mesmo cliente em um turno só.

Quem pede pelo WhatsApp não escreve um parágrafo: escreve "quero um pote",
depois "G", depois "de pistache e morango", três balões em poucos segundos.
Tratando cada balão como um turno, o agente responde três vezes, interpreta
"G" fora de contexto e ainda corre o risco de duas mensagens mexerem no mesmo
estado ao mesmo tempo.

A solução padrão para isso é um *debounce* de borda final: cada mensagem
reagenda o processamento para daqui a `wa_debounce_seconds`; quando o prazo
vence sem nada novo, o buffer inteiro vira um texto só e o agente roda uma vez.
Como o processamento sai do caminho da resposta HTTP, o webhook da Evolution
passa a responder 200 na hora — e webhook lento é justamente o que faz o
gateway reentregar a mesma mensagem.

O buffer é de processo, não distribuído: um backend, um container. Se um dia
houver duas réplicas, o lugar disto é o Redis, não uma variável de módulo.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from app.agent.whatsapp import InboundMessage
from app.core.config import get_settings

logger = logging.getLogger(__name__)

#: Quem processa o turno já agrupado (o webhook passa um que abre sessão de
#: banco própria — a original morre junto com a request).
Handler = Callable[[InboundMessage], Awaitable[None]]


@dataclass
class _Buffer:
    """Mensagens de um telefone esperando o prazo vencer."""

    last: InboundMessage
    texts: list[str] = field(default_factory=list)
    deadline: float = 0.0


_buffers: dict[str, _Buffer] = {}
#: Referência forte para as tasks: sem isso o coletor de lixo do asyncio pode
#: recolher uma task em voo e o cliente fica sem resposta.
_tasks: set[asyncio.Task[None]] = set()


def _merged(buffer: _Buffer) -> InboundMessage:
    """Os balões viram um texto só, guardando o id da ÚLTIMA mensagem.

    O id é o que garante idempotência lá no `runner`; usar o da última faz a
    reentrega de qualquer balão anterior ainda ser reconhecida como nova, mas
    a reentrega do turno inteiro (o caso comum) ser descartada.
    """
    return buffer.last.model_copy(update={"text": "\n".join(buffer.texts)})


async def submit(message: InboundMessage, handler: Handler) -> None:
    """Enfileira a mensagem; o handler roda quando o cliente parar de digitar."""
    window = get_settings().wa_debounce_seconds
    if window <= 0:  # agrupamento desligado: comportamento antigo, turno a turno
        await handler(message)
        return

    buffer = _buffers.get(message.phone)
    if buffer is None:
        buffer = _Buffer(last=message)
        _buffers[message.phone] = buffer
        task = asyncio.create_task(_process_when_idle(message.phone, handler))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    else:
        buffer.last = message

    buffer.texts.append(message.text)
    buffer.deadline = time.monotonic() + window


async def _process_when_idle(phone: str, handler: Handler) -> None:
    """Espera o silêncio do cliente e roda o turno uma única vez."""
    while True:
        buffer = _buffers.get(phone)
        if buffer is None:  # ninguém para processar (só acontece em teardown)
            return
        remaining = buffer.deadline - time.monotonic()
        if remaining <= 0:
            break
        await asyncio.sleep(remaining)

    buffer = _buffers.pop(phone, None)
    if buffer is None:
        return

    try:
        await handler(_merged(buffer))
    except Exception:
        # Um turno com problema não pode derrubar a task nem calar o próximo.
        logger.exception("falha ao processar turno de %s", phone)


async def drain() -> None:
    """Espera tudo que está em voo — usado nos testes e no shutdown."""
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)
