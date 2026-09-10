"""Escolha do provedor de pagamento — o único lugar que sabe qual é qual."""

from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.services.payments.base import PaymentProvider
from app.services.payments.fake import FakePaymentProvider
from app.services.payments.mercadopago import MercadoPagoProvider


@lru_cache
def get_payment_provider() -> PaymentProvider:
    """FAKE_MODE=true -> Pix falso; false -> Mercado Pago de verdade.

    Em cache porque o provedor falso guarda estado (as cobranças aprovadas) e
    precisa ser o mesmo objeto entre a rota de dev e o webhook.
    """
    settings = get_settings()
    if settings.fake_mode:
        return FakePaymentProvider()
    return MercadoPagoProvider()


def reset_payment_provider() -> None:
    """Descarta o provedor em cache (usado em teste)."""
    get_payment_provider.cache_clear()


__all__ = ["get_payment_provider", "reset_payment_provider"]
