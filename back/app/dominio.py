"""As estruturas de dados do negócio: estados, cardápio e carrinho.

Três coisas que não dependem de nada — nem de banco, nem de API, nem do
agente — e que todo o resto usa:

* **Enumerações** — os valores em string espelham exatamente os tipos ENUM de
  `back/db/schema.sql`. Mudou aqui, muda lá.
* **Cardápio** — o snapshot imutável que serve de "chão" para o agente: o LLM
  nunca inventa produto, sabor ou preço; ele devolve texto livre e o resolvedor
  casa esse texto contra este snapshot.
* **Carrinho** — o pedido em construção durante a conversa, e a conta dele.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enumerações
# ---------------------------------------------------------------------------


class OrderStatus(StrEnum):
    NOVO = "novo"
    PREPARANDO = "preparando"
    ENTREGA = "entrega"
    FINALIZADO = "finalizado"
    CANCELADO = "cancelado"


class PaymentStatus(StrEnum):
    PENDENTE = "pendente"
    PAGO = "pago"
    EXPIRADO = "expirado"
    CANCELADO = "cancelado"
    REEMBOLSADO = "reembolsado"


class FulfillmentType(StrEnum):
    ENTREGA = "entrega"
    RETIRADA = "retirada"


class OrderChannel(StrEnum):
    WHATSAPP = "whatsapp"
    ADMIN = "admin"
    SIMULADOR = "simulador"


class MessageDirection(StrEnum):
    ENTRADA = "entrada"
    SAIDA = "saida"


class ConversationState(StrEnum):
    """Onde a conversa está — só o que muda o que o sistema PODE fazer.

    Eram dez estados, um para cada etapa do diálogo (saudação, escolhendo
    produto, personalizando item, revisando carrinho, coletando endereço). Na
    prática a etapa do diálogo já está nos `slots` — tem item em construção?
    o carrinho está vazio? falta endereço? — e ter as duas coisas fazia o
    agente brigar consigo mesmo: o cliente falava de sabor num estado que só
    aceitava produto e ouvia "não entendi".

    Ficaram os estados que carregam uma *garantia*, não uma etapa:

    - `CONVERSANDO`: montando o pedido. O que acontece aqui é decidido pelo
      que a IA entendeu + o que já está nos slots.
    - `CONFIRMANDO_PEDIDO`: o cliente viu o resumo com o total. É o único
      lugar de onde se pode cobrar.
    - `AGUARDANDO_PAGAMENTO`: Pix emitido; só o webhook do provedor tira daqui.
    - `CONCLUIDO` / `CANCELADO`: fim de ciclo.
    - `ATENDIMENTO_HUMANO`: o bot cala enquanto a loja atende.
    """

    CONVERSANDO = "conversando"
    CONFIRMANDO_PEDIDO = "confirmando_pedido"
    AGUARDANDO_PAGAMENTO = "aguardando_pagamento"
    CONCLUIDO = "concluido"
    ATENDIMENTO_HUMANO = "atendimento_humano"
    CANCELADO = "cancelado"


#: Estados das versões anteriores, para as conversas que já estão no banco.
#: Todos eram etapas do diálogo, e hoje o diálogo inteiro é `CONVERSANDO`.
LEGACY_STATES = {
    "saudacao": ConversationState.CONVERSANDO,
    "escolhendo_produto": ConversationState.CONVERSANDO,
    "personalizando_item": ConversationState.CONVERSANDO,
    "revisando_carrinho": ConversationState.CONVERSANDO,
    "coletando_endereco": ConversationState.CONVERSANDO,
}


def parse_state(raw: str) -> ConversationState:
    """Lê o estado do banco aceitando os nomes antigos."""
    try:
        return ConversationState(raw)
    except ValueError:
        return LEGACY_STATES.get(raw, ConversationState.CONVERSANDO)


# ---------------------------------------------------------------------------
# Cardápio
# ---------------------------------------------------------------------------


def normalize(text: str) -> str:
    """Minúsculas, sem acento e sem espaço sobrando — para casar nomes."""
    stripped = unicodedata.normalize("NFKD", text.strip().lower())
    return "".join(ch for ch in stripped if not unicodedata.combining(ch))


class CatalogComplement(BaseModel):
    #: "Sem lactose" / "Com lactose" — é o que deixa o cardápio sair agrupado
    #: numa mensagem só em vez de 31 linhas soltas.
    category: str | None = None
    id: UUID
    group_id: UUID
    name: str
    extra_price: Decimal = Decimal("0")
    is_available: bool = True


class CatalogGroup(BaseModel):
    """Um grupo de escolhas JÁ RESOLVIDO para um produto.

    `id` é o id do grupo compartilhado (`complement_groups`), e é ele que casa
    com o `group_id` dos complementos no carrinho. `min_choices`/`max_choices`
    vêm do vínculo daquele produto, porque a mesma lista de sabores pode pedir
    2 escolhas num pote e 6 no combo. O snapshot é desnormalizado de propósito:
    o agente lê "este produto tem estes grupos com estas regras" e não precisa
    saber que existe uma tabela de vínculo.
    """

    id: UUID
    name: str
    min_choices: int = 0
    max_choices: int = 1
    is_required: bool = False
    complements: list[CatalogComplement] = Field(default_factory=list)

    @property
    def available_complements(self) -> list[CatalogComplement]:
        return [c for c in self.complements if c.is_available]


class CatalogProduct(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    base_price: Decimal
    is_available: bool = True
    groups: list[CatalogGroup] = Field(default_factory=list)

    @property
    def required_groups(self) -> list[CatalogGroup]:
        return [g for g in self.groups if g.is_required or g.min_choices > 0]


class CatalogSnapshot(BaseModel):
    """O cardápio inteiro, já montado em árvore, como o agente enxerga."""

    products: list[CatalogProduct] = Field(default_factory=list)

    @property
    def available_products(self) -> list[CatalogProduct]:
        return [p for p in self.products if p.is_available]

    def product_by_id(self, product_id: UUID) -> CatalogProduct | None:
        return next((p for p in self.products if p.id == product_id), None)

    def product_by_name(self, name: str) -> CatalogProduct | None:
        """Produto cujo nome é exatamente `name` (ignorando acento e caixa).

        É por aqui que passa o nome de cardápio devolvido pelo LLM: ou ele
        existe de verdade, ou é descartado. Nome parecido não serve — para
        texto livre do cliente existe o `resolver`.
        """
        wanted = normalize(name)
        return next((p for p in self.products if normalize(p.name) == wanted), None)


# ---------------------------------------------------------------------------
# Carrinho e a conta dele
# ---------------------------------------------------------------------------
# O carrinho vive serializado no campo JSONB `conversations.cart` e vira
# order_items quando o pedido fecha. **Os nomes dos campos abaixo são dados
# gravados em conversas reais: renomeá-los quebraria toda conversa em aberto.**
#
# A conta mora aqui, e é uma só. Antes havia duas — estas propriedades somavam
# `Decimal` cru e eram o que o cliente via e confirmava no WhatsApp, enquanto
# `pricing` arredondava unidade por unidade e era o que virava pedido e
# cobrança. Os resultados batiam por causa do `numeric(10, 2)` do banco, mas
# duas implementações da mesma conta é exatamente a divergência que se queria
# evitar. Hoje o `pricing` só cuida do que depende de configuração (taxa de
# entrega, o resumo em `PriceBreakdown`) e chama esta conta.
#
# A regra do arredondamento: **arredonda o unitário antes de multiplicar**. É
# assim que o cliente confere ("2 x R$ 24,90 = R$ 49,80") e é o que evita
# diferença de centavo entre o que foi dito no WhatsApp e o que foi gravado.

CENTS = Decimal("0.01")
ZERO = Decimal("0.00")


def arredondar_dinheiro(value: Decimal | int | float | str) -> Decimal:
    """Normaliza qualquer valor monetário para 2 casas (ROUND_HALF_UP).

    ROUND_HALF_UP é o arredondamento comercial esperado no Brasil — e não o
    `ROUND_HALF_EVEN` que o Python usa por padrão.

    Chamava-se `money`, igual à função que formata "R$ 12,34" em `textos.py`:
    mesmo nome, uma devolvendo número e a outra texto. Quem lia `money(x)`
    precisava saber em que arquivo estava para saber o que ia receber.
    """
    return Decimal(str(value)).quantize(CENTS, rounding=ROUND_HALF_UP)


def complements_total(extras: Iterable[Decimal]) -> Decimal:
    """Soma dos adicionais de UMA unidade do item."""
    return arredondar_dinheiro(sum(extras, ZERO))


def item_unit_price(base_price: Decimal, extras: Iterable[Decimal] = ()) -> Decimal:
    """Preço de uma unidade: base + complementos escolhidos."""
    return arredondar_dinheiro(arredondar_dinheiro(base_price) + complements_total(extras))


class CartComplement(BaseModel):
    id: UUID
    group_id: UUID
    name: str
    extra_price: Decimal = Decimal("0")


class CartItem(BaseModel):
    product_id: UUID
    product_name: str
    unit_base_price: Decimal
    quantity: int = 1
    complements: list[CartComplement] = Field(default_factory=list)
    details: str | None = None

    @property
    def unit_price(self) -> Decimal:
        """Preço de uma unidade já com os complementos escolhidos."""
        return item_unit_price(
            self.unit_base_price, (c.extra_price for c in self.complements)
        )

    @property
    def line_total(self) -> Decimal:
        """Total da linha: (base + adicionais) * quantidade."""
        if self.quantity < 1:
            raise ValueError("quantidade precisa ser >= 1")
        return arredondar_dinheiro(self.unit_price * self.quantity)


class Cart(BaseModel):
    items: list[CartItem] = Field(default_factory=list)

    @property
    def subtotal(self) -> Decimal:
        return arredondar_dinheiro(sum((item.line_total for item in self.items), ZERO))

    @property
    def is_empty(self) -> bool:
        return not self.items

    def total(self, delivery_fee: Decimal = ZERO) -> Decimal:
        return arredondar_dinheiro(self.subtotal + arredondar_dinheiro(delivery_fee))
