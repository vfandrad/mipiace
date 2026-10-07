"""Os schemas: o contrato de dados entre o backend e o painel.

**Os nomes dos campos aqui são as chaves do JSON que o painel lê**, e
`front/src/types/` os espelha um a um — renomear um campo aqui quebra a tela
do outro lado.

Ficam num arquivo próprio, e não dentro de `api.py`, porque quem os monta são
os serviços: se morassem junto das rotas, `servicos.py` teria de importar a
camada de API, e as duas se importariam em círculo.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator, model_validator

from app.dominio import FulfillmentType, MessageDirection, OrderChannel, OrderStatus, PaymentStatus

# ---------------------------------------------------------------------------
# Tipos comuns
# ---------------------------------------------------------------------------

#: Dinheiro trafega como número JSON (12.5), não string.
#: Internamente continua sendo `Decimal` — a conversão só acontece na borda,
#: na serialização, para o front não precisar de `Number(...)` em todo lugar.
Money = Annotated[
    Decimal,
    Field(ge=0, max_digits=10, decimal_places=2),
    PlainSerializer(float, return_type=float, when_used="json"),
]

#: Igual a `Money`, mas sem o piso de zero (variações percentuais, deltas).
Amount = Annotated[
    Decimal,
    PlainSerializer(float, return_type=float, when_used="json"),
]


class ORMModel(BaseModel):
    """DTO lido diretamente de um objeto SQLAlchemy."""

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Catálogo — entrada e saída
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------


class ComplementRead(ORMModel):
    id: UUID
    group_id: UUID
    name: str
    extra_price: Money
    is_available: bool
    sort_order: int
    category_id: UUID | None = None


class GroupRead(ORMModel):
    """Um grupo da biblioteca: a lista com nome, sem regra de escolha.

    A regra ("escolhe 2 a 3") não está aqui porque ela é de cada produto que usa
    o grupo — mora em `ProductGroupRead`.
    """

    id: UUID
    name: str
    sort_order: int
    complements: list[ComplementRead] = Field(default_factory=list)


class ProductGroupRead(ORMModel):
    """Um grupo COMO ESTE PRODUTO O USA — é o que o painel e o agente leem.

    Achata o vínculo e o grupo numa coisa só: `id` é o do vínculo (é o que se
    edita para mudar quantos sabores este produto pede, ou se desvincula),
    `group_id` é o da lista compartilhada.
    """

    id: UUID
    group_id: UUID
    name: str
    min_choices: int
    max_choices: int
    is_required: bool
    sort_order: int
    complements: list[ComplementRead] = Field(default_factory=list)


class ProductRead(ORMModel):
    id: UUID
    name: str
    description: str | None = None
    base_price: Money
    is_available: bool
    sort_order: int
    created_at: datetime | None = None
    updated_at: datetime | None = None
    groups: list[ProductGroupRead] = Field(default_factory=list)


class ProductList(BaseModel):
    """Envelope de `GET /api/products` (contrato do SPEC)."""

    products: list[ProductRead] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Escrita
# ---------------------------------------------------------------------------


def _clean_name(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("nome não pode ser vazio")
    return cleaned


class _ComNome(BaseModel):
    """Base de todo schema que recebe `name` do painel.

    O mesmo validador estava copiado dez vezes, uma por entidade. Aqui ele
    existe uma vez só; `check_fields=False` é o que permite declará-lo antes
    de o campo `name` existir, já que quem o declara é a subclasse.
    """

    @field_validator("name", check_fields=False)
    @classmethod
    def _limpar_nome(cls, value: str | None) -> str | None:
        return _clean_name(value) if value is not None else None


class ProductCreate(_ComNome):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    base_price: Money
    is_available: bool = True
    sort_order: int = Field(default=0, ge=0)


class ProductUpdate(_ComNome):
    """PATCH: só os campos enviados são alterados."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    base_price: Money | None = None
    is_available: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)


class GroupCreate(_ComNome):
    """Cria a lista na biblioteca. Vincular a um produto é outra operação."""

    name: str = Field(min_length=1, max_length=120)
    sort_order: int = Field(default=0, ge=0)


class GroupUpdate(_ComNome):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    sort_order: int | None = Field(default=None, ge=0)


def _validar_escolhas(min_choices: int, max_choices: int, is_required: bool) -> None:
    if max_choices < min_choices:
        raise ValueError("max_choices não pode ser menor que min_choices")
    if is_required and min_choices < 1:
        # Grupo obrigatório com min=0 é contraditório e travaria o agente, que
        # decide "falta escolher?" olhando min_choices.
        raise ValueError("grupo obrigatório precisa de min_choices >= 1")


class ProductGroupCreate(_ComNome):
    """Faz um produto usar um grupo — o "importar grupo" do painel.

    Ou aponta um grupo que já existe (`group_id`), ou cria um novo pelo nome
    (`name`). Os dois caminhos numa requisição só porque, na tela, "usar o grupo
    Sabores" e "criar o grupo Coberturas" são o mesmo gesto.
    """

    group_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    min_choices: int = Field(default=0, ge=0)
    max_choices: int = Field(default=1, ge=1)
    is_required: bool = False
    sort_order: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _check(self) -> ProductGroupCreate:
        if (self.group_id is None) == (self.name is None):
            raise ValueError("informe group_id (usar um grupo) ou name (criar um)")
        _validar_escolhas(self.min_choices, self.max_choices, self.is_required)
        return self


class ProductGroupUpdate(_ComNome):
    """Edita o grupo como este produto o usa.

    A regra de escolha é deste produto. O `name` é da lista compartilhada, então
    renomear aqui renomeia para todos os produtos que a usam — que é o
    esperado, é a mesma lista. Os dois vêm juntos porque, na tela, "editar o
    grupo Sabores deste produto" é um gesto só.
    """

    name: str | None = Field(default=None, min_length=1, max_length=120)
    min_choices: int | None = Field(default=None, ge=0)
    max_choices: int | None = Field(default=None, ge=1)
    is_required: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _check_range(self) -> ProductGroupUpdate:
        if (
            self.min_choices is not None
            and self.max_choices is not None
            and self.max_choices < self.min_choices
        ):
            raise ValueError("max_choices não pode ser menor que min_choices")
        return self


class ComplementCreate(_ComNome):
    name: str = Field(min_length=1, max_length=120)
    extra_price: Money = Decimal("0")
    is_available: bool = True
    sort_order: int = Field(default=0, ge=0)
    category_id: UUID | None = None


class ComplementUpdate(_ComNome):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    extra_price: Money | None = None
    is_available: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)
    category_id: UUID | None = None


class ComplementCategoryRead(ORMModel):
    id: UUID
    name: str
    sort_order: int


class ComplementCategoryCreate(_ComNome):
    """Categoria de sabor ("Sem lactose", "Clássicos", "Frutados"...).

    É o lojista que decide quais existem: numa sorveteria são restrições, numa
    hamburgueria seriam outras coisas. Por isso a lista é dado, não constante
    de código.
    """

    name: str = Field(min_length=1, max_length=120)
    sort_order: int = Field(default=0, ge=0)


class ComplementCategoryUpdate(_ComNome):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    sort_order: int | None = Field(default=None, ge=0)


class ReorderRequest(BaseModel):
    """A nova ordem de uma lista, como ela ficou na tela depois do arrasto."""

    kind: Literal["product", "group", "product_group", "complement", "category"]
    ids: list[UUID] = Field(min_length=1, max_length=500)


# ---------------------------------------------------------------------------
# Pedidos — entrada e saída
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Contrato com o agente
# ---------------------------------------------------------------------------


class OrderCreated(BaseModel):
    """Retorno de `create_order_from_cart` — o mínimo para o agente responder."""

    id: UUID
    code: str
    subtotal: Money
    delivery_fee: Money
    total: Money
    status: OrderStatus = OrderStatus.NOVO
    payment_status: PaymentStatus = PaymentStatus.PENDENTE


class OrderSummaryItem(BaseModel):
    product_name: str
    quantity: int
    complements: list[str] = Field(default_factory=list)
    unit_price: Money
    line_total: Money
    details: str | None = None


class OrderSummary(BaseModel):
    """Resumo legível de um pedido, usado pelo agente ao responder o cliente."""

    id: UUID
    code: str
    status: OrderStatus
    payment_status: PaymentStatus
    fulfillment_type: FulfillmentType
    subtotal: Money
    delivery_fee: Money
    total: Money
    items: list[OrderSummaryItem] = Field(default_factory=list)
    customer_name: str | None = None
    customer_phone: str | None = None
    address_line: str | None = None
    notes: str | None = None
    created_at: datetime | None = None
    paid_at: datetime | None = None
    pix_qr_code: str | None = None  # copia-e-cola da última cobrança pendente


# ---------------------------------------------------------------------------
# Leitura (painel / Kanban)
# ---------------------------------------------------------------------------


class OrderItemComplementRead(ORMModel):
    id: UUID
    complement_id: UUID | None = None
    complement_name_snapshot: str
    extra_price_snapshot: Money


class OrderItemRead(ORMModel):
    id: UUID
    product_id: UUID | None = None
    product_name_snapshot: str
    unit_base_price: Money
    quantity: int
    line_total: Money
    details: str | None = None
    complements: list[OrderItemComplementRead] = Field(default_factory=list)


class PaymentRead(ORMModel):
    id: UUID
    provider: str
    provider_payment_id: str | None = None
    method: str
    amount: Money
    status: PaymentStatus
    qr_code: str | None = None
    ticket_url: str | None = None
    expires_at: datetime | None = None
    created_at: datetime | None = None


class AddressRead(ORMModel):
    id: UUID
    rua: str
    numero: str
    bairro: str
    complemento: str | None = None
    referencia: str | None = None


class CustomerRead(ORMModel):
    id: UUID
    phone: str
    name: str | None = None


class OrderRead(ORMModel):
    id: UUID
    code: str
    status: OrderStatus
    payment_status: PaymentStatus
    fulfillment_type: FulfillmentType
    channel: OrderChannel
    subtotal: Money
    delivery_fee: Money
    total: Money
    notes: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    paid_at: datetime | None = None
    cancelled_at: datetime | None = None
    customer: CustomerRead | None = None
    address: AddressRead | None = None
    items: list[OrderItemRead] = Field(default_factory=list)
    payments: list[PaymentRead] = Field(default_factory=list)


class OrderStatusUpdate(BaseModel):
    """Corpo de `PATCH /api/orders/{id}/status`."""

    status: OrderStatus


# ---------------------------------------------------------------------------
# Criação manual (painel) — fallback para quando o agente de IA está fora
# ---------------------------------------------------------------------------


class OrderItemInput(BaseModel):
    """Um item do pedido manual: produto e complementos pelo `id` do cardápio.

    O painel manda só os ids — nome e preço vêm do catálogo no servidor,
    nunca do que o navegador mandou. É a mesma regra do agente: quem decide
    preço é o backend.
    """

    product_id: UUID
    quantity: int = Field(default=1, ge=1, le=50)
    complement_ids: list[UUID] = Field(default_factory=list)


class AddressInput(BaseModel):
    rua: str
    numero: str
    bairro: str
    complemento: str | None = None
    referencia: str | None = None


class OrderCreateInput(BaseModel):
    """Corpo de `POST /api/orders` — lançamento manual pelo painel.

    Existe para o lojista continuar registrando pedido (telefone, balcão)
    quando o agente de WhatsApp está fora do ar. O pedido entra direto em
    `PREPARANDO`, pulando `NOVO`/Pix: quem lança já confirmou o pagamento (ou
    decidiu cobrar na entrega) na hora.
    """

    items: list[OrderItemInput] = Field(min_length=1)
    customer_name: str | None = None
    phone: str
    fulfillment_type: FulfillmentType
    address: AddressInput | None = None
    payment_status: PaymentStatus = PaymentStatus.PENDENTE
    notes: str | None = None


# ---------------------------------------------------------------------------
# Conversas — saída
# ---------------------------------------------------------------------------

class ConversationRead(ORMModel):
    id: UUID
    phone: str
    channel: str
    state: str
    handoff: bool
    fail_count: int
    customer_name: str | None = None
    last_message_preview: str | None = None
    active_order_id: UUID | None = None
    last_message_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ConversationMessageRead(ORMModel):
    id: UUID
    direction: MessageDirection
    content: str
    state_before: str | None = None
    state_after: str | None = None
    detected_intent: str | None = None
    confidence: Decimal | None = None
    llm_model: str | None = None
    created_at: datetime


class HandoffUpdate(BaseModel):
    """Corpo de `POST /api/conversations/{id}/handoff`."""

    handoff: bool


class HandoffResult(BaseModel):
    id: UUID
    handoff: bool
    state: str


# ---------------------------------------------------------------------------
# Métricas — saída
# ---------------------------------------------------------------------------

class MetricsRange(StrEnum):
    HOJE = "hoje"
    SEMANA = "semana"
    MES = "mes"


class MetricsSummary(BaseModel):
    total_vendas: Money
    total_pedidos: int
    ticket_medio: Money
    #: Variação % contra o período anterior de mesmo tamanho (pode ser negativa).
    variacao_percentual: Amount
    por_status: dict[str, int] = Field(default_factory=dict)


class DailySales(BaseModel):
    dia: date
    pedidos: int
    total: Money


class ProductSales(BaseModel):
    produto: str
    unidades: int
    receita: Money


class HourlySales(BaseModel):
    hora: int
    pedidos: int
    receita: Money
