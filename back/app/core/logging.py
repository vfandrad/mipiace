"""Configuração de log da aplicação.

Log em uma linha por evento, com o nome do módulo — o suficiente para depurar
o agente e o webhook de pagamento sem trazer dependência de observabilidade.
"""

from __future__ import annotations

import logging
import sys

from app.core.config import get_settings

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


__all__ = ["get_logger", "setup_logging"]
