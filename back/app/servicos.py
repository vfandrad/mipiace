"""Os serviços: tudo que fala com o banco e com o Mercado Pago.

Aqui moram as regras que não são do agente nem da API — criar um pedido a
partir do carrinho, montar o cardápio, registrar um pagamento, contar as
vendas do dia. As rotas chamam daqui; o agente chama daqui; ninguém daqui
chama de volta.

A ordem das seções é a ordem das dependências: preços e catálogo não dependem
de nada, pedidos dependem de preços e clientes, pagamentos dependem de
pedidos. Como tudo mora no mesmo arquivo, o que antes era um ciclo entre
`orders` e `payments` (remendado com import dentro da função) virou uma
chamada comum.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import lru_cache
from typing import Any, Protocol
from urllib.parse import urlparse
from uuid import UUID

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.banco import (
    Address,
    Complement,
    ComplementCategory,
    ComplementGroup,
    Conversation,
    ConversationMessage,
    Customer,
    Order,
    OrderItem,
    OrderItemComplement,
    Payment,
    Product,
    ProductGroup,
    WebhookEvent,
    order_code_seq,
)
from app.configuracao import get_logger, get_settings
from app.dominio import (
    ZERO,
    Cart,
    CatalogComplement,
    CatalogGroup,
    CatalogProduct,
    CatalogSnapshot,
    ConversationState,
    FulfillmentType,
    OrderChannel,
    OrderStatus,
    PaymentStatus,
    arredondar_dinheiro,
    item_unit_price,
)
from app.esquemas import (
    ConversationMessageRead,
    ConversationRead,
    DailySales,
    HourlySales,
    MetricsRange,
    MetricsSummary,
    Money,
    OrderCreated,
    OrderSummary,
    OrderSummaryItem,
    ProductSales,
)

# ---------------------------------------------------------------------------
# Preços — a conta que depende de configuração
# ---------------------------------------------------------------------------

class PriceBreakdown(BaseModel):
    """Resultado do cálculo, pronto para virar colunas de `orders`."""

    subtotal: Money
    delivery_fee: Money
    total: Money


def delivery_fee_for(
    fulfillment_type: FulfillmentType, *, fee: Decimal | None = None
) -> Decimal:
    """Retirada na loja não paga entrega; entrega usa a taxa de `settings`."""
    if fulfillment_type is FulfillmentType.RETIRADA:
        return ZERO
    return arredondar_dinheiro(get_settings().delivery_fee if fee is None else fee)


def calculate_cart(
    cart: Cart,
    *,
    fulfillment_type: FulfillmentType = FulfillmentType.ENTREGA,
    delivery_fee: Decimal | None = None,
) -> PriceBreakdown:
    """Subtotal + taxa de entrega + total de um carrinho."""
    subtotal = cart.subtotal
    fee = delivery_fee_for(fulfillment_type, fee=delivery_fee)
    return PriceBreakdown(subtotal=subtotal, delivery_fee=fee, total=arredondar_dinheiro(subtotal + fee))


# ---------------------------------------------------------------------------
# Catálogo — monta o cardápio que o agente enxerga
# ---------------------------------------------------------------------------

#: Tudo que o CRUD do cardápio edita. Criar/editar/apagar é igual para os três,
#: então as funções genéricas abaixo servem a todos.
CatalogRow = Product | ComplementGroup | ProductGroup | Complement | ComplementCategory


# ---------------------------------------------------------------------------
# Operações comuns aos três níveis (produto > grupo > complemento)
# ---------------------------------------------------------------------------

async def update_item[T: CatalogRow](session: AsyncSession, item: T, data: dict[str, Any]) -> T:
    """Aplica os campos enviados no PATCH. `data` já vem validado pelo schema."""
    for field, value in data.items():
        setattr(item, field, value)
    await session.flush()
    return item


async def delete_item(session: AsyncSession, item: CatalogRow) -> None:
    await session.delete(item)
    await session.flush()


async def _add(session: AsyncSession, item: CatalogRow) -> Any:
    session.add(item)
    await session.flush()
    await session.refresh(item)
    return item


# ---------------------------------------------------------------------------
# Produtos
# ---------------------------------------------------------------------------

async def list_products(
    session: AsyncSession, *, only_available: bool = False
) -> list[Product]:
    """Produtos com grupos e complementos (carregados via selectin no model)."""
    stmt = select(Product).order_by(Product.sort_order, Product.name)
    if only_available:
        stmt = stmt.where(Product.is_available.is_(True))
    result = await session.scalars(stmt)
    return list(result)


async def get_product(session: AsyncSession, product_id: UUID) -> Product | None:
    return await session.get(Product, product_id)


async def create_product(session: AsyncSession, data: dict[str, Any]) -> Product:
    return await _add(session, Product(**data))


# ---------------------------------------------------------------------------
# Grupos de complementos (a biblioteca) e os vínculos com os produtos
# ---------------------------------------------------------------------------

async def list_groups(session: AsyncSession) -> list[ComplementGroup]:
    """A biblioteca de grupos — é dela que o painel oferece "usar este grupo"."""
    stmt = select(ComplementGroup).order_by(
        ComplementGroup.sort_order, ComplementGroup.name
    )
    result = await session.scalars(stmt)
    return list(result)


async def get_group(session: AsyncSession, group_id: UUID) -> ComplementGroup | None:
    return await session.get(ComplementGroup, group_id)


async def create_group(session: AsyncSession, data: dict[str, Any]) -> ComplementGroup:
    """Cria a lista. Ela ainda não pertence a produto nenhum — `link_group` faz isso."""
    return await _add(session, ComplementGroup(**data))


async def get_product_group(
    session: AsyncSession, link_id: UUID
) -> ProductGroup | None:
    return await session.get(ProductGroup, link_id)


async def find_link(
    session: AsyncSession, *, product_id: UUID, group_id: UUID
) -> ProductGroup | None:
    """O vínculo existente entre este produto e este grupo, se houver."""
    stmt = select(ProductGroup).where(
        ProductGroup.product_id == product_id, ProductGroup.group_id == group_id
    )
    return await session.scalar(stmt)


async def link_group(
    session: AsyncSession, *, product_id: UUID, group_id: UUID, data: dict[str, Any]
) -> ProductGroup:
    """Faz o produto usar o grupo, com a regra de escolha DELE.

    Se o vínculo já existe, atualiza a regra em vez de criar um segundo — dois
    vínculos iguais fariam o agente perguntar os sabores duas vezes.
    """
    existente = await find_link(session, product_id=product_id, group_id=group_id)
    if existente is not None:
        return await update_item(session, existente, data)
    return await _add(
        session, ProductGroup(product_id=product_id, group_id=group_id, **data)
    )


# ---------------------------------------------------------------------------
# Complementos (os sabores)
# ---------------------------------------------------------------------------

async def get_complement(
    session: AsyncSession, complement_id: UUID
) -> Complement | None:
    return await session.get(Complement, complement_id)


async def create_complement(
    session: AsyncSession, *, group_id: UUID, data: dict[str, Any]
) -> Complement:
    return await _add(session, Complement(group_id=group_id, **data))


async def get_category(
    session: AsyncSession, category_id: UUID
) -> ComplementCategory | None:
    return await session.get(ComplementCategory, category_id)


async def create_category(
    session: AsyncSession, data: dict[str, Any]
) -> ComplementCategory:
    return await _add(session, ComplementCategory(**data))


async def list_complement_categories(session: AsyncSession) -> list[ComplementCategory]:
    stmt = select(ComplementCategory).order_by(
        ComplementCategory.sort_order, ComplementCategory.name
    )
    result = await session.scalars(stmt)
    return list(result)


# ---------------------------------------------------------------------------
# Ordem (arrastar e soltar no painel)
# ---------------------------------------------------------------------------

#: Qual tabela cada tipo de item reordenável usa.
_ORDERABLE = {
    "product": Product,
    "group": ComplementGroup,
    # A ordem em que os grupos aparecem DENTRO de um produto é do vínculo.
    "product_group": ProductGroup,
    "complement": Complement,
    "category": ComplementCategory,
}


async def reorder(session: AsyncSession, *, kind: str, ids: list[UUID]) -> int:
    """Grava a ordem em que o lojista arrastou os itens.

    `sort_order` vira a posição na lista — 0, 1, 2... — numa transação só. É
    assim porque a alternativa (um PATCH por item) deixa a lista meio ordenada
    se uma das requisições falhar no meio, e o cardápio sai torto no WhatsApp.

    Ids desconhecidos são ignorados em vez de derrubar a operação: a tela pode
    estar mostrando algo que outra aba acabou de apagar.
    """
    model = _ORDERABLE.get(kind)
    if model is None:
        raise ValueError(f"tipo não ordenável: {kind}")

    encontrados = await session.scalars(select(model).where(model.id.in_(ids)))
    por_id = {item.id: item for item in encontrados}
    mexidos = 0
    for posicao, item_id in enumerate(ids):
        item = por_id.get(item_id)
        if item is None:
            continue
        if item.sort_order != posicao:
            item.sort_order = posicao
            mexidos += 1
    await session.flush()
    return mexidos


# ---------------------------------------------------------------------------
# O cardápio como o agente enxerga
# ---------------------------------------------------------------------------

async def get_catalog_snapshot(session: AsyncSession) -> CatalogSnapshot:
    """Cardápio inteiro em árvore produto → grupos → complementos.

    Traz também os indisponíveis (com `is_available=False`): quem filtra é o
    consumidor, e o agente precisa saber que o sabor existe mas acabou para
    responder "hoje não tem pistache" em vez de "não entendi".
    """
    rows = await list_products(session)
    return CatalogSnapshot(
        products=[
            CatalogProduct(
                id=product.id,
                name=product.name,
                description=product.description,
                base_price=product.base_price,
                is_available=product.is_available,
                # `link` é o vínculo produto<->grupo: dele vem a regra de
                # escolha daquele produto; do `link.group`, a lista de itens.
                groups=[
                    CatalogGroup(
                        id=link.group.id,
                        name=link.group.name,
                        min_choices=link.min_choices,
                        max_choices=link.max_choices,
                        is_required=link.is_required,
                        complements=[
                            CatalogComplement(
                                id=complement.id,
                                group_id=complement.group_id,
                                name=complement.name,
                                extra_price=complement.extra_price,
                                is_available=complement.is_available,
                                category=(
                                    complement.category.name
                                    if complement.category
                                    else None
                                ),
                            )
                            for complement in link.group.complements
                        ],
                    )
                    for link in product.groups
                ],
            )
            for product in rows
        ]
    )


# ---------------------------------------------------------------------------
# Clientes e endereços
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Acesso a dados
# ---------------------------------------------------------------------------


async def get_customer_by_phone(session: AsyncSession, phone: str) -> Customer | None:
    return await session.scalar(select(Customer).where(Customer.phone == phone))




async def create_customer(
    session: AsyncSession, *, phone: str, name: str | None = None
) -> Customer:
    customer = Customer(phone=phone, name=name)
    session.add(customer)
    await session.flush()
    return customer


async def list_addresses(session: AsyncSession, customer_id: UUID) -> list[Address]:
    result = await session.scalars(
        select(Address)
        .where(Address.customer_id == customer_id)
        .order_by(Address.is_default.desc(), Address.created_at.desc())
    )
    return list(result)


async def create_address(
    session: AsyncSession, *, customer_id: UUID, data: dict[str, Any]
) -> Address:
    address = Address(customer_id=customer_id, **data)
    session.add(address)
    await session.flush()
    return address

# ---------------------------------------------------------------------------
# Regras
# ---------------------------------------------------------------------------

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
    customer = await get_customer_by_phone(session, normalized)
    if customer is None:
        return await create_customer(
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

    existing = await list_addresses(session, customer_id)
    for candidate in existing:
        same = (
            candidate.rua.casefold() == cleaned["rua"].casefold()
            and candidate.numero == cleaned["numero"]
            and candidate.bairro.casefold() == cleaned["bairro"].casefold()
        )
        if same:
            return candidate

    return await create_address(
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


# ---------------------------------------------------------------------------
# Conversas (leitura para o painel)
# ---------------------------------------------------------------------------

#: Corta a prévia pra caber numa linha da lista (o histórico tem o texto inteiro).
_PREVIEW_MAX_LEN = 80


def _preview(content: str | None) -> str | None:
    if not content:
        return None
    flat = " ".join(content.split())
    return flat if len(flat) <= _PREVIEW_MAX_LEN else flat[: _PREVIEW_MAX_LEN - 1] + "…"


async def list_conversations(
    session: AsyncSession, *, limit: int = 50, offset: int = 0
) -> list[ConversationRead]:
    """Lista para o painel, cada linha já com nome do cliente e prévia.

    O nome mora em `customers`, não na conversa; os clientes das conversas
    listadas são carregados de uma vez só para não fazer uma consulta por linha.
    """
    last_message = (
        select(ConversationMessage.content)
        .where(ConversationMessage.conversation_id == Conversation.id)
        .order_by(ConversationMessage.created_at.desc())
        .limit(1)
        .correlate(Conversation)
        .scalar_subquery()
    )
    result = await session.execute(
        select(Conversation, last_message)
        .order_by(
            Conversation.last_message_at.desc().nullslast(),
            Conversation.created_at.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    rows = [(row[0], row[1]) for row in result.all()]

    customer_ids = {c.customer_id for c, _ in rows if c.customer_id}
    names: dict[UUID, str | None] = {}
    if customer_ids:
        customers = await session.scalars(
            select(Customer).where(Customer.id.in_(customer_ids))
        )
        names = {c.id: c.name for c in customers}

    return [
        ConversationRead.model_validate(conversation).model_copy(
            update={
                "last_message_preview": _preview(last_message_text),
                "customer_name": names.get(conversation.customer_id),
            }
        )
        for conversation, last_message_text in rows
    ]


async def get_conversation(
    session: AsyncSession, conversation_id: UUID
) -> Conversation | None:
    return await session.get(Conversation, conversation_id)


async def list_messages(
    session: AsyncSession, conversation_id: UUID, *, limit: int = 200
) -> list[ConversationMessageRead]:
    """Histórico completo da conversa, do mais antigo para o mais novo."""
    result = await session.scalars(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation_id)
        .order_by(ConversationMessage.created_at)
        .limit(limit)
    )
    return [ConversationMessageRead.model_validate(m) for m in result]


async def set_handoff(
    session: AsyncSession, conversation: Conversation, *, handoff: bool
) -> Conversation:
    """`handoff=True` faz o agente parar de responder este telefone.

    Devolver a conversa para o bot (`handoff=False`) precisa também tirá-la do
    estado ATENDIMENTO_HUMANO: a máquina de estados fica calada com base no
    ESTADO (`machine.run`), não neste booleano. Sem isso, uma conversa que o
    próprio bot escalou — o que acontece depois de MAX_NLU_FAILURES falhas —
    ficaria muda para sempre, mesmo o lojista clicando em "devolver ao bot".

    O carrinho é preservado de propósito: o cliente pode ter montado o pedido
    antes da escalada e não deve perdê-lo. Só o contador de falhas é zerado,
    senão a próxima incompreensão escalaria a conversa na hora de novo.
    """
    conversation.handoff = handoff

    if not handoff and conversation.state == ConversationState.ATENDIMENTO_HUMANO:
        conversation.state = ConversationState.CONVERSANDO
        conversation.fail_count = 0

    await session.flush()
    return conversation


# ---------------------------------------------------------------------------
# Métricas do dashboard
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

#: Quantos dias cada faixa do dashboard cobre (inclusive o dia de hoje).
RANGE_DAYS: dict[str, int] = {"hoje": 1, "semana": 7, "mes": 30}

#: O que conta como venda. As views do schema já embutem esta regra, mas elas
#: agregam sobre todo o histórico e por isso não servem para as consultas que
#: precisam respeitar o filtro de período do dashboard. Para não escrever a
#: regra em dois lugares, os SQLs por período reaproveitam este fragmento.
_VALID_SALE = "o.payment_status = 'pago' AND o.status <> 'cancelado'"

#: Início da janela: hoje = só hoje; semana = últimos 7 dias, contando hoje.
_WINDOW_START = "date_trunc('day', now()) - make_interval(days => :days - 1)"

_PERIOD_CTE = """
WITH bounds AS (
    SELECT date_trunc('day', now()) - make_interval(days => :days - 1) AS inicio,
           date_trunc('day', now()) - make_interval(days => 2 * :days - 1) AS inicio_anterior
)
"""

_SUMMARY_SQL = text(
    _PERIOD_CTE
    + """
SELECT
    (SELECT coalesce(sum(o.total), 0) FROM orders o, bounds b
      WHERE o.payment_status = 'pago' AND o.status <> 'cancelado'
        AND o.created_at >= b.inicio)                                AS total_vendas,
    (SELECT count(*) FROM orders o, bounds b
      WHERE o.payment_status = 'pago' AND o.status <> 'cancelado'
        AND o.created_at >= b.inicio)                                AS total_pedidos,
    (SELECT coalesce(sum(o.total), 0) FROM orders o, bounds b
      WHERE o.payment_status = 'pago' AND o.status <> 'cancelado'
        AND o.created_at >= b.inicio_anterior AND o.created_at < b.inicio)
                                                                     AS total_anterior
"""
)

_STATUS_SQL = text(
    _PERIOD_CTE
    + """
SELECT o.status::text AS status, count(*) AS quantidade
FROM orders o, bounds b
WHERE o.created_at >= b.inicio
GROUP BY 1
"""
)

# generate_series garante dia sem venda no gráfico (senão a linha "pula" datas).
_DAILY_SQL = text(
    """
SELECT d.dia::date            AS dia,
       coalesce(v.pedidos, 0) AS pedidos,
       coalesce(v.total, 0)   AS total
FROM generate_series(
        date_trunc('day', now()) - make_interval(days => :days - 1),
        date_trunc('day', now()),
        interval '1 day'
     ) AS d(dia)
LEFT JOIN vw_daily_sales v ON v.dia = d.dia::date
ORDER BY d.dia
"""
)

_PRODUCT_SQL = text(
    f"""
SELECT oi.product_name_snapshot AS produto,
       sum(oi.quantity)         AS unidades,
       sum(oi.line_total)       AS receita
FROM order_items oi
JOIN orders o ON o.id = oi.order_id
WHERE {_VALID_SALE}
  AND o.created_at >= {_WINDOW_START}
GROUP BY 1
ORDER BY receita DESC, unidades DESC
LIMIT :limit
"""
)

# generate_series mantém as 24 faixas no gráfico mesmo sem venda na hora.
_HOURLY_SQL = text(
    f"""
SELECT h.hora                 AS hora,
       coalesce(v.pedidos, 0) AS pedidos,
       coalesce(v.receita, 0) AS receita
FROM generate_series(0, 23) AS h(hora)
LEFT JOIN (
    SELECT extract(hour FROM o.created_at)::int AS hora,
           count(*)                             AS pedidos,
           coalesce(sum(o.total), 0)            AS receita
    FROM orders o
    WHERE {_VALID_SALE}
      AND o.created_at >= {_WINDOW_START}
    GROUP BY 1
) v ON v.hora = h.hora
ORDER BY h.hora
"""
)


async def summary_totals(session: AsyncSession, *, days: int) -> dict[str, Any]:
    row = (await session.execute(_SUMMARY_SQL, {"days": days})).mappings().one()
    return dict(row)


async def summary_by_status(session: AsyncSession, *, days: int) -> dict[str, int]:
    rows = (await session.execute(_STATUS_SQL, {"days": days})).mappings().all()
    return {row["status"]: int(row["quantidade"]) for row in rows}


async def daily_sales(session: AsyncSession, *, days: int) -> list[dict[str, Any]]:
    rows = (await session.execute(_DAILY_SQL, {"days": days})).mappings().all()
    return [dict(row) for row in rows]


async def product_sales(
    session: AsyncSession, *, limit: int = 10, days: int = 7
) -> list[dict[str, Any]]:
    rows = (
        (await session.execute(_PRODUCT_SQL, {"limit": limit, "days": days}))
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


async def hourly_sales(session: AsyncSession, *, days: int = 7) -> list[dict[str, Any]]:
    rows = (await session.execute(_HOURLY_SQL, {"days": days})).mappings().all()
    return [dict(row) for row in rows]


def as_decimal(value: Any) -> Decimal:
    """`sum()` do Postgres volta como Decimal, mas 0 pode vir como int."""
    return value if isinstance(value, Decimal) else Decimal(str(value or 0))

# ---------------------------------------------------------------------------
# Números do painel
# ---------------------------------------------------------------------------


def _variation(current: Decimal, previous: Decimal) -> Decimal:
    """Variação % contra o período anterior.

    Sem base de comparação (período anterior zerado) devolvemos 0 em vez de
    "+100%": o dashboard não deve inventar crescimento no primeiro dia de uso.
    """
    if previous <= ZERO:
        return ZERO
    return ((current - previous) / previous * 100).quantize(Decimal("0.1"))


async def get_summary(
    session: AsyncSession, *, range_: MetricsRange = MetricsRange.HOJE
) -> MetricsSummary:
    days = RANGE_DAYS[range_.value]
    totals = await summary_totals(session, days=days)
    by_status = await summary_by_status(session, days=days)

    total_vendas = arredondar_dinheiro(as_decimal(totals["total_vendas"]))
    total_pedidos = int(totals["total_pedidos"])
    anterior = as_decimal(totals["total_anterior"])
    ticket = arredondar_dinheiro(total_vendas / total_pedidos) if total_pedidos else ZERO

    return MetricsSummary(
        total_vendas=total_vendas,
        total_pedidos=total_pedidos,
        ticket_medio=ticket,
        variacao_percentual=_variation(total_vendas, anterior),
        por_status=by_status,
    )


async def get_daily_sales(session: AsyncSession, *, days: int = 7) -> list[DailySales]:
    rows = await daily_sales(session, days=days)
    return [
        DailySales(
            dia=row["dia"],
            pedidos=int(row["pedidos"]),
            total=arredondar_dinheiro(as_decimal(row["total"])),
        )
        for row in rows
    ]


async def get_product_sales(
    session: AsyncSession,
    *,
    limit: int = 10,
    range_: MetricsRange = MetricsRange.SEMANA,
) -> list[ProductSales]:
    days = RANGE_DAYS[range_.value]
    rows = await product_sales(session, limit=limit, days=days)
    return [
        ProductSales(
            produto=row["produto"],
            unidades=int(row["unidades"]),
            receita=arredondar_dinheiro(as_decimal(row["receita"])),
        )
        for row in rows
    ]


async def get_hourly_sales(
    session: AsyncSession, *, range_: MetricsRange = MetricsRange.SEMANA
) -> list[HourlySales]:
    days = RANGE_DAYS[range_.value]
    rows = await hourly_sales(session, days=days)
    return [
        HourlySales(
            hora=int(row["hora"]),
            pedidos=int(row["pedidos"]),
            receita=arredondar_dinheiro(as_decimal(row["receita"])),
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Provedor de Pix (Mercado Pago e o falso)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Pedidos
# ---------------------------------------------------------------------------

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Acesso a dados
# ---------------------------------------------------------------------------


async def list_orders(
    session: AsyncSession,
    *,
    status: OrderStatus | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Order]:
    """Lista para o Kanban: mais recentes primeiro, com itens e pagamentos."""
    stmt = select(Order).order_by(Order.created_at.desc()).limit(limit).offset(offset)
    if status is not None:
        stmt = stmt.where(Order.status == status)
    result = await session.scalars(stmt)
    return list(result)


async def get_order(session: AsyncSession, order_id: UUID) -> Order | None:
    return await session.get(Order, order_id)


async def next_code_number(session: AsyncSession) -> int:
    """`nextval('order_code_seq')` — números sem colisão mesmo em concorrência."""
    value = await session.scalar(select(order_code_seq.next_value()))
    return int(value)


# ---------------------------------------------------------------------------
# Erros de domínio (as rotas traduzem para HTTP)
# ---------------------------------------------------------------------------


class OrderError(RuntimeError):
    """Erro de regra de negócio de pedido."""


class EmptyCartError(OrderError):
    pass


class MissingAddressError(OrderError):
    pass


class OrderNotFoundError(OrderError):
    pass


class InvalidStatusTransition(OrderError):
    def __init__(self, origin: OrderStatus, destination: OrderStatus) -> None:
        super().__init__(f"Não dá para ir de '{origin}' para '{destination}'.")
        self.origin = origin
        self.destination = destination


# ---------------------------------------------------------------------------
# Transições de status do PEDIDO (o Kanban)
# ---------------------------------------------------------------------------
# Nada a ver com o estado da CONVERSA (app/agent/states.py): aqui é o fluxo
# físico do pedido dentro da loja.

ORDER_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.NOVO: {OrderStatus.PREPARANDO, OrderStatus.CANCELADO},
    OrderStatus.PREPARANDO: {
        OrderStatus.ENTREGA,
        OrderStatus.FINALIZADO,  # retirada no balcão pula a entrega
        OrderStatus.CANCELADO,
    },
    OrderStatus.ENTREGA: {OrderStatus.FINALIZADO, OrderStatus.CANCELADO},
    OrderStatus.FINALIZADO: set(),
    OrderStatus.CANCELADO: set(),
}


def can_transition_order(origin: OrderStatus, destination: OrderStatus) -> bool:
    """Repetir o mesmo status é aceito (PATCH idempotente vindo do Kanban)."""
    if origin == destination:
        return True
    return destination in ORDER_TRANSITIONS.get(origin, set())


def assert_order_transition(origin: OrderStatus, destination: OrderStatus) -> None:
    if not can_transition_order(origin, destination):
        raise InvalidStatusTransition(origin, destination)


# ---------------------------------------------------------------------------
# Código curto do pedido
# ---------------------------------------------------------------------------

_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_CODE_SPACE = 36**4
#: Primo coprimo com 36^4: embaralha a sequência sem gerar colisão (bijetivo),
#: para "#0001, #0002" não virar contador público de vendas.
_SCRAMBLE = 7919


def format_order_code(number: int) -> str:
    """Transforma o nextval da sequence num código curto tipo "#063Z"."""
    value = (number * _SCRAMBLE) % _CODE_SPACE
    digits = []
    for _ in range(4):
        value, remainder = divmod(value, 36)
        digits.append(_ALPHABET[remainder])
    return "#" + "".join(reversed(digits))


# ---------------------------------------------------------------------------
# Criação do pedido
# ---------------------------------------------------------------------------


async def create_order_from_cart(
    session: AsyncSession,
    *,
    cart: Cart,
    phone: str,
    customer_name: str | None,
    fulfillment_type: FulfillmentType,
    address: dict | None,
    channel: OrderChannel,
    notes: str | None = None,
) -> OrderCreated:
    """Fecha o carrinho num pedido persistido e devolve o essencial.

    Congela nome e preço de produto/complemento em cada item: se o lojista
    mudar a tabela amanhã, o histórico continua contando a verdade.
    """
    if cart.is_empty:
        raise EmptyCartError("Carrinho vazio — não há o que fechar.")

    customer = await get_or_create_customer(
        session, phone=phone, name=customer_name
    )

    saved_address = None
    if fulfillment_type is FulfillmentType.ENTREGA:
        saved_address = await save_address(
            session, customer_id=customer.id, address=address or {}
        )
        if saved_address is None:
            raise MissingAddressError(
                "Entrega exige rua, número e bairro."
            )

    breakdown = calculate_cart(cart, fulfillment_type=fulfillment_type)
    code = format_order_code(await next_code_number(session))

    order = Order(
        code=code,
        customer_id=customer.id,
        address_id=saved_address.id if saved_address else None,
        fulfillment_type=fulfillment_type,
        channel=channel,
        status=OrderStatus.NOVO,
        payment_status=PaymentStatus.PENDENTE,
        subtotal=breakdown.subtotal,
        delivery_fee=breakdown.delivery_fee,
        total=breakdown.total,
        notes=notes,
    )
    session.add(order)
    await session.flush()

    for cart_item in cart.items:
        item = OrderItem(
            order_id=order.id,
            product_id=cart_item.product_id,
            product_name_snapshot=cart_item.product_name,
            unit_base_price=arredondar_dinheiro(cart_item.unit_base_price),
            quantity=cart_item.quantity,
            line_total=cart_item.line_total,
            details=cart_item.details,
        )
        session.add(item)
        await session.flush()
        for complement in cart_item.complements:
            session.add(
                OrderItemComplement(
                    order_item_id=item.id,
                    complement_id=complement.id,
                    complement_name_snapshot=complement.name,
                    extra_price_snapshot=arredondar_dinheiro(complement.extra_price),
                )
            )

    await session.flush()
    logger.info("Pedido %s criado (%s) total=%s", order.code, channel, order.total)

    return OrderCreated(
        id=order.id,
        code=order.code,
        subtotal=order.subtotal,
        delivery_fee=order.delivery_fee,
        total=order.total,
        status=order.status,
        payment_status=order.payment_status,
    )


# ---------------------------------------------------------------------------
# Status e leitura
# ---------------------------------------------------------------------------


async def update_order_status(
    session: AsyncSession, order_id: UUID, new_status: OrderStatus
) -> Order:
    order = await get_order(session, order_id)
    if order is None:
        raise OrderNotFoundError(f"Pedido {order_id} não encontrado.")

    assert_order_transition(order.status, new_status)
    if order.status == new_status:
        return order

    order.status = new_status
    if new_status is OrderStatus.CANCELADO:
        order.cancelled_at = datetime.now(timezone.utc)
    await session.flush()
    logger.info("Pedido %s -> %s", order.code, new_status)
    return order


def _summary_item(item: OrderItem) -> OrderSummaryItem:
    unit_price = item_unit_price(
        item.unit_base_price, (c.extra_price_snapshot for c in item.complements)
    )
    return OrderSummaryItem(
        product_name=item.product_name_snapshot,
        quantity=item.quantity,
        complements=[c.complement_name_snapshot for c in item.complements],
        unit_price=unit_price,
        line_total=item.line_total,
        details=item.details,
    )


async def get_order_summary(
    session: AsyncSession, order_id: UUID
) -> OrderSummary | None:
    """Resumo pronto para o agente ler em voz alta para o cliente."""
    order = await get_order(session, order_id)
    if order is None:
        return None

    pending = await get_pending_payment(session, order.id)
    return OrderSummary(
        id=order.id,
        code=order.code,
        status=order.status,
        payment_status=order.payment_status,
        fulfillment_type=order.fulfillment_type,
        subtotal=order.subtotal,
        delivery_fee=order.delivery_fee,
        total=order.total,
        items=[_summary_item(item) for item in order.items],
        customer_name=order.customer.name if order.customer else None,
        customer_phone=order.customer.phone if order.customer else None,
        address_line=format_address(order.address),
        notes=order.notes,
        created_at=order.created_at,
        paid_at=order.paid_at,
        pix_qr_code=pending.qr_code if pending else None,
    )


# ---------------------------------------------------------------------------
# Pagamentos
# ---------------------------------------------------------------------------

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Acesso a dados
# ---------------------------------------------------------------------------


async def get_payment_by_provider_id(
    session: AsyncSession, *, provider: str, provider_payment_id: str
) -> Payment | None:
    return await session.scalar(
        select(Payment).where(
            Payment.provider == provider,
            Payment.provider_payment_id == provider_payment_id,
        )
    )


async def get_latest_payment(
    session: AsyncSession,
    order_id: UUID,
    *,
    status: PaymentStatus | None = None,
) -> Payment | None:
    stmt = (
        select(Payment)
        .where(Payment.order_id == order_id)
        .order_by(Payment.created_at.desc())
        .limit(1)
    )
    if status is not None:
        stmt = stmt.where(Payment.status == status)
    return await session.scalar(stmt)


async def create_payment(session: AsyncSession, data: dict[str, Any]) -> Payment:
    payment = Payment(**data)
    session.add(payment)
    await session.flush()
    return payment


async def claim_webhook_event(
    session: AsyncSession,
    *,
    source: str,
    external_id: str,
    payload: dict[str, Any],
) -> WebhookEvent | None:
    """Registra o evento e devolve None se ele já tinha sido registrado.

    A idempotência é do banco (UNIQUE source+external_id) e não da aplicação:
    o Mercado Pago reenvia a mesma notificação e duas réplicas do backend
    podem recebê-la ao mesmo tempo.
    """
    stmt = (
        pg_insert(WebhookEvent)
        .values(source=source, external_id=external_id, payload=payload)
        .on_conflict_do_nothing(constraint="uq_webhook_event")
        .returning(WebhookEvent.id)
    )
    inserted_id = await session.scalar(stmt)
    if inserted_id is None:
        return None
    return await session.get(WebhookEvent, inserted_id)


async def mark_event_processed(
    session: AsyncSession, event: WebhookEvent, *, error: str | None = None
) -> None:
    event.processed_at = datetime.now(timezone.utc)
    event.error = error
    await session.flush()

# ---------------------------------------------------------------------------
# Cobrança e confirmação
# ---------------------------------------------------------------------------


async def create_pix_for_order(session: AsyncSession, order_id: UUID) -> PixCharge:
    """Cria (ou reaproveita) a cobrança Pix do pedido.

    Reaproveitar a cobrança pendente evita gerar dois QR para o mesmo pedido
    quando o cliente pede o código de novo.
    """
    order = await get_order(session, order_id)
    if order is None:
        raise OrderNotFoundError(f"Pedido {order_id} não encontrado.")
    if order.payment_status is PaymentStatus.PAGO:
        raise OrderError("Pedido já está pago.")

    provider = get_payment_provider()

    existing = await get_latest_payment(
        session, order_id, status=PaymentStatus.PENDENTE
    )
    if existing is not None and existing.provider == provider.name and existing.qr_code:
        return PixCharge(
            provider=existing.provider,
            provider_payment_id=existing.provider_payment_id or "",
            amount=existing.amount,
            qr_code=existing.qr_code,
            qr_code_base64=existing.qr_code_base64,
            ticket_url=existing.ticket_url,
            expires_at=existing.expires_at,
            raw=existing.raw_payload or {},
        )

    charge = await provider.create_pix_charge(
        order_id=order.id,
        order_code=order.code,
        amount=order.total,
        payer_name=order.customer.name if order.customer else None,
        payer_phone=order.customer.phone if order.customer else None,
    )

    await create_payment(
        session,
        {
            "order_id": order.id,
            "provider": charge.provider,
            "provider_payment_id": charge.provider_payment_id,
            "method": "pix",
            "amount": arredondar_dinheiro(charge.amount),
            "status": PaymentStatus.PENDENTE,
            "qr_code": charge.qr_code,
            "qr_code_base64": charge.qr_code_base64,
            "ticket_url": charge.ticket_url,
            "expires_at": charge.expires_at,
            "raw_payload": charge.raw or None,
        },
    )
    await session.flush()
    logger.info("Pix criado para %s (%s)", order.code, charge.provider_payment_id)
    return charge


async def apply_payment_result(
    session: AsyncSession, result: PaymentStatusResult, *, provider_name: str
) -> tuple[Order | None, bool]:
    """Aplica ao banco o status consultado no provedor.

    Devolve `(pedido, aprovado_agora)`. `aprovado_agora` é False quando o
    pedido já estava pago — é o que impede o webhook de notificar o cliente
    duas vezes.
    """
    payment = await get_payment_by_provider_id(
        session,
        provider=provider_name,
        provider_payment_id=result.provider_payment_id,
    )
    order: Order | None = None
    if payment is not None:
        order = await get_order(session, payment.order_id)
    elif result.external_reference:
        # Cobrança criada fora do nosso fluxo: ainda dá para achar o pedido.
        try:
            order = await get_order(session, UUID(result.external_reference))
        except ValueError:
            order = None

    if order is None:
        logger.warning(
            "Pagamento %s sem pedido correspondente", result.provider_payment_id
        )
        return None, False

    if payment is not None:
        payment.status = result.status
        payment.raw_payload = result.raw or payment.raw_payload

    already_paid = order.payment_status is PaymentStatus.PAGO
    approved_now = result.status is PaymentStatus.PAGO and not already_paid

    if approved_now:
        order.payment_status = PaymentStatus.PAGO
        order.paid_at = datetime.now(timezone.utc)
        if order.status is OrderStatus.NOVO:
            # Pagou, entra na fila da produção.
            order.status = OrderStatus.PREPARANDO
    elif result.status in {PaymentStatus.EXPIRADO, PaymentStatus.CANCELADO}:
        if not already_paid:
            order.payment_status = result.status

    await session.flush()
    return order, approved_now


async def get_pending_payment(session: AsyncSession, order_id: UUID) -> Payment | None:
    """Cobrança Pix pendente do pedido, se houver."""
    return await get_latest_payment(
        session, order_id, status=PaymentStatus.PENDENTE
    )
