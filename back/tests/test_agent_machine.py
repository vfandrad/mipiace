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
from uuid import UUID, uuid4

import pytest

from app import textos as r
from app.agente import (
    TRANSITIONS,
    Action,
    Address,
    AgentDeps,
    AgentPlan,
    ConversationSession,
    InvalidTransition,
    Operation,
    assert_transition,
    can_transition,
    fulfillment_of,
    run,
)
from app.configuracao import get_settings
from app.dominio import (
    CatalogComplement,
    CatalogGroup,
    CatalogProduct,
    CatalogSnapshot,
    FulfillmentType,
)
from app.dominio import ConversationState as S

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


def build_deps(catalog: CatalogSnapshot | None = None, *, returning_customer: bool = False) -> AgentDeps:
    async def _create_order(db, **kwargs):
        return _FakeOrder()

    async def _create_pix(db, order_id):
        return _FakePix()

    async def _summary(db, order_id):
        return None

    async def _saved_address():
        return None

    async def _returning_customer():
        return returning_customer

    return AgentDeps(
        db=None,
        catalog=catalog or build_catalog(),
        settings=get_settings(),
        create_order=_create_order,
        create_pix=_create_pix,
        order_summary=_summary,
        saved_address=_saved_address,
        returning_customer=_returning_customer,
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
    assert replies[-1] == "PIX-COPIA-E-COLA"
    assert session.cart.is_empty


@pytest.mark.asyncio
async def test_fechar_informal_com_resumo_na_tela_confirma() -> None:
    """"fechou mano, pode mandar" veio como close_order, não confirm_order.

    Achado em conversa real: com o resumo já na tela esperando resposta, o
    modelo às vezes classifica uma confirmação bem informal como close_order
    — e sem isto o bot só reexibia o mesmo resumo, obrigando o cliente a
    confirmar de um jeito mais formal antes de o Pix sair.
    """
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)
    await run(
        deps,
        session,
        plano(op(Action.SET_FULFILLMENT, fulfillment="retirada"), op(Action.CLOSE_ORDER)),
        "pode fechar, vou retirar",
    )
    assert session.state is S.CONFIRMANDO_PEDIDO

    replies = await run(deps, session, plano(op(Action.CLOSE_ORDER)), "fechou mano, pode mandar")

    assert session.state is S.AGUARDANDO_PAGAMENTO
    assert replies[-1] == "PIX-COPIA-E-COLA"


@pytest.mark.asyncio
async def test_fechar_informal_morno_ainda_nao_confirma() -> None:
    """A trava da resposta morna vale para close_order tanto quanto para confirm_order."""
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)
    await run(
        deps,
        session,
        plano(op(Action.SET_FULFILLMENT, fulfillment="retirada"), op(Action.CLOSE_ORDER)),
        "pode fechar, vou retirar",
    )

    replies = await run(deps, session, plano(op(Action.CLOSE_ORDER)), "acho que sim, pode ser")

    assert session.state is S.CONFIRMANDO_PEDIDO
    assert session.active_order_id is None
    assert replies


@pytest.mark.asyncio
async def test_correcao_junto_com_fechar_nao_vira_cobranca() -> None:
    """Quem ainda está corrigindo o pedido NÃO está confirmando.

    O pior achado das conversas de teste: com o resumo na tela, o cliente
    escreveu "nao ta certo nao, voce nao mudou nada. no item 2 troca brownie
    por coco". O modelo devolveu update_item + close_order, e o bot respondeu
    emitindo um Pix de R$ 165. Uma reclamação virou cobrança.
    """
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)
    await run(
        deps,
        session,
        plano(op(Action.SET_FULFILLMENT, fulfillment="retirada"), op(Action.CLOSE_ORDER)),
        "pode fechar, vou retirar",
    )
    assert session.state is S.CONFIRMANDO_PEDIDO

    await run(
        deps,
        session,
        plano(
            op(Action.UPDATE_ITEM, remove_flavors=["Pistache"], add_flavors=["Chocolate"]),
            op(Action.CLOSE_ORDER),
        ),
        "nao ta certo nao, troca pistache por chocolate",
    )

    assert session.state is S.CONFIRMANDO_PEDIDO, "alterar e cobrar no mesmo turno"
    assert session.active_order_id is None, "não pode ter cobrado"
    sabores = [c.name for c in session.cart.items[0].complements]
    assert "Chocolate" in sabores and "Pistache" not in sabores, "a troca tinha que valer"


@pytest.mark.asyncio
async def test_dispensar_o_atendente_nao_cancela_o_pedido() -> None:
    """"deixa pra lá, continua vc mesmo" dispensa o ATENDENTE, não o pedido.

    Achado em conversa real: o modelo devolveu cancel_order para essa frase,
    o cliente perdeu o pedido inteiro e, ao reclamar ("eu não mandei cancelar
    nada"), ouviu "cancelei o pedido" de novo.
    """
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)
    await run(deps, session, plano(op(Action.REQUEST_HUMAN)), "quero falar com um atendente")
    assert session.state is S.ATENDIMENTO_HUMANO

    await run(
        deps, session, plano(op(Action.CANCEL_ORDER)), "deixa pra la continua vc mesmo"
    )

    assert session.state is not S.CANCELADO, "dispensar o atendente não é cancelar"
    assert len(session.cart.items) == 1, "o pedido tinha que continuar de pé"


@pytest.mark.asyncio
async def test_cancelar_de_verdade_no_atendimento_humano_continua_valendo() -> None:
    """O contrapeso do teste acima: quem pede para cancelar, cancela."""
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)
    await run(deps, session, plano(op(Action.REQUEST_HUMAN)), "chama um atendente")

    await run(deps, session, plano(op(Action.CANCEL_ORDER)), "cancela meu pedido")

    assert session.state is S.CANCELADO
    assert session.cart.is_empty


# ---------------------------------------------------------------------------
# Frustração clara: oferece atendente sem esperar a escada de fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_frustracao_clara_oferece_atendente_mesmo_sem_o_modelo_pedir() -> None:
    """O modelo não classificou como request_human, mas o texto é inequívoco."""
    deps, session = build_deps(), build_session()

    await run(deps, session, plano(op(Action.NO_ACTION)), "atendimento pessimo, vou reclamar")

    assert session.state is S.ATENDIMENTO_HUMANO


@pytest.mark.asyncio
async def test_reclamacao_de_produto_nao_e_tratada_como_frustracao_com_o_atendimento() -> None:
    """"não gostei do sabor" é feedback de produto, não motivo pra chamar gente."""
    deps, session = build_deps(), build_session()

    await run(deps, session, plano(op(Action.NO_ACTION)), "nao gostei do sabor do pistache")

    assert session.state is not S.ATENDIMENTO_HUMANO


@pytest.mark.asyncio
async def test_frustracao_nao_dobra_pedido_de_humano_ja_feito_pelo_modelo() -> None:
    """O modelo já pediu humano: não duplica a operação por conta do texto."""
    deps, session = build_deps(), build_session()

    replies = await run(
        deps, session, plano(op(Action.REQUEST_HUMAN)), "atendimento pessimo, quero cancelar tudo"
    )

    assert session.state is S.ATENDIMENTO_HUMANO
    assert replies.count(replies[0]) == 1  # uma oferta de atendente, não duas


@pytest.mark.asyncio
async def test_pedir_pra_tirar_a_taxa_nao_oferece_apagar_produto() -> None:
    """"tira essa taxa aí" não é pedido para apagar um pote de R$ 50.

    Achado em conversa real: o bot respondia "Qual deles? 1. GG  2. M" — e um
    "1" teria apagado o produto. Pior, insistia na mesma pergunta depois de o
    cliente explicar que falava da taxa.
    """
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)

    replies = await run(
        deps, session, plano(op(Action.REMOVE_ITEM)), "tira essa taxa de entrega ai vai"
    )

    assert len(session.cart.items) == 1, "nenhum item pode sair"
    resposta = " ".join(replies).lower()
    assert "qual deles" not in resposta, "não pode oferecer apagar produto"
    assert "taxa" in resposta, "tinha que falar da taxa"


@pytest.mark.asyncio
async def test_lista_de_sabores_sem_virgula_nao_perde_sabor() -> None:
    """"pistache chocolate e morango" são TRÊS sabores, não só o último.

    O modelo devolve só o último sabor quando a lista vem sem vírgula, e o
    cliente não vê o que sumiu. O catálogo recupera: só entra sabor que está
    escrito na mensagem E existe no grupo.
    """
    deps, session = build_deps(), build_session()
    await run(
        deps, session, plano(op(Action.ADD_ITEM, product_name="Pote 500ml")), "um pote"
    )

    await run(
        deps,
        session,
        # O plano traz só o último, como o modelo real devolve.
        plano(op(Action.UPDATE_ITEM, add_flavors=["Morango"])),
        "pistache e morango",
    )

    sabores = [c.name for c in session.cart.items[0].complements]
    assert sabores == ["Pistache", "Morango"], sabores


@pytest.mark.asyncio
async def test_varredura_de_sabores_nao_readiciona_o_que_foi_removido() -> None:
    """"tira o pistache e poe morango" não pode trazer o pistache de volta.

    A recuperação pelo catálogo lê a mensagem inteira, e o nome do sabor
    removido está escrito nela.
    """
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)  # Pistache + Morango

    await run(
        deps,
        session,
        plano(op(Action.UPDATE_ITEM, remove_flavors=["Pistache"], add_flavors=["Chocolate"])),
        "tira o pistache e poe chocolate",
    )

    sabores = [c.name for c in session.cart.items[0].complements]
    assert "Pistache" not in sabores, sabores
    assert "Chocolate" in sabores, sabores


@pytest.mark.asyncio
async def test_varios_itens_na_mesma_frase_nao_mistura_sabores() -> None:
    """"M de frutas vermelhas, G de chocolate e GG de morango" numa frase só.

    Achado em conversa real: os três potes saíam todos com a MESMA mistura dos
    três sabores. Cada grupo de sabores aceita de 1 até N escolhas (min=1): um
    sabor só já é um pedido válido, não "incompleto". Mas a varredura do texto
    cru que recupera listas sem vírgula (`_sabores_ditos`) olhava a mensagem
    inteira, achava os três sabores (um de cada item) e os enfiava em CADA
    item, achando que o modelo tinha "esquecido" os outros dois.
    """
    sabores_id = uuid4()
    complementos = [
        CatalogComplement(id=uuid4(), group_id=sabores_id, name="Frutas vermelhas"),
        CatalogComplement(id=uuid4(), group_id=sabores_id, name="Chocolate"),
        CatalogComplement(id=uuid4(), group_id=sabores_id, name="Morango"),
    ]

    def produto(nome: str, max_choices: int) -> CatalogProduct:
        return CatalogProduct(
            id=uuid4(),
            name=nome,
            base_price=Decimal("30.00"),
            groups=[
                CatalogGroup(
                    id=uuid4(),
                    name="Sabores",
                    min_choices=1,
                    max_choices=max_choices,
                    is_required=True,
                    complements=complementos,
                )
            ],
        )

    catalog = CatalogSnapshot(
        products=[produto("M - 240ml", 2), produto("G - 500ml", 3), produto("GG - 1000ml", 6)]
    )
    deps, session = build_deps(catalog), build_session()

    mensagem = "quero um M de frutas vermelhas, um G de chocolate e um GG de morango"
    await run(
        deps,
        session,
        plano(
            op(Action.ADD_ITEM, product_name="M - 240ml", add_flavors=["Frutas vermelhas"]),
            op(Action.ADD_ITEM, product_name="G - 500ml", add_flavors=["Chocolate"]),
            op(Action.ADD_ITEM, product_name="GG - 1000ml", add_flavors=["Morango"]),
        ),
        mensagem,
    )

    sabores_por_item = {
        item.product_name: {c.name for c in item.complements} for item in session.cart.items
    }
    assert sabores_por_item["M - 240ml"] == {"Frutas vermelhas"}, sabores_por_item
    assert sabores_por_item["G - 500ml"] == {"Chocolate"}, sabores_por_item
    assert sabores_por_item["GG - 1000ml"] == {"Morango"}, sabores_por_item


@pytest.mark.asyncio
async def test_sabor_sem_dono_em_varios_itens_pergunta_em_vez_de_adivinhar() -> None:
    """O modelo erra a atribuição (não só a quantidade) em várias itens na mesma frase.

    Mesma mensagem do teste acima, mas aqui o plano (como o modelo às vezes
    devolve de verdade) repete "Frutas vermelhas" no G em vez de "Chocolate" —
    sobra "Chocolate" dito no texto sem pousar em nenhum item. Antes desta
    checagem, nada acusava isso: o item ficava com o sabor errado em silêncio.
    Agora o bot pergunta de qual item é, sem mexer no que já foi aplicado.
    """
    sabores_id = uuid4()
    complementos = [
        CatalogComplement(id=uuid4(), group_id=sabores_id, name="Frutas vermelhas"),
        CatalogComplement(id=uuid4(), group_id=sabores_id, name="Chocolate"),
        CatalogComplement(id=uuid4(), group_id=sabores_id, name="Morango"),
    ]

    def produto(nome: str, max_choices: int) -> CatalogProduct:
        return CatalogProduct(
            id=uuid4(),
            name=nome,
            base_price=Decimal("30.00"),
            groups=[
                CatalogGroup(
                    id=uuid4(),
                    name="Sabores",
                    min_choices=1,
                    max_choices=max_choices,
                    is_required=True,
                    complements=complementos,
                )
            ],
        )

    catalog = CatalogSnapshot(
        products=[produto("M - 240ml", 2), produto("G - 500ml", 3), produto("GG - 1000ml", 6)]
    )
    deps, session = build_deps(catalog), build_session()

    mensagem = "quero um M de frutas vermelhas, um G de chocolate e um GG de morango"
    replies = await run(
        deps,
        session,
        plano(
            op(Action.ADD_ITEM, product_name="M - 240ml", add_flavors=["Frutas vermelhas"]),
            # Errado de propósito: devia ser "Chocolate".
            op(Action.ADD_ITEM, product_name="G - 500ml", add_flavors=["Frutas vermelhas"]),
            op(Action.ADD_ITEM, product_name="GG - 1000ml", add_flavors=["Morango"]),
        ),
        mensagem,
    )

    resposta = " ".join(replies)
    assert "Chocolate" in resposta, replies
    assert "qual item" in resposta.lower(), replies

    sabores_por_item = {
        item.product_name: {c.name for c in item.complements} for item in session.cart.items
    }
    # Pergunta, não corrige sozinho: o G continua com o sabor errado do plano.
    assert sabores_por_item["G - 500ml"] == {"Frutas vermelhas"}, sabores_por_item


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

    # O texto varia por conversa (ver `textos._NAO_ENTENDI`) — o que importa
    # aqui é que cada rodada é um pedido para reformular, não o texto exato.
    assert primeira[0] == r.nao_entendi(session.id)
    assert segunda[0] == r.nao_entendi_de_novo(session.id)
    assert "time" in terceira[0].lower()
    assert session.state is S.CONVERSANDO  # não escalou sozinho
    assert session.handoff is False


@pytest.mark.asyncio
async def test_cardapio_completo_so_na_primeira_mensagem() -> None:
    """A lista inteira de sabores só sai para quem chega sem saber o que tem.

    Mandar o cardápio de novo a cada "oi" mais tarde vira spam — pedido
    explícito do dono do produto depois de ver isso acontecer num cardápio
    real com 30+ sabores.
    """
    deps, session = build_deps(), build_session()

    primeira = await run(deps, session, plano(op(Action.NO_ACTION)), "oi")
    segunda = await run(deps, session, plano(op(Action.NO_ACTION)), "oi de novo")

    assert any("cardápio de hoje" in reply for reply in primeira)
    assert not any("cardápio de hoje" in reply for reply in segunda)
    assert segunda  # continua respondendo, só não repete a lista inteira


@pytest.mark.asyncio
async def test_cardapio_nao_repete_quando_carrinho_esvazia() -> None:
    """Tirar o único item do pedido não dispara o cardápio inteiro de novo."""
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)

    replies = await run(
        deps, session, plano(op(Action.REMOVE_ITEM, item_index=1)), "tira o pote"
    )

    assert not any("cardápio de hoje" in reply for reply in replies)
    assert replies


@pytest.mark.asyncio
async def test_saudacao_calorosa_para_quem_ja_pagou_pedido_antes() -> None:
    """Cliente com pedido pago anterior ouve uma saudação mais calorosa."""
    deps = build_deps(returning_customer=True)
    session = build_session()
    session.slots["customer_name"] = "Marina"

    replies = await run(deps, session, plano(op(Action.SHOW_MENU)), "oi")

    assert "Marina" in replies[0]
    assert "de novo" in replies[0]


@pytest.mark.asyncio
async def test_saudacao_generica_para_quem_nunca_pagou_mesmo_com_nome_conhecido() -> None:
    """Conhecer o nome (profile_name do WhatsApp) não é o mesmo que já ter pedido."""
    deps = build_deps(returning_customer=False)
    session = build_session()
    session.slots["customer_name"] = "Marina"

    replies = await run(deps, session, plano(op(Action.SHOW_MENU)), "oi")

    assert "de novo" not in replies[0]


@pytest.mark.asyncio
async def test_cardapio_completo_na_primeira_vez_que_e_pedido() -> None:
    """show_menu mostra a lista inteira quando ela ainda não saiu na conversa."""
    deps, session = build_deps(), build_session()

    replies = await run(deps, session, plano(op(Action.SHOW_MENU)), "me manda o cardapio")

    assert any("cardápio de hoje" in reply for reply in replies)


@pytest.mark.asyncio
async def test_cardapio_nao_repete_mesmo_quando_pedido_de_novo() -> None:
    """Pedir o cardápio de novo não manda a parede de texto inteira outra vez.

    Antes, `show_menu` reenviava a lista inteira (tamanhos + 30 e tantos
    sabores) toda vez que o cliente pedia — várias vezes na mesma conversa
    virava spam. Continua respondendo ao pedido, só que sem repetir tudo.
    """
    deps, session = build_deps(), build_session()
    await run(deps, session, plano(op(Action.SHOW_MENU)), "me manda o cardapio")

    replies = await run(deps, session, plano(op(Action.SHOW_MENU)), "manda de novo o cardapio")

    assert not any("cardápio de hoje" in reply for reply in replies)
    assert replies


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
    from app.agente import _hedged  # noqa: PLC0415

    assert _hedged(resposta), f"{resposta!r} deveria ser tratada como morna"


@pytest.mark.parametrize(
    "resposta",
    ["sim", "isso mesmo", "pode mandar o pix", "sim, pode mandar", "perfeito", "ta certo"],
)
def test_sim_claro_continua_confirmando(resposta: str) -> None:
    """A trava não pode engolir a confirmação de verdade."""
    from app.agente import _hedged  # noqa: PLC0415

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


def test_endereco_do_texto_ignora_enfeite_falado_antes_da_rua() -> None:
    """Áudio real: "cara, é avenida Guaporé, 4202" saiu da transcrição com
    "cara," virado em "Carena," — e a leitura antiga colava esse ruído na rua
    porque lia do início da frase até o número, não da palavra do logradouro.
    """
    from app.agente import _endereco_do_texto  # noqa: PLC0415

    endereco = _endereco_do_texto(
        "carena, avenida guapore, 4202, aqui no jardim clodoaldo"
    )

    assert endereco is not None
    assert endereco.rua == "avenida guapore"
    assert endereco.numero == "4202"
    assert endereco.bairro == "jardim clodoaldo"


@pytest.mark.asyncio
async def test_entrega_sem_endereco_pergunta_na_hora_nao_so_ao_fechar() -> None:
    """Escolher entrega já pergunta o endereço, sem esperar o "pode fechar"."""
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)

    replies = await run(
        deps, session, plano(op(Action.SET_FULFILLMENT, fulfillment="entrega")), "quero entrega"
    )

    assert any("endereço" in reply.lower() for reply in replies), replies
    assert session.slots.get("closing") is not True  # ainda não pediu pra fechar


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
async def test_pix_expirado_libera_pedido_novo() -> None:
    """Pix que já morreu não pode travar um pedido novo atrás dele para sempre.

    Diferente do teste acima: aqui o Pix não está mais pendente de verdade
    (expirou no provedor) — travar o cliente numa cobrança morta, oferecendo
    só "chamar alguém do time", é pior do que deixar montar o pedido de novo.
    """
    from types import SimpleNamespace

    cancelados: list[UUID] = []

    async def _cancel_order(db, order_id):
        cancelados.append(order_id)

    async def _summary(db, order_id):
        return SimpleNamespace(code="MP-0009", payment_status="expirado")

    deps, session = build_deps(), build_session()
    deps.cancel_order = _cancel_order
    deps.order_summary = _summary
    await montar_pote(deps, session)
    await run(
        deps,
        session,
        plano(op(Action.SET_FULFILLMENT, fulfillment="retirada"), op(Action.CLOSE_ORDER)),
        "pode fechar, vou retirar",
    )
    await run(deps, session, plano(op(Action.CONFIRM_ORDER)), "sim, confirmo")
    assert session.state is S.AGUARDANDO_PAGAMENTO
    pedido_morto = session.active_order_id
    assert pedido_morto is not None

    respostas = await run(
        deps,
        session,
        plano(op(Action.ADD_ITEM, product_name="Casquinha")),
        "quero uma casquinha",
    )

    assert cancelados == [pedido_morto]
    assert not session.cart.is_empty, "o pedido novo não foi montado"
    assert session.active_order_id != pedido_morto
    assert not any("esperando o pagamento" in resposta.lower() for resposta in respostas), respostas


@pytest.mark.asyncio
async def test_com_pix_pendente_ainda_da_para_cancelar_e_perguntar() -> None:
    """O congelamento vale para o PEDIDO, não para a conversa."""
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)
    await run(
        deps,
        session,
        plano(op(Action.SET_FULFILLMENT, fulfillment="retirada"), op(Action.CLOSE_ORDER)),
        "pode fechar, vou retirar",
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
async def test_cancelar_e_pedir_de_novo_no_mesmo_turno_nao_perde_o_novo_pedido() -> None:
    """"cancela isso... ah deixa, na verdade quero sim, bota X" não pode virar silêncio.

    Achado em conversa real: o plano do modelo trazia cancel_order + add_item
    corretamente, mas o executor parava no primeiro `turn.finished` (o
    cancelamento) e nunca processava o add_item — o carrinho ficava vazio, o
    estado ficava cancelado, e o cliente não era avisado que o pedido novo
    simplesmente não entrou.
    """
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)

    replies = await run(
        deps,
        session,
        plano(op(Action.CANCEL_ORDER), op(Action.ADD_ITEM, product_name="Casquinha")),
        "cancela isso... ah deixa, na verdade quero uma casquinha",
    )

    assert session.state is S.CONVERSANDO
    assert len(session.cart.items) == 1
    assert session.cart.items[0].product_name == "Casquinha"
    assert any("cancel" in reply.lower() for reply in replies)


@pytest.mark.asyncio
async def test_cancelar_sozinho_continua_cancelando_normalmente() -> None:
    """A mudança para não perder operações depois de cancelar não pode reabrir o pedido sozinha."""
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)

    replies = await run(deps, session, plano(op(Action.CANCEL_ORDER)), "cancela, desisti")

    assert session.state is S.CANCELADO
    assert session.cart.is_empty
    assert replies


@pytest.mark.asyncio
async def test_atendente_junto_com_pergunta_nao_perde_a_resposta() -> None:
    """"quanto vou pagar, e chama um atendente" não pode responder só sobre o atendente.

    Achado em conversa real: `show_total` respondia certo, mas a resposta
    inteira sumia quando `request_human` vinha depois na mesma mensagem — o
    executor retornava só o texto do handoff, descartando o que já tinha sido
    dito.
    """
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)

    replies = await run(
        deps,
        session,
        plano(op(Action.SHOW_TOTAL), op(Action.REQUEST_HUMAN)),
        "quanto vou pagar, e chama um atendente",
    )

    assert any("32" in reply for reply in replies), replies
    assert any("chamei" in reply.lower() for reply in replies), replies


@pytest.mark.asyncio
async def test_quanto_fica_antes_de_escolher_entrega_nao_inventa_taxa() -> None:
    """"quanto fica?" antes de perguntar entrega/retirada não pode cobrar taxa.

    Achado testando conversas difíceis: sem entrega/retirada decidido, o
    total respondia como se fosse entrega (R$ 5 a mais) sem o cliente ter
    dito nada sobre isso — quem ia retirar via um total inflado antes mesmo
    de ser perguntado.
    """
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)

    replies = await run(deps, session, plano(op(Action.SHOW_TOTAL)), "quanto fica?")

    resposta = " ".join(replies)
    assert "32" in resposta, replies
    assert "entrega ou retirada" in resposta.lower(), replies
    assert "Taxa de entrega" not in resposta, replies
    assert "*Total:" not in resposta, replies


@pytest.mark.asyncio
async def test_fechar_morno_no_meio_do_pedido_nao_avanca_pro_checkout() -> None:
    """"sei lá, pode ser" respondendo "quer mais alguma coisa?" não é "pode fechar".

    Mesma trava da confirmação final (`_hedged`), só que mais cedo: antes essa
    frase avançava o fluxo até a pergunta de entrega/retirada mesmo o cliente
    tendo marcado a própria fala como incerta.
    """
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)

    replies = await run(deps, session, plano(op(Action.CLOSE_ORDER)), "sei lá, pode ser")

    assert session.state is S.CONVERSANDO
    assert "fulfillment" not in session.slots
    assert replies


@pytest.mark.asyncio
async def test_trocar_tamanho_via_remove_e_add_avisa_sabor_descartado() -> None:
    """Troca de tamanho às vezes chega como remove_item + add_item, não replace_item.

    Achado em conversa real, reproduzido 2x: "na verdade quero o pequeno" com
    um Pote 500ml (2 sabores) no carrinho fazia o modelo tirar o item e
    recriar um Pote 240ml (1 sabor) mantendo só o primeiro — sem nunca avisar
    qual sabor sumiu.
    """
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session, sabores=("Pistache", "Morango"))

    replies = await run(
        deps,
        session,
        plano(
            op(Action.REMOVE_ITEM, item_index=1),
            op(Action.ADD_ITEM, product_name="Pote 240ml", add_flavors=["Pistache"]),
        ),
        "na verdade quero o pequeno mesmo, só isso",
    )

    assert len(session.cart.items) == 1
    assert session.cart.items[0].product_name == "Pote 240ml"
    assert any("Morango" in reply for reply in replies), (
        f"o sabor descartado (Morango) nunca foi mencionado: {replies}"
    )


@pytest.mark.asyncio
async def test_trocar_tamanho_via_replace_item_avisa_sabor_descartado() -> None:
    """O mesmo aviso vale quando o modelo usa replace_item (o caminho "certo")."""
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session, sabores=("Pistache", "Morango"))

    replies = await run(
        deps,
        session,
        plano(op(Action.REPLACE_ITEM, product_name="Pote 240ml")),
        "na verdade quero o pequeno mesmo",
    )

    assert len(session.cart.items) == 1
    assert session.cart.items[0].product_name == "Pote 240ml"
    assert any("Morango" in reply for reply in replies), replies


@pytest.mark.asyncio
async def test_fulfillment_nao_entra_sem_sinal_na_mensagem() -> None:
    """Achado em conversa real: o modelo marcou fulfillment=entrega sem o
    cliente ter dito uma palavra sobre entrega ou retirada — a mensagem era só
    sobre sabor e um item novo. Isso gruda taxa de R$5 e exige endereço para
    um pedido que talvez fosse retirada.
    """
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)

    await run(
        deps,
        session,
        plano(op(Action.SET_FULFILLMENT, fulfillment="entrega")),
        "quero os dois sabores de chocolate, e bota mais uma casquinha também",
    )

    assert session.slots.get("fulfillment") is None


@pytest.mark.asyncio
async def test_fulfillment_ainda_entra_quando_o_cliente_diz() -> None:
    """A trava é só para invenção — dizer de verdade continua funcionando."""
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)

    await run(
        deps,
        session,
        plano(op(Action.SET_FULFILLMENT, fulfillment="entrega")),
        "quero entrega mesmo",
    )

    assert session.slots.get("fulfillment") == "entrega"


@pytest.mark.asyncio
async def test_pergunta_sobre_pedido_pago_nao_ve_carrinho_vazio() -> None:
    """"qual sabor eu escolhi mesmo?" depois do Pix não pode soar como pedido sumido.

    `place_order` esvazia o carrinho ao emitir o Pix. Achado em conversa
    real: sem consultar o pedido já registrado, show_cart respondia "seu
    pedido está vazio, o que você vai querer hoje?" para quem tinha acabado
    de fechar e pagar.
    """
    from types import SimpleNamespace

    async def _summary(db, order_id):
        item = SimpleNamespace(
            product_name="Pote 500ml",
            quantity=1,
            complements=["Pistache", "Morango"],
            line_total=Decimal("32.00"),
        )
        return SimpleNamespace(
            code="MP-0007",
            items=[item],
            total=Decimal("32.00"),
            payment_status="pendente",
            pix_qr_code="PIX-COPIA-E-COLA",
        )

    deps, session = build_deps(), build_session()
    deps.order_summary = _summary
    await montar_pote(deps, session)
    await run(
        deps,
        session,
        plano(op(Action.SET_FULFILLMENT, fulfillment="retirada"), op(Action.CLOSE_ORDER)),
        "pode fechar, vou retirar",
    )
    await run(deps, session, plano(op(Action.CONFIRM_ORDER)), "sim")
    assert session.cart.is_empty

    replies = await run(
        deps, session, plano(op(Action.SHOW_CART)), "qual sabor eu escolhi mesmo?"
    )

    assert replies
    assert "vazio" not in replies[0].lower()
    assert "Pistache" in replies[0]
    assert "MP-0007" in replies[0]


@pytest.mark.asyncio
async def test_resposta_curta_nao_recria_item_ja_completo() -> None:
    """"sim" fez o modelo reemitir itens já completos, dobrando o carrinho.

    Achado em duas conversas de teste reais: uma resposta curta sem nada
    sobre o pedido veio acompanhada de add_item recriando exatamente o que já
    estava no carrinho, e o subtotal dobrou sem o cliente ter pedido nada
    disso. O executor agora recusa um add_item que duplicaria um item já
    completo quando a mensagem não cita nem o produto nem os sabores.
    """
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)  # Pote 500ml, Pistache+Morango, completo
    await run(deps, session, plano(op(Action.ADD_ITEM, product_name="Casquinha")), "e uma casquinha")
    assert len(session.cart.items) == 2

    replies = await run(
        deps,
        session,
        plano(
            op(Action.ADD_ITEM, product_name="Pote 500ml", add_flavors=["Pistache", "Morango"]),
            op(Action.ADD_ITEM, product_name="Casquinha"),
        ),
        "sim",
    )

    assert len(session.cart.items) == 2, (
        f"'sim' recriou item(ns) já completo(s): {[i.product_name for i in session.cart.items]}"
    )
    assert replies


@pytest.mark.asyncio
async def test_resposta_curta_mas_que_cita_o_produto_ainda_adiciona() -> None:
    """A trava é só para quando a mensagem não dá nenhum sinal — citar o produto ainda funciona."""
    deps, session = build_deps(), build_session()
    await run(
        deps,
        session,
        plano(op(Action.ADD_ITEM, product_name="Casquinha")),
        "quero uma casquinha",
    )
    assert len(session.cart.items) == 1

    await run(
        deps,
        session,
        plano(op(Action.ADD_ITEM, product_name="Casquinha")),
        "bota mais uma casquinha",
    )

    assert len(session.cart.items) == 2


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


# ---------------------------------------------------------------------------
# A regra estrutural: ação destrutiva exige a fala do cliente
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ancoragem_das_acoes_destrutivas() -> None:
    """Nenhuma ação que destrói pedido ou cobra age só porque o modelo mandou.

    Este teste existe por causa do jeito como os defeitos apareceram: uma
    trava por bug, sempre DEPOIS de um cliente real ser prejudicado —
    endereço inventado, entrega marcada sozinha, confirmação morna virando
    Pix, "deixa pra lá" apagando o carrinho. A regra existia na cabeça de
    quem escreveu, não no código.

    Aqui cada ação de `_EXIGEM_FALA_DO_CLIENTE` recebe uma mensagem que não
    pede nada daquilo. Se alguma delas mexer no pedido mesmo assim, este
    teste quebra — inclusive para uma ação destrutiva que venha a ser criada
    depois e entre na lista sem trava.
    """
    from app.agente import _EXIGEM_FALA_DO_CLIENTE

    inocente = "bom dia, tudo bem?"
    argumentos = {
        Action.SET_FULFILLMENT: {"fulfillment": "entrega"},
        Action.UPDATE_ADDRESS: {
            "address": Address(rua="Rua Inventada", numero="9", bairro="Centro")
        },
    }

    for acao in sorted(_EXIGEM_FALA_DO_CLIENTE, key=lambda a: a.value):
        deps, session = build_deps(), build_session()
        await montar_pote(deps, session)

        await run(deps, session, plano(op(acao, **argumentos.get(acao, {}))), inocente)

        assert len(session.cart.items) == 1, f"{acao.value} mexeu no carrinho"
        assert session.state is not S.CANCELADO, f"{acao.value} cancelou o pedido"
        assert session.state is not S.AGUARDANDO_PAGAMENTO, f"{acao.value} cobrou"
        assert session.active_order_id is None, f"{acao.value} criou pedido"
        assert not session.slots.get("fulfillment"), f"{acao.value} escolheu a entrega"
        assert not session.slots.get("address"), f"{acao.value} inventou endereço"


@pytest.mark.asyncio
async def test_a_mesma_acao_funciona_quando_o_cliente_pede() -> None:
    """O contrapeso: com a fala certa, cada uma das travas deixa passar."""
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)
    await run(deps, session, plano(op(Action.REMOVE_ITEM)), "tira esse pote")
    assert session.cart.is_empty, "remover deixou de funcionar"

    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)
    await run(deps, session, plano(op(Action.CANCEL_ORDER)), "cancela meu pedido")
    assert session.state is S.CANCELADO, "cancelar deixou de funcionar"

    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)
    await run(
        deps,
        session,
        plano(op(Action.SET_FULFILLMENT, fulfillment="retirada")),
        "vou retirar na loja",
    )
    assert session.slots.get("fulfillment") == "retirada", "retirada deixou de funcionar"


# ---------------------------------------------------------------------------
# Defeitos achados na revisão de robustez para produção
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancelar_com_pix_pendente_cancela_o_pedido_no_banco_tambem() -> None:
    """Cancelar só a sessão deixava o `Order` real como "novo"/pendente.

    Um pagamento atrasado (ou pago sem o cliente ver a confirmação de
    cancelamento a tempo) aprovava normalmente depois — um pedido que a
    conversa já tratava como morto ia para a cozinha sem ninguém perceber.
    """
    cancelados: list[UUID] = []

    async def _cancel_order(db, order_id):
        cancelados.append(order_id)

    deps, session = build_deps(), build_session()
    deps.cancel_order = _cancel_order
    await montar_pote(deps, session)
    await run(
        deps,
        session,
        plano(op(Action.SET_FULFILLMENT, fulfillment="retirada"), op(Action.CLOSE_ORDER)),
        "pode fechar, vou retirar",
    )
    await run(deps, session, plano(op(Action.CONFIRM_ORDER)), "sim")
    assert session.state is S.AGUARDANDO_PAGAMENTO
    pedido_criado = session.active_order_id
    assert pedido_criado is not None

    await run(deps, session, plano(op(Action.CANCEL_ORDER)), "cancela meu pedido")

    assert session.state is S.CANCELADO
    assert cancelados == [pedido_criado]


@pytest.mark.asyncio
async def test_trocar_entrega_na_mesma_mensagem_do_fechamento_nao_cobra_com_taxa_antiga() -> None:
    """"mudei de ideia, quero entrega, fecha" não pode cobrar com a forma de
    recebimento ANTIGA.

    `place_order` rodava antes de `set_fulfillment` ser aplicado, porque o
    gate de confirmação só olhava para operações de ITEM — a troca de entrega
    ficava de fora da conta, e o pedido era criado e cobrado com a forma de
    recebimento de antes da troca.
    """
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)
    await run(
        deps,
        session,
        plano(op(Action.SET_FULFILLMENT, fulfillment="retirada"), op(Action.CLOSE_ORDER)),
        "pode fechar, vou retirar",
    )
    assert session.state is S.CONFIRMANDO_PEDIDO
    assert fulfillment_of(session) is FulfillmentType.RETIRADA

    await run(
        deps,
        session,
        plano(op(Action.SET_FULFILLMENT, fulfillment="entrega"), op(Action.CLOSE_ORDER)),
        "mudei de ideia, quero entrega, fecha",
    )

    assert session.state is not S.AGUARDANDO_PAGAMENTO, "cobrou antes de aplicar a troca"
    assert session.active_order_id is None
    assert fulfillment_of(session) is FulfillmentType.ENTREGA, "a troca em si tem que ter valido"


@pytest.mark.asyncio
async def test_editar_carrinho_apos_pix_falhar_descarta_o_pedido_velho() -> None:
    """Pix falhou (provedor fora do ar); o cliente edita o carrinho antes de
    tentar de novo — a nova tentativa não pode reaproveitar o pedido velho.

    Sem isto, a confirmação seguinte gerava o Pix para os itens/total de
    ANTES da edição, e o cliente pagava um valor que não batia com o que
    tinha acabado de pedir.
    """
    from types import SimpleNamespace

    pedidos_criados: list[str] = []
    pix_deveria_falhar = True
    cancelados: list[UUID] = []

    async def _create_order(db, **kwargs):
        pedido = SimpleNamespace(
            id=uuid4(), code=f"MP-{len(pedidos_criados) + 1:04d}", total=Decimal("32.00")
        )
        pedidos_criados.append(str(pedido.id))
        return pedido

    async def _create_pix(db, order_id):
        nonlocal pix_deveria_falhar
        if pix_deveria_falhar:
            pix_deveria_falhar = False
            raise RuntimeError("provedor fora do ar")
        return SimpleNamespace(qr_code="PIX-NOVO", provider_payment_id="novo-1")

    async def _cancel_order(db, order_id):
        cancelados.append(order_id)

    deps, session = build_deps(), build_session()
    deps.create_order = _create_order
    deps.create_pix = _create_pix
    deps.cancel_order = _cancel_order
    await montar_pote(deps, session)
    await run(
        deps,
        session,
        plano(op(Action.SET_FULFILLMENT, fulfillment="retirada"), op(Action.CLOSE_ORDER)),
        "pode fechar, vou retirar",
    )
    await run(deps, session, plano(op(Action.CONFIRM_ORDER)), "sim")  # Pix falha aqui

    assert session.state is S.CONFIRMANDO_PEDIDO, "não podia ter avançado com o Pix falho"
    pedido_antigo = session.slots.get("pending_order_id")
    assert pedido_antigo == pedidos_criados[0]

    await run(
        deps,
        session,
        plano(op(Action.ADD_ITEM, product_name="Casquinha")),
        "bota uma casquinha",
    )

    assert session.slots.get("pending_order_id") is None, "o pedido velho tinha que sair do slot"
    assert cancelados == [UUID(pedido_antigo)]

    await run(deps, session, plano(op(Action.CONFIRM_ORDER)), "sim")

    assert session.state is S.AGUARDANDO_PAGAMENTO
    assert len(pedidos_criados) == 2, "tinha que ter criado um pedido NOVO, não reaproveitado o velho"


@pytest.mark.asyncio
async def test_editar_por_nome_com_dois_itens_iguais_respeita_o_ordinal() -> None:
    """"tira o pistache do PRIMEIRO pote" não pode sempre acertar o último.

    Com dois itens do mesmo produto no carrinho, o código só tinha um jeito
    de desempatar (o último) — mesmo quando o cliente disse qual dos dois.
    """
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)
    await run(deps, session, plano(op(Action.DUPLICATE_ITEM)), "quero outro igual")
    assert len(session.cart.items) == 2

    await run(
        deps,
        session,
        plano(op(Action.UPDATE_QUANTITY, item_index=2, quantity=5)),
        "no segundo, coloca 5",
    )
    assert session.cart.items[1].quantity == 5

    await run(
        deps,
        session,
        plano(op(Action.REMOVE_ITEM, product_name="Pote 500ml")),
        "tira o primeiro pote",
    )

    assert len(session.cart.items) == 1
    assert session.cart.items[0].quantity == 5, "removeu o item errado"


@pytest.mark.asyncio
async def test_duas_remocoes_pelo_mesmo_indice_no_mesmo_turno_nao_apaga_dois() -> None:
    """"tira o primeiro, tira o primeiro de novo" não pode remover dois itens.

    O segundo `remove_item(item_index=1)` é sobre o carrinho que o cliente
    VIU (2 itens) — não sobre o carrinho já encolhido pela primeira remoção
    do mesmo plano.
    """
    deps, session = build_deps(), build_session()
    await montar_pote(deps, session)
    await run(
        deps, session, plano(op(Action.ADD_ITEM, product_name="Casquinha")), "e uma casquinha"
    )
    assert len(session.cart.items) == 2

    await run(
        deps,
        session,
        plano(
            op(Action.REMOVE_ITEM, item_index=1),
            op(Action.REMOVE_ITEM, item_index=1),
        ),
        "tira o primeiro, tira o primeiro de novo",
    )

    assert len(session.cart.items) == 1
    assert session.cart.items[0].product_name == "Casquinha"
