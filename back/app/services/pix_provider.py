"""Como o Pix é cobrado — contrato, provedor real, provedor falso e a escolha.

O resto do sistema nunca fala "Mercado Pago": fala `PaymentProvider`. É isso
que permite rodar o fluxo completo de Pix localmente, sem chave nenhuma, e
trocar para o real só mudando `FAKE_MODE`.

Estão os quatro pedaços num arquivo só porque a pergunta é uma só — "como o
Pix é cobrado?" — e a decisão entre os dois provedores cabe em uma linha.
"""

from __future__ import annotations

import hashlib
import unicodedata
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import lru_cache
from typing import Any, Protocol
from urllib.parse import urlparse
from uuid import UUID

import httpx
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.logging import get_logger
from app.domain.enums import PaymentStatus

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Contrato
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Provedor real: Pix via API do Mercado Pago
#
# Duas decisões que valem comentário:
#   * `external_reference` recebe o id do pedido — é por ele que o webhook
#     reencontra a venda mesmo se a linha de `payments` tiver se perdido;
#   * `get_payment` sempre consulta a API. O payload do webhook não é
#     confiável (pode ser forjado ou estar desatualizado).
# ---------------------------------------------------------------------------

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
            "description": f"{get_settings().store_name} — pedido {order_code}",
            "external_reference": str(order_id),
            "notification_url": self._notification_url,
            # O MP quer offset explícito e milissegundos neste campo.
            "date_of_expiration": expires_at.strftime("%Y-%m-%dT%H:%M:%S.000+00:00"),
            "payer": {
                "email": _payer_email(order_id),
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

# ---------------------------------------------------------------------------
# Provedor falso — o que permite rodar o fluxo inteiro offline
#
# Regras que ele precisa respeitar para o teste local valer alguma coisa:
#   * o copia-e-cola é determinístico (mesmo pedido, mesmo código);
#   * o id da cobrança carrega o id do pedido, então `get_payment` continua
#     funcionando depois de reiniciar o processo;
#   * a aprovação é explícita (`approve`), acionada por
#     `POST /api/simulator/payments/{id}/approve`, imitando o cliente pagando.
# ---------------------------------------------------------------------------

#: Cobranças aprovadas nesta execução (o "banco do provedor" de mentira).
_APPROVED: set[str] = set()


def _payer_email(order_id: UUID) -> str:
    """E-mail técnico do pagador, exigido pelo Mercado Pago.

    O cliente chega pelo WhatsApp: não temos e-mail dele, e pedir um só para
    satisfazer a API seria atrito puro. O domínio sai da URL pública da
    instalação para não carimbar o nome de uma loja na cobrança de outra.
    """
    host = urlparse(get_settings().public_base_url).hostname or "localhost"
    return f"pedido-{order_id.hex[:12]}@{host}"


def _fake_qr_code(order_code: str, amount: Decimal) -> str:
    """Payload no formato do BR Code, com dígitos derivados do pedido.

    O nome e a cidade do recebedor saem da configuração porque o BR Code os
    carrega em campos de tamanho fixo — é o mesmo lugar onde o provedor real
    poria os dados da loja.
    """
    settings = get_settings()
    seed = f"{order_code}:{amount}".encode()
    digest = hashlib.sha256(seed).hexdigest().upper()
    # Campos 59 (nome do recebedor) e 60 (cidade): dois dígitos de tamanho
    # seguidos do valor, em maiúsculas e sem acento, como manda o padrão.
    nome = _brcode_field("59", settings.store_name, 25)
    cidade = _brcode_field("60", settings.store_city, 15)
    return (
        "00020126580014BR.GOV.BCB.PIX0136"
        + digest[:32]
        # 5204 0000 (MCC) + 5303 986 (moeda BRL) + 5802 BR (país)
        + "5204000053039865802BR"
        + nome
        + cidade
        + "62070503***6304"
        + digest[32:36]
    )


def _brcode_field(tag: str, value: str, limit: int) -> str:
    """Um campo do BR Code: tag + tamanho em 2 dígitos + valor."""
    texto = unicodedata.normalize("NFKD", value.strip().upper())
    texto = "".join(c for c in texto if not unicodedata.combining(c))[:limit]
    return f"{tag}{len(texto):02d}{texto}"


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


# ---------------------------------------------------------------------------
# Escolha do provedor
# ---------------------------------------------------------------------------

@lru_cache
def get_payment_provider() -> PaymentProvider:
    """FAKE_MODE=true -> Pix falso; false -> Mercado Pago de verdade.

    Em cache porque o provedor falso guarda estado (as cobranças aprovadas) e
    precisa ser o mesmo objeto entre o simulador e o webhook.
    """
    if get_settings().fake_mode:
        return FakePaymentProvider()
    return MercadoPagoProvider()
