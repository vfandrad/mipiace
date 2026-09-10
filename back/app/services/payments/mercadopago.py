"""Provedor real: Pix via API do Mercado Pago.

Duas decisões que valem comentário:
  * `external_reference` recebe o id do pedido — é por ele que o webhook
    reencontra a venda mesmo se a linha de `payments` tiver se perdido;
  * `get_payment` sempre consulta a API. O payload do webhook não é
    confiável (pode ser forjado ou estar desatualizado).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.domain.enums import PaymentStatus
from app.services.payments.base import PaymentStatusResult, PixCharge

logger = get_logger(__name__)

API_BASE = "https://api.mercadopago.com"

#: Tradução do vocabulário do MP para o nosso.
_STATUS_MAP: dict[str, PaymentStatus] = {
    "approved": PaymentStatus.PAGO,
    "authorized": PaymentStatus.PAGO,
    "pending": PaymentStatus.PENDENTE,
    "in_process": PaymentStatus.PENDENTE,
    "in_mediation": PaymentStatus.PENDENTE,
    "rejected": PaymentStatus.CANCELADO,
    "cancelled": PaymentStatus.CANCELADO,
    "refunded": PaymentStatus.REEMBOLSADO,
    "charged_back": PaymentStatus.REEMBOLSADO,
}


class PaymentProviderError(RuntimeError):
    """Falha ao falar com o provedor de pagamento."""


def map_status(status: str | None, status_detail: str | None = None) -> PaymentStatus:
    if status_detail and "expired" in status_detail:
        return PaymentStatus.EXPIRADO
    return _STATUS_MAP.get((status or "").lower(), PaymentStatus.PENDENTE)


class MercadoPagoProvider:
    """Implementa `PaymentProvider` contra a API v1 do Mercado Pago."""

    name = "mercadopago"

    def __init__(self, access_token: str | None = None, timeout: float = 20.0) -> None:
        settings = get_settings()
        self._token = access_token or settings.mp_access_token
        if not self._token:
            raise PaymentProviderError(
                "MP_ACCESS_TOKEN ausente — use FAKE_MODE=true para rodar sem chave."
            )
        self._timeout = timeout
        self._notification_url = f"{settings.public_base_url}/webhooks/mercadopago"
        self._expiration_minutes = settings.pix_expiration_minutes

    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["X-Idempotency-Key"] = idempotency_key
        return headers

    async def create_pix_charge(
        self,
        *,
        order_id: UUID,
        order_code: str,
        amount: Decimal,
        payer_name: str | None = None,
        payer_phone: str | None = None,
    ) -> PixCharge:
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=self._expiration_minutes
        )
        first_name = (payer_name or "Cliente").split(" ")[0][:40]
        body: dict[str, Any] = {
            "transaction_amount": float(Decimal(amount)),
            "payment_method_id": "pix",
            "description": f"Mi Piace — pedido {order_code}",
            "external_reference": str(order_id),
            "notification_url": self._notification_url,
            # O MP quer offset explícito e milissegundos neste campo.
            "date_of_expiration": expires_at.strftime("%Y-%m-%dT%H:%M:%S.000+00:00"),
            "payer": {
                "email": f"pedido-{order_id.hex[:12]}@mipiace.app",
                "first_name": first_name,
            },
        }

        async with httpx.AsyncClient(base_url=API_BASE, timeout=self._timeout) as client:
            try:
                response = await client.post(
                    "/v1/payments",
                    json=body,
                    headers=self._headers(idempotency_key=f"pix-{order_id}"),
                )
            except httpx.HTTPError as exc:  # rede fora do ar
                raise PaymentProviderError(f"Falha de rede no Mercado Pago: {exc}") from exc

        if response.status_code >= 400:
            logger.error("Mercado Pago recusou a cobrança: %s", response.text[:500])
            raise PaymentProviderError(
                f"Mercado Pago devolveu {response.status_code} ao criar o Pix."
            )

        data = response.json()
        transaction = (data.get("point_of_interaction") or {}).get(
            "transaction_data"
        ) or {}
        return PixCharge(
            provider=self.name,
            provider_payment_id=str(data.get("id")),
            amount=Decimal(str(data.get("transaction_amount", amount))),
            qr_code=transaction.get("qr_code"),
            qr_code_base64=transaction.get("qr_code_base64"),
            ticket_url=transaction.get("ticket_url"),
            expires_at=expires_at,
            raw=data,
        )

    async def get_payment(self, provider_payment_id: str) -> PaymentStatusResult:
        async with httpx.AsyncClient(base_url=API_BASE, timeout=self._timeout) as client:
            try:
                response = await client.get(
                    f"/v1/payments/{provider_payment_id}", headers=self._headers()
                )
            except httpx.HTTPError as exc:
                raise PaymentProviderError(f"Falha de rede no Mercado Pago: {exc}") from exc

        if response.status_code == 404:
            raise PaymentProviderError(f"Pagamento {provider_payment_id} não existe.")
        if response.status_code >= 400:
            raise PaymentProviderError(
                f"Mercado Pago devolveu {response.status_code} ao consultar o pagamento."
            )

        data = response.json()
        amount = data.get("transaction_amount")
        return PaymentStatusResult(
            provider_payment_id=str(data.get("id", provider_payment_id)),
            status=map_status(data.get("status"), data.get("status_detail")),
            external_reference=data.get("external_reference"),
            amount=Decimal(str(amount)) if amount is not None else None,
            raw=data,
        )


__all__ = ["MercadoPagoProvider", "PaymentProviderError", "map_status"]
