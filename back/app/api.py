"""As rotas HTTP e as dependências que elas usam.

Cada grupo de rotas tem o seu `APIRouter` (`rotas_produtos`, `rotas_pedidos`,
…) porque num arquivo só não dá para todos se chamarem `router`. Quem os liga
no app é o `main.py`, que também decide quais exigem a chave de API.

Os schemas de entrada e saída moram em `esquemas.py` — são o contrato, e os
serviços também os usam.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import agente as inbox
from app import servicos as catalog
from app import servicos as conversations_service
from app import servicos as metrics_service
from app import servicos as orders_service
from app import servicos as payments_service
from app.agente import (
    EvolutionAdapter,
    InboundMessage,
    handle_inbound,
    handle_outbound_echo,
    load_or_create,
    notify_payment_approved,
    phone_allowed,
    reset_session,
)
from app.banco import get_session, get_sessionmaker
from app.configuracao import Settings, get_logger, get_settings, require_api_key
from app.dominio import OrderStatus
from app.esquemas import (
    ComplementCategoryCreate,
    ComplementCategoryRead,
    ComplementCategoryUpdate,
    ComplementCreate,
    ComplementRead,
    ComplementUpdate,
    ConversationMessageRead,
    ConversationRead,
    DailySales,
    GroupCreate,
    GroupRead,
    GroupUpdate,
    HandoffResult,
    HandoffUpdate,
    HourlySales,
    MetricsRange,
    MetricsSummary,
    OrderRead,
    OrderStatusUpdate,
    OrderSummary,
    ProductCreate,
    ProductGroupCreate,
    ProductGroupRead,
    ProductGroupUpdate,
    ProductList,
    ProductRead,
    ProductSales,
    ProductUpdate,
    ReorderRequest,
)
from app.servicos import FakePaymentProvider, get_payment_provider

# ---------------------------------------------------------------------------
# Dependências das rotas
# ---------------------------------------------------------------------------

#: Sessão de banco por request.
SessionDep = Annotated[AsyncSession, Depends(get_session)]

#: Configuração da aplicação.
SettingsDep = Annotated[Settings, Depends(get_settings)]

#: Proteção das rotas administrativas — aplicada no `include_router`.
ADMIN_DEPS = [Depends(require_api_key)]


async def require_fake_mode(settings: SettingsDep) -> None:
    """Bloqueia rotas de desenvolvimento quando o sistema roda pra valer."""
    if not settings.fake_mode:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rota disponível apenas com FAKE_MODE=true.",
        )


def not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


# ---------------------------------------------------------------------------
# Rota pública: saúde
# ---------------------------------------------------------------------------

rotas_saude = APIRouter(tags=["saúde"])

#: Versão do MVP; sobe junto com o contrato da API.
API_VERSION = "1.0.0"


class HealthResponse(BaseModel):
    status: str
    version: str
    fake_mode: bool
    environment: str
    database: str


@rotas_saude.get("/health", response_model=HealthResponse)
async def health(
    settings: SettingsDep, session: SessionDep, response: Response
) -> HealthResponse:
    """"ok" só se a request REALMENTE alcançar o banco.

    Antes só ecoava `Settings` — o processo respondia "ok" mesmo com o banco
    fora do ar ou com o schema desatualizado. Foi assim que um 503 real em
    `/api/products` (schema sem a tabela `product_groups`) passou despercebido:
    o `HEALTHCHECK` do Docker batia aqui, via "ok" e marcava o container
    saudável o tempo todo. Um `SELECT 1` é a checagem mais barata que ainda
    prova que a conexão funciona de verdade.
    """
    try:
        await session.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "erro"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status="ok" if db_status == "ok" else "degradado",
        version=API_VERSION,
        fake_mode=settings.fake_mode,
        environment=settings.environment,
        database=db_status,
    )


# ---------------------------------------------------------------------------
# Rotas do catálogo
# ---------------------------------------------------------------------------

rotas_produtos = APIRouter(prefix="/api", tags=["catálogo"])


@rotas_produtos.get("/complement-categories", response_model=list[ComplementCategoryRead])
async def list_complement_categories(session: SessionDep) -> list[ComplementCategoryRead]:
    categories = await catalog.list_complement_categories(session)
    return [ComplementCategoryRead.model_validate(c) for c in categories]


@rotas_produtos.post(
    "/complement-categories",
    response_model=ComplementCategoryRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_category(
    payload: ComplementCategoryCreate, session: SessionDep
) -> ComplementCategoryRead:
    category = await catalog.create_category(session, payload.model_dump())
    await session.commit()
    return ComplementCategoryRead.model_validate(category)


@rotas_produtos.patch("/complement-categories/{category_id}", response_model=ComplementCategoryRead)
async def update_category(
    category_id: UUID, payload: ComplementCategoryUpdate, session: SessionDep
) -> ComplementCategoryRead:
    category = await catalog.get_category(session, category_id)
    if category is None:
        raise not_found("Categoria não encontrada.")
    await catalog.update_item(session, category, payload.model_dump(exclude_unset=True))
    await session.commit()
    return ComplementCategoryRead.model_validate(category)


@rotas_produtos.delete(
    "/complement-categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_category(category_id: UUID, session: SessionDep) -> Response:
    """Apagar a categoria não apaga sabor nenhum.

    O vínculo em `complements.category_id` é ON DELETE SET NULL: os
    sabores continuam no cardápio, só deixam de estar agrupados.
    """
    category = await catalog.get_category(session, category_id)
    if category is None:
        raise not_found("Categoria não encontrada.")
    await catalog.delete_item(session, category)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@rotas_produtos.post("/catalog/reorder", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_catalog(payload: ReorderRequest, session: SessionDep) -> Response:
    """Grava a ordem que o lojista montou arrastando os itens no painel.

    Uma requisição para a lista inteira, e não uma por item: a ordem é uma
    coisa só, e meia ordem gravada sai torta no cardápio do WhatsApp.
    """
    try:
        await catalog.reorder(session, kind=payload.kind, ids=payload.ids)
    except ValueError as exc:
        raise bad_request(str(exc)) from exc
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Produtos
# ---------------------------------------------------------------------------


@rotas_produtos.get("/products", response_model=ProductList)
async def list_products(session: SessionDep, only_available: bool = False) -> ProductList:
    products = await catalog.list_products(
        session, only_available=only_available
    )
    return ProductList(products=[ProductRead.model_validate(p) for p in products])


@rotas_produtos.post("/products", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
async def create_product(payload: ProductCreate, session: SessionDep) -> ProductRead:
    product = await catalog.create_product(session, payload.model_dump())
    await session.commit()
    return ProductRead.model_validate(product)


@rotas_produtos.get("/products/{product_id}", response_model=ProductRead)
async def get_product(product_id: UUID, session: SessionDep) -> ProductRead:
    product = await catalog.get_product(session, product_id)
    if product is None:
        raise not_found("Produto não encontrado.")
    return ProductRead.model_validate(product)


@rotas_produtos.patch("/products/{product_id}", response_model=ProductRead)
async def update_product(
    product_id: UUID, payload: ProductUpdate, session: SessionDep
) -> ProductRead:
    product = await catalog.get_product(session, product_id)
    if product is None:
        raise not_found("Produto não encontrado.")
    await catalog.update_item(
        session, product, payload.model_dump(exclude_unset=True)
    )
    await session.commit()
    return ProductRead.model_validate(product)


@rotas_produtos.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(product_id: UUID, session: SessionDep) -> Response:
    product = await catalog.get_product(session, product_id)
    if product is None:
        raise not_found("Produto não encontrado.")
    await catalog.delete_item(session, product)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Grupos de complementos — a biblioteca
# ---------------------------------------------------------------------------
# Um grupo ("Sabores") é uma lista com nome, e vários produtos a usam. Quantas
# escolhas cada produto pede fica no vínculo, logo abaixo.


@rotas_produtos.get("/groups", response_model=list[GroupRead])
async def list_groups(session: SessionDep) -> list[GroupRead]:
    groups = await catalog.list_groups(session)
    return [GroupRead.model_validate(g) for g in groups]


@rotas_produtos.post("/groups", response_model=GroupRead, status_code=status.HTTP_201_CREATED)
async def create_group(payload: GroupCreate, session: SessionDep) -> GroupRead:
    group = await catalog.create_group(session, payload.model_dump())
    await session.commit()
    return GroupRead.model_validate(group)


@rotas_produtos.patch("/groups/{group_id}", response_model=GroupRead)
async def update_group(
    group_id: UUID, payload: GroupUpdate, session: SessionDep
) -> GroupRead:
    group = await catalog.get_group(session, group_id)
    if group is None:
        raise not_found("Grupo não encontrado.")
    await catalog.update_item(session, group, payload.model_dump(exclude_unset=True))
    await session.commit()
    return GroupRead.model_validate(group)


@rotas_produtos.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(group_id: UUID, session: SessionDep) -> Response:
    """Apaga a lista inteira — e com ela os itens e todos os vínculos.

    Para tirar o grupo de UM produto sem apagar a lista, use
    `DELETE /api/product-groups/{id}`.
    """
    group = await catalog.get_group(session, group_id)
    if group is None:
        raise not_found("Grupo não encontrado.")
    await catalog.delete_item(session, group)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Vínculo produto <-> grupo (o "importar grupo" do painel)
# ---------------------------------------------------------------------------


@rotas_produtos.post(
    "/products/{product_id}/groups",
    response_model=ProductGroupRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_group_to_product(
    product_id: UUID, payload: ProductGroupCreate, session: SessionDep
) -> ProductGroupRead:
    """Faz o produto usar um grupo: um que já existe, ou um criado na hora."""
    product = await catalog.get_product(session, product_id)
    if product is None:
        raise not_found("Produto não encontrado.")

    dados = payload.model_dump()
    group_id = dados.pop("group_id")
    nome = dados.pop("name")

    if group_id is None:
        group = await catalog.create_group(session, {"name": nome, "sort_order": 0})
        group_id = group.id
    elif await catalog.get_group(session, group_id) is None:
        raise not_found("Grupo não encontrado.")

    link = await catalog.link_group(
        session, product_id=product_id, group_id=group_id, data=dados
    )
    await session.commit()
    return ProductGroupRead.model_validate(link)


@rotas_produtos.patch("/product-groups/{link_id}", response_model=ProductGroupRead)
async def update_product_group(
    link_id: UUID, payload: ProductGroupUpdate, session: SessionDep
) -> ProductGroupRead:
    """Muda quantas escolhas ESTE produto pede, e/ou o nome da lista."""
    link = await catalog.get_product_group(session, link_id)
    if link is None:
        raise not_found("Grupo não encontrado neste produto.")

    dados = payload.model_dump(exclude_unset=True)
    nome = dados.pop("name", None)
    if nome is not None:
        # O nome é da lista, não do vínculo — e renomear vale para todo produto
        # que usa a lista, porque é a mesma lista.
        await catalog.update_item(session, link.group, {"name": nome})
    if dados:
        await catalog.update_item(session, link, dados)
    await session.commit()
    return ProductGroupRead.model_validate(link)


@rotas_produtos.delete("/product-groups/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_group_from_product(link_id: UUID, session: SessionDep) -> Response:
    """Tira o grupo deste produto. A lista continua existindo para os outros."""
    link = await catalog.get_product_group(session, link_id)
    if link is None:
        raise not_found("Grupo não encontrado neste produto.")
    await catalog.delete_item(session, link)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Complementos
# ---------------------------------------------------------------------------


@rotas_produtos.post(
    "/groups/{group_id}/complements",
    response_model=ComplementRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_complement(
    group_id: UUID, payload: ComplementCreate, session: SessionDep
) -> ComplementRead:
    group = await catalog.get_group(session, group_id)
    if group is None:
        raise not_found("Grupo não encontrado.")
    complement = await catalog.create_complement(
        session, group_id=group_id, data=payload.model_dump()
    )
    await session.commit()
    return ComplementRead.model_validate(complement)


@rotas_produtos.patch("/complements/{complement_id}", response_model=ComplementRead)
async def update_complement(
    complement_id: UUID, payload: ComplementUpdate, session: SessionDep
) -> ComplementRead:
    complement = await catalog.get_complement(session, complement_id)
    if complement is None:
        raise not_found("Complemento não encontrado.")
    await catalog.update_item(
        session, complement, payload.model_dump(exclude_unset=True)
    )
    await session.commit()
    return ComplementRead.model_validate(complement)


@rotas_produtos.delete("/complements/{complement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_complement(complement_id: UUID, session: SessionDep) -> Response:
    complement = await catalog.get_complement(session, complement_id)
    if complement is None:
        raise not_found("Complemento não encontrado.")
    await catalog.delete_item(session, complement)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Rotas de pedidos
# ---------------------------------------------------------------------------

rotas_pedidos = APIRouter(prefix="/api", tags=["pedidos"])


@rotas_pedidos.get("/orders", response_model=list[OrderRead])
async def list_orders(
    session: SessionDep,
    status: OrderStatus | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[OrderRead]:
    """Lista para o Kanban, já com itens, complementos e pagamentos."""
    orders = await orders_service.list_orders(
        session, status=status, limit=limit, offset=offset
    )
    return [OrderRead.model_validate(order) for order in orders]


@rotas_pedidos.get("/orders/{order_id}", response_model=OrderRead)
async def get_order(order_id: UUID, session: SessionDep) -> OrderRead:
    order = await orders_service.get_order(session, order_id)
    if order is None:
        raise not_found("Pedido não encontrado.")
    return OrderRead.model_validate(order)


@rotas_pedidos.get("/orders/{order_id}/summary", response_model=OrderSummary)
async def get_order_summary(order_id: UUID, session: SessionDep) -> OrderSummary:
    """Mesmo resumo que o agente usa para falar com o cliente."""
    summary = await orders_service.get_order_summary(session, order_id)
    if summary is None:
        raise not_found("Pedido não encontrado.")
    return summary


@rotas_pedidos.patch("/orders/{order_id}/status", response_model=OrderRead)
async def update_status(
    order_id: UUID, payload: OrderStatusUpdate, session: SessionDep
) -> OrderRead:
    """Move o pedido no Kanban validando a transição (409 se for salto inválido)."""
    try:
        order = await orders_service.update_order_status(
            session, order_id, payload.status
        )
    except orders_service.OrderNotFoundError as exc:
        raise not_found(str(exc)) from exc
    except orders_service.InvalidStatusTransition as exc:
        raise conflict(str(exc)) from exc
    await session.commit()
    return OrderRead.model_validate(order)


# ---------------------------------------------------------------------------
# Rotas de métricas
# ---------------------------------------------------------------------------

rotas_metricas = APIRouter(prefix="/api/metrics", tags=["métricas"])


@rotas_metricas.get("/summary", response_model=MetricsSummary)
async def summary(
    session: SessionDep, range: MetricsRange = MetricsRange.HOJE
) -> MetricsSummary:
    """Cartões do topo do dashboard, comparados com o período anterior."""
    return await metrics_service.get_summary(session, range_=range)


@rotas_metricas.get("/daily-sales", response_model=list[DailySales])
async def daily_sales(
    session: SessionDep, days: int = Query(default=7, ge=1, le=90)
) -> list[DailySales]:
    return await metrics_service.get_daily_sales(session, days=days)


@rotas_metricas.get("/product-sales", response_model=list[ProductSales])
async def product_sales(
    session: SessionDep,
    limit: int = Query(default=10, ge=1, le=50),
    range: MetricsRange = MetricsRange.SEMANA,
) -> list[ProductSales]:
    """Respeita o mesmo filtro de período do resto do dashboard."""
    return await metrics_service.get_product_sales(session, limit=limit, range_=range)


@rotas_metricas.get("/hourly-sales", response_model=list[HourlySales])
async def hourly_sales(
    session: SessionDep, range: MetricsRange = MetricsRange.SEMANA
) -> list[HourlySales]:
    return await metrics_service.get_hourly_sales(session, range_=range)


# ---------------------------------------------------------------------------
# Rotas de conversas
# ---------------------------------------------------------------------------

rotas_conversas = APIRouter(prefix="/api/conversations", tags=["conversas"])


@rotas_conversas.get("", response_model=list[ConversationRead])
async def list_conversations(
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[ConversationRead]:
    return await conversations_service.list_conversations(
        session, limit=limit, offset=offset
    )


@rotas_conversas.get("/{conversation_id}/messages", response_model=list[ConversationMessageRead])
async def list_messages(
    conversation_id: UUID,
    session: SessionDep,
    limit: int = Query(default=200, ge=1, le=500),
) -> list[ConversationMessageRead]:
    conversation = await conversations_service.get_conversation(session, conversation_id)
    if conversation is None:
        raise not_found("Conversa não encontrada.")
    return await conversations_service.list_messages(
        session, conversation_id, limit=limit
    )


@rotas_conversas.post("/{conversation_id}/handoff", response_model=HandoffResult)
async def toggle_handoff(
    conversation_id: UUID, payload: HandoffUpdate, session: SessionDep
) -> HandoffResult:
    """Com `handoff=true` o agente para de responder este telefone."""
    conversation = await conversations_service.get_conversation(session, conversation_id)
    if conversation is None:
        raise not_found("Conversa não encontrada.")
    await conversations_service.set_handoff(
        session, conversation, handoff=payload.handoff
    )
    await session.commit()
    return HandoffResult(
        id=conversation.id, handoff=conversation.handoff, state=conversation.state
    )


# ---------------------------------------------------------------------------
# Rotas do simulador (só com FAKE_MODE)
# ---------------------------------------------------------------------------

rotas_simulador = APIRouter(
    prefix="/api/simulator",
    tags=["simulador"],
    dependencies=[Depends(require_fake_mode)],
)

CHANNEL = "simulador"


class SimulatorMessage(BaseModel):
    phone: str = Field(min_length=3, max_length=32)
    text: str = Field(min_length=1, max_length=2000)


class SimulatorReply(BaseModel):
    replies: list[str]
    state: str


class SimulatorReset(BaseModel):
    phone: str = Field(min_length=3, max_length=32)


@rotas_simulador.post("/message", response_model=SimulatorReply)
async def send_message(payload: SimulatorMessage, db: SessionDep) -> SimulatorReply:
    """Manda uma mensagem como se fosse o cliente e devolve o que o bot diria."""
    message = InboundMessage(phone=payload.phone, text=payload.text)
    replies = await handle_inbound(db, message, channel_name=CHANNEL)
    conversation = await load_or_create(db, payload.phone, CHANNEL)
    await db.commit()

    return SimulatorReply(replies=replies, state=conversation.state.value)


@rotas_simulador.post("/reset", response_model=SimulatorReply)
async def reset(payload: SimulatorReset, db: SessionDep) -> SimulatorReply:
    """Volta a conversa para o início e apaga o histórico de mensagens."""
    conversation = await reset_session(db, payload.phone, CHANNEL)
    await db.commit()
    return SimulatorReply(replies=[], state=conversation.state.value)


@rotas_simulador.post("/payments/{order_id}/approve", response_model=OrderSummary)
async def approve_fake_payment(order_id: UUID, session: SessionDep) -> OrderSummary:
    """Aprova o Pix falso do pedido e roda a mesma rotina do webhook real.

    É o que substitui "abrir o app do banco e pagar o Pix" no teste local:
    dispara exatamente o mesmo caminho, agente notificado inclusive.
    """
    provider = get_payment_provider()
    if not isinstance(provider, FakePaymentProvider):
        raise bad_request("Provedor de pagamento real não pode ser aprovado à mão.")

    payment = await payments_service.get_pending_payment(session, order_id)
    if payment is None or not payment.provider_payment_id:
        raise not_found("Nenhuma cobrança Pix pendente para este pedido.")

    provider.approve(payment.provider_payment_id)
    result = await provider.get_payment(payment.provider_payment_id)
    order, approved_now = await payments_service.apply_payment_result(
        session, result, provider_name=provider.name
    )
    await session.commit()
    if order is None:
        raise not_found("Pedido não encontrado.")
    if approved_now:
        await avisar_agente_do_pagamento(session, order.id)

    summary = await orders_service.get_order_summary(session, order.id)
    if summary is None:  # pragma: no cover - o pedido acabou de ser lido
        raise not_found("Pedido não encontrado.")
    return summary


# ---------------------------------------------------------------------------
# Webhooks: WhatsApp e Mercado Pago
# ---------------------------------------------------------------------------

logger = get_logger(__name__)

rotas_webhooks = APIRouter(prefix="/webhooks", tags=["webhooks"])

SOURCE = "mercadopago"


async def avisar_agente_do_pagamento(session: SessionDep, order_id: Any) -> None:
    """Avisa o agente que o Pix caiu — sem deixar o webhook morrer por isso.

    Mora aqui, e não em `services/payments`, porque avisar o cliente é
    orquestração: o serviço registra o pagamento, a rota decide o que fazer
    depois. Quando estava lá dentro, o serviço precisava importar o agente, que
    importa os serviços de volta — um ciclo remendado com import tardio.
    """
    try:
        await notify_payment_approved(session, order_id)
        # ÚNICA exceção à regra "quem comita é a rota": isto roda DEPOIS do
        # commit da rota, já fora do fluxo da resposta, e escreve o novo estado
        # da conversa. Sem o commit aqui a conversa fica presa em
        # "aguardando_pagamento" e o cliente nunca recebe a confirmação.
        await session.commit()
    except Exception:  # noqa: BLE001 - notificação nunca derruba o webhook
        logger.exception("Falha ao notificar o cliente do pedido %s", order_id)
        await session.rollback()


# ---------------------------------------------------------------------------
# WhatsApp (Evolution API)
# ---------------------------------------------------------------------------

def _evolution_token_ok(token: str | None) -> bool:
    """Evolution API não assina o corpo: a validação é um token na query string.

    O token vem cadastrado na própria URL que a Evolution chama
    (WEBHOOK_GLOBAL_URL no docker-compose.yml).
    """
    settings = get_settings()
    expected = settings.evolution_webhook_token

    if not expected:
        if settings.fake_mode:
            logger.warning(
                "EVOLUTION_WEBHOOK_TOKEN ausente: token NÃO validado (fake_mode)."
            )
            return True
        logger.error("EVOLUTION_WEBHOOK_TOKEN ausente em produção; rejeitando webhook")
        return False

    return bool(token) and hmac.compare_digest(token, expected)


@rotas_webhooks.post("/evolution", status_code=status.HTTP_200_OK)
async def evolution_webhook(
    request: Request,
    token: str | None = Query(default=None),
) -> dict[str, str]:
    """Recebe eventos da Evolution API e roda o agente para cada mensagem."""
    if not _evolution_token_ok(token):
        logger.warning("token do webhook da Evolution API inválido; evento descartado")
        return {"status": "ignored"}

    try:
        payload = await request.json()
    except Exception:
        logger.warning("payload do webhook da Evolution API não é JSON válido")
        return {"status": "ignored"}

    try:
        messages = EvolutionAdapter(get_settings()).parse_webhook(payload)
    except Exception:
        logger.exception("payload do webhook da Evolution API em formato inesperado")
        return {"status": "ignored"}

    sessionmaker = get_sessionmaker()

    async def process(message: Any) -> None:
        """Um turno, com sessão de banco própria (a da request já morreu)."""
        async with sessionmaker() as db:
            await handle_inbound(db, message, channel_name="whatsapp")
            await db.commit()

    for message in messages:
        # Trava de contatos: com ALLOWED_PHONES preenchida, mensagem de
        # qualquer outro número é descartada aqui, antes de virar conversa no
        # banco. Não responde, não registra, não existe.
        if not phone_allowed(message.phone):
            logger.info(
                "mensagem de %s ignorada: fora de ALLOWED_PHONES", message.phone
            )
            continue
        try:
            if message.from_me:
                # Eco do bot ou resposta manual do lojista: só histórico, nunca
                # aciona IA/máquina de estados — e sem esperar por agrupamento.
                async with sessionmaker() as db:
                    await handle_outbound_echo(db, message, channel_name="whatsapp")
                    await db.commit()
            else:
                # Mensagem de cliente espera os balões seguintes (inbox.py) e
                # roda fora desta request: webhook que demora é reentregue.
                await inbox.submit(message, process)
        except Exception:
            # Uma mensagem com problema não pode impedir as outras nem virar 500.
            logger.exception("falha ao processar mensagem de %s", message.phone)

    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Pagamento (Mercado Pago)
# ---------------------------------------------------------------------------


def _extract_payment_id(body: dict[str, Any], query: dict[str, str]) -> str | None:
    """O MP manda o id ora no corpo, ora na query (`data.id`)."""
    data = body.get("data") or {}
    candidate = (
        data.get("id")
        or query.get("data.id")
        or query.get("id")
        or body.get("resource")
    )
    if candidate is None:
        return None
    # Notificações antigas mandam a URL inteira em "resource".
    return str(candidate).rstrip("/").split("/")[-1]


def _event_topic(body: dict[str, Any], query: dict[str, str]) -> str:
    return str(
        body.get("type") or body.get("topic") or query.get("type") or query.get("topic") or ""
    ).lower()


def _event_id(body: dict[str, Any], payment_id: str | None) -> str:
    """Id do evento: o do MP quando existe, senão tópico+ação+pagamento."""
    if body.get("id") is not None:
        return str(body["id"])
    action = body.get("action") or body.get("type") or "payment"
    return f"{action}:{payment_id}"


def _valid_signature(request: Request, payment_id: str | None) -> bool:
    """Valida `x-signature` no formato ts=...,v1=... (HMAC-SHA256).

    Sem `MP_WEBHOOK_SECRET` configurado a validação é pulada — o segredo é
    opcional na conta do MP e travar aqui deixaria o MVP sem webhook.
    """
    secret = get_settings().mp_webhook_secret
    if not secret:
        return True

    signature = request.headers.get("x-signature", "")
    parts = dict(
        piece.strip().split("=", 1) for piece in signature.split(",") if "=" in piece
    )
    ts, received = parts.get("ts"), parts.get("v1")
    if not ts or not received:
        return False

    request_id = request.headers.get("x-request-id", "")
    manifest = f"id:{payment_id};request-id:{request_id};ts:{ts};"
    expected = hmac.new(
        secret.encode(), manifest.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, received)


@rotas_webhooks.post("/mercadopago")
async def mercadopago_webhook(request: Request, session: SessionDep) -> dict[str, str]:
    raw = await request.body()
    try:
        body: dict[str, Any] = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        body = {}
    query = dict(request.query_params)

    topic = _event_topic(body, query)
    payment_id = _extract_payment_id(body, query)

    if not _valid_signature(request, payment_id):
        logger.warning("Assinatura inválida no webhook do Mercado Pago.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Assinatura inválida."
        )

    # Só pagamento interessa; o resto (merchant_order, plan...) é descartado com 200
    # para o MP não ficar reenviando.
    if topic and "payment" not in topic:
        return {"status": "ignorado"}
    if not payment_id:
        return {"status": "sem_id"}

    event = await payments_service.claim_webhook_event(
        session, source=SOURCE, external_id=_event_id(body, payment_id), payload=body
    )
    if event is None:
        logger.info("Evento repetido do Mercado Pago ignorado (%s).", payment_id)
        return {"status": "duplicado"}
    await session.commit()

    try:
        # get_payment_provider() também pode falhar (ex.: MP_ACCESS_TOKEN
        # ausente); precisa estar dentro do try para liberar o "claim" acima.
        provider = get_payment_provider()
        # Fonte da verdade é a API, nunca o corpo do webhook.
        result = await provider.get_payment(payment_id)
        order, approved_now = await payments_service.apply_payment_result(
            session, result, provider_name=provider.name
        )
    except Exception as exc:  # noqa: BLE001
        # Solta o "claim" para o MP poder reenviar e a gente reprocessar.
        await session.rollback()
        await session.delete(event)
        await session.commit()
        logger.exception("Falha ao processar pagamento %s", payment_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Não foi possível confirmar o pagamento no provedor.",
        ) from exc

    await payments_service.mark_event_processed(session, event)
    await session.commit()

    if order is not None and approved_now:
        await avisar_agente_do_pagamento(session, order.id)

    return {"status": "ok", "pedido": order.code if order else ""}


@rotas_webhooks.get("/mercadopago")
async def mercadopago_probe() -> Response:
    """O MP faz um GET de teste ao cadastrar a URL."""
    return Response(status_code=status.HTTP_200_OK)
