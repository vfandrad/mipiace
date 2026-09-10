"""Regras de cliente e endereço.

O telefone do WhatsApp é a identidade natural do cliente — por isso tudo aqui
gira em torno dele, normalizado para só dígitos.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Address, Customer
from app.repositories import customers as customers_repo

#: Campos aceitos vindos do agente (o LLM devolve texto livre com estas chaves).
ADDRESS_FIELDS = ("rua", "numero", "bairro", "complemento", "referencia")

_NON_DIGITS = re.compile(r"\D+")


def normalize_phone(phone: str) -> str:
    """Só dígitos: "+55 (11) 99999-8888" e "5511999998888" viram a mesma chave."""
    digits = _NON_DIGITS.sub("", phone or "")
    if not digits:
        raise ValueError("telefone inválido")
    return digits


async def get_or_create_customer(
    session: AsyncSession, *, phone: str, name: str | None = None
) -> Customer:
    """Acha pelo telefone ou cria. Só sobrescreve o nome se ainda não houver um."""
    normalized = normalize_phone(phone)
    customer = await customers_repo.get_customer_by_phone(session, normalized)
    if customer is None:
        return await customers_repo.create_customer(
            session, phone=normalized, name=(name or None)
        )
    if name and not customer.name:
        customer.name = name
        await session.flush()
    return customer


def clean_address(address: dict[str, Any] | None) -> dict[str, str] | None:
    """Fica só com as chaves conhecidas e exige rua/número/bairro."""
    if not address:
        return None
    cleaned = {
        field: str(address[field]).strip()
        for field in ADDRESS_FIELDS
        if address.get(field) not in (None, "")
    }
    if not all(cleaned.get(field) for field in ("rua", "numero", "bairro")):
        return None
    return cleaned


async def save_address(
    session: AsyncSession, *, customer_id: UUID, address: dict[str, Any]
) -> Address | None:
    """Grava o endereço do pedido; reaproveita se for igual ao último salvo."""
    cleaned = clean_address(address)
    if cleaned is None:
        return None

    existing = await customers_repo.list_addresses(session, customer_id)
    for candidate in existing:
        same = (
            candidate.rua.casefold() == cleaned["rua"].casefold()
            and candidate.numero == cleaned["numero"]
            and candidate.bairro.casefold() == cleaned["bairro"].casefold()
        )
        if same:
            return candidate

    return await customers_repo.create_address(
        session,
        customer_id=customer_id,
        data={**cleaned, "is_default": not existing},
    )


def format_address(address: Address | None) -> str | None:
    """"Rua X, 123, Centro — ap 2 (perto da praça)"."""
    if address is None:
        return None
    line = f"{address.rua}, {address.numero}, {address.bairro}"
    if address.complemento:
        line += f" — {address.complemento}"
    if address.referencia:
        line += f" ({address.referencia})"
    return line


__all__ = [
    "ADDRESS_FIELDS",
    "clean_address",
    "format_address",
    "get_or_create_customer",
    "normalize_phone",
    "save_address",
]
