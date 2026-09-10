"""Contrato de provedor de pagamento.

O resto do sistema nunca fala "Mercado Pago" — fala PaymentProvider. Isso é o
que permite rodar o fluxo completo de Pix localmente com o provedor falso e
trocar para o real só mudando FAKE_MODE.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.enums import PaymentStatus


class PixCharge(BaseModel):
    """Cobrança Pix recém-criada, pronta para ser enviada ao cliente."""

    provider: str
    provider_payment_id: str
    amount: Decimal
    qr_code: str | None = None          # copia-e-cola
    qr_code_base64: str | None = None   # imagem do QR
    ticket_url: str | None = None
    expires_at: datetime | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class PaymentStatusResult(BaseModel):
    """Resultado da consulta de uma cobrança no provedor."""

    provider_payment_id: str
    status: PaymentStatus
    external_reference: str | None = None  # o id do pedido no nosso banco
    amount: Decimal | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class PaymentProvider(Protocol):
    """Implementado por MercadoPagoProvider e FakePaymentProvider."""

    name: str

    async def create_pix_charge(
        self,
        *,
        order_id: UUID,
        order_code: str,
        amount: Decimal,
        payer_name: str | None = None,
        payer_phone: str | None = None,
    ) -> PixCharge:
        """Cria a cobrança e devolve o copia-e-cola."""
        ...

    async def get_payment(self, provider_payment_id: str) -> PaymentStatusResult:
        """Consulta a cobrança na fonte — nunca confie no payload do webhook."""
        ...
