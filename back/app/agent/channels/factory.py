"""Escolha do canal de saída.

Com `FAKE_MODE=true` tudo vai para o ConsoleAdapter — inclusive o que chegou
pelo webhook do WhatsApp, o que é útil para inspecionar payload real sem
mandar mensagem de verdade para ninguém.
"""

from __future__ import annotations

from functools import lru_cache

from app.agent.channels.base import ChannelAdapter
from app.agent.channels.console import ConsoleAdapter
from app.core.config import get_settings

#: Canal em memória compartilhado do processo — o simulador lê daqui.
_console = ConsoleAdapter()


def get_console_adapter() -> ConsoleAdapter:
    return _console


@lru_cache
def get_channel_adapter(channel_name: str = "whatsapp") -> ChannelAdapter:
    """Adapter do canal pedido, respeitando o modo falso.

    Para "whatsapp", o provedor concreto (Cloud API da Meta ou Evolution API
    self-hosted) é decidido por `settings.whatsapp_provider` — a máquina de
    estados e o resto do app não sabem qual dos dois está atrás do adapter.
    """
    settings = get_settings()

    if channel_name == "console" or settings.fake_mode:
        return _console

    if channel_name == "whatsapp" and settings.whatsapp_provider == "evolution":
        from app.agent.channels.evolution import EvolutionAdapter

        return EvolutionAdapter(settings)

    from app.agent.channels.whatsapp import WhatsAppCloudAdapter

    return WhatsAppCloudAdapter(settings)


def reset_channel_cache() -> None:
    """Usado em teste, quando as settings mudam entre casos."""
    get_channel_adapter.cache_clear()
