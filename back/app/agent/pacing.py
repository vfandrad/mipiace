"""Ritmo de envio no WhatsApp — o que separa um atendente de um robô.

Este projeto fala com o WhatsApp por um cliente não-oficial (Evolution API,
Baileys por baixo). O que derruba um número nesse cenário quase nunca é o
conteúdo da mensagem: é o *padrão* de envio. Responder em 200ms, disparar três
mensagens no mesmo segundo e manter uma cadência constante hora após hora é
exatamente o que o antispam do WhatsApp procura.

Nada aqui esconde o que o sistema é, nem tenta enganar detecção. O que este
módulo faz é impor ao bot os mesmos limites de um humano atrás do balcão:
ele lê, leva um tempo proporcional ao tamanho do que vai escrever, e não
consegue mandar cem mensagens por minuto nem se quiser.

As três regras, em ordem de importância:

1. **Só responder a quem escreveu primeiro.** Não está aqui porque é
   estrutural: o agente só é acionado pelo webhook de mensagem recebida, e
   `notify_payment_approved` só fala com quem tem pedido aberto. O sistema não
   tem nenhum caminho que envie mensagem para um número frio — e é essa
   propriedade, mais do que qualquer delay, que mantém o número vivo.
2. **Demorar como gente demora** — `typing_delay_ms`.
3. **Ter um teto** — `Throttle`, por contato e global.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections import deque

from app.core.config import get_settings

#: Piso e teto do "digitando..." (ms). O piso evita a resposta instantânea que
#: denuncia automação; o teto evita que o cliente ache que ninguém viu.
MIN_TYPING_MS = 1_200
MAX_TYPING_MS = 8_000


def typing_delay_ms(text: str, *, wpm: float | None = None) -> int:
    """Quanto tempo um humano levaria para digitar `text`, com variação.

    Modela a digitação em palavras por minuto sorteadas de uma normal em torno
    da velocidade média configurada — não um valor fixo, porque cadência
    constante é ela própria uma assinatura de robô. Cinco caracteres contam
    como uma palavra, que é a convenção usual de WPM.
    """
    settings = get_settings()
    mean = wpm if wpm is not None else settings.wa_typing_wpm
    speed = max(15.0, random.gauss(mean, mean * 0.33))
    words = max(1, len(text) / 5)
    ms = (words / speed) * 60_000
    # Jitter multiplicativo: duas mensagens de tamanho igual não saem no mesmo tempo.
    ms *= random.uniform(0.85, 1.25)
    return int(min(MAX_TYPING_MS, max(MIN_TYPING_MS, ms)))


class Throttle:
    """Teto de envio: um por contato, um global.

    O limite global é uma janela deslizante de um minuto — comunidade e
    documentação de gateways não-oficiais convergem em algo entre 10 e 20
    mensagens por minuto por instância antes de o antispam reagir, e o padrão
    daqui fica na parte de baixo dessa faixa. Uma gelateria não chega perto
    disso: o teto existe para o caso patológico (um laço de repetição, uma
    tempestade de webhooks), que é justamente quando o número se perde.

    O intervalo por contato serve a outra coisa: o agente responde em rajada
    (resumo do carrinho + pergunta, por exemplo), e duas mensagens no mesmo
    segundo para a mesma pessoa não acontecem quando quem digita é gente.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._recent: deque[float] = deque()      # envios do último minuto
        self._last_by_phone: dict[str, float] = {}

    async def acquire(self, phone: str) -> None:
        """Bloqueia até que enviar para `phone` esteja dentro dos dois limites."""
        settings = get_settings()
        gap = settings.wa_min_seconds_between_messages
        ceiling = settings.wa_max_messages_per_minute

        while True:
            async with self._lock:
                now = time.monotonic()

                while self._recent and now - self._recent[0] >= 60.0:
                    self._recent.popleft()

                wait = 0.0
                last = self._last_by_phone.get(phone)
                if last is not None:
                    wait = max(wait, gap - (now - last))
                if len(self._recent) >= ceiling:
                    wait = max(wait, 60.0 - (now - self._recent[0]))

                if wait <= 0:
                    self._recent.append(now)
                    self._last_by_phone[phone] = now
                    # O dicionário cresceria com um número novo por cliente;
                    # entradas velhas não dizem mais nada sobre o ritmo atual.
                    if len(self._last_by_phone) > 1_000:
                        corte = now - 3_600
                        self._last_by_phone = {
                            p: t for p, t in self._last_by_phone.items() if t > corte
                        }
                    return

            await asyncio.sleep(min(wait, 5.0))


#: Compartilhado pelo processo: o limite é da instância do WhatsApp, não da
#: conversa. Dois clientes falando ao mesmo tempo dividem o mesmo teto.
throttle = Throttle()
