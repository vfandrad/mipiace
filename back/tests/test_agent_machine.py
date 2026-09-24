"""Testes do executor: o que cada operação faz com o pedido.

Quase todos nasceram de um defeito visto em conversa real — com cliente de
verdade ou com os dez clientes simulados. O padrão dos piores era sempre o
mesmo: **corrigir o pedido criava item novo em vez de mudar o que existia**, e
o cliente pagava por isso.

Aqui o plano da IA é escrito à mão (`plano(...)`), porque o que está sob teste
é o executor, não o modelo.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from app.agent.checkout import AgentDeps
from app.agent.machine import run
from app.agent.plan import Action, Address, AgentPlan, Operation
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

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def build_catalog() -> CatalogSnapshot:
    pote_id, sabores_id = uuid4(), uuid4()
    pote = CatalogProduct(
        id=pote_id,
        name="Pote 500ml",
        description="Pote grande: escolha 2 sabores",
        base_price=Decimal("32.00"),
        groups=[
            CatalogGroup(
                id=sabores_id,
                name="Escolha 2 sabores",
                min_choices=2,
                max_choices=2,
                is_required=True,
                complements=[
                    CatalogComplement(id=uuid4(), group_id=sabores_id, name="Pistache"),
                    CatalogComplement(id=uuid4(), group_id=sabores_id, name="Morango"),
                    CatalogComplement(id=uuid4(), group_id=sabores_id, name="Chocolate"),
                    CatalogComplement(
                        id=uuid4(), group_id=sabores_id, name="Maracujá", is_available=False
                    ),
                ],
            )
        ],
    )
    pote240_id, sabores240_id = uuid4(), uuid4()
    pote240 = CatalogProduct(
        id=pote240_id,
        name="Pote 240ml",
        description="Pote médio: escolha 1 sabor",
        base_price=Decimal("18.00"),
        groups=[
            CatalogGroup(
                id=sabores240_id,
                name="Escolha 1 sabor",
                min_choices=1,
                max_choices=1,
                is_required=True,
                complements=[
                    CatalogComplement(id=uuid4(), group_id=sabores240_id, name="Pistache"),
                    CatalogComplement(id=uuid4(), group_id=sabores240_id, name="Morango"),
                ],
            )
        ],
    )
    casquinha = CatalogProduct(id=uuid4(), name="Casquinha", base_price=Decimal("9.00"))
    milkshake = CatalogProduct(
        id=uuid4(), name="Milkshake", base_price=Decimal("22.00"), is_available=False
    )
    return CatalogSnapshot(products=[pote, pote240, casquinha, milkshake])


class _FakeOrder:
    def __init__(self) -> None:
        self.id = uuid4()
        self.code = "MP-0001"
        self.total = Decimal("37.00")


class _FakePix:
    qr_code = "PIX-COPIA-E-COLA"
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


def build_session(state: S = S.CONVERSANDO) -> ConversationSession:
    return ConversationSession(
        id=uuid4(), phone="5511999990000", channel="simulador", state=state
    )


def plano(*ops: Operation) -> AgentPlan:
    return AgentPlan(operations=list(ops), confidence=0.9)


def op(action: Action, **kwargs) -> Operation:
    return Operation(action=action, **kwargs)


async def montar_pote(deps, session, sabores=("Pistache", "Morango")) -> None:
    """Deixa um Pote 500ml completo no carrinho."""
    await run(
        deps,
        session,
        plano(op(Action.ADD_ITEM, product_name="Pote 500ml", add_flavors=list(sabores))),
        "quero um pote",
    )


# ---------------------------------------------------------------------------
# A tabela de transições — o que sobrou dela é a garantia do dinheiro
# ---------------------------------------------------------------------------

def test_so_se_cobra_depois_da_confirmacao() -> None:
    assert can_transition(S.CONFIRMANDO_PEDIDO, S.AGUARDANDO_PAGAMENTO)
    assert not can_transition(S.CONVERSANDO, S.AGUARDANDO_PAGAMENTO)
    with pytest.raises(InvalidTransition):
        assert_transition(S.CONVERSANDO, S.AGUARDANDO_PAGAMENTO)


def test_todo_estado_tem_saida_declarada() -> None:
    for state in S:
        assert state in TRANSITIONS, f"{state} ficou fora da tabela"


# ---------------------------------------------------------------------------
# Montar o pedido
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_item_sem_sabor_obrigatorio_entra_direto() -> None:
    deps, session = build_deps(), build_session()
    await run(deps, session, plano(op(Action.ADD_ITEM, product_name="Casquinha")), "casquinha")
    assert len(session.cart.items) == 1
    assert session.cart.subtotal == Decimal("9.00")


@pytest.mark.asyncio
async def test_item_com_sabores_fica_em_montagem_ate_completar() -> None:
    deps, session = build_deps(), build_session()

    replies = await run(
        deps, session, plano(op(Action.ADD_ITEM, product_name="Pote 500ml")), "um pote"
    )
    # O item entra no pedido em montagem: é o mesmo item, com o mesmo número,
    # que o cliente vê e que a IA recebe na situação.
    assert len(session.cart.items) == 1
    assert session.cart.items[0].complements == []
    assert "sabores" in replies[-1].lower()

    await run(
        deps,
        session,
        plano(op(Action.UPDATE_ITEM, add_flavors=["Pistache", "Morango"])),
        "pistache e morango",
    )
    assert len(session.cart.items) == 1
    assert [c.name for c in session.cart.items[0].complements] == ["Pistache", "Morango"]


@pytest.mark.asyncio
async def test_sabor_nao_se_repete_no_mesmo_pote() -> None:
    """Regressão: o cliente recebia um pote com pistache duas vezes.

    O modelo repete os sabores já escolhidos junto com o novo. Quando vem
    junto de uma escolha de verdade, a repetição some sem comentário; quando
    é o cliente que pediu duas vezes, ele ouve o porquê.
    """
    deps, session = build_deps(), build_session()
    await run(
        deps,
        session,
        plano(op(Action.ADD_ITEM, product_name="Pote 500ml", add_flavors=["Pistache"])),
        "pote com pistache",
    )

    replies = await run(
        deps,
        session,
        plano(op(Action.UPDATE_ITEM, add_flavors=["Pistache", "Morango"])),
        "morango tambem",
    )

    assert [c.name for c in session.cart.items[0].complements] == ["Pistache", "Morango"]
    assert not any("já está" in reply for reply in replies)


@pytest.mark.asyncio
async def test_pedir_o_mesmo_sabor_de_novo_e_explicado() -> None:
    deps, session = build_deps(), build_session()
    await run(
        deps,
        session,
        plano(op(Action.ADD_ITEM, product_name="Pote 500ml", add_flavors=["Pistache"])),
        "pote com pistache",
    )

    replies = await run(
        deps,
        session,
        plano(op(Action.UPDATE_ITEM, add_flavors=["Pistache"])),
        "mais pistache",
    )

    assert [c.name for c in session.cart.items[0].complements] == ["Pistache"]
    assert any("já está" in reply for reply in replies)


@pytest.mark.asyncio
async def test_sabor_esgotado_nao_entra() -> None:
    deps, session = build_deps(), build_session()
    replies = await run(
        deps,
        session,
        plano(op(Action.ADD_ITEM, product_name="Pote 500ml", add_flavors=["Maracujá"])),
        "pote de maracujá",
    )
    assert session.cart.items[0].complements == []  # o sabor esgotado não entrou
    assert any("acabou" in reply.lower() for reply in replies)


@pytest.mark.asyncio
async def test_produto_esgotado_nao_entra() -> None:
    deps, session = build_deps(), build_session()
    replies = await run(
        deps, session, plano(op(Action.ADD_ITEM, product_name="Milkshake")), "milkshake"
    )
    assert session.cart.is_empty
    assert any("acabou" in reply.lower() for reply in replies)


@pytest.mark.asyncio
async def test_nome_que_nao_existe_no_cardapio_e_recusado() -> None:
    """A IA propõe, o catálogo decide: nome inventado não vira item."""
    deps, session = build_deps(), build_session()
    await run(
        deps, session, plano(op(Action.ADD_ITEM, product_name="Pizza de calabresa")), "pizza"
    )
    assert session.cart.is_empty


# ---------------------------------------------------------------------------
# Editar — o que antes virava item novo
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trocar_sabor_edita_o_mesmo_item() -> None:
    """Regressão cara: "troca X por Y" criava um segundo pote e dobrava a conta."""
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session, ("Pistache", "Morango"))

    await run(
        deps,
        session,
        plano(
            op(
                Action.UPDATE_ITEM,
                item_index=1,
                remove_flavors=["Morango"],
                add_flavors=["Chocolate"],
            )
        ),
        "troca morango por chocolate",
    )

    assert len(session.cart.items) == 1
    assert [c.name for c in session.cart.items[0].complements] == ["Pistache", "Chocolate"]
    assert session.cart.subtotal == Decimal("32.00")


@pytest.mark.asyncio
async def test_remover_item_tira_do_pedido() -> None:
    """Regressão: "remove o item 1" ADICIONAVA um item e inflava o total."""
    deps, session = build_deps(), build_session()
    await run(deps, session, plano(op(Action.ADD_ITEM, product_name="Casquinha")), "casquinha")
    await montar_pote(deps, session)
    assert len(session.cart.items) == 2

    replies = await run(
        deps, session, plano(op(Action.REMOVE_ITEM, item_index=1)), "remove o item 1"
    )

    assert len(session.cart.items) == 1
    assert session.cart.items[0].product_name == "Pote 500ml"
    assert any("Tirei" in reply for reply in replies)


@pytest.mark.asyncio
async def test_remover_sem_dizer_qual_pergunta() -> None:
    deps, session = build_deps(), build_session()
    await run(deps, session, plano(op(Action.ADD_ITEM, product_name="Casquinha")), "casquinha")
    await montar_pote(deps, session)

    replies = await run(deps, session, plano(op(Action.REMOVE_ITEM)), "tira um ai")

    assert len(session.cart.items) == 2  # nada removido no escuro
    assert any("Qual" in reply for reply in replies)


@pytest.mark.asyncio
async def test_trocar_o_tamanho_no_meio_dos_sabores() -> None:
    """"na verdade queria o médio" mexe no rascunho, não cria outro item."""
    deps, session = build_deps(), build_session()
    await run(
        deps,
        session,
        plano(op(Action.ADD_ITEM, product_name="Pote 500ml", add_flavors=["Pistache"])),
        "pote grande de pistache",
    )

    await run(
        deps,
        session,
        plano(op(Action.REPLACE_ITEM, product_name="Pote 240ml")),
        "na verdade queria o medio",
    )

    # O sabor que ainda existe no tamanho novo é mantido.
    item = session.cart.items[0] if session.cart.items else None
    assert item is not None
    assert item.product_name == "Pote 240ml"
    assert [c.name for c in item.complements] == ["Pistache"]


@pytest.mark.asyncio
async def test_alterar_quantidade() -> None:
    deps, session = build_deps(), build_session()
    await run(deps, session, plano(op(Action.ADD_ITEM, product_name="Casquinha")), "casquinha")

    await run(
        deps, session, plano(op(Action.UPDATE_QUANTITY, item_index=1, quantity=3)), "quero 3"
    )

    assert session.cart.items[0].quantity == 3
    assert session.cart.subtotal == Decimal("27.00")


@pytest.mark.asyncio
async def test_duplicar_item() -> None:
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)

    await run(deps, session, plano(op(Action.DUPLICATE_ITEM)), "quero outro igual")

    assert len(session.cart.items) == 2
    assert [c.name for c in session.cart.items[1].complements] == ["Pistache", "Morango"]


# ---------------------------------------------------------------------------
# Várias operações numa mensagem só
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_uma_mensagem_pode_trazer_tudo() -> None:
    """"um pote de pistache e morango, entrega na Rua X, 10, Centro"."""
    deps, session = build_deps(), build_session()

    replies = await run(
        deps,
        session,
        plano(
            op(
                Action.ADD_ITEM,
                product_name="Pote 500ml",
                add_flavors=["Pistache", "Morango"],
            ),
            op(Action.SET_FULFILLMENT, fulfillment="entrega"),
            op(
                Action.UPDATE_ADDRESS,
                address=Address(rua="Rua das Flores", numero="10", bairro="Centro"),
            ),
            op(Action.CLOSE_ORDER),
        ),
        "um pote de pistache e morango, entrega na rua das flores 10 centro",
    )

    # Nada de três turnos: já chega no resumo final.
    assert session.state is S.CONFIRMANDO_PEDIDO
    assert "Total" in replies[-1]
    assert len(session.cart.items) == 1


# ---------------------------------------------------------------------------
# Perguntas não derrubam o pedido
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pergunta_no_meio_dos_sabores_nao_perde_o_item() -> None:
    deps, session = build_deps(), build_session()
    await run(
        deps,
        session,
        plano(op(Action.ADD_ITEM, product_name="Pote 500ml", add_flavors=["Pistache"])),
        "pote de pistache",
    )

    replies = await run(
        deps,
        session,
        plano(
            op(
                Action.ANSWER_QUESTION,
                question_topic="pagamento",
                question_text="aceita cartao?",
            )
        ),
        "aceita cartao?",
    )

    assert any("Pix" in reply for reply in replies)
    assert any("Voltando" in reply for reply in replies)  # retoma de onde estava
    assert session.cart.items[0].complements != []  # o item em montagem continua lá


@pytest.mark.asyncio
async def test_pergunta_de_preco_sai_do_catalogo() -> None:
    deps, session = build_deps(), build_session()
    replies = await run(
        deps,
        session,
        plano(
            op(Action.ANSWER_QUESTION, question_topic="preco", question_text="quanto custa o maior?")
        ),
        "quanto custa o maior?",
    )
    assert any("R$ 32,00" in reply for reply in replies)


# ---------------------------------------------------------------------------
# Dinheiro
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_confirmar_sem_resumo_na_tela_nao_cobra() -> None:
    """"pode ser" no meio da conversa não pode virar Pix."""
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)

    await run(deps, session, plano(op(Action.CONFIRM_ORDER)), "pode ser")

    assert session.state is not S.AGUARDANDO_PAGAMENTO
    assert session.active_order_id is None


@pytest.mark.asyncio
async def test_confirmar_depois_do_resumo_gera_o_pix() -> None:
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)
    await run(
        deps,
        session,
        plano(op(Action.SET_FULFILLMENT, fulfillment="retirada"), op(Action.CLOSE_ORDER)),
        "vou buscar, pode fechar",
    )
    assert session.state is S.CONFIRMANDO_PEDIDO

    replies = await run(deps, session, plano(op(Action.CONFIRM_ORDER)), "sim")

    assert session.state is S.AGUARDANDO_PAGAMENTO
    assert "PIX-COPIA-E-COLA" in replies[0]
    assert session.cart.is_empty


@pytest.mark.asyncio
async def test_retirada_nao_pede_endereco() -> None:
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)

    replies = await run(
        deps,
        session,
        plano(op(Action.SET_FULFILLMENT, fulfillment="retirada"), op(Action.CLOSE_ORDER)),
        "vou retirar",
    )

    assert session.state is S.CONFIRMANDO_PEDIDO
    assert "endereço" not in replies[-1].lower()


# ---------------------------------------------------------------------------
# Atendimento humano e reparo
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handoff_nao_emudece_o_bot() -> None:
    deps, session = build_deps(), build_session()
    await run(deps, session, plano(op(Action.REQUEST_HUMAN)), "quero um atendente")
    assert session.state is S.ATENDIMENTO_HUMANO

    replies = await run(deps, session, plano(op(Action.NO_ACTION)), "alo?")
    assert replies and "aguardando" in replies[0].lower()


@pytest.mark.asyncio
async def test_cliente_pode_voltar_para_o_bot() -> None:
    deps, session = build_deps(), build_session()
    await run(deps, session, plano(op(Action.REQUEST_HUMAN)), "quero um atendente")

    replies = await run(
        deps, session, plano(op(Action.ADD_ITEM, product_name="Casquinha")), "deixa, quero casquinha"
    )

    assert session.handoff is False
    assert replies


@pytest.mark.asyncio
async def test_cancelar_funciona_ate_em_atendimento_humano() -> None:
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)
    await run(deps, session, plano(op(Action.REQUEST_HUMAN)), "atendente")

    replies = await run(deps, session, plano(op(Action.CANCEL_ORDER)), "cancela tudo")

    assert session.state is S.CANCELADO
    assert session.cart.is_empty
    assert "cancelei" in replies[0].lower()


@pytest.mark.asyncio
async def test_fallback_progressivo_nunca_cala_o_bot() -> None:
    """Três incompreensões oferecem gente — e continuam atendendo."""
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)

    primeira = await run(deps, session, AgentPlan(), "xjskd 382")
    segunda = await run(deps, session, AgentPlan(), "382 xjskd")
    terceira = await run(deps, session, AgentPlan(), "??")

    assert "não peguei" in primeira[0].lower()
    assert "ainda não consegui" in segunda[0].lower()
    assert "time" in terceira[0].lower()
    assert session.state is S.CONVERSANDO  # não escalou sozinho
    assert session.handoff is False


@pytest.mark.asyncio
async def test_resposta_morna_nao_vira_cobranca() -> None:
    """"pode ser" não é um sim. Cobrança não se faz com quase-certeza."""
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)
    await run(
        deps,
        session,
        plano(op(Action.SET_FULFILLMENT, fulfillment="retirada"), op(Action.CLOSE_ORDER)),
        "retirada, pode fechar",
    )
    assert session.slots.get("awaiting_confirm") is True

    replies = await run(deps, session, plano(op(Action.CONFIRM_ORDER)), "pode ser")

    assert session.state is S.CONFIRMANDO_PEDIDO
    assert session.active_order_id is None
    assert "certeza" in replies[0].lower()

    # E um sim de verdade logo depois fecha normalmente.
    replies = await run(deps, session, plano(op(Action.CONFIRM_ORDER)), "isso, pode mandar")
    assert session.state is S.AGUARDANDO_PAGAMENTO


# ---------------------------------------------------------------------------
# O que as conversas de teste encontraram
# ---------------------------------------------------------------------------
# Três clientes simulados conversaram com o modelo de verdade e acharam estes
# defeitos. Cada um vira um teste aqui, porque nenhum deles precisa de LLM para
# ser reproduzido — são do código.


@pytest.mark.parametrize(
    "resposta",
    [
        "pode ser",
        "acho que sim",
        "acho que sim, pode ser",   # a vírgula furava a trava
        "sei la, pode ser",
        "talvez",
        "tanto faz",
        "pode ser que sim",
    ],
)
def test_resposta_morna_nunca_gera_pix(resposta: str) -> None:
    """A única trava obrigatória: quase-sim não é sim quando há dinheiro.

    `_hedged` só olhava o começo da frase, então "acho que sim, pode ser" —
    duas respostas mornas emendadas — passava direto e emitia o Pix.
    """
    from app.agent.machine import _hedged  # noqa: PLC0415

    assert _hedged(resposta), f"{resposta!r} deveria ser tratada como morna"


@pytest.mark.parametrize(
    "resposta",
    ["sim", "isso mesmo", "pode mandar o pix", "sim, pode mandar", "perfeito", "ta certo"],
)
def test_sim_claro_continua_confirmando(resposta: str) -> None:
    """A trava não pode engolir a confirmação de verdade."""
    from app.agent.machine import _hedged  # noqa: PLC0415

    assert not _hedged(resposta), f"{resposta!r} é um sim claro"


@pytest.mark.asyncio
async def test_endereco_que_o_cliente_nao_disse_e_descartado() -> None:
    """Endereço é o único dado do pedido sem catálogo para conferir — e a IA
    inventou um bairro respondendo "sim" a "qual o bairro?".

    A entrega iria para o lugar errado, e o cliente não teria como perceber.
    """
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)

    await run(
        deps,
        session,
        plano(
            op(
                Action.UPDATE_ADDRESS,
                address=Address(rua="Rua das Flores", numero="128", bairro="Jardim América"),
            )
        ),
        "entrega na rua das flores 128",   # o cliente NÃO disse o bairro
    )

    endereco = session.slots.get("address", {})
    assert endereco.get("rua") == "Rua das Flores"
    assert endereco.get("numero") == "128"
    assert "bairro" not in endereco, f"bairro inventado entrou no pedido: {endereco}"


@pytest.mark.asyncio
async def test_endereco_que_o_cliente_disse_entra_mesmo_com_erro_de_digitacao() -> None:
    """A trava é frouxa de propósito: quem escreve "flres" no WhatsApp é gente."""
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)

    await run(
        deps,
        session,
        plano(
            op(
                Action.UPDATE_ADDRESS,
                address=Address(rua="Rua das Flores", numero="128", bairro="Centro"),
            )
        ),
        "entrega na rua das flres 128 centro",
    )

    endereco = session.slots.get("address", {})
    assert endereco.get("rua") == "Rua das Flores"
    assert endereco.get("bairro") == "Centro"


@pytest.mark.asyncio
async def test_pix_pendente_congela_o_pedido() -> None:
    """Com o Pix emitido, mexer no pedido montaria um segundo por baixo.

    Um cliente simulado pediu "poe mais uma casquinha" logo depois de receber
    um Pix de R$ 73,00, e o bot respondeu "*Seu pedido* 1x Casquinha — R$ 9,00.
    Quer mais alguma coisa ou já posso fechar?". Dois pedidos, um Pix.
    """
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)
    await run(
        deps,
        session,
        plano(op(Action.SET_FULFILLMENT, fulfillment="retirada"), op(Action.CLOSE_ORDER)),
        "pode fechar, vou retirar",
    )
    await run(deps, session, plano(op(Action.CONFIRM_ORDER)), "sim, confirmo")
    assert session.state is S.AGUARDANDO_PAGAMENTO

    respostas = await run(
        deps,
        session,
        plano(op(Action.ADD_ITEM, product_name="Casquinha")),
        "poe mais uma casquinha",
    )

    assert session.cart.is_empty, f"o carrinho foi remontado: {session.cart.items}"
    assert session.state is S.AGUARDANDO_PAGAMENTO
    assert any("esperando o pagamento" in resposta for resposta in respostas), respostas


@pytest.mark.asyncio
async def test_com_pix_pendente_ainda_da_para_cancelar_e_perguntar() -> None:
    """O congelamento vale para o PEDIDO, não para a conversa."""
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)
    await run(
        deps,
        session,
        plano(op(Action.SET_FULFILLMENT, fulfillment="retirada"), op(Action.CLOSE_ORDER)),
        "pode fechar",
    )
    await run(deps, session, plano(op(Action.CONFIRM_ORDER)), "sim")

    perguntou = await run(
        deps,
        session,
        plano(op(Action.ANSWER_QUESTION, question_topic="prazo", question_text="demora?")),
        "quanto demora?",
    )
    assert perguntou

    cancelou = await run(deps, session, plano(op(Action.CANCEL_ORDER)), "cancela")
    assert cancelou
    assert session.state is S.CANCELADO


@pytest.mark.asyncio
async def test_tirar_uma_de_tres_nao_apaga_a_linha() -> None:
    """"tira uma casquinha" havendo 3 tira UMA — o executor apagava as três."""
    deps, session = build_deps(), build_session()
    await run(
        deps,
        session,
        plano(op(Action.ADD_ITEM, product_name="Casquinha", quantity=3)),
        "me ve 3 casquinha",
    )
    assert session.cart.items[0].quantity == 3

    await run(
        deps,
        session,
        plano(op(Action.REMOVE_ITEM, product_name="Casquinha", quantity=1)),
        "tira uma casquinha",
    )

    assert len(session.cart.items) == 1, "a linha inteira foi apagada"
    assert session.cart.items[0].quantity == 2


@pytest.mark.asyncio
async def test_tirar_sem_dizer_quantos_apaga_a_linha() -> None:
    """Sem quantidade, "tira a casquinha" continua tirando tudo."""
    deps, session = build_deps(), build_session()
    await run(
        deps,
        session,
        plano(op(Action.ADD_ITEM, product_name="Casquinha", quantity=3)),
        "me ve 3 casquinha",
    )
    await run(
        deps,
        session,
        plano(op(Action.REMOVE_ITEM, product_name="Casquinha")),
        "tira a casquinha",
    )
    assert session.cart.is_empty
