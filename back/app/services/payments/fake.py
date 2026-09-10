"""Provedor de pagamento falso — o que permite rodar o fluxo inteiro offline.

Regras que ele precisa respeitar para o teste local valer alguma coisa:
  * o copia-e-cola é determinístico (mesmo pedido, mesmo código);
  * o id da cobrança carrega o id do pedido, então `get_payment` continua
    funcionando depois de reiniciar o processo;
  * a aprovação é explícita (`approve`), acionada por `POST /api/dev/...`,
    imitando o cliente pagando o Pix.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from app.core.config import get_settings
from app.core.logging import get_logger
from app.domain.enums import PaymentStatus
from app.services.payments.base import PaymentStatusResult, PixCharge

logger = get_logger(__name__)

#: Cobranças aprovadas nesta execução (o "banco do provedor" de mentira).
_APPROVED: set[str] = set()


def _fake_qr_code(order_code: str, amount: Decimal) -> str:
    """Payload no formato do BR Code, com dígitos derivados do pedido."""
    seed = f"{order_code}:{amount}".encode()
    digest = hashlib.sha256(seed).hexdigest().upper()
    return (
        "00020126580014BR.GOV.BCB.PIX0136"
        + digest[:32]
        + "5204000053039865802BR5908MI PIACE6009SAO PAULO62070503***6304"
        + digest[32:36]
    )


class FakePaymentProvider:
    """Implementa `PaymentProvider` sem sair da máquina."""

    name = "fake"

    async def create_pix_charge(
        self,
        *,
        order_id: UUID,
        order_code: str,
        amount: Decimal,
        payer_name: str | None = None,
        payer_phone: str | None = None,
    ) -> PixCharge:
        settings = get_settings()
        cents = int(Decimal(amount) * 100)
        provider_payment_id = f"fake-{order_id.hex}-{cents}"
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=settings.pix_expiration_minutes
        )
        qr_code = _fake_qr_code(order_code, Decimal(amount))
        logger.info("Pix falso emitido para %s (%s)", order_code, provider_payment_id)
        return PixCharge(
            provider=self.name,
            provider_payment_id=provider_payment_id,
            amount=Decimal(amount),
            qr_code=qr_code,
            qr_code_base64=None,
            ticket_url=f"{settings.public_base_url}/api/dev/payments/{order_id}/approve",
            expires_at=expires_at,
            raw={"fake": True, "order_code": order_code, "payer": payer_name},
        )

    async def get_payment(self, provider_payment_id: str) -> PaymentStatusResult:
        order_id, amount = _parse_payment_id(provider_payment_id)
        status = (
            PaymentStatus.PAGO
            if provider_payment_id in _APPROVED
            else PaymentStatus.PENDENTE
        )
        return PaymentStatusResult(
            provider_payment_id=provider_payment_id,
            status=status,
            external_reference=str(order_id) if order_id else None,
            amount=amount,
            raw={"fake": True, "status": status.value},
        )

    def approve(self, provider_payment_id: str) -> None:
        """Marca a cobrança como paga — chamado pela rota de desenvolvimento."""
        _APPROVED.add(provider_payment_id)
        logger.info("Pix falso aprovado: %s", provider_payment_id)

    def reset(self) -> None:
        """Limpa as aprovações (usado em teste)."""
        _APPROVED.clear()


def _parse_payment_id(provider_payment_id: str) -> tuple[UUID | None, Decimal | None]:
    """"fake-<uuid hex>-<centavos>" -> (uuid, valor)."""
    parts = provider_payment_id.split("-")
    if len(parts) != 3 or parts[0] != "fake":
        return None, None
    try:
        return UUID(hex=parts[1]), Decimal(parts[2]) / 100
    except (ValueError, ArithmeticError):
        return None, None


__all__ = ["FakePaymentProvider"]
