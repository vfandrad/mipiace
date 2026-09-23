"""Testes da máquina de estados.

Cobrem duas coisas diferentes: a tabela de transições (o contrato declarativo)
e o comportamento dos handlers — inclusive os caminhos ruins, que são os que
realmente importam num bot de atendimento: não entender, item em falta,
ambiguidade e escalada para humano.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.agent.llm import ExtractedAddress, NluResult
from app.agent.checkout import AgentDeps
from app.agent.machine import run
from app.agent.session import ConversationSession
from app.agent.states import (
    TRANSITIONS,
    InvalidTransition,
    assert_transition,
    can_transition,
)
from app.core.config import get_settings
from app.domain.catalog import (
    CatalogComplement,
    CatalogGroup,
    CatalogProduct,
    CatalogSnapshot,
)
from app.domain.enums import ConversationState as S
from app.domain.enums import Intent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def build_catalog() -> CatalogSnapshot:
    pote_id = uuid4()
    sabores = uuid4()
    cobertura = uuid4()
    pote = CatalogProduct(
        id=pote_id,
        name="Pote 500ml",
        base_price=Decimal("32.00"),
        groups=[
            CatalogGroup(
                id=sabores,
                product_id=pote_id,
                name="Sabores",
                min_choices=2,
                max_choices=2,
                is_required=True,
                complements=[
                    CatalogComplement(id=uuid4(), group_id=sabores, name="Pistache"),
                    CatalogComplement(id=uuid4(), group_id=sabores, name="Morango"),
                    CatalogComplement(
                        id=uuid4(), group_id=sabores, name="Maracujá", is_available=False
                    ),
                ],
            ),
            CatalogGroup(
                id=cobertura,
                product_id=pote_id,
                name="Cobertura",
                min_choices=0,
                max_choices=1,
                is_required=False,
                complements=[
                    CatalogComplement(
                        id=uuid4(),
                        group_id=cobertura,
                        name="Calda de Chocolate",
                        extra_price=Decimal("3.00"),
                    )
                ],
            ),
        ],
    )
    casquinha = CatalogProduct(id=uuid4(), name="Casquinha", base_price=Decimal("9.00"))
    pote240 = CatalogProduct(id=uuid4(), name="Pote 240ml", base_price=Decimal("18.00"))
    milkshake = CatalogProduct(
        id=uuid4(), name="Milkshake", base_price=Decimal("22.00"), is_available=False
    )
    return CatalogSnapshot(products=[pote, pote240, casquinha, milkshake])


class _FakeOrder:
    def __init__(self) -> None:
        self.id = uuid4()
        self.code = "MP-0001"
        self.subtotal = Decimal("32.00")
        self.delivery_fee = Decimal("5.00")
        self.total = Decimal("37.00")


class _FakePix:
    qr_code = "00020126PIX-COPIA-E-COLA"
    provider_payment_id = "fake-1"


def build_deps(catalog: CatalogSnapshot | None = None) -> AgentDeps:
    async def _create_order(db, **kwargs):
        return _FakeOrder()

    async def _create_pix(db, order_id):
        return _FakePix()

    async def _summary(db, order_id):
        return None

    async def _saved_address():
        return None

    return AgentDeps(
        db=None,
        catalog=catalog or build_catalog(),
        settings=get_settings(),
        create_order=_create_order,
        create_pix=_create_pix,
        order_summary=_summary,
        saved_address=_saved_address,
    )


def build_session(state: S = S.SAUDACAO) -> ConversationSession:
    return ConversationSession(
        id=uuid4(), phone="5511999990000", channel="simulador", state=state
    )


def nlu(intent: Intent, **kwargs) -> NluResult:
    return NluResult(intent=intent, confidence=0.9, **kwargs)


# ---------------------------------------------------------------------------
# Tabela de transições
# ---------------------------------------------------------------------------

def test_transicoes_validas_declaradas() -> None:
    assert can_transition(S.SAUDACAO, S.ESCOLHENDO_PRODUTO)
    assert can_transition(S.ESCOLHENDO_PRODUTO, S.PERSONALIZANDO_ITEM)
    assert can_transition(S.PERSONALIZANDO_ITEM, S.REVISANDO_CARRINHO)
    assert can_transition(S.REVISANDO_CARRINHO, S.COLETANDO_ENDERECO)
    assert can_transition(S.COLETANDO_ENDERECO, S.CONFIRMANDO_PEDIDO)
    assert can_transition(S.CONFIRMANDO_PEDIDO, S.AGUARDANDO_PAGAMENTO)
    assert can_transition(S.AGUARDANDO_PAGAMENTO, S.CONCLUIDO)


def test_atalhos_proibidos() -> None:
    # Não se gera Pix sem passar pela confirmação.
    assert not can_transition(S.SAUDACAO, S.AGUARDANDO_PAGAMENTO)
    # Nem se pula do carrinho direto para o pagamento.
    assert not can_transition(S.REVISANDO_CARRINHO, S.AGUARDANDO_PAGAMENTO)
    # Nem se volta de um pedido concluído para o meio do fluxo.
    assert not can_transition(S.CONCLUIDO, S.CONFIRMANDO_PEDIDO)


def test_assert_transition_levanta() -> None:
    with pytest.raises(InvalidTransition):
        assert_transition(S.SAUDACAO, S.CONFIRMANDO_PEDIDO)
    # e não levanta no caminho válido
    assert_transition(S.SAUDACAO, S.ESCOLHENDO_PRODUTO)


def test_todo_estado_tem_saida_declarada() -> None:
    for state in S:
        assert state in TRANSITIONS, f"{state} ficou fora da tabela"


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_saudacao_apresenta_cardapio() -> None:
    deps, session = build_deps(), build_session()
    result = await run(deps, session, nlu(Intent.SAUDAR), "oi")
    assert session.state is S.ESCOLHENDO_PRODUTO
    assert any("cardápio" in reply.lower() for reply in result.replies)


@pytest.mark.asyncio
async def test_produto_com_grupo_obrigatorio_vai_personalizar() -> None:
    deps, session = build_deps(), build_session(S.ESCOLHENDO_PRODUTO)
    result = await run(
        deps, session, nlu(Intent.ESCOLHER_PRODUTO, product_query="Pote 500ml"), "pote 500ml"
    )
    assert session.state is S.PERSONALIZANDO_ITEM
    assert "Sabores" in result.replies[0]
    assert session.cart.is_empty  # só entra no carrinho depois de personalizado


@pytest.mark.asyncio
async def test_produto_sem_grupo_vai_direto_para_o_carrinho() -> None:
    deps, session = build_deps(), build_session(S.ESCOLHENDO_PRODUTO)
    await run(
        deps, session, nlu(Intent.ESCOLHER_PRODUTO, product_query="Casquinha"), "casquinha"
    )
    assert session.state is S.REVISANDO_CARRINHO
    assert len(session.cart.items) == 1
    assert session.cart.subtotal == Decimal("9.00")


@pytest.mark.asyncio
async def test_produto_ambiguo_pergunta_qual() -> None:
    deps, session = build_deps(), build_session(S.ESCOLHENDO_PRODUTO)
    result = await run(
        deps, session, nlu(Intent.ESCOLHER_PRODUTO, product_query="pote"), "quero um pote"
    )
    assert session.state is S.ESCOLHENDO_PRODUTO
    assert "Pote 500ml" in result.replies[0] and "Pote 240ml" in result.replies[0]
    # E a resposta numérica seguinte resolve o desempate.
    result = await run(deps, session, nlu(Intent.ESCOLHER_PRODUTO, product_query="2"), "2")
    assert session.state in {S.PERSONALIZANDO_ITEM, S.REVISANDO_CARRINHO}


@pytest.mark.asyncio
async def test_produto_indisponivel_nao_entra_no_carrinho() -> None:
    deps, session = build_deps(), build_session(S.ESCOLHENDO_PRODUTO)
    result = await run(
        deps, session, nlu(Intent.ESCOLHER_PRODUTO, product_query="milkshake"), "milkshake"
    )
    assert session.cart.is_empty
    assert "acabou" in result.replies[0]


@pytest.mark.asyncio
async def test_grupo_obrigatorio_conta_min_choices() -> None:
    deps, session = build_deps(), build_session(S.ESCOLHENDO_PRODUTO)
    await run(deps, session, nlu(Intent.ESCOLHER_PRODUTO, product_query="Pote 500ml"), "pote")

    # Um sabor só: ainda falta um, então não sai do estado.
    await run(
        deps,
        session,
        nlu(Intent.ESCOLHER_COMPLEMENTOS, complement_queries=["pistache"]),
        "pistache",
    )
    assert session.state is S.PERSONALIZANDO_ITEM
    assert session.cart.is_empty

    await run(
        deps,
        session,
        nlu(Intent.ESCOLHER_COMPLEMENTOS, complement_queries=["morango"]),
        "morango",
    )
    assert session.state is S.REVISANDO_CARRINHO
    assert len(session.cart.items[0].complements) == 2


@pytest.mark.asyncio
async def test_sabor_indisponivel_e_recusado() -> None:
    deps, session = build_deps(), build_session(S.ESCOLHENDO_PRODUTO)
    await run(deps, session, nlu(Intent.ESCOLHER_PRODUTO, product_query="Pote 500ml"), "pote")
    result = await run(
        deps,
        session,
        nlu(Intent.ESCOLHER_COMPLEMENTOS, complement_queries=["maracujá"]),
        "maracujá",
    )
    assert session.state is S.PERSONALIZANDO_ITEM
    assert "falta" in result.replies[0].lower()


@pytest.mark.asyncio
async def test_fail_count_escala_para_humano() -> None:
    deps, session = build_deps(), build_session(S.ESCOLHENDO_PRODUTO)
    limite = deps.settings.max_nlu_failures

    for _ in range(limite - 1):
        await run(deps, session, nlu(Intent.DESCONHECIDO), "blablabla")
        assert session.state is S.ESCOLHENDO_PRODUTO

    result = await run(deps, session, nlu(Intent.DESCONHECIDO), "blablabla")
    assert session.state is S.ATENDIMENTO_HUMANO
    assert session.handoff is True
    assert session.fail_count >= limite
    assert result.replies


@pytest.mark.asyncio
async def test_handoff_silencia_o_bot() -> None:
    deps, session = build_deps(), build_session(S.ATENDIMENTO_HUMANO)
    session.handoff = True
    session.touch_handoff()  # alguém da loja acabou de assumir
    result = await run(deps, session, nlu(Intent.SAUDAR), "oi")
    assert result.replies == []


@pytest.mark.asyncio
async def test_pedido_de_humano_para_o_fluxo() -> None:
    deps, session = build_deps(), build_session(S.REVISANDO_CARRINHO)
    await run(deps, session, nlu(Intent.FALAR_COM_HUMANO), "quero falar com atendente")
    assert session.state is S.ATENDIMENTO_HUMANO
    assert session.handoff is True


@pytest.mark.asyncio
async def test_cancelar_limpa_o_carrinho() -> None:
    deps, session = build_deps(), build_session(S.ESCOLHENDO_PRODUTO)
    await run(deps, session, nlu(Intent.ESCOLHER_PRODUTO, product_query="Casquinha"), "casquinha")
    assert not session.cart.is_empty

    await run(deps, session, nlu(Intent.CANCELAR), "cancelar")
    assert session.state is S.CANCELADO
    assert session.cart.is_empty


@pytest.mark.asyncio
async def test_endereco_incompleto_pede_so_o_que_falta() -> None:
    deps, session = build_deps(), build_session(S.ESCOLHENDO_PRODUTO)
    await run(deps, session, nlu(Intent.ESCOLHER_PRODUTO, product_query="Casquinha"), "casquinha")
    await run(deps, session, nlu(Intent.FINALIZAR_PEDIDO), "fechar")
    # Fechar o carrinho pergunta entrega ou retirada e espera a resposta.
    assert session.state is S.REVISANDO_CARRINHO
    await run(deps, session, nlu(Intent.ESCOLHER_ENTREGA), "entrega")
    assert session.state is S.COLETANDO_ENDERECO

    result = await run(
        deps,
        session,
        nlu(
            Intent.INFORMAR_ENDERECO,
            address=ExtractedAddress(rua="Rua das Flores", numero="123"),
        ),
        "rua das flores 123",
    )
    assert session.state is S.COLETANDO_ENDERECO
    assert "bairro" in result.replies[0].lower()


@pytest.mark.asyncio
async def test_confirmacao_gera_pix_e_pedido() -> None:
    deps, session = build_deps(), build_session(S.CONFIRMANDO_PEDIDO)
    await run(deps, session, nlu(Intent.ESCOLHER_PRODUTO, product_query="Casquinha"), "casquinha")
    session.state = S.CONFIRMANDO_PEDIDO
    session.slots["address"] = {"rua": "Rua A", "numero": "1", "bairro": "Centro"}

    result = await run(deps, session, nlu(Intent.CONFIRMAR), "sim")
    assert session.state is S.AGUARDANDO_PAGAMENTO
    assert isinstance(session.active_order_id, UUID)
    assert session.cart.is_empty  # carrinho virou pedido
    assert "PIX-COPIA-E-COLA" in result.replies[0]


@pytest.mark.asyncio
async def test_aguardando_pagamento_e_passivo() -> None:
    deps, session = build_deps(), build_session(S.AGUARDANDO_PAGAMENTO)
    result = await run(deps, session, nlu(Intent.ESCOLHER_PRODUTO, product_query="Casquinha"), "casquinha")
    assert session.state is S.AGUARDANDO_PAGAMENTO
    assert session.cart.is_empty  # não reabre o fluxo de compra
    assert result.replies


@pytest.mark.asyncio
async def test_cardapio_a_qualquer_momento() -> None:
    deps, session = build_deps(), build_session(S.REVISANDO_CARRINHO)
    result = await run(deps, session, nlu(Intent.VER_CARDAPIO), "cardápio")
    assert "cardápio" in result.replies[0].lower()
    assert session.state is S.REVISANDO_CARRINHO


@pytest.mark.asyncio
async def test_estado_terminal_reinicia_a_conversa() -> None:
    deps, session = build_deps(), build_session(S.CANCELADO)
    result = await run(deps, session, nlu(Intent.SAUDAR), "oi de novo")
    assert session.state is S.ESCOLHENDO_PRODUTO
    assert result.replies


@pytest.mark.asyncio
async def test_falha_repetida_na_personalizacao_tambem_escala() -> None:
    """Sem isto o cliente ficaria preso para sempre no grupo de sabores."""
    deps, session = build_deps(), build_session(S.ESCOLHENDO_PRODUTO)
    await run(deps, session, nlu(Intent.ESCOLHER_PRODUTO, product_query="Pote 500ml"), "pote")
    assert session.state is S.PERSONALIZANDO_ITEM

    for _ in range(deps.settings.max_nlu_failures):
        await run(
            deps,
            session,
            nlu(Intent.ESCOLHER_COMPLEMENTOS, complement_queries=["pizza"]),
            "pizza",
        )

    assert session.state is S.ATENDIMENTO_HUMANO
    assert session.handoff is True


@pytest.mark.asyncio
async def test_escolha_parcial_mostra_progresso_e_nao_diz_que_nao_entendeu() -> None:
    """Regressão: sabor aceito no meio do grupo respondia "não entendi".

    O complemento era gravado corretamente, mas a resposta ao cliente era o
    texto de incompreensão — o bot dizia não ter entendido algo que entendeu.
    Os testes antigos só olhavam o estado, então o bug passava.
    """
    deps, session = build_deps(), build_session(S.ESCOLHENDO_PRODUTO)
    await run(deps, session, nlu(Intent.ESCOLHER_PRODUTO, product_query="Pote 500ml"), "pote")

    result = await run(
        deps,
        session,
        nlu(Intent.ESCOLHER_COMPLEMENTOS, complement_queries=["pistache"]),
        "pistache",
    )

    resposta = "\n".join(result.replies)
    assert "Já anotei" in resposta, "deveria confirmar o que foi escolhido"
    assert "Pistache" in resposta
    assert "não entendi" not in resposta.lower()
    # E a escolha realmente entrou no item em construção.
    pendente = session.slots["pending_item"]
    assert [c["name"] for c in pendente["complements"]] == ["Pistache"]


# ---------------------------------------------------------------------------
# Entrega x retirada
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fechar_carrinho_pergunta_a_modalidade() -> None:
    """Sem saber se é entrega ou retirada, o agente não pede endereço."""
    deps, session = build_deps(), build_session(S.ESCOLHENDO_PRODUTO)
    await run(deps, session, nlu(Intent.ESCOLHER_PRODUTO, product_query="Casquinha"), "casquinha")
    result = await run(deps, session, nlu(Intent.FINALIZAR_PEDIDO), "fechar")

    assert session.state is S.REVISANDO_CARRINHO
    texto = result.replies[0].lower()
    assert "entrega" in texto and "retirada" in texto


@pytest.mark.asyncio
async def test_retirada_pula_o_endereco() -> None:
    """Quem vai buscar na loja não responde rua, número nem bairro."""
    deps, session = build_deps(), build_session(S.ESCOLHENDO_PRODUTO)
    await run(deps, session, nlu(Intent.ESCOLHER_PRODUTO, product_query="Casquinha"), "casquinha")
    await run(deps, session, nlu(Intent.FINALIZAR_PEDIDO), "fechar")
    result = await run(deps, session, nlu(Intent.ESCOLHER_RETIRADA), "vou retirar")

    assert session.state is S.CONFIRMANDO_PEDIDO
    resumo = result.replies[0]
    assert "Retirada na loja" in resumo
    # Sem taxa e sem linha de endereço no resumo.
    assert "Taxa de entrega" not in resumo
    assert "Entregar em" not in resumo


@pytest.mark.asyncio
async def test_endereco_solto_ja_significa_entrega() -> None:
    """Quem manda a rua está pedindo entrega, mesmo sem dizer a palavra."""
    deps, session = build_deps(), build_session(S.ESCOLHENDO_PRODUTO)
    await run(deps, session, nlu(Intent.ESCOLHER_PRODUTO, product_query="Casquinha"), "casquinha")
    await run(deps, session, nlu(Intent.FINALIZAR_PEDIDO), "fechar")
    await run(
        deps,
        session,
        nlu(Intent.INFORMAR_ENDERECO, address=ExtractedAddress(rua="Rua A", numero="1", bairro="Centro")),
        "Rua A, 1, Centro",
    )
    assert session.state is S.CONFIRMANDO_PEDIDO


@pytest.mark.asyncio
async def test_fechar_no_meio_dos_sabores_diz_o_que_falta() -> None:
    """"Não temos 'quero fechar' em Sabores" é verdade e não ajuda ninguém."""
    deps, session = build_deps(), build_session(S.ESCOLHENDO_PRODUTO)
    await run(deps, session, nlu(Intent.ESCOLHER_PRODUTO, product_query="Pote 500ml"), "pote")

    result = await run(deps, session, nlu(Intent.FINALIZAR_PEDIDO), "quero fechar")

    assert session.state is S.PERSONALIZANDO_ITEM
    assert "falta" in result.replies[0].lower()
    assert "não temos" not in result.replies[0].lower()


@pytest.mark.asyncio
async def test_desambiguacao_de_sabor_preserva_a_lista_oferecida() -> None:
    """Se a lista voltar a ser o grupo inteiro, o "1" do cliente vira outro sabor."""
    grupo_id = uuid4()
    produto_id = uuid4()
    limao = CatalogComplement(id=uuid4(), group_id=grupo_id, name="Limão siciliano")
    torta = CatalogComplement(id=uuid4(), group_id=grupo_id, name="Torta de limão")
    catalogo = CatalogSnapshot(
        products=[
            CatalogProduct(
                id=produto_id,
                name="Pote 500ml",
                base_price=Decimal("32.00"),
                groups=[
                    CatalogGroup(
                        id=grupo_id,
                        product_id=produto_id,
                        name="Sabores",
                        min_choices=2,
                        max_choices=2,
                        is_required=True,
                        complements=[
                            CatalogComplement(id=uuid4(), group_id=grupo_id, name="Morango"),
                            limao,
                            torta,
                        ],
                    )
                ],
            )
        ]
    )
    deps, session = build_deps(catalogo), build_session(S.ESCOLHENDO_PRODUTO)
    await run(deps, session, nlu(Intent.ESCOLHER_PRODUTO, product_query="Pote 500ml"), "pote")

    result = await run(
        deps, session, nlu(Intent.ESCOLHER_COMPLEMENTOS, complement_queries=["limao"]), "limao"
    )

    assert "Qual desses" in result.replies[0]
    assert session.slots["options"] == [str(limao.id), str(torta.id)]
