"""O agente de WhatsApp inteiro: da mensagem do cliente à resposta.

O desenho, que vale para qualquer mudança aqui: **a LLM traduz, a máquina de
estados garante, o backend calcula**. A LLM tem liberdade total para
interpretar o que o cliente quis dizer e devolver isso como operações
estruturadas; ela nunca inventa produto, preço, taxa ou disponibilidade, e
nunca executa uma cobrança. Quem valida é a máquina; quem faz conta é o
backend.

    mensagem -> LLM (interpreta) -> operações -> máquina (valida)
             -> serviços (calculam) -> resposta

As seções estão na ordem das dependências, das folhas para o topo: o plano e
os estados primeiro, a orquestração por último. Quem chama o agente de fora
usa só a última seção (`handle_inbound`, `handle_outbound_echo`,
`notify_payment_approved`).

O que o cliente lê não está aqui — está em `textos.py`.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import random
import re
import time
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from difflib import SequenceMatcher, get_close_matches
from enum import StrEnum
from functools import lru_cache
from typing import Any, Protocol, TypeVar
from uuid import UUID

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import text

from app import textos as r
from app.configuracao import Settings, get_settings
from app.dominio import (
    Cart,
    CartComplement,
    CartItem,
    CatalogComplement,
    CatalogGroup,
    CatalogProduct,
    CatalogSnapshot,
    ConversationState,
    FulfillmentType,
    MessageDirection,
    OrderChannel,
    OrderStatus,
    normalize,
    parse_state,
)
from app.dominio import ConversationState as S
from app.servicos import (
    InvalidStatusTransition,
    OrderNotFoundError,
    create_order_from_cart,
    create_pix_for_order,
    get_catalog_snapshot,
    get_order_summary,
    update_order_status,
)

# ---------------------------------------------------------------------------
# O plano: o que a LLM pode devolver
# ---------------------------------------------------------------------------

class Action(StrEnum):
    """O que o cliente está tentando fazer.

    Cada uma é uma operação sobre o pedido, independente do ponto da conversa
    em que ela chega. É isso que permite ao cliente perguntar o horário no meio
    da escolha de sabores sem perder o pedido.
    """

    ADD_ITEM = "add_item"                 # põe um item novo no pedido
    UPDATE_ITEM = "update_item"           # mexe num item que já existe
    REPLACE_ITEM = "replace_item"         # troca o produto do item, mantendo o resto
    REMOVE_ITEM = "remove_item"           # tira um item do pedido
    UPDATE_QUANTITY = "update_quantity"   # "na verdade só um", "coloca mais dois"
    DUPLICATE_ITEM = "duplicate_item"     # "quero outro igual"
    SET_FULFILLMENT = "set_fulfillment"   # entrega ou retirada
    UPDATE_ADDRESS = "update_address"     # endereço, inteiro ou aos pedaços
    SHOW_MENU = "show_menu"
    SHOW_CART = "show_cart"
    SHOW_TOTAL = "show_total"
    ANSWER_QUESTION = "answer_question"   # pergunta informativa; não mexe no pedido
    CLOSE_ORDER = "close_order"           # "pode fechar", "é só isso"
    CONFIRM_ORDER = "confirm_order"       # "sim" ao resumo final — só isso gera Pix
    CANCEL_ORDER = "cancel_order"
    REQUEST_HUMAN = "request_human"
    ASK_CLARIFICATION = "ask_clarification"  # a IA viu ambiguidade e NÃO escolheu
    NO_ACTION = "no_action"               # cumprimento, agradecimento, conversa fiada


#: Assuntos de pergunta que o sistema sabe responder com dado de verdade.
QUESTION_TOPICS = (
    "preco",
    "pagamento",
    "taxa_entrega",
    "area_entrega",
    "prazo",
    "horario",
    "endereco_loja",
    "restricao",
    "disponibilidade",
    "outro",
)


class Address(BaseModel):
    """Endereço como objeto, para o cliente completar em qualquer ordem."""

    rua: str | None = None
    numero: str | None = None
    bairro: str | None = None
    complemento: str | None = None
    referencia: str | None = None


#: Ver `OpenAILLMClient._positive`.
_QUANTIDADE_MAXIMA_POR_OPERACAO = 50


class Operation(BaseModel):
    """Uma coisa que o cliente quer fazer com o pedido.

    Os campos são todos opcionais porque cada ação usa os seus. O que nunca
    muda: `product_name` e os sabores são NOMES DO CARDÁPIO, validados pelo
    backend antes de qualquer coisa acontecer.
    """

    action: Action = Action.NO_ACTION

    #: Qual item do pedido a operação atinge (1 = o primeiro da lista mostrada).
    #: Sem índice, vale o item em construção; sem ele, o último do carrinho.
    item_index: int | None = None

    #: Nome exato do produto no cardápio.
    product_name: str | None = None
    quantity: int | None = None

    #: Sabores a acrescentar e a tirar — é o que torna "troca X por Y" uma
    #: edição do mesmo item, e não um item novo.
    add_flavors: list[str] = Field(default_factory=list)
    remove_flavors: list[str] = Field(default_factory=list)

    fulfillment: str | None = None          # "entrega" | "retirada"
    address: Address | None = None

    question_topic: str | None = None
    #: A pergunta do cliente, nas palavras dele — para o sistema responder o
    #: que ele perguntou, e não um texto genérico.
    question_text: str | None = None

    #: O que o cliente citou e o sistema não achou; vira "não temos açaí".
    raw_text: str | None = None

    #: Quando a IA viu duas leituras possíveis, o que precisa ser esclarecido.
    clarification: str | None = None


class AgentPlan(BaseModel):
    """Tudo que a IA entendeu de uma mensagem.

    Uma mensagem pode conter várias operações ("tira o primeiro, põe um grande
    de chocolate e quero entrega") — e o cliente não deveria precisar de três
    turnos para dizer isso.
    """

    operations: list[Operation] = Field(default_factory=list)
    confidence: float = 0.0
    customer_name: str | None = None

    # Metadados de auditoria/custo (gravados em conversation_messages).
    model: str | None = None
    usage: dict | None = None

    @property
    def actions(self) -> list[Action]:
        return [op.action for op in self.operations]

    def first(self, action: Action) -> Operation | None:
        return next((op for op in self.operations if op.action is action), None)

    def has(self, action: Action) -> bool:
        return any(op.action is action for op in self.operations)

    def has_any(self, actions: frozenset[Action] | set[Action]) -> bool:
        return any(op.action in actions for op in self.operations)


# ---------------------------------------------------------------------------
# Estados da conversa e transições permitidas
# ---------------------------------------------------------------------------

TRANSITIONS: dict[S, set[S]] = {
    S.CONVERSANDO: {
        S.CONVERSANDO,          # o diálogo inteiro acontece aqui
        S.CONFIRMANDO_PEDIDO,
        S.ATENDIMENTO_HUMANO,
        S.CANCELADO,
    },
    S.CONFIRMANDO_PEDIDO: {
        S.AGUARDANDO_PAGAMENTO,  # único caminho para a cobrança
        S.CONVERSANDO,           # cliente quis mudar algo
        S.CONFIRMANDO_PEDIDO,
        S.ATENDIMENTO_HUMANO,
        S.CANCELADO,
    },
    S.AGUARDANDO_PAGAMENTO: {
        S.CONCLUIDO,             # webhook de pagamento aprovado
        S.AGUARDANDO_PAGAMENTO,  # cliente perguntou algo enquanto paga
        S.CONVERSANDO,           # desistiu do Pix e voltou a montar o pedido
        S.ATENDIMENTO_HUMANO,
        S.CANCELADO,             # Pix expirou ou cliente desistiu
    },
    S.CONCLUIDO: {
        S.CONVERSANDO,           # cliente volta para um novo pedido
        S.ATENDIMENTO_HUMANO,
    },
    S.ATENDIMENTO_HUMANO: {
        S.CONVERSANDO,           # lojista devolve, ou ninguém respondeu a tempo
        S.CANCELADO,
        S.CONFIRMANDO_PEDIDO,    # retomou do handoff com o resumo ainda na tela
        S.AGUARDANDO_PAGAMENTO,  # retomou do handoff com o Pix já emitido e pendente
    },
    S.CANCELADO: {
        S.CONVERSANDO,           # novo pedido depois de cancelar
    },
}

#: Estados a partir dos quais um "quero cancelar" do cliente é aceito.
CANCELLABLE_STATES: frozenset[S] = frozenset(
    {S.CONVERSANDO, S.CONFIRMANDO_PEDIDO, S.AGUARDANDO_PAGAMENTO}
)


class InvalidTransition(RuntimeError):
    """Tentativa de pular uma etapa do fluxo."""

    def __init__(self, origin: S, destination: S) -> None:
        super().__init__(f"Transição inválida: {origin} -> {destination}")
        self.origin = origin
        self.destination = destination


def can_transition(origin: S, destination: S) -> bool:
    return destination in TRANSITIONS.get(origin, set())


def assert_transition(origin: S, destination: S) -> None:
    if not can_transition(origin, destination):
        raise InvalidTransition(origin, destination)


#: Estados que aceitam "entrar de novo" no mesmo estado — repetir a pergunta é
#: parte do fluxo neles. Nos demais, mandar para o estado atual é ruído.
_REENTERABLE: frozenset[S] = frozenset(
    {S.CONVERSANDO, S.CONFIRMANDO_PEDIDO, S.AGUARDANDO_PAGAMENTO}
)


def advance(session: ConversationSession, destination: S) -> None:
    """Única porta de mudança de estado — valida contra a tabela de transições."""
    if session.state == destination and destination not in _REENTERABLE:
        return
    assert_transition(session.state, destination)
    session.state = destination


# ---------------------------------------------------------------------------
# Casar o que o cliente falou com o cardápio
# ---------------------------------------------------------------------------

#: Abaixo disso a similaridade é chute; melhor repreguntar do que errar o pedido.
SIMILARITY_CUTOFF = 0.72

#: Candidatos com score muito próximo do melhor também entram como ambiguidade.
SIMILARITY_TOLERANCE = 0.06

#: Palavras que não ajudam a identificar item nenhum no cardápio.
_STOPWORDS = frozenset(
    {
        "quero", "queria", "querer", "gostaria", "de", "do", "da", "dos", "das", "um",
        "uma", "uns", "umas", "o", "a", "os", "as", "por", "favor", "pfv",
        "me", "ve", "ver", "manda", "pode", "ser", "e", "com", "sabor",
        "sabores", "ai", "pra", "para", "vou", "levar", "no",
        # Quantidade escrita por extenso. Sem tirar, "dois potes" casava com a
        # descrição do GG ("Dois potes G") e o cliente que queria dois potes
        # médios recebia, calado, um pote de R$ 90.
        "dois", "duas", "tres", "quatro", "cinco", "meia", "meio",
        # "tem acai?" -> a consulta é "acai"; o resto é a pergunta.
        "tem", "temos", "voces", "vcs", "tinha",
        # Verbos de pedido. Sem eles, "poe tambem um G de morango..." chegava
        # ao resolvedor como "poe tambem g" e não casava com nada, enquanto
        # "vou querer um M..." casava — a diferença era só o ruído em volta.
        "poe", "põe", "bota", "coloca", "colocar", "adiciona", "acrescenta",
        "tambem", "também", "traz", "trazer", "quer",
    }
)


class MatchStatus(StrEnum):
    """Como o texto do cliente se comportou contra o catálogo."""

    OK = "ok"                    # exatamente um item disponível
    AMBIGUOUS = "ambiguous"      # dois ou mais bons candidatos: perguntar qual
    NOT_FOUND = "not_found"      # nada parecido no cardápio: repreguntar
    UNAVAILABLE = "unavailable"  # existe, mas está esgotado/desativado


T = TypeVar("T", CatalogProduct, CatalogComplement)


@dataclass(slots=True)
class ProductMatch:
    status: MatchStatus
    query: str
    product: CatalogProduct | None = None
    candidates: list[CatalogProduct] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status is MatchStatus.OK and self.product is not None


@dataclass(slots=True)
class ComplementMatch:
    status: MatchStatus
    query: str
    complement: CatalogComplement | None = None
    candidates: list[CatalogComplement] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status is MatchStatus.OK and self.complement is not None


# ---------------------------------------------------------------------------
# Núcleo do casamento (independente de ser produto ou complemento)
# ---------------------------------------------------------------------------

#: Litro e mililitro são a mesma medida escrita de dois jeitos, e o cliente
#: usa a que quiser: "o de um litro" para um produto chamado "GG - 1000ml".
#: A troca é conversão de unidade, não conhecimento da loja — se a casa não
#: nomear os tamanhos em ml, o termo simplesmente não casa com nada, como já
#: acontecia antes.
_MEDIDAS = (
    ("meio litro", "500ml"),
    ("1 litro", "1000ml"),
    ("um litro", "1000ml"),
    ("2 litros", "2000ml"),
    ("dois litros", "2000ml"),
    ("litro", "1000ml"),
)


def _clean(query: str) -> str:
    """Normaliza e remove ruído de pedido ("quero um...") do texto."""
    norm = normalize(query)
    for escrito, medida in _MEDIDAS:
        norm = norm.replace(escrito, medida)
    tokens = [t for t in norm.replace("/", " ").split() if t]
    kept = [t for t in tokens if t not in _STOPWORDS]
    return " ".join(kept) if kept else norm


def _score(query: str, name: str) -> float:
    return SequenceMatcher(None, query, name).ratio()


def _singular(text: str) -> str:
    """Tira o plural simples das palavras ("potes" -> "pote").

    Só é usada como busca ADICIONAL, nunca no lugar do texto original: um
    sabor chamado "Frutas vermelhas" precisa continuar casando no exato.
    """
    return " ".join(t[:-1] if len(t) >= 4 and t.endswith("s") else t for t in text.split())


def _terms(text: str) -> list[str]:
    """Quebra um nome em pedaços casáveis: "G - 500ml" -> ["g", "500ml"]."""
    return [t for t in re.split(r"[^a-z0-9]+", text) if t]


def _match_names(query: str, items: Sequence[T]) -> list[T]:
    """Devolve os candidatos plausíveis, do mais para o menos provável.

    Olha o nome E a descrição do item. Num cardápio de gelateria o nome é o
    tamanho ("G - 500ml") e o jeito como o cliente fala está na descrição
    ("Pote grande: escolha 3 sabores") — comparar só com o nome era o que fazia
    "quero um pote grande" não casar com nada.
    """
    cleaned = _clean(query)
    if not cleaned:
        return []

    # Complemento não tem descrição; produto tem (às vezes vazia).
    pairs = [
        (item, normalize(item.name), normalize(getattr(item, "description", None) or ""))
        for item in items
    ]

    # 1) match exato — o caminho feliz de quem digitou o nome do cardápio.
    exact = [item for item, name, _ in pairs if name == cleaned]
    if exact:
        return exact

    # 2) o cliente respondeu só o tamanho: "g", "gg", "500ml".
    by_term = [item for item, name, _ in pairs if cleaned in _terms(name)]
    if by_term:
        return by_term

    # 3) substring nos dois sentidos ("pote" -> "Pote 500ml";
    #    "quero pote 500ml gelado" -> "Pote 500ml").
    substring = [item for item, name, _ in pairs if name in cleaned or cleaned in name]
    if substring:
        # nomes mais próximos em tamanho batem melhor com a query
        substring.sort(key=lambda item: abs(len(normalize(item.name)) - len(cleaned)))
        return substring

    # 4) o texto do cliente aparece na descrição ("pote grande", "pote g").
    #    O singular entra junto de propósito: "dois potes" casava só com a
    #    descrição do GG ("Dois potes G") e o cliente que queria dois potes
    #    médios levava um de R$ 90 sem ser perguntado. Com "pote" na busca, os
    #    três tamanhos entram como candidatos e a máquina pergunta qual é.
    buscas = {cleaned, _singular(cleaned)}
    in_description = [
        item for item, _, desc in pairs if desc and any(b in desc for b in buscas)
    ]
    if in_description:
        return in_description

    # 5) similaridade — cobre erro de digitação e acento perdido.
    scored = [(item, _score(cleaned, name)) for item, name, _ in pairs]
    scored = [(item, s) for item, s in scored if s >= SIMILARITY_CUTOFF]
    if not scored:
        # última tentativa: casar palavra a palavra
        # ("morango" dentro de "Sorvete de Morango").
        # Singular dos dois lados: "2 potes" tem que alcançar os três tamanhos
        # (e virar pergunta), não só o GG, cuja descrição fala em "potes".
        token_hits = [
            item
            for item, name, desc in pairs
            if any(
                tok in _terms(_singular(name)) or tok in _terms(_singular(desc))
                for tok in _singular(cleaned).split()
                if len(tok) >= 4
            )
        ]
        return token_hits

    scored.sort(key=lambda pair: pair[1], reverse=True)
    best = scored[0][1]
    return [item for item, s in scored if best - s <= SIMILARITY_TOLERANCE]


def _classify(candidates: Sequence[T]) -> tuple[MatchStatus, T | None, list[T]]:
    """Transforma a lista de candidatos em veredito, respeitando disponibilidade."""
    if not candidates:
        return MatchStatus.NOT_FOUND, None, []

    available = [c for c in candidates if c.is_available]
    if not available:
        # Existe no cardápio mas acabou: mensagem diferente de "não entendi".
        return MatchStatus.UNAVAILABLE, None, list(candidates)
    if len(available) == 1:
        return MatchStatus.OK, available[0], available
    return MatchStatus.AMBIGUOUS, None, available


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def resolve_product(query: str, catalog: CatalogSnapshot) -> ProductMatch:
    """Casa texto livre com um produto do cardápio. Nunca inventa produto."""
    if not query or not query.strip():
        return ProductMatch(MatchStatus.NOT_FOUND, query or "")

    candidates = _match_names(query, catalog.products)
    status, product, shortlist = _classify(candidates)
    return ProductMatch(status, query, product, list(shortlist))


def resolve_complement(query: str, group: CatalogGroup) -> ComplementMatch:
    """Casa texto livre com um complemento *dentro de um grupo específico*.

    Restringir ao grupo é o que impede o cliente de escolher "chocolate" da
    cobertura quando a pergunta era sobre sabor.
    """
    if not query or not query.strip():
        return ComplementMatch(MatchStatus.NOT_FOUND, query or "")

    candidates = _match_names(query, group.complements)
    status, complement, shortlist = _classify(candidates)
    return ComplementMatch(status, query, complement, list(shortlist))


def split_queries(text: str) -> list[str]:
    """Quebra "pistache, morango e limão" em pedaços resolvíveis."""
    normalized = text.replace(" e ", ",").replace("/", ",").replace(" + ", ",")
    parts = [part.strip(" .;") for part in normalized.split(",")]
    return [part for part in parts if part]


# ---------------------------------------------------------------------------
# Perguntas que o cardápio não responde
# ---------------------------------------------------------------------------

#: Palavras que identificam o assunto sem margem para dúvida. É o contrário de
#: depender de palavra-chave para ENTENDER o cliente: aqui a IA já entendeu que
#: é uma pergunta, e isto só conserta a etiqueta errada que ela colou nela.
_PISTAS = {
    "pagamento": (
        "pagamento", "pagar", "pix", "cartao", "credito", "debito",
        "dinheiro", "especie", "maquininha", "vale refeicao", "vr",
    ),
    "taxa_entrega": ("taxa", "frete", "entrega custa", "cobra pra entregar"),
    "prazo": ("demora", "quanto tempo", "prazo", "chega que horas", "leva quanto"),
    "horario": ("horario", "que horas", "abre", "fecha", "aberto", "funciona ate"),
    "endereco_loja": ("onde fica", "endereco da loja", "endereco de voces", "fica onde"),
    "area_entrega": ("entregam em", "entrega em", "atendem o", "chega no bairro"),
    # Preço e sabores estavam faltando, e eram as duas perguntas mais comuns:
    # em conversa real "quanto tá o gelato aí?" e "vocês têm algum sabor sem
    # lactose?" foram respondidas com "não sei" — com o catálogo na mão.
    "preco": (
        "quanto custa", "quanto ta", "quanto sai", "qual o preco", "qual o valor",
        "precos", "tabela de preco", "quais tamanhos", "que tamanhos",
        "quais os tamanhos", "tamanhos tem", "quais os potes", "que potes",
        "tamanhos de pote",
    ),
    "sabores": (
        "quais sabores", "que sabores", "quais os sabores", "sabores tem",
        "sabores de hoje", "lista de sabores", "sem lactose", "com lactose",
        "tem sabor", "quais opcoes de sabor", "intoleran", "alergi",
    ),
}


def _assunto(topic: str | None, texto: str) -> str | None:
    """O assunto da pergunta: o texto tem a palavra final sobre o palpite da IA."""
    for assunto, pistas in _PISTAS.items():
        if any(pista in texto for pista in pistas):
            return assunto
    return topic


def answer(
    *,
    topic: str | None,
    question: str,
    raw_text: str | None,
    catalog: CatalogSnapshot,
    settings: Any,
    cart: Cart | None = None,
) -> str:
    """Resposta para a pergunta do cliente. Nunca devolve vazio."""
    texto = normalize(f"{question or ''} {raw_text or ''}")
    assunto = _assunto(topic, texto)

    if assunto == "pagamento":
        return _pagamento(texto)

    if assunto == "taxa_entrega":
        taxa: Decimal = settings.delivery_fee
        return (
            f"A taxa de entrega é *{r.em_reais(taxa)}*, fixa para toda a região que "
            "atendemos.\nSe preferir retirar na loja, não tem taxa. 🛵🏠"
        )

    if assunto == "preco":
        return _precos(catalog, texto)

    if assunto == "sabores":
        return _sabores(catalog, texto)

    if assunto in {"restricao", "disponibilidade"} and _parece_produto_ou_sabor(
        raw_text or question
    ):
        return _tem_isso(catalog, raw_text or question)

    if assunto == "prazo":
        prazo = _config(settings, "store_delivery_estimate")
        if prazo:
            return (
                f"A entrega costuma levar *{prazo}* depois que o Pix cai. 🛵\n"
                "Nos dias de movimento pode variar um pouco."
            )
        return (
            "Assim que o Pix cai a gente já começa a montar. 🍨\n"
            "O tempo exato depende do movimento — se quiser, eu chamo alguém do "
            "time pra te dar uma previsão certinha."
        )

    if assunto == "horario":
        return _configurado_ou_nao(_config(settings, "store_hours"), "horario",
                                   "A gente atende *{}*. 😊")

    if assunto == "endereco_loja":
        return _configurado_ou_nao(_config(settings, "store_address"), "endereco_loja",
                                   "A loja fica em *{}*. 📍")

    if assunto == "area_entrega":
        return _configurado_ou_nao(_config(settings, "store_delivery_area"), "area_entrega",
                                   "A gente entrega em *{}*. 🛵")

    return (
        "Essa eu não sei responder com certeza. 🙈 "
        "Quer que eu chame alguém do time pra te ajudar?"
    )


def _config(settings: Any, campo: str) -> str:
    return (getattr(settings, campo, None) or "").strip()


def _configurado_ou_nao(valor: str, topic: str, molde: str) -> str:
    return molde.format(valor) if valor else _nao_sei(topic)


def _pagamento(texto: str) -> str:
    """Pix é o único meio que o sistema tem — e dizer isso é melhor que 'não sei'."""
    outro_meio = any(
        p in texto
        for p in ("cartao", "credito", "debito", "dinheiro", "especie", "maquininha", "vr")
    )
    base = (
        "Por aqui o pagamento é no *Pix* 💳\n"
        "Quando fechar o pedido eu já mando o código para copiar e colar."
    )
    if outro_meio:
        return (
            "Pelo WhatsApp eu só consigo fechar no *Pix* 💳\n"
            "Mando o código na hora de fechar. Para outra forma de pagamento, "
            "posso chamar alguém do time. 😊"
        )
    return base


def _nao_sei(topic: str) -> str:
    assunto = {
        "horario": "do horário",
        "area_entrega": "se entregamos nessa região",
        "endereco_loja": "do endereço da loja",
    }.get(topic, "disso")
    return (
        f"{assunto.capitalize()} eu não tenho certeza pra te falar. 🙈\n"
        "Quer que eu chame alguém do time pra confirmar?"
    )


def _sabores(catalog: CatalogSnapshot, texto: str) -> str:
    """Sabores de hoje, do catálogo — filtrando por categoria quando o cliente cita uma.

    "tem algo sem lactose?" devolve só os sem lactose. A categoria vem do
    cadastro do lojista, não de lista fixa no código: numa outra loja as
    categorias seriam outras.
    """
    vistos: dict[str, Any] = {}
    for produto in catalog.available_products:
        for grupo in produto.groups:
            for complemento in grupo.available_complements:
                vistos.setdefault(normalize(complemento.name), complemento)
    todos = list(vistos.values())

    categorias = {
        normalize(c.category): c.category for c in todos if c.category
    }

    def da_categoria(chave: str) -> list[Any]:
        return [c for c in todos if c.category and normalize(c.category) == chave]

    for chave, nome in categorias.items():
        if chave and chave in texto:
            return r.lista_de_sabores(da_categoria(chave), f"Sabores {nome.lower()}")

    # "sou intolerante a lactose" quer a categoria "Sem lactose" sem citá-la
    # pelo nome. Procura uma categoria "sem X" cujo X apareça na frase.
    restricao = any(m in texto for m in ("intoleran", "alergi", "nao posso", "nao pode"))
    if restricao:
        for chave, nome in categorias.items():
            if chave.startswith("sem ") and chave[4:].strip() and chave[4:].strip() in texto:
                return r.lista_de_sabores(da_categoria(chave), f"Sabores {nome.lower()}")
        # Restrição que o catálogo não sabe responder (alergia a castanha, por
        # exemplo). Devolver a lista inteira aqui soaria como "pode comer
        # tudo" — e é exatamente o tipo de garantia que o sistema não tem.
        return _nao_sei("restricao")

    return r.lista_de_sabores(todos)


def _precos(catalog: CatalogSnapshot, texto: str) -> str:
    """Preço vem do catálogo, sempre. A IA nunca diz valor."""
    produtos = catalog.available_products
    if not produtos:
        return "Hoje estamos sem itens disponíveis. 😔"

    # "quanto custa o maior?" / "e o pequeno?" — se der para identificar um,
    # responde só ele; senão manda a tabela inteira, que é curta.
    if any(p in texto for p in ("maior", "grande", "mais caro")):
        alvo = max(produtos, key=lambda p: p.base_price)
        return f"O *{alvo.name}* sai {r.em_reais(alvo.base_price)}. 😊"
    if any(p in texto for p in ("menor", "pequeno", "mais barato")):
        alvo = min(produtos, key=lambda p: p.base_price)
        return f"O *{alvo.name}* sai {r.em_reais(alvo.base_price)}. 😊"

    linhas = ["Os preços de hoje:"]
    linhas += [f"• *{p.name}* — {r.em_reais(p.base_price)}" for p in produtos]
    return "\n".join(linhas)


def _parece_produto_ou_sabor(texto: str) -> bool:
    """"tem pistache?", "vende açaí?" parecem nome de produto ou sabor.

    "qual o tamanho mais pedido?", "dá pra escolher qualquer sabor?" não são
    — são perguntas abertas que o modelo, sem opção melhor, rotulou como
    "disponibilidade". Tratando a frase inteira como nome de produto,
    `_tem_isso` respondia "não temos QUAL O TAMANHO MAIS PEDIDO no cardápio",
    o que não faz sentido nenhum para quem só queria uma recomendação.
    Frouxo de propósito: só barra o que claramente não é um nome (frase
    longa ou com "?"), sem tentar entender a pergunta em si — isso cai no
    "não sei responder" genérico, honesto em vez de nonsense.
    """
    limpo = (texto or "").strip()
    if not limpo or "?" in limpo:
        return False
    return len(limpo.split()) <= 6


def _tem_isso(catalog: CatalogSnapshot, procurado: str) -> str:
    """"tem sem açúcar?", "tem açaí?", "tem sem lactose?" — a resposta é o cardápio.

    Os sabores mudam todo dia; procurar no catálogo é o único jeito de a
    resposta continuar verdadeira amanhã. A busca por CATEGORIA existe porque
    "tem sabor sem lactose?" não casa com nome nenhum — "Sem lactose" é o nome
    da categoria, e é ela que responde a pergunta.

    A busca por nome (produto e sabor) olha o cardápio INTEIRO, disponível ou
    não — sem isto, perguntar por algo que existe mas está esgotado hoje
    (Milkshake indisponível, Maracujá esgotado) respondia "não temos no
    cardápio", que é diferente de "temos, mas acabou hoje" e engana o cliente
    sobre o que a loja vende de verdade.
    """
    alvo = normalize(procurado or "").strip()
    if not alvo:
        return "Me diz o que você procura que eu vejo se temos hoje. 😊"

    sabores_disponiveis = {
        c.name: c
        for p in catalog.available_products
        for g in p.groups
        for c in g.available_complements
    }
    sabores_todos = {
        c.name: c for p in catalog.products for g in p.groups for c in g.complements
    }

    # 1. Categoria ("sem lactose", "com lactose", "vegano"...).
    categorias: dict[str, list[str]] = {}
    for nome, c in sabores_disponiveis.items():
        if c.category:
            categorias.setdefault(c.category, []).append(nome)
    for categoria, nomes in categorias.items():
        chave = normalize(categoria)
        if chave in alvo or alvo in chave:
            return f"Temos sim! *{categoria}*: " + ", ".join(nomes) + ". 😊"

    # 2. Sabor pelo nome, disponível.
    achados = [nome for nome in sabores_disponiveis if alvo in normalize(nome)]
    if achados:
        if len(achados) == 1:
            return f"Temos sim: *{achados[0]}*. 😊"
        return "Temos sim! Hoje: *" + "*, *".join(achados) + "*. 😊"

    # 3. Produto pelo nome, disponível.
    produtos = [p.name for p in catalog.available_products if alvo in normalize(p.name)]
    if produtos:
        return f"Temos sim: *{', '.join(produtos)}*. 😊"

    # 4. Existe no cardápio, mas está esgotado/indisponível hoje — não é o
    # mesmo que "nunca vendemos isso".
    esgotado = next((nome for nome in sabores_todos if alvo in normalize(nome)), None)
    if esgotado:
        return f"*{esgotado}* a gente tem, mas acabou hoje. 😔\nQuer ver o que tem disponível?"
    produto_esgotado = next(
        (p.name for p in catalog.products if alvo in normalize(p.name)), None
    )
    if produto_esgotado:
        return (
            f"*{produto_esgotado}* está fora do cardápio hoje. 😔\n"
            "Quer ver o que tem disponível?"
        )

    return f'Hoje não temos *{procurado}* no cardápio. 🙈\nQuer ver o que tem?'


# ---------------------------------------------------------------------------
# Ritmo de envio — o que protege o número de ser banido
# ---------------------------------------------------------------------------

#: Piso e teto do "digitando..." (ms). O piso evita a resposta instantânea que
#: denuncia automação; o teto evita que o cliente ache que ninguém viu.
MIN_TYPING_MS = 1_200
MAX_TYPING_MS = 8_000


def typing_delay_ms(text: str, *, wpm: float | None = None) -> int:
    """Quanto tempo um humano levaria para digitar `text`, com variação.

    Modela a digitação em palavras por minuto sorteadas de uma normal em torno
    da velocidade média configurada — não um valor fixo, porque cadência
    constante é ela própria uma assinatura de robô. Cinco caracteres contam
    como uma palavra, que é a convenção usual de WPM.
    """
    settings = get_settings()
    mean = wpm if wpm is not None else settings.wa_typing_wpm
    speed = max(15.0, random.gauss(mean, mean * 0.33))
    words = max(1, len(text) / 5)
    ms = (words / speed) * 60_000
    # Jitter multiplicativo: duas mensagens de tamanho igual não saem no mesmo tempo.
    ms *= random.uniform(0.85, 1.25)
    return int(min(MAX_TYPING_MS, max(MIN_TYPING_MS, ms)))


class Throttle:
    """Teto de envio: um por contato, um global.

    O limite global é uma janela deslizante de um minuto — comunidade e
    documentação de gateways não-oficiais convergem em algo entre 10 e 20
    mensagens por minuto por instância antes de o antispam reagir, e o padrão
    daqui fica na parte de baixo dessa faixa. Uma gelateria não chega perto
    disso: o teto existe para o caso patológico (um laço de repetição, uma
    tempestade de webhooks), que é justamente quando o número se perde.

    O intervalo por contato serve a outra coisa: o agente responde em rajada
    (resumo do carrinho + pergunta, por exemplo), e duas mensagens no mesmo
    segundo para a mesma pessoa não acontecem quando quem digita é gente.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._recent: deque[float] = deque()      # envios do último minuto
        self._last_by_phone: dict[str, float] = {}

    async def acquire(self, phone: str) -> None:
        """Bloqueia até que enviar para `phone` esteja dentro dos dois limites."""
        settings = get_settings()
        gap = settings.wa_min_seconds_between_messages
        ceiling = settings.wa_max_messages_per_minute

        while True:
            async with self._lock:
                now = time.monotonic()

                while self._recent and now - self._recent[0] >= 60.0:
                    self._recent.popleft()

                wait = 0.0
                last = self._last_by_phone.get(phone)
                if last is not None:
                    wait = max(wait, gap - (now - last))
                if len(self._recent) >= ceiling:
                    wait = max(wait, 60.0 - (now - self._recent[0]))

                if wait <= 0:
                    self._recent.append(now)
                    self._last_by_phone[phone] = now
                    # O dicionário cresceria com um número novo por cliente;
                    # entradas velhas não dizem mais nada sobre o ritmo atual.
                    if len(self._last_by_phone) > 1_000:
                        corte = now - 3_600
                        self._last_by_phone = {
                            p: t for p, t in self._last_by_phone.items() if t > corte
                        }
                    return

            await asyncio.sleep(min(wait, 5.0))


#: Compartilhado pelo processo: o limite é da instância do WhatsApp, não da
#: conversa. Dois clientes falando ao mesmo tempo dividem o mesmo teto.
throttle = Throttle()


# ---------------------------------------------------------------------------
# O prompt e o contrato da ferramenta que a LLM chama
# ---------------------------------------------------------------------------

#: Nome da tool. O modelo é forçado a chamá-la (tool_choice), então ela é o
#: único formato de saída possível — não há texto livre para parsear.
TOOL_NAME = "registrar_operacoes"

_ACTION_DESCRIPTIONS = {
    Action.ADD_ITEM: (
        "quer um item NOVO no pedido. product_name = nome exato do cardápio; "
        "add_flavors = sabores que ele já disse; quantity se ele deu"
    ),
    Action.UPDATE_ITEM: (
        "quer MUDAR um item que já existe: trocar, tirar ou acrescentar sabor. "
        '"troca o chocolate por fior di latte" -> remove_flavors=["Chocolate"], '
        'add_flavors=["Fior di latte"]. NUNCA use add_item para isso'
    ),
    Action.REPLACE_ITEM: (
        'trocar o PRODUTO do item mantendo o resto: "na verdade queria o médio"'
    ),
    Action.REMOVE_ITEM: (
        'tirar um item do pedido: "remove o item 1", "tira o segundo", '
        '"quero só um pote". Use item_index quando ele apontar qual. Se ele '
        'disser QUANTOS tirar ("tira uma casquinha" havendo 3), mande também '
        "quantity com esse número — sem ele a linha inteira sai"
    ),
    Action.UPDATE_QUANTITY: (
        '"quero 3 cascões", "coloca mais dois", "na verdade só um", '
        '"são 2 potes não 1", "muda a quantidade do item 1 pra 2", '
        '"quero 2 desses". Qualquer frase que mude QUANTOS de um item que JÁ '
        "está no pedido, mesmo corrigindo o bot. Ponha o total desejado em "
        "`quantity` (2, e não +1) e o número do item em `item_index` quando "
        "ele disser qual"
    ),
    Action.DUPLICATE_ITEM: (
        '"quero outro igual", "mais um desses" — SÓ quando é uma cópia do '
        "mesmo item. Se ele nomear outro produto, use add_item"
    ),
    Action.SET_FULFILLMENT: (
        'como ele quer receber, dito de qualquer jeito: "manda aqui em casa", '
        '"vou buscar aí", "passo aí pegar", "entrega" -> fulfillment'
    ),
    Action.UPDATE_ADDRESS: "mandou endereço, inteiro ou um pedaço dele",
    Action.SHOW_MENU: "quer ver o cardápio/as opções/os sabores",
    Action.SHOW_CART: '"me mostra o carrinho", "o que eu pedi?"',
    Action.SHOW_TOTAL: '"quanto deu?", "quanto ficou?", "qual o total?"',
    Action.ANSWER_QUESTION: (
        "fez uma PERGUNTA informativa (preço, horário, taxa, prazo, se tem tal "
        "sabor, onde fica a loja). Preencha question_topic e question_text. "
        "NÃO mexe no pedido — o cliente continua exatamente de onde estava"
    ),
    Action.CLOSE_ORDER: (
        'quer fechar, dito como for: "pode fechar", "é só isso", "só isso '
        'mesmo", "pode mandar", "tá certo", "pode finalizar", "manda o pix"'
    ),
    Action.CONFIRM_ORDER: (
        "disse SIM ao resumo final que acabamos de mostrar. Use APENAS se a "
        "situação disser que há um resumo aguardando confirmação e a resposta "
        'for claramente positiva. Na dúvida ("pode ser", "acho que sim"), use '
        "ask_clarification — esta ação gera cobrança"
    ),
    Action.CANCEL_ORDER: (
        "quer desistir do pedido INTEIRO (não de um item). Vale para o que as "
        'pessoas dizem de verdade ao desistir: "cancela", "desisti", "deixa '
        'pra lá", "esquece", "não quero mais", "melhor não". Havendo pedido em '
        "andamento, essas falas são cancelamento — não são conversa fiada"
    ),
    Action.REQUEST_HUMAN: "quer falar com uma pessoa do time",
    Action.ASK_CLARIFICATION: (
        "há duas leituras possíveis e escolher seria chutar. Ex.: \"quero dois "
        'potes" pode ser 2 médios ou o GG. Preencha clarification com o que '
        "precisa ser perguntado. Prefira isto a errar"
    ),
    Action.NO_ACTION: (
        "cumprimento, agradecimento, desabafo — nada a fazer com o pedido"
    ),
}


def tool_schema() -> dict[str, Any]:
    """input_schema espelhando `AgentPlan`."""
    return {
        "name": TOOL_NAME,
        "description": (
            "Registra, em forma de operações, tudo o que o cliente quis dizer "
            "nesta mensagem. Use SEMPRE esta ferramenta."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "operations": {
                    "type": "array",
                    "description": (
                        "Uma entrada por coisa que o cliente quer. Uma mensagem "
                        "pode ter várias: \"tira o primeiro, põe um grande de "
                        "chocolate e quero entrega\" são três operações. Ordem "
                        "importa: aplique na ordem em que ele falou."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": [a.value for a in Action],
                                "description": "\n".join(
                                    f"{action.value}: {desc}"
                                    for action, desc in _ACTION_DESCRIPTIONS.items()
                                ),
                            },
                            "item_index": {
                                "type": ["integer", "null"],
                                "description": (
                                    "Qual item do pedido, contando a partir de 1 "
                                    "na ordem em que o carrinho foi mostrado."
                                ),
                            },
                            "product_name": {
                                "type": ["string", "null"],
                                "description": (
                                    "NOME EXATO do item do cardápio, copiado da "
                                    'lista. Use tamanho, volume, descrição e o '
                                    'contexto: "o grande", "o de 500", "esse '
                                    'mesmo" são itens do cardápio. Nulo se não '
                                    "houver item claro."
                                ),
                            },
                            "quantity": {"type": ["integer", "null"]},
                            "add_flavors": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": (
                                    "TODOS os sabores do cardápio que ele "
                                    "escolheu NESTA mensagem, um por entrada, "
                                    "com o nome EXATO do cardápio. Liste todos "
                                    "mesmo quando vierem numa frase corrida, sem "
                                    "vírgula: \"pistache chocolate e brownie\" são "
                                    "TRÊS sabores, e o resultado tem que ser "
                                    "[\"Pistache\", \"Chocolate\", \"Brownie\"] — "
                                    "nunca só o último. Se respondeu por número, "
                                    "traduza usando a lista mostrada. Não repita o "
                                    "que ele já tinha escolhido."
                                ),
                            },
                            "remove_flavors": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Sabores que ele quer TIRAR do item.",
                            },
                            "fulfillment": {
                                "type": ["string", "null"],
                                "description": 'Exatamente "entrega" ou "retirada".',
                            },
                            "address": {
                                "type": ["object", "null"],
                                "description": (
                                    "Endereço da entrega, quebrado em campos. O "
                                    "cliente escreve de QUALQUER jeito e quase "
                                    "nunca com vírgula — preencha assim mesmo. "
                                    "\"rua das laranjeiras 45 bairro santa rita\" "
                                    "é rua=\"Rua das Laranjeiras\", numero=\"45\", "
                                    "bairro=\"Santa Rita\". \"av brasil 1200 apto "
                                    "91 bloco B centro\" é rua=\"Av Brasil\", "
                                    "numero=\"1200\", complemento=\"apto 91 bloco "
                                    "B\", bairro=\"Centro\". Apartamento, bloco, "
                                    "casa e fundos vão em complemento, nunca "
                                    "grudados na rua. Só preencha o que o cliente "
                                    "escreveu; o resto fica null."
                                ),
                                "properties": {
                                    "rua": {"type": ["string", "null"]},
                                    "numero": {"type": ["string", "null"]},
                                    "bairro": {"type": ["string", "null"]},
                                    "complemento": {"type": ["string", "null"]},
                                    "referencia": {"type": ["string", "null"]},
                                },
                                "required": [
                                    "rua",
                                    "numero",
                                    "bairro",
                                    "complemento",
                                    "referencia",
                                ],
                                "additionalProperties": False,
                            },
                            "question_topic": {
                                "type": ["string", "null"],
                                "description": "Um destes: " + ", ".join(QUESTION_TOPICS),
                            },
                            "question_text": {"type": ["string", "null"]},
                            "raw_text": {
                                "type": ["string", "null"],
                                "description": (
                                    "Trecho literal do que ele pediu quando isso "
                                    "NÃO existe no cardápio (\"açaí\", "
                                    '"milkshake"). É assim que o sistema '
                                    'responde "não trabalhamos com isso".'
                                ),
                            },
                            "clarification": {"type": ["string", "null"]},
                        },
                        # `strict` da OpenAI exige TODAS as chaves em required
                        # (as opcionais aceitando null). Sem isso o gpt-4o-mini
                        # devolvia operação sem o campo `action` — o pedido
                        # inteiro virava "no_action" e o cliente ouvia que não
                        # tinha sido entendido.
                        "required": [
                            "action",
                            "item_index",
                            "product_name",
                            "quantity",
                            "add_flavors",
                            "remove_flavors",
                            "fulfillment",
                            "address",
                            "question_topic",
                            "question_text",
                            "raw_text",
                            "clarification",
                        ],
                        "additionalProperties": False,
                    },
                },
                "confidence": {"type": "number"},
                "customer_name": {"type": ["string", "null"]},
            },
            "required": ["operations", "confidence", "customer_name"],
            "additionalProperties": False,
        },
    }


def compact_catalog(catalog: CatalogSnapshot) -> str:
    """Cardápio em texto enxuto — é o universo fechado do modelo."""
    lines: list[str] = []
    for product in catalog.available_products:
        descricao = f" — {product.description}" if product.description else ""
        preco = f"R$ {product.base_price:.2f}".replace(".", ",")
        lines.append(f"- {product.name} ({preco}){descricao}")
        for group in product.groups:
            nomes = ", ".join(c.name for c in group.available_complements)
            if not nomes:
                continue
            regra = f"escolhe {group.min_choices} a {group.max_choices}, sem repetir"
            lines.append(f"    [{group.name} | {regra}]: {nomes}")
    esgotados = [p.name for p in catalog.products if not p.is_available]
    if esgotados:
        lines.append("(hoje sem: " + ", ".join(esgotados) + ")")
    return "\n".join(lines) or "(cardápio vazio)"


#: O molde das instruções. `{loja}` e `{ramo}` vêm da configuração: o sistema
#: não sabe de antemão que é uma gelateria, e não deve saber.
BASE_INSTRUCTIONS_TEMPLATE = """Você é o tradutor de um atendimento de {ramo} \
brasileira ({loja}) pelo WhatsApp.

O cliente fala como quiser: solto, com erro de digitação, sem acento, em \
vários pedaços, por número, por apelido ou por "esse mesmo". Seu trabalho é \
entender e registrar em OPERAÇÕES. Quem responde ao cliente, calcula preço, \
aplica taxa e cobra é o sistema — você nunca escreve para o cliente e nunca \
decide dinheiro.

Como trabalhar:
1. Sempre chame a ferramenta registrar_operacoes.
2. ANTES de montar as operações, quebre a mensagem em PEDAÇOS — cada vírgula, \
"e", "mas", "também", ou frase encostada na outra costuma ser um pedaço \
diferente. Um pedido de item, uma pergunta, um pedido de atendente e uma \
reclamação podem chegar todos na MESMA mensagem, e cada pedaço vira UMA \
operação — nenhum pedaço fica de fora só porque outro pedaço já "resolveu" o \
plano. Dois exemplos do que dá errado quando isso não é feito:
   - "quero um médio de pistache e morango, entrega no Jardim América" tem 3 \
pedaços: o item, a forma de entrega, o endereço. É add_item + \
set_fulfillment + update_address, os três — não faça o cliente repetir o que \
já disse.
   - "e uma casquinha também, vocês têm maracujá hoje?" tem 2 pedaços: um \
pedido (a casquinha) e uma PERGUNTA (disponibilidade do maracujá). É \
add_item + answer_question, os dois — a pergunta não é decoração da frase, é \
um pedaço com operação própria, e sumiu em testes reais quando só o pedido \
foi registrado.
3. Use a SITUAÇÃO ATUAL para resolver o implícito. A situação traz os itens \
do pedido NUMERADOS — é essa numeração que vai em item_index, e ela inclui o \
item que ainda está sendo montado. "tira o médio" é remove_item com o número \
do médio naquela lista; não mande um número que não esteja lá.
4. MUDAR não é ADICIONAR. Qualquer "troca", "tira", "na verdade", "não era \
isso", "ficou errado" é update_item, replace_item, remove_item ou \
update_quantity sobre o que já existe. Criar item novo aí faz o cliente pagar \
duas vezes.
4b. E ADICIONAR não é MUDAR. "põe também", "e mais um", "quero outro", "e um \
médio de..." são add_item — mesmo que haja um item pela metade na situação. \
Se ele nomear um tamanho/produto DIFERENTE do que está sendo montado, é item \
novo, e os sabores que ele citou nessa frase são do item novo. Um produto que \
NÃO está no pedido nunca é update_quantity nem update_item: é add_item.
5. product_name e os sabores saem do CARDÁPIO, escritos exatamente como estão \
lá. Nunca invente item. Se ele pedir algo que não existe, use \
answer_question com question_topic="disponibilidade" e raw_text com o que ele \
pediu — o sistema responde que não temos e mostra o que tem.
6. Pergunta é pergunta: answer_question NÃO mexe no pedido. Depois de \
responder, o cliente continua exatamente de onde estava.
7. Ambiguidade de verdade vira ask_clarification, nunca um chute. "quero dois \
potes" pode ser 2 médios ou o GG de 1 litro: pergunte. Quantidade no plural \
sem número ("uns potes", "umas casquinhas", "quero mais alguns") também é \
ambígua — pergunte quantos em vez de assumir 1.
8. "sim" só é confirm_order se a situação disser que há um resumo final \
aguardando resposta. Em qualquer outro lugar, "sim" é concordância com a \
última pergunta que fizemos.
9. Sabor não se repete no mesmo pote. Se ele pedir um que já escolheu, não \
repita em add_flavors — e NUNCA ponha em remove_flavors um sabor que ele \
acabou de pedir nesta mensagem.
9b. question_topic tem que casar com a pergunta: pagamento/pix/cartão/dinheiro \
-> "pagamento"; taxa ou frete -> "taxa_entrega"; quanto demora -> "prazo"; que \
horas abre/fecha -> "horario"; onde fica a loja -> "endereco_loja"; se entrega \
em tal bairro -> "area_entrega"; se tem tal sabor/produto -> "disponibilidade".
10. Se a mensagem não disser nada aproveitável, mande uma operação \
no_action — não invente.
11. O HISTÓRICO É CONTEXTO, NÃO TAREFA. Tudo que aparece nas falas \
anteriores JÁ foi aplicado; o pedido de verdade é o que está na SITUAÇÃO. \
Nunca reemita um add_item de item que já está lá. "pode fechar" é \
close_order e MAIS NADA — repetir os itens da primeira mensagem faz o \
cliente pagar o pedido duas vezes.
12. NÃO PREENCHA ENDEREÇO QUE O CLIENTE NÃO DISSE. Rua, número e bairro \
só entram se estiverem escritos na mensagem dele. Faltando o bairro, \
deixe null: o sistema pergunta. Inventar bairro manda a entrega para o \
lugar errado, e "sim" respondendo "qual o bairro?" não é um bairro.
13. PEDIR O MESMO SABOR DUAS VEZES NO MESMO ITEM NUNCA É remove_item OU \
add_item DE UM ITEM NOVO. "quero os dois de pistache", "pistache e pistache" \
é update_item sobre o item que já existe, com add_flavors=["Pistache"] — o \
sistema já sabe recusar o sabor repetido sem apagar nada. Apagar o item \
inteiro por causa de um sabor repetido faz o cliente perder o pedido.
14. "MAIS UM", "OUTRO POTE" SEM TAMANHO NEM SABOR NÃO SE CHUTA copiando o \
item anterior. Ou é duplicate_item (uma cópia exata do último item, se foi \
isso que ele quis) ou é ask_clarification perguntando tamanho e sabor — \
nunca invente um add_item com produto e sabores que ele não disse nesta \
mensagem.
15. fulfillment SÓ ENTRA (set_fulfillment, ou junto de outra operação) \
QUANDO ELE DISSE COMO QUER RECEBER NESTA MENSAGEM ("entrega", "retirar", \
"vou buscar", "manda aqui"...). Não reafirme fulfillment em toda operação \
sobre o pedido só porque ele já tinha sido definido antes — isso é reafirmar \
sozinho um dado financeiro (a taxa de entrega) que ele não mencionou agora.
16. request_human NUNCA SOME quando vem junto de outra operação na mesma \
mensagem. "quero também uma casquinha, mas chama um atendente" é add_item \
E request_human, os dois — não descarte o pedido de atendente só porque a \
mensagem também mexeu no pedido.
17. "ESQUECE O ATENDENTE", "PODE VOLTAR A ME ATENDER VOCÊ MESMO", "NÃO \
PRECISA MAIS DE GENTE" significam o CONTRÁRIO de request_human — o cliente \
quer DISPENSAR o atendimento humano, não chamar de novo. Não confunda o \
verbo "atender" com o substantivo "atendente": se a frase é sobre voltar a \
falar com o bot, não devolva request_human.
18. "TROCA X POR Y" QUANDO X E Y SÃO PRODUTOS DIFERENTES (não sabor nem \
tamanho do mesmo item) é remove_item (ou update_quantity reduzindo em 1) do \
X E add_item do Y — os dois, sempre. "troca uma das casquinhas por um pote \
pequeno" com 2 casquinhas no carrinho tem que deixar 1 casquinha, não 2: \
esquecer de tirar a unidade antiga é cobrar por algo que o cliente disse que \
não quer mais.
19. NENHUMA PERGUNTA SOME quando a mensagem também tem uma edição, um \
pedido de atendente ou qualquer outra coisa. Se ele perguntou "vocês aceitam \
cartão?" no meio de uma troca de sabor, registre update_item E \
answer_question — nunca deixe a pergunta de fora do plano."""


def base_instructions() -> str:
    """As instruções já com o nome e o ramo da loja configurados."""
    settings = get_settings()
    return BASE_INSTRUCTIONS_TEMPLATE.format(
        loja=settings.store_name, ramo=settings.store_segment
    )


def build_system_blocks(
    catalog: CatalogSnapshot, situation: str = ""
) -> list[dict[str, Any]]:
    """System prompt em blocos: o do cardápio vai com cache efêmero."""
    return [
        {"type": "text", "text": base_instructions()},
        {
            "type": "text",
            "text": (
                "CARDÁPIO DE HOJE — universo fechado. É DESTA lista que saem "
                "product_name, add_flavors e remove_flavors, copiados "
                "exatamente como estão escritos aqui:\n" + compact_catalog(catalog)
            ),
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": "SITUAÇÃO ATUAL DO PEDIDO:\n"
            + (situation or "Conversa começando, nada pedido ainda."),
        },
    ]


# ---------------------------------------------------------------------------
# Cliente de LLM: o contrato e a fábrica
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


class Fala(BaseModel):
    """Uma fala do histórico recente da conversa."""

    role: str  # "cliente" | "agente"
    content: str


class LLMClient(Protocol):
    """Implementado por OpenAILLMClient e FakeLLMClient."""

    name: str

    async def interpret(
        self,
        *,
        catalog: CatalogSnapshot,
        history: Sequence[Fala],
        message: str,
        situation: str = "",
    ) -> AgentPlan:
        """Traduz a mensagem do cliente em operações sobre o pedido.

        `situation` é o retrato do pedido agora (o que está no carrinho, que
        sabores faltam, se há um resumo aguardando confirmação). É o que
        permite resolver "esse mesmo", "o segundo" e "1 e 3" sem obrigar o
        cliente a repetir nomes.
        """
        ...


@lru_cache
def get_llm_client() -> LLMClient:
    """Cliente de LLM do processo (cacheado: o SDK reaproveita a conexão)."""
    settings = get_settings()

    if not settings.fake_mode and settings.openai_api_key:
        return OpenAILLMClient(settings)

    if not settings.fake_mode:
        logger.warning(
            "FAKE_MODE=false mas OPENAI_API_KEY não está configurada; "
            "usando o LLM falso."
        )

    return FakeLLMClient()


# ---------------------------------------------------------------------------
# Cliente de LLM: OpenAI de verdade
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


def _function_tool() -> dict[str, Any]:
    """Converte o schema da tool (`input_schema`) para o formato OpenAI."""
    schema = tool_schema()
    return {
        "type": "function",
        "function": {
            "name": schema["name"],
            "description": schema["description"],
            "parameters": schema["input_schema"],
            # Structured outputs: a OpenAI passa a GARANTIR o formato. Sem
            # isto o modelo devolvia operação sem `action` e o pedido virava
            # "não entendi".
            "strict": True,
        },
    }


def _system_text(catalog: CatalogSnapshot, situation: str) -> str:
    """OpenAI recebe uma única mensagem de sistema; junta os blocos em um."""
    return "\n\n".join(
        block["text"] for block in build_system_blocks(catalog, situation)
    )


class OpenAILLMClient:
    """Implementa `LLMClient` chamando a API de Chat Completions da OpenAI."""

    name = "openai"

    def __init__(self, settings: Settings | None = None, client: Any | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = client  # injetável em teste
        self._tool = _function_tool()

    # -- infraestrutura ----------------------------------------------------

    def _ensure_client(self) -> Any:
        if self._client is None:
            from openai import AsyncOpenAI  # noqa: PLC0415 (import tardio)

            if not self._settings.openai_api_key:
                raise RuntimeError("OPENAI_API_KEY não configurada")
            self._client = AsyncOpenAI(
                api_key=self._settings.openai_api_key,
                timeout=self._settings.llm_timeout_seconds,
                # O próprio SDK tenta de novo com backoff exponencial em erro
                # passageiro (timeout, 429, 5xx) — não precisamos reescrever
                # esse laço, só dizer quantas vezes vale a pena tentar.
                max_retries=self._settings.llm_max_retries,
            )
        return self._client

    @staticmethod
    def _messages(
        system_text: str, history: Sequence[Fala], message: str
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_text}]
        for turn in history[-8:]:
            role = "user" if turn.role == "cliente" else "assistant"
            messages.append({"role": role, "content": turn.content})
        messages.append({"role": "user", "content": message})
        return messages

    # -- contrato ----------------------------------------------------------

    async def interpret(
        self,
        *,
        catalog: CatalogSnapshot,
        history: Sequence[Fala],
        message: str,
        situation: str = "",
    ) -> AgentPlan:
        inicio = time.monotonic()
        try:
            client = self._ensure_client()
            response = await client.chat.completions.create(
                model=self._settings.openai_model,
                max_tokens=self._settings.llm_max_tokens,
                messages=self._messages(
                    _system_text(catalog, situation), history, message
                ),
                tools=[self._tool],
                tool_choice={"type": "function", "function": {"name": TOOL_NAME}},
            )
        except Exception:
            # Timeout, rate limit, chave inválida: a conversa continua viva.
            logger.exception("falha ao chamar o LLM; plano vazio")
            return AgentPlan(model=self._settings.openai_model)
        finally:
            logger.info("LLM (%s) respondeu em %.2fs", self._settings.openai_model, time.monotonic() - inicio)

        return self._to_plan(response)

    # -- parsing -----------------------------------------------------------

    def _to_plan(self, response: Any) -> AgentPlan:
        usage = self._usage(response)
        model = getattr(response, "model", self._settings.openai_model)

        payload = self._tool_input(response)
        if payload is None:
            logger.warning(
                "resposta do LLM sem tool call: %r", getattr(response, "id", None)
            )
            return AgentPlan(model=model, usage=usage)

        try:
            operations = [
                self._operation(raw)
                for raw in (payload.get("operations") or [])
                if isinstance(raw, dict)
            ]
            plan = AgentPlan(
                operations=operations,
                confidence=float(payload.get("confidence") or 0.0),
                customer_name=payload.get("customer_name") or None,
            )
        except Exception:
            logger.exception("input da tool fora do contrato: %r", payload)
            return AgentPlan(model=model, usage=usage)

        plan.model = model
        plan.usage = usage
        return plan

    @classmethod
    def _operation(cls, raw: dict[str, Any]) -> Operation:
        return Operation(
            action=cls._action(raw.get("action")),
            item_index=cls._positive(raw.get("item_index")),
            product_name=raw.get("product_name") or None,
            quantity=cls._positive(raw.get("quantity")),
            add_flavors=cls._names(raw.get("add_flavors")),
            remove_flavors=cls._names(raw.get("remove_flavors")),
            fulfillment=cls._fulfillment(raw.get("fulfillment")),
            address=cls._address(raw.get("address")),
            question_topic=cls._topic(raw.get("question_topic")),
            question_text=raw.get("question_text") or None,
            raw_text=raw.get("raw_text") or None,
            clarification=raw.get("clarification") or None,
        )

    @staticmethod
    def _tool_input(response: Any) -> dict[str, Any] | None:
        choices = getattr(response, "choices", None) or []
        if not choices:
            return None
        message = getattr(choices[0], "message", None)
        tool_calls = getattr(message, "tool_calls", None) or []
        for call in tool_calls:
            function = getattr(call, "function", None)
            if getattr(function, "name", None) != TOOL_NAME:
                continue
            raw_args = getattr(function, "arguments", None)
            if not raw_args:
                continue
            try:
                payload = json.loads(raw_args)
            except json.JSONDecodeError:
                logger.warning("arguments da tool não são JSON válido: %r", raw_args)
                return None
            return payload if isinstance(payload, dict) else None
        return None

    @staticmethod
    def _action(raw: Any) -> Action:
        try:
            return Action(str(raw))
        except ValueError:
            logger.warning("ação fora do enum: %r", raw)
            return Action.NO_ACTION

    @staticmethod
    def _names(raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []
        return [str(name).strip() for name in raw if str(name).strip()]

    @staticmethod
    def _positive(raw: Any) -> int | None:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return None
        if value <= 0:
            return None
        # Teto de sanidade, não regra de negócio: a loja não tem um máximo de
        # potes por pedido, mas sem isto "quero 900000 potes" virava item de
        # carrinho com preço "correto" porém sem sentido, capaz de travar a
        # geração do Pix.
        return min(value, _QUANTIDADE_MAXIMA_POR_OPERACAO)

    @staticmethod
    def _fulfillment(raw: Any) -> str | None:
        """Só "entrega" ou "retirada" passam; o resto é ruído do modelo."""
        value = str(raw).strip().lower() if raw else ""
        return value if value in {"entrega", "retirada"} else None

    @staticmethod
    def _topic(raw: Any) -> str | None:
        value = str(raw).strip().lower() if raw else ""
        if not value:
            return None
        return value if value in QUESTION_TOPICS else "outro"

    @staticmethod
    def _address(raw: Any) -> Address | None:
        if not isinstance(raw, dict):
            return None
        address = Address(**{k: v for k, v in raw.items() if v})
        return address if address.model_dump(exclude_none=True) else None

    @staticmethod
    def _usage(response: Any) -> dict[str, Any] | None:
        """Tokens gastos, inclusive os de cache automático da OpenAI."""
        usage = getattr(response, "usage", None)
        if usage is None:
            return None
        data = {
            "input_tokens": getattr(usage, "prompt_tokens", None),
            "output_tokens": getattr(usage, "completion_tokens", None),
        }
        details = getattr(usage, "prompt_tokens_details", None)
        cached = getattr(details, "cached_tokens", None) if details else None
        if cached:
            data["cache_read_input_tokens"] = cached
        return {k: v for k, v in data.items() if v is not None}


# ---------------------------------------------------------------------------
# Cliente de LLM: o falso, para rodar sem chave
# ---------------------------------------------------------------------------

_SAUDACOES = ("oi", "ola", "bom dia", "boa tarde", "boa noite", "opa", "eai", "e ai")
_CARDAPIO = ("cardapio", "menu", "opcoes", "que sabores", "quais sabores")
_CARRINHO = ("carrinho", "meu pedido", "o que eu pedi")
_TOTAL = ("total", "quanto deu", "quanto ficou", "quanto fica no total")
_HUMANO = ("atendente", "humano", "pessoa", "alguem do time")
_CANCELAR = ("cancela", "cancelar", "desisto", "deixa pra la")
_FECHAR = ("fechar", "finalizar", "so isso", "pode mandar", "ta certo", "e isso")
_CONFIRMA = ("sim", "isso", "confirmo", "confirmar", "certo", "perfeito", "pode ser")
_NEGA = ("nao", "nao quero", "chega")
_RETIRADA = ("retirada", "retirar", "buscar", "passo ai", "vou ai")
_ENTREGA = ("entrega", "entregar", "delivery", "manda aqui", "em casa")
_REMOVER = ("tira", "tirar", "remove", "remover", "apaga", "apagar", "sem o")
_PERGUNTA = ("?", "quanto custa", "voces tem", "vcs tem", "tem ", "que horas", "aceita")
#: Marcas de correção — o cliente está consertando o que já pediu.
_CORRIGE = ("na verdade", "muda", "mudar", "troca", "trocar", "queria", "era pra ser")


def _tem(texto: str, termos: Sequence[str]) -> bool:
    """Casa por palavra inteira.

    Por substring, "vou retirar na loja" casava com "tirar" e o cliente que
    ia buscar o pedido tinha um item removido junto.
    """
    for termo in termos:
        if " " in termo or termo == "?":
            if termo in texto:
                return True
        elif re.search(rf"\b{re.escape(termo)}\b", texto):
            return True
    return False


class FakeLLMClient:
    """Implementa `LLMClient` sem rede."""

    name = "fake"

    async def interpret(
        self,
        *,
        catalog: CatalogSnapshot,
        history: Sequence[Fala] = (),
        message: str,
        situation: str = "",
    ) -> AgentPlan:
        texto = normalize(message)
        ops: list[Operation] = []

        if not texto.strip():
            return AgentPlan(operations=[Operation(action=Action.NO_ACTION)])

        # Ordem importa: o que é comando explícito vem antes do que é pedido.
        if _tem(texto, _HUMANO):
            return self._plan([Operation(action=Action.REQUEST_HUMAN)])
        if _tem(texto, _CANCELAR):
            return self._plan([Operation(action=Action.CANCEL_ORDER)])

        endereco = self._address(message)
        if endereco is not None:
            ops.append(Operation(action=Action.UPDATE_ADDRESS, address=endereco))

        if _tem(texto, _RETIRADA):
            ops.append(Operation(action=Action.SET_FULFILLMENT, fulfillment="retirada"))
        elif _tem(texto, _ENTREGA) and "quanto" not in texto:
            ops.append(Operation(action=Action.SET_FULFILLMENT, fulfillment="entrega"))

        if _tem(texto, _REMOVER):
            ops.append(self._remove(texto, catalog))

        troca = self._swap(message, catalog)
        if troca is not None:
            ops.append(troca)

        if not ops or not any(
            op.action in {Action.REMOVE_ITEM, Action.UPDATE_ITEM} for op in ops
        ):
            item = self._item(message, texto, catalog, situation)
            if item is not None:
                ops.append(item)

        if _tem(texto, _CARDAPIO):
            ops.append(Operation(action=Action.SHOW_MENU))
        if _tem(texto, _CARRINHO):
            ops.append(Operation(action=Action.SHOW_CART))
        if _tem(texto, _TOTAL):
            ops.append(Operation(action=Action.SHOW_TOTAL))

        if _tem(texto, _FECHAR):
            ops.append(Operation(action=Action.CLOSE_ORDER))
        elif not ops and _tem(texto, _CONFIRMA):
            ops.append(
                Operation(action=Action.CONFIRM_ORDER)
                if "resumo final" in situation.lower()
                or "esperando o cliente confirmar" in situation.lower()
                else Operation(action=Action.CLOSE_ORDER)
            )
        elif not ops and _tem(texto, _NEGA):
            ops.append(Operation(action=Action.CLOSE_ORDER))

        if not ops and _tem(texto, _SAUDACOES):
            ops.append(Operation(action=Action.NO_ACTION))

        if not ops and "?" in message:
            ops.append(
                Operation(
                    action=Action.ANSWER_QUESTION,
                    question_topic="outro",
                    question_text=message,
                )
            )

        if not ops:
            ops.append(Operation(action=Action.NO_ACTION))

        return self._plan(ops)

    # -- pedaços -----------------------------------------------------------

    @staticmethod
    def _plan(ops: list[Operation]) -> AgentPlan:
        # `usage` zerado, e não ausente: o painel e o teste de auditoria
        # esperam a mesma forma que a OpenAI devolve.
        return AgentPlan(
            operations=ops,
            confidence=0.9,
            model="fake",
            usage={"input_tokens": 0, "output_tokens": 0},
        )

    @staticmethod
    def _address(message: str) -> Address | None:
        """"Rua X, 123, Bairro" — o formato que as pessoas mandam."""
        if not re.search(r"\d", message):
            return None
        partes = [p.strip() for p in message.split(",") if p.strip()]
        if len(partes) < 2:
            return None
        rua = partes[0]
        if not re.match(r"^(rua|av|avenida|travessa|alameda|r\.)", normalize(rua)):
            return None
        numero = next((p for p in partes[1:] if re.fullmatch(r"\d+[a-zA-Z]?", p)), None)
        bairro = next(
            (p for p in partes[1:] if not re.fullmatch(r"\d+[a-zA-Z]?", p)), None
        )
        return Address(rua=rua, numero=numero, bairro=bairro)

    @staticmethod
    def _remove(texto: str, catalog: CatalogSnapshot) -> Operation:
        indice = None
        numeros = re.findall(r"\d+", texto)
        if numeros:
            indice = int(numeros[0])
        ordinais = {"primeiro": 1, "segundo": 2, "terceiro": 3, "ultimo": 99}
        for palavra, valor in ordinais.items():
            if palavra in texto:
                indice = valor
                break

        sabores: list[str] = []
        for pedaco in split_queries(texto):
            for produto in catalog.available_products:
                for grupo in produto.groups:
                    match = resolve_complement(pedaco, grupo)
                    if match.ok and match.complement.name not in sabores:
                        sabores.append(match.complement.name)
        if sabores:
            return Operation(action=Action.REMOVE_ITEM, remove_flavors=sabores)
        return Operation(action=Action.REMOVE_ITEM, item_index=indice)

    @staticmethod
    def _swap(message: str, catalog: CatalogSnapshot) -> Operation | None:
        """"troca X por Y" — a operação que antes virava item novo."""
        texto = normalize(message)
        match = re.search(r"troca(?:r)?\s+(?:o\s+|a\s+)?(.+?)\s+por\s+(.+)", texto)
        if not match:
            return None
        antigo, novo = match.group(1).strip(), match.group(2).strip()

        def nome_de_sabor(query: str) -> str | None:
            for produto in catalog.available_products:
                for grupo in produto.groups:
                    achado = resolve_complement(query, grupo)
                    if achado.ok:
                        return achado.complement.name
            return None

        sai, entra = nome_de_sabor(antigo), nome_de_sabor(novo)
        if sai or entra:
            return Operation(
                action=Action.UPDATE_ITEM,
                remove_flavors=[sai] if sai else [],
                add_flavors=[entra] if entra else [],
            )

        produto = resolve_product(novo, catalog)
        if produto.ok:
            return Operation(action=Action.REPLACE_ITEM, product_name=produto.product.name)
        return None

    @staticmethod
    def _item(
        message: str, texto: str, catalog: CatalogSnapshot, situation: str
    ) -> Operation | None:
        """Produto e/ou sabores citados na mensagem."""
        montando = "em montagem" in normalize(situation)
        corrigindo = _tem(texto, _CORRIGE)

        # Sabores primeiro: durante a montagem é o que o cliente costuma dizer.
        sabores: list[str] = []
        grupos = [
            g
            for p in catalog.available_products
            for g in p.groups
            if g.available_complements
        ]
        for pedaco in split_queries(message):
            for grupo in grupos:
                achado = resolve_complement(pedaco, grupo)
                if achado.ok and achado.complement.name not in sabores:
                    sabores.append(achado.complement.name)
                    break

        produto = resolve_product(message, catalog)
        if produto.ok:
            # "na verdade eu queria o de 240ml" no meio da montagem é TROCAR o
            # tamanho do item que está aberto, não começar outro pote.
            action = (
                Action.REPLACE_ITEM if (montando and corrigindo) else Action.ADD_ITEM
            )
            return Operation(
                action=action,
                product_name=produto.product.name,
                add_flavors=sabores,
                quantity=FakeLLMClient._quantity(texto),
            )
        if produto.status is MatchStatus.AMBIGUOUS:
            return Operation(
                action=Action.ASK_CLARIFICATION,
                clarification="Qual tamanho você quer?",
            )

        if sabores:
            action = Action.UPDATE_ITEM if montando else Action.ADD_ITEM
            return Operation(action=action, add_flavors=sabores)

        if produto.status is MatchStatus.UNAVAILABLE:
            return Operation(action=Action.ADD_ITEM, raw_text=message)

        if _tem(texto, _PERGUNTA):
            return Operation(
                action=Action.ANSWER_QUESTION,
                question_topic="disponibilidade",
                question_text=message,
                raw_text=message,
            )
        return None

    @staticmethod
    def _quantity(texto: str) -> int | None:
        match = re.search(r"\b(\d+)\s*(x|potes?|cascoes?|unidades?)\b", texto)
        if match:
            return int(match.group(1))
        for palavra, valor in {"dois": 2, "duas": 2, "tres": 3}.items():
            if f"{palavra} " in texto:
                return valor
        return None


# ---------------------------------------------------------------------------
# WhatsApp: normalização de telefone e os canais
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Trava de contatos
# ---------------------------------------------------------------------------

def _only_digits(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def _normalize_br(digits: str) -> str:
    """Põe o mesmo celular brasileiro sempre na mesma forma.

    O WhatsApp entrega o número ora com o nono dígito (5569993061196), ora sem
    (556993061196), e o lojista digita com "+", espaço e traço. A diferença
    fica no MEIO do número, então comparar por sufixo não resolve: o que
    identifica a linha é DDI + DDD + os 8 últimos dígitos. Fora do formato
    brasileiro (12 ou 13 dígitos começando em 55) devolvemos como está, e a
    comparação passa a ser literal — melhor recusar um número exótico do que
    deixar entrar um parecido.
    """
    if digits.startswith("55") and len(digits) in (12, 13):
        return digits[:4] + digits[-8:]
    return digits


def phone_allowed(phone: str, settings: Settings | None = None) -> bool:
    """O agente pode falar com este número?

    Com `ALLOWED_PHONES` vazia a resposta é sempre sim — é o estado normal de
    produção. Preenchida, o sistema vira uma sala fechada: serve para deixar a
    loja no ar e testar pelo WhatsApp de verdade sem risco de atender um
    cliente pela metade.
    """
    settings = settings or get_settings()
    if not settings.allowed_phones:
        return True

    digits = _only_digits(phone)
    if len(digits) < 8:
        return False

    alvo = _normalize_br(digits)
    return any(_normalize_br(a) == alvo for a in settings.allowed_phones)


# ---------------------------------------------------------------------------
# Contrato
# ---------------------------------------------------------------------------

class InboundMessage(BaseModel):
    """Mensagem recebida, já normalizada e independente de canal."""

    phone: str                       # E.164 sem "+": 5511999998888
    text: str
    provider_message_id: str | None = None
    profile_name: str | None = None
    timestamp: datetime | None = None
    #: True quando a própria conta conectada enviou (lojista respondendo pelo
    #: celular, ou eco do que o bot mandou). Não passa pela IA/máquina de
    #: estados — só é registrada no histórico para o painel espelhar o chat.
    from_me: bool = False
    #: "audio" quando esta mensagem é uma nota de voz sem texto ainda — `text`
    #: vem vazio e `resolve_audio_message` o preenche com a transcrição. None
    #: em qualquer outro caso (é a maioria).
    media_type: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class ChannelAdapter(Protocol):
    """Implementado por EvolutionAdapter e ConsoleAdapter."""

    name: str

    async def send_text(self, to: str, text: str) -> str | None:
        """Envia texto e devolve o id da mensagem no provedor, se houver."""
        ...

    def parse_webhook(self, payload: dict[str, Any]) -> list[InboundMessage]:
        """Extrai as mensagens de um payload de webhook do provedor."""
        ...


# ---------------------------------------------------------------------------
# WhatsApp de verdade
# ---------------------------------------------------------------------------

class EvolutionAdapter:
    """Implementa `ChannelAdapter` para a Evolution API."""

    name = "whatsapp"

    def __init__(
        self, settings: Settings | None = None, client: httpx.AsyncClient | None = None
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client

    @property
    def _send_url(self) -> str:
        base = self._settings.evolution_api_url.rstrip("/")
        instance = self._settings.evolution_instance
        return f"{base}/message/sendText/{instance}"

    async def send_text(self, to: str, text: str) -> str | None:
        """Envia texto e devolve o id da mensagem na Evolution API (ou None se falhou).

        Não sai daqui nada instantâneo: o envio espera a vez no `throttle` e
        chega à Evolution API pedindo "digitando..." por um tempo proporcional
        ao tamanho do texto. O porquê está em a seção de ritmo de envio deste arquivo.
        """
        if not self._settings.evolution_api_key:
            logger.warning(
                "Evolution API não configurada; mensagem não enviada para %s", to
            )
            return None

        # Segundo cadeado da trava de contatos. O primeiro está na entrada do
        # webhook; este existe porque é o que garante que nenhum caminho do
        # sistema — nem o aviso de Pix pago, nem um bug futuro — consiga mandar
        # mensagem para um terceiro enquanto a loja está em teste.
        if not phone_allowed(to, self._settings):
            logger.warning(
                "envio bloqueado: %s fora de ALLOWED_PHONES", to
            )
            return None

        await throttle.acquire(to)
        delay_ms = typing_delay_ms(text)

        payload = {
            "number": to,
            "text": text,
            # A Evolution segura a mensagem por `delay` ms exibindo o status de
            # "digitando..." antes de soltar — é ela que faz a pausa, não nós.
            "delay": delay_ms,
            "presence": "composing",
            # Prévia de link é uma requisição extra feita pelo número e um
            # traço a mais de automação; o bot manda copia-e-cola do Pix, não
            # link clicável.
            "linkPreview": False,
        }
        headers = {
            "apikey": self._settings.evolution_api_key,
            "Content-Type": "application/json; charset=utf-8",
        }
        # A chamada só retorna depois que o delay correu no servidor.
        timeout = delay_ms / 1000 + 20.0

        try:
            if self._client is not None:
                response = await self._client.post(self._send_url, json=payload, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(self._send_url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            return (data.get("key") or {}).get("id")
        except httpx.HTTPStatusError as e:
            logger.error(
                "Evolution API erro %s ao enviar para %s: %s",
                e.response.status_code,
                to,
                e.response.text[:200] if e.response.text else "(sem corpo)",
            )
            raise
        except Exception as e:
            logger.exception("falha ao conectar com Evolution API para %s: %s", to, str(e))
            raise

    async def fetch_media_base64(
        self, message_key: dict[str, Any]
    ) -> tuple[bytes, str] | None:
        """Baixa o conteúdo de uma mídia (áudio, por ora) a partir da chave da mensagem.

        A Evolution não manda o arquivo dentro do webhook, só os metadados e a
        chave (`key`) que identifica a mensagem — é essa chave que se devolve
        para pedir o conteúdo. Nunca levanta: Evolution fora do ar não pode
        derrubar o turno, só faz o áudio virar "não consegui ouvir".

        Uma tentativa extra depois de 1s: é uma chamada de rede a mais que a
        Evolution não fazia antes (baixar mídia, e não só mandar texto), e uma
        falha passageira aqui custaria uma nota de voz inteira sem resposta.
        """
        if not self._settings.evolution_api_key:
            logger.warning("Evolution API não configurada; não é possível baixar mídia")
            return None

        base = self._settings.evolution_api_url.rstrip("/")
        url = f"{base}/chat/getBase64FromMediaMessage/{self._settings.evolution_instance}"
        headers = {
            "apikey": self._settings.evolution_api_key,
            "Content-Type": "application/json; charset=utf-8",
        }
        payload = {"message": {"key": message_key}, "convertToMp4": False}

        data: dict[str, Any] | None = None
        for tentativa in range(2):
            try:
                if self._client is not None:
                    response = await self._client.post(url, json=payload, headers=headers)
                else:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                break
            except Exception:
                if tentativa == 0:
                    await asyncio.sleep(1.0)
                    continue
                logger.exception("falha ao baixar mídia da Evolution API")
                return None

        raw_b64 = (data or {}).get("base64")
        if not raw_b64:
            logger.warning("Evolution API não devolveu base64 para a mídia")
            return None
        if raw_b64.startswith("data:") and "," in raw_b64:
            raw_b64 = raw_b64.split(",", 1)[1]  # já visto vir como data URI

        try:
            audio_bytes = base64.b64decode(raw_b64)
        except (ValueError, TypeError):
            logger.warning("base64 inválido devolvido pela Evolution API")
            return None

        mimetype = data.get("mimetype") or "audio/ogg"
        return audio_bytes, mimetype

    # -- webhook -----------------------------------------------------------

    def parse_webhook(self, payload: dict[str, Any]) -> list[InboundMessage]:
        """Extrai mensagens de texto do evento `messages.upsert`; ignora o resto."""
        if payload.get("event") != "messages.upsert":
            return []

        data = payload.get("data")
        entries: list[Any] = data if isinstance(data, list) else [data] if data else []

        messages: list[InboundMessage] = []
        for raw in entries:
            message = self._to_inbound(raw or {})
            if message is not None:
                messages.append(message)
        return messages

    @staticmethod
    def _to_inbound(raw: dict[str, Any]) -> InboundMessage | None:
        key = raw.get("key") or {}
        remote_jid = key.get("remoteJid") or ""

        # Só processamos chat individual (sufixo "@s.whatsapp.net"). O número
        # ficou pareado com o WhatsApp da loja, então grupos (`@g.us`), listas
        # de transmissão/status (`@broadcast`) e canais (`@newsletter`) também
        # chegam como messages.upsert — sem esse filtro, qualquer mensagem de
        # terceiros num grupo viraria "pedido" (ou, no caso de fromMe, entraria
        # no histórico do painel como se fosse uma resposta 1:1).
        if not remote_jid.endswith("@s.whatsapp.net"):
            logger.info("mensagem fora de chat individual ignorada (jid=%s)", remote_jid)
            return None

        # remoteJid pode vir com sufixo de device multi-aparelho ("<numero>:<n>@...");
        # sem remover, o mesmo cliente vira duas conversas diferentes conforme o
        # aparelho usado.
        phone = remote_jid.split("@")[0].split(":")[0]
        if not phone:
            return None

        message_body = raw.get("message") or {}
        text = EvolutionAdapter._text_of(raw)
        media_type = None
        if not text:
            if EvolutionAdapter._is_audio(message_body):
                # Sem texto, mas é uma nota de voz: `resolve_audio_message`
                # baixa e transcreve antes do turno seguir — não se ignora.
                media_type = "audio"
            else:
                logger.info("mensagem sem texto ignorada (jid=%s)", key.get("remoteJid"))
                return None

        return InboundMessage(
            phone=phone,
            text=text or "",
            media_type=media_type,
            provider_message_id=key.get("id"),
            profile_name=raw.get("pushName"),
            timestamp=EvolutionAdapter._timestamp(raw.get("messageTimestamp")),
            # fromMe = eco do bot ou resposta manual do lojista pelo celular.
            # Não descartamos mais: o runner trata separado (vira só histórico,
            # nunca aciona IA/máquina de estados) para o painel espelhar o chat
            # inteiro do número da loja, não só o que passou pelo bot.
            from_me=bool(key.get("fromMe")),
            raw=raw,
        )

    @staticmethod
    def _text_of(raw: dict[str, Any]) -> str | None:
        """Texto puro ou a resposta de um botão/lista interativa do Baileys."""
        message = raw.get("message") or {}
        if message.get("conversation"):
            return message["conversation"]

        extended = message.get("extendedTextMessage") or {}
        if extended.get("text"):
            return extended["text"]

        buttons_reply = message.get("buttonsResponseMessage") or {}
        if buttons_reply.get("selectedDisplayText"):
            return buttons_reply["selectedDisplayText"]

        list_reply = message.get("listResponseMessage") or {}
        single_select = list_reply.get("singleSelectReply") or {}
        return list_reply.get("title") or single_select.get("selectedRowId")

    @staticmethod
    def _is_audio(message: dict[str, Any]) -> bool:
        """Nota de voz e áudio enviado como arquivo chegam os dois em `audioMessage`."""
        return bool(message.get("audioMessage"))

    @staticmethod
    def _timestamp(raw: Any) -> datetime | None:
        try:
            return datetime.fromtimestamp(int(raw), tz=timezone.utc)
        except (TypeError, ValueError):
            return None


# ---------------------------------------------------------------------------
# Áudio: ouvir a nota de voz do cliente
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


class AudioTranscriber(Protocol):
    """Implementado por OpenAIAudioTranscriber e FakeAudioTranscriber."""

    name: str

    async def transcribe(self, *, audio: bytes, mimetype: str) -> str | None:
        """O que foi dito no áudio, ou None se não deu para transcrever."""
        ...


class OpenAIAudioTranscriber:
    """Implementa `AudioTranscriber` chamando a API de transcrição da OpenAI."""

    name = "openai"

    def __init__(self, settings: Settings | None = None, client: Any | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = client  # injetável em teste

    def _ensure_client(self) -> Any:
        if self._client is None:
            from openai import AsyncOpenAI  # noqa: PLC0415 (import tardio)

            if not self._settings.openai_api_key:
                raise RuntimeError("OPENAI_API_KEY não configurada")
            self._client = AsyncOpenAI(
                api_key=self._settings.openai_api_key,
                timeout=self._settings.llm_timeout_seconds,
                # Mesmo backoff automático do cliente de chat — ver o
                # comentário em OpenAILLMClient._ensure_client.
                max_retries=self._settings.llm_max_retries,
            )
        return self._client

    async def transcribe(self, *, audio: bytes, mimetype: str) -> str | None:
        inicio = time.monotonic()
        try:
            client = self._ensure_client()
            response = await client.audio.transcriptions.create(
                model=self._settings.openai_transcribe_model,
                # O nome do arquivo é sempre "audio.ogg", e não o que a
                # Evolution reportou: nota de voz do WhatsApp é ogg/opus, e a
                # extensão real (.oga) já foi vista sendo rejeitada por
                # modelos de transcrição mais novos com um 400 que não tem
                # nada a ver com o conteúdo do áudio.
                file=("audio.ogg", audio, "audio/ogg"),
            )
        except Exception:
            logger.exception("falha ao transcrever áudio")
            return None
        finally:
            logger.info("transcrição de áudio em %.2fs", time.monotonic() - inicio)
        texto = getattr(response, "text", None)
        return texto.strip() if texto else None


class FakeAudioTranscriber:
    """Implementa `AudioTranscriber` sem rede: decodifica os bytes como texto.

    Em FAKE_MODE e nos testes, "gravar um áudio" É escrever a frase e mandar
    os bytes dela — não existe voz de verdade para reconhecer, e não faz
    sentido fingir que existe.
    """

    name = "fake"

    async def transcribe(self, *, audio: bytes, mimetype: str) -> str | None:
        try:
            texto = audio.decode("utf-8").strip()
        except UnicodeDecodeError:
            return None
        return texto or None


@lru_cache
def get_audio_transcriber() -> AudioTranscriber | None:
    """Transcritor do processo, ou None quando não há como ouvir áudio.

    Espelha `get_llm_client`: em FAKE_MODE usa o falso; sem chave em produção
    devolve None — o áudio simplesmente não é ouvido, e quem decide o que
    dizer ao cliente é `handle_inbound`, nunca esta função tentando decodificar
    bytes de voz de verdade como se fossem texto.
    """
    settings = get_settings()
    if settings.fake_mode:
        return FakeAudioTranscriber()
    if settings.openai_api_key:
        return OpenAIAudioTranscriber(settings)
    logger.warning(
        "FAKE_MODE=false mas OPENAI_API_KEY não está configurada; "
        "áudio do cliente não será transcrito."
    )
    return None


async def resolve_audio_message(
    message: InboundMessage,
    *,
    adapter: EvolutionAdapter,
    transcriber: AudioTranscriber | None,
) -> InboundMessage:
    """Baixa e transcreve uma nota de voz; texto vazio quando não foi possível.

    Nunca levanta: Evolution fora do ar, chave da OpenAI ausente, áudio longo
    demais ou corrompido viram texto vazio — e quem decide o que fazer com
    isso é `handle_inbound`. Esta função nunca inventa uma transcrição.
    """
    if transcriber is None:
        return message.model_copy(update={"text": ""})

    audio_message = ((message.raw.get("message") or {}).get("audioMessage")) or {}
    duracao = audio_message.get("seconds")
    limite = get_settings().audio_max_seconds
    if isinstance(duracao, (int, float)) and duracao > limite:
        logger.info(
            "áudio de %ss acima do limite de %ss; não transcrito", duracao, limite
        )
        return message.model_copy(update={"text": ""})

    fetched = await adapter.fetch_media_base64(message.raw.get("key") or {})
    if fetched is None:
        return message.model_copy(update={"text": ""})

    audio, mimetype = fetched
    texto = await transcriber.transcribe(audio=audio, mimetype=mimetype)
    return message.model_copy(update={"text": texto or ""})


# ---------------------------------------------------------------------------
# Canal em memória (FAKE_MODE, simulador, CLI e testes)
# ---------------------------------------------------------------------------

class ConsoleAdapter:
    """Implementa `ChannelAdapter` guardando as respostas numa lista."""

    name = "console"

    #: Teto do histórico: em modo falso este adapter é um singleton de processo
    #: e viveria para sempre acumulando mensagens.
    MAX_HISTORY = 500

    def __init__(self, echo: bool = False) -> None:
        #: Todas as respostas enviadas, na ordem: [(telefone, texto), ...]
        self.sent: list[tuple[str, str]] = []
        self._echo = echo

    async def send_text(self, to: str, text: str) -> str | None:
        self.sent.append((to, text))
        if len(self.sent) > self.MAX_HISTORY:
            del self.sent[: -self.MAX_HISTORY]
        if self._echo:
            print(text)
        return None

    def parse_webhook(self, payload: dict[str, Any]) -> list[InboundMessage]:
        """Aceita o formato simples do simulador: {"phone": ..., "text": ...}."""
        phone = payload.get("phone")
        text = payload.get("text")
        if not phone or not text:
            return []
        return [InboundMessage(phone=str(phone), text=str(text), raw=payload)]

    def replies_for(self, phone: str) -> list[str]:
        """Usado pelos testes e pelo simulador para ler o que o bot respondeu."""
        return [text for to, text in self.sent if to == phone]


# ---------------------------------------------------------------------------
# Escolha do canal
# ---------------------------------------------------------------------------

#: Canal em memória compartilhado do processo — o simulador lê daqui.
_console = ConsoleAdapter()


@lru_cache
def get_channel_adapter(channel_name: str = "whatsapp") -> ChannelAdapter:
    """Adapter do canal pedido. Em FAKE_MODE tudo vai para o console."""
    if channel_name == "console" or get_settings().fake_mode:
        return _console

    return EvolutionAdapter(get_settings())


# ---------------------------------------------------------------------------
# Juntar balões seguidos antes de pensar
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

#: Quem processa o turno já agrupado (o webhook passa um que abre sessão de
#: banco própria — a original morre junto com a request).
Handler = Callable[[InboundMessage], Awaitable[None]]


@dataclass
class _Buffer:
    """Mensagens de um telefone esperando o prazo vencer."""

    last: InboundMessage
    texts: list[str] = field(default_factory=list)
    deadline: float = 0.0
    #: ids já somados a `texts` — ver `submit`.
    seen_ids: set[str] = field(default_factory=set)


_buffers: dict[str, _Buffer] = {}
#: Referência forte para as tasks: sem isso o coletor de lixo do asyncio pode
#: recolher uma task em voo e o cliente fica sem resposta.
_tasks: set[asyncio.Task[None]] = set()

#: Um cadeado por telefone: o turno de UM cliente nunca roda duas vezes ao
#: mesmo tempo. Sem isto, uma mensagem que chega depois que a janela de
#: agrupamento fechou mas ANTES do turno anterior terminar (a chamada ao LLM
#: mais a espera do ritmo de envio somam fácil mais que os 3s padrão de
#: `WA_DEBOUNCE_SECONDS`) dispara um SEGUNDO `handle_inbound` sobre a MESMA
#: conversa — os dois leem o mesmo estado do banco, e quem salva por último
#: apaga silenciosamente o que o outro mudou.
_phone_locks: dict[str, asyncio.Lock] = {}
#: Teto de memória, no mesmo espírito do `_last_by_phone` do `Throttle`: o
#: processo fica no ar por meses e atende milhares de números ao longo do tempo.
_MAX_PHONE_LOCKS = 2_000


def _lock_for(phone: str) -> asyncio.Lock:
    """O cadeado deste telefone, criando se for a primeira vez."""
    lock = _phone_locks.get(phone)
    if lock is not None:
        return lock
    if len(_phone_locks) >= _MAX_PHONE_LOCKS:
        # Só descarta cadeados livres — um em uso não pode desaparecer
        # debaixo de quem já está esperando por ele.
        livres = [p for p, cadeado in _phone_locks.items() if not cadeado.locked()]
        for p in livres[: len(_phone_locks) - _MAX_PHONE_LOCKS + 1]:
            del _phone_locks[p]
    lock = asyncio.Lock()
    _phone_locks[phone] = lock
    return lock


def _merged(buffer: _Buffer) -> InboundMessage:
    """Os balões viram um texto só, guardando o id da ÚLTIMA mensagem.

    O id é o que garante idempotência lá no `runner`; usar o da última faz a
    reentrega de qualquer balão anterior ainda ser reconhecida como nova, mas
    a reentrega do turno inteiro (o caso comum) ser descartada.
    """
    return buffer.last.model_copy(update={"text": "\n".join(buffer.texts)})


async def submit(message: InboundMessage, handler: Handler) -> None:
    """Enfileira a mensagem; o handler roda quando o cliente parar de digitar."""
    window = get_settings().wa_debounce_seconds
    if window <= 0:  # agrupamento desligado: comportamento antigo, turno a turno
        async with _lock_for(message.phone):
            await handler(message)
        return

    buffer = _buffers.get(message.phone)
    if (
        buffer is not None
        and message.provider_message_id
        and message.provider_message_id in buffer.seen_ids
    ):
        # Reentrega do gateway (retry de webhook) de um balão que já está
        # NESTA janela de agrupamento: sem isto o texto entrava de novo no
        # buffer antes do turno rodar, e o LLM lia a mesma frase repetida
        # como se o cliente tivesse dito duas vezes. A reentrega de um balão
        # de um turno ANTERIOR já processado é outro caso — esse é pego pela
        # dedupe de `already_seen` lá no `handle_inbound`.
        return

    if buffer is None:
        buffer = _Buffer(last=message)
        _buffers[message.phone] = buffer
        task = asyncio.create_task(_process_when_idle(message.phone, handler))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    else:
        buffer.last = message

    if message.provider_message_id:
        buffer.seen_ids.add(message.provider_message_id)
    buffer.texts.append(message.text)
    buffer.deadline = time.monotonic() + window


async def _process_when_idle(phone: str, handler: Handler) -> None:
    """Espera o silêncio do cliente e roda o turno uma única vez."""
    while True:
        buffer = _buffers.get(phone)
        if buffer is None:  # ninguém para processar (só acontece em teardown)
            return
        remaining = buffer.deadline - time.monotonic()
        if remaining <= 0:
            break
        await asyncio.sleep(remaining)

    buffer = _buffers.pop(phone, None)
    if buffer is None:
        return

    async with _lock_for(phone):
        try:
            await handler(_merged(buffer))
        except Exception:
            # Um turno com problema não pode derrubar a task nem calar o próximo.
            logger.exception("falha ao processar turno de %s", phone)


async def drain() -> None:
    """Espera tudo que está em voo — usado nos testes e no shutdown."""
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)


# ---------------------------------------------------------------------------
# A sessão da conversa e sua persistência
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

DEFAULT_CHANNEL = "whatsapp"


@dataclass(slots=True)
class ConversationSession:
    """A linha de `conversations` já desserializada em objetos de domínio."""

    id: UUID
    phone: str
    channel: str
    state: ConversationState
    slots: dict[str, Any] = field(default_factory=dict)
    cart: Cart = field(default_factory=Cart)
    customer_id: UUID | None = None
    active_order_id: UUID | None = None
    handoff: bool = False
    fail_count: int = 0

    def reset_flow(self) -> None:
        """Zera o pedido em construção mantendo a identidade do cliente."""
        self.state = ConversationState.CONVERSANDO
        self.slots = {}
        self.cart = Cart()
        self.active_order_id = None
        self.fail_count = 0

    def touch_handoff(self) -> None:
        """Marca agora como o último sinal de vida do atendimento humano.

        Chamado quando o bot escala e de novo a cada resposta que a loja digita
        pelo celular: enquanto houver gente falando, o bot continua calado.
        """
        self.slots["handoff_since"] = datetime.now(timezone.utc).isoformat()

    def handoff_idle_minutes(self) -> float:
        """Minutos desde o último sinal do atendimento humano.

        Sem marca (conversa que entrou em handoff antes desta versão) devolve
        infinito: melhor o bot reassumir do que deixar o cliente sem ninguém.
        """
        raw = self.slots.get("handoff_since")
        if not isinstance(raw, str):
            return float("inf")
        try:
            since = datetime.fromisoformat(raw)
        except ValueError:
            return float("inf")
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - since).total_seconds() / 60.0


# ---------------------------------------------------------------------------
# Serialização do JSONB
# ---------------------------------------------------------------------------

def _load_cart(raw: Any) -> Cart:
    """Aceita tanto `[itens]` (default do schema) quanto `{"items": [...]}`."""
    if raw is None or raw == "":
        return Cart()
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("cart JSONB inválido, reiniciando carrinho")
            return Cart()
    try:
        if isinstance(raw, list):
            return Cart(items=raw)
        if isinstance(raw, dict):
            return Cart(items=raw.get("items", []))
    except Exception:  # dado antigo/incompatível não pode derrubar a conversa
        logger.warning("cart JSONB incompatível, reiniciando carrinho", exc_info=True)
    return Cart()


def _dump_cart(cart: Cart) -> str:
    """Serializa como lista de itens — é o formato do default '[]' da coluna."""
    payload = json.loads(cart.model_dump_json())
    return json.dumps(payload["items"], ensure_ascii=False)


def _load_slots(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return dict(raw) if isinstance(raw, dict) else {}


def _dump_slots(slots: dict[str, Any]) -> str:
    return json.dumps(slots, ensure_ascii=False, default=str)


def _as_state(raw: Any) -> ConversationState:
    """Aceita os nomes antigos: há conversas gravadas antes da redução."""
    return parse_state(str(raw))


def _as_uuid(raw: Any) -> UUID | None:
    if raw is None:
        return None
    return raw if isinstance(raw, UUID) else UUID(str(raw))


def _expires_at() -> datetime:
    ttl = get_settings().session_ttl_minutes
    return datetime.now(timezone.utc) + timedelta(minutes=ttl)


# ---------------------------------------------------------------------------
# Leitura / escrita
# ---------------------------------------------------------------------------

_SELECT = """
    SELECT id, phone, channel, state, slots, cart, customer_id,
           active_order_id, handoff, fail_count, expires_at
    FROM conversations
"""


def _row_to_session(row: Any) -> ConversationSession:
    mapping = row._mapping if hasattr(row, "_mapping") else row
    return ConversationSession(
        id=_as_uuid(mapping["id"]),  # type: ignore[arg-type]
        phone=mapping["phone"],
        channel=mapping["channel"],
        state=_as_state(mapping["state"]),
        slots=_load_slots(mapping["slots"]),
        cart=_load_cart(mapping["cart"]),
        customer_id=_as_uuid(mapping["customer_id"]),
        active_order_id=_as_uuid(mapping["active_order_id"]),
        handoff=bool(mapping["handoff"]),
        fail_count=int(mapping["fail_count"] or 0),
    )


async def load_or_create(
    db: Any, phone: str, channel: str = DEFAULT_CHANNEL
) -> ConversationSession:
    """Busca a conversa do telefone/canal, criando se for a primeira mensagem.

    Sessão vencida (`expires_at` no passado) reinicia do zero: um cliente
    que sumiu por uma hora e voltou não deve cair no meio de um carrinho antigo.
    """
    result = await db.execute(
        text(_SELECT + " WHERE phone = :phone AND channel = :channel"),
        {"phone": phone, "channel": channel},
    )
    row = result.first()

    if row is None:
        insert = await db.execute(
            text(
                """
                INSERT INTO conversations (phone, channel, state, slots, cart,
                                           last_message_at, expires_at)
                VALUES (:phone, :channel, :state, CAST(:slots AS jsonb),
                        CAST(:cart AS jsonb), now(), :expires_at)
                ON CONFLICT (phone, channel) DO UPDATE SET last_message_at = now()
                RETURNING id
                """
            ),
            {
                "phone": phone,
                "channel": channel,
                "state": ConversationState.CONVERSANDO.value,
                "slots": "{}",
                "cart": "[]",
                "expires_at": _expires_at(),
            },
        )
        new_id = insert.scalar_one()
        return ConversationSession(
            id=_as_uuid(new_id),  # type: ignore[arg-type]
            phone=phone,
            channel=channel,
            state=ConversationState.CONVERSANDO,
        )

    session = _row_to_session(row)
    expires_at = row._mapping["expires_at"]
    if _is_expired(expires_at):
        session.reset_flow()
    return session


def _is_expired(expires_at: Any) -> bool:
    if expires_at is None:
        return False
    if isinstance(expires_at, str):
        try:
            expires_at = datetime.fromisoformat(expires_at)
        except ValueError:
            return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at < datetime.now(timezone.utc)


async def save_session(db: Any, session: ConversationSession) -> None:
    """Persiste estado + slots + carrinho e renova o TTL da sessão."""
    await db.execute(
        text(
            """
            UPDATE conversations
               SET state = :state,
                   slots = CAST(:slots AS jsonb),
                   cart = CAST(:cart AS jsonb),
                   customer_id = :customer_id,
                   active_order_id = :active_order_id,
                   handoff = :handoff,
                   fail_count = :fail_count,
                   last_message_at = now(),
                   expires_at = :expires_at
             WHERE id = :id
            """
        ),
        {
            "id": session.id,
            "state": session.state.value,
            "slots": _dump_slots(session.slots),
            "cart": _dump_cart(session.cart),
            "customer_id": session.customer_id,
            "active_order_id": session.active_order_id,
            "handoff": session.handoff,
            "fail_count": session.fail_count,
            "expires_at": _expires_at(),
        },
    )


async def reset_session(
    db: Any, phone: str, channel: str = DEFAULT_CHANNEL
) -> ConversationSession:
    """Volta a conversa ao início — usado pelo simulador e pelo `/reset` da CLI."""
    session = await load_or_create(db, phone, channel)
    session.reset_flow()
    session.handoff = False
    await save_session(db, session)
    await db.execute(
        text("DELETE FROM conversation_messages WHERE conversation_id = :id"),
        {"id": session.id},
    )
    return session


async def find_by_active_order(db: Any, order_id: UUID) -> ConversationSession | None:
    """Localiza a conversa dona de um pedido — o webhook só conhece o order_id."""
    result = await db.execute(
        text(_SELECT + " WHERE active_order_id = :order_id LIMIT 1"),
        {"order_id": order_id},
    )
    row = result.first()
    return _row_to_session(row) if row is not None else None


# ---------------------------------------------------------------------------
# Log de mensagens
# ---------------------------------------------------------------------------

async def log_message(
    db: Any,
    *,
    conversation_id: UUID,
    direction: MessageDirection,
    content: str,
    state_before: ConversationState | None = None,
    state_after: ConversationState | None = None,
    detected_intent: str | None = None,
    confidence: float | None = None,
    llm_model: str | None = None,
    llm_usage: dict[str, Any] | None = None,
    provider_message_id: str | None = None,
) -> None:
    """Grava a mensagem (entrada ou saída) com os metadados de custo do LLM.

    `ON CONFLICT (provider_message_id) DO NOTHING` porque o eco de uma mensagem
    enviada pelo bot chega de volta pelo webhook do WhatsApp com o mesmo id —
    sem isso, toda resposta do bot apareceria duplicada no histórico.

    `created_at` é `clock_timestamp()`, e não o `now()` do DEFAULT: `now()` é o
    horário de *início da transação*, igual para as três ou quatro mensagens de
    um mesmo turno. Com o id sendo um uuid aleatório, o painel ordenava o turno
    ao acaso — a saudação aparecendo depois do cardápio.
    """
    await db.execute(
        text(
            """
            INSERT INTO conversation_messages (
                conversation_id, direction, content, state_before, state_after,
                detected_intent, confidence, llm_model, llm_usage,
                provider_message_id, created_at
            ) VALUES (
                :conversation_id, :direction, :content, :state_before, :state_after,
                :detected_intent, :confidence, :llm_model,
                CAST(:llm_usage AS jsonb), :provider_message_id, clock_timestamp()
            )
            ON CONFLICT (provider_message_id) WHERE provider_message_id IS NOT NULL
            DO NOTHING
            """
        ),
        {
            "conversation_id": conversation_id,
            "direction": direction.value,
            "content": content,
            "state_before": state_before.value if state_before else None,
            "state_after": state_after.value if state_after else None,
            "detected_intent": detected_intent,
            "confidence": round(confidence, 3) if confidence is not None else None,
            "llm_model": llm_model,
            "llm_usage": json.dumps(llm_usage, default=str) if llm_usage else None,
            "provider_message_id": provider_message_id,
        },
    )


async def already_seen(db: Any, provider_message_id: str | None) -> bool:
    """A mensagem já foi atendida numa entrega anterior deste mesmo evento?

    O WhatsApp (e a Evolution no meio) entrega *pelo menos* uma vez: a mesma
    mensagem chega de novo quando o webhook demora ou devolve erro. Sem esta
    checagem o agente roda duas vezes — a segunda já com o estado adiantado
    pela primeira, respondendo "não entendi" a uma pergunta que ninguém fez e
    consumindo o contador de falhas até cair em atendimento humano.

    A entrada duplicada não aparece no painel (o `ON CONFLICT` de `log_message`
    a descarta), mas a resposta sai — foi o que confundiu o teste com cliente
    real. Quem decide é a mesma coluna única: se já existe, já foi atendida.
    """
    if not provider_message_id:
        return False
    result = await db.execute(
        text(
            "SELECT 1 FROM conversation_messages "
            "WHERE provider_message_id = :id LIMIT 1"
        ),
        {"id": provider_message_id},
    )
    return result.first() is not None


async def recent_turns(db: Any, conversation_id: UUID, limit: int = 8) -> list[Fala]:
    """Histórico curto para dar contexto ao LLM (mais antigo primeiro)."""
    result = await db.execute(
        text(
            """
            SELECT direction, content
            FROM conversation_messages
            WHERE conversation_id = :conversation_id
            ORDER BY created_at DESC, id DESC
            LIMIT :limit
            """
        ),
        {"conversation_id": conversation_id, "limit": limit},
    )
    rows: Sequence[Any] = result.fetchall()
    turns = [
        Fala(
            role="cliente" if str(row[0]) == MessageDirection.ENTRADA.value else "agente",
            content=row[1],
        )
        for row in rows
    ]
    turns.reverse()
    return turns


# ---------------------------------------------------------------------------
# Dados do cliente (leitura oportunista — nunca derruba a conversa)
# ---------------------------------------------------------------------------

async def get_saved_address(db: Any, phone: str) -> dict[str, Any] | None:
    """Último endereço do cliente, para não pedir tudo de novo a quem já pediu."""
    try:
        result = await db.execute(
            text(
                """
                SELECT a.rua, a.numero, a.bairro, a.complemento, a.referencia
                FROM addresses a
                JOIN customers c ON c.id = a.customer_id
                WHERE c.phone = :phone
                ORDER BY a.is_default DESC, a.created_at DESC
                LIMIT 1
                """
            ),
            {"phone": phone},
        )
        row = result.first()
    except Exception:  # cliente novo, tabela vazia ou banco de teste
        logger.debug("não foi possível ler endereço salvo", exc_info=True)
        return None
    if row is None:
        return None
    return {
        "rua": row[0],
        "numero": row[1],
        "bairro": row[2],
        "complemento": row[3],
        "referencia": row[4],
    }


# ---------------------------------------------------------------------------
# Fechamento: endereço, pedido e Pix
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

CreateOrder = Callable[..., Awaitable[Any]]
CreatePix = Callable[..., Awaitable[Any]]
OrderSummaryFn = Callable[..., Awaitable[Any]]
CancelOrderFn = Callable[[Any, UUID], Awaitable[Any]]


@dataclass(slots=True)
class AgentDeps:
    """Tudo que o agente consome de fora — injetado para poder testar sem banco."""

    db: Any
    catalog: CatalogSnapshot
    settings: Settings
    create_order: CreateOrder
    create_pix: CreatePix
    order_summary: OrderSummaryFn
    cancel_order: CancelOrderFn | None = None
    saved_address: Callable[[], Awaitable[dict[str, Any] | None]] | None = None
    channel: OrderChannel = OrderChannel.WHATSAPP


async def build_deps(
    db: Any,
    catalog: CatalogSnapshot,
    *,
    phone: str | None = None,
    channel: OrderChannel = OrderChannel.WHATSAPP,
) -> AgentDeps:
    """Monta as dependências reais do agente."""

    async def _saved_address() -> dict[str, Any] | None:
        if phone is None:
            return None
        return await get_saved_address(db, phone)

    async def _cancel_order(db: Any, order_id: UUID) -> Any:
        return await update_order_status(db, order_id, OrderStatus.CANCELADO)

    return AgentDeps(
        db=db,
        catalog=catalog,
        settings=get_settings(),
        create_order=create_order_from_cart,
        create_pix=create_pix_for_order,
        order_summary=get_order_summary,
        cancel_order=_cancel_order,
        saved_address=_saved_address,
        channel=channel,
    )


# ---------------------------------------------------------------------------
# Endereço
# ---------------------------------------------------------------------------

def address_of(session: ConversationSession) -> dict[str, Any]:
    address = session.slots.get("address")
    return dict(address) if isinstance(address, dict) else {}


def missing_address_fields(address: dict[str, Any]) -> list[str]:
    return [f for f in ("rua", "numero", "bairro") if not (address.get(f) or "").strip()]


#: Slot onde fica a escolha do cliente: "entrega" ou "retirada".
FULFILLMENT_SLOT = "fulfillment"


def fulfillment_of(session: ConversationSession) -> FulfillmentType | None:
    """O que o cliente escolheu, ou None se ainda não foi perguntado."""
    raw = session.slots.get(FULFILLMENT_SLOT)
    if raw in (FulfillmentType.RETIRADA, FulfillmentType.RETIRADA.value):
        return FulfillmentType.RETIRADA
    if raw in (FulfillmentType.ENTREGA, FulfillmentType.ENTREGA.value):
        return FulfillmentType.ENTREGA
    return None


def set_fulfillment(session: ConversationSession, kind: FulfillmentType) -> None:
    session.slots[FULFILLMENT_SLOT] = kind.value


def final_summary(deps: AgentDeps, session: ConversationSession) -> str:
    return r.resumo_final(
        session.cart,
        delivery_fee=deps.settings.delivery_fee,
        address=address_of(session),
        is_pickup=fulfillment_of(session) is FulfillmentType.RETIRADA,
    )


# ---------------------------------------------------------------------------
# Do carrinho ao Pix
# ---------------------------------------------------------------------------

async def _abandon_pending_order(deps: AgentDeps, session: ConversationSession) -> None:
    """Descarta um pedido que ficou esperando o Pix e já não bate com o carrinho.

    Sem isto, `place_order` reaproveitava esse `pending_order_id` na próxima
    tentativa e gerava o Pix para os itens/total de ANTES da edição — o
    cliente pagava um valor que não correspondia ao que tinha acabado de
    pedir. O pedido abandonado é cancelado no banco (melhor esforço) para não
    ficar como um pedido "novo" órfão na fila da cozinha.
    """
    pending = session.slots.pop("pending_order_id", None)
    if not pending or deps.cancel_order is None:
        return
    try:
        await deps.cancel_order(deps.db, UUID(pending))
    except Exception:
        logger.exception("não deu para cancelar o pedido pendente %s", pending)


async def place_order(deps: AgentDeps, session: ConversationSession) -> list[str]:
    """Cria o pedido, gera o Pix e leva para AGUARDANDO_PAGAMENTO.

    Guarda o id do pedido em `pending_order_id` assim que ele é criado: se o
    Pix falhar depois (provedor fora do ar, token ausente) e o cliente mandar
    "sim" de novo, reaproveitamos o mesmo pedido em vez de duplicar a compra.
    """
    pending_id = session.slots.get("pending_order_id")
    kind = fulfillment_of(session) or FulfillmentType.ENTREGA
    try:
        if pending_id:
            summary = await deps.order_summary(deps.db, UUID(pending_id))
        else:
            summary = None

        if summary is not None:
            order_id, order_code, order_total = UUID(pending_id), summary.code, summary.total
        else:
            order = await deps.create_order(
                deps.db,
                cart=session.cart,
                phone=session.phone,
                customer_name=session.slots.get("customer_name"),
                fulfillment_type=kind,
                # Retirada não tem endereço: mandar um dict vazio criaria uma
                # linha em `addresses` sem rua nem número.
                address=address_of(session) if kind is FulfillmentType.ENTREGA else None,
                channel=deps.channel,
                notes=session.slots.get("notes"),
            )
            order_id, order_code, order_total = order.id, order.code, order.total
            session.slots["pending_order_id"] = str(order_id)

        charge = await deps.create_pix(deps.db, order_id)
    except Exception:
        logger.exception("falha ao criar pedido/Pix para %s", session.phone)
        return [r.pix_falhou()]

    session.active_order_id = order_id
    session.cart.items.clear()
    session.slots.pop("pending_order_id", None)
    # "draft" é de conversas abertas na versão anterior do executor; some junto
    # para a próxima conversa desse cliente começar limpa.
    session.slots.pop("draft", None)
    session.slots.pop("closing", None)
    session.slots.pop("awaiting_confirm", None)
    session.fail_count = 0
    advance(session, S.AGUARDANDO_PAGAMENTO)
    return [
        r.mensagem_do_pix(
            order_code=order_code,
            total=order_total,
            qr_code=charge.qr_code,
            expires_minutes=deps.settings.pix_expiration_minutes,
        )
    ]


# ---------------------------------------------------------------------------
# As operações: o que cada intenção faz com o pedido
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

#: Slots usados pelo executor.
CLOSING = "closing"                    # o cliente já disse que quer fechar
AWAITING_CONFIRM = "awaiting_confirm"  # resumo final na tela, esperando "sim"
LAST_OFFER = "last_offer"              # a última lista numerada que mostramos
LEGACY_DRAFT = "draft"                 # conversas antigas (ver `adopt_legacy_draft`)


@dataclass
class Turno:
    """O que aconteceu neste turno, para compor UMA resposta no fim.

    Sem isto o bot responde uma mensagem por operação e vira metralhadora:
    "Tirei o X." / "Adicionei o Y." / "Anotei entrega." / "Qual o endereço?".
    """

    notes: list[str] = field(default_factory=list)   # o que o bot confirma/responde
    changed: bool = False                            # mexeu no pedido?
    answered: bool = False                           # respondeu pergunta?
    finished: list[str] | None = None                # resposta final (Pix, cancelamento)
    #: Sabores do último item REMOVIDO neste turno — ver `_op_add_item`. Troca
    #: de tamanho às vezes chega como remove_item + add_item (em vez de
    #: replace_item), e sem isto o sabor que não coube no tamanho novo era
    #: descartado sem o cliente nunca ser avisado de qual sumiu.
    sabores_removidos: list[str] = field(default_factory=list)
    #: O carrinho como estava ANTES da primeira operação deste turno. Um plano
    #: com mais de uma operação por `item_index` (ex.: duas remoções, "tira o
    #: primeiro, tira o primeiro de novo") não pode resolver a segunda contra
    #: o carrinho já encolhido pela primeira — o número que o cliente viu era
    #: sobre ESTA lista, não sobre a lista depois de mexida. Ver `_target`.
    cart_no_inicio_do_turno: list[CartItem] | None = None

    def say(self, *texts: str) -> None:
        """Acrescenta falas, sem repetir a mesma no mesmo turno.

        O modelo às vezes reparte uma frase em várias operações (um
        `update_address` por campo do endereço), e o cliente recebia
        "Endereço anotado" três vezes seguidas.
        """
        for texto in texts:
            if texto and texto not in self.notes:
                self.notes.append(texto)


# ---------------------------------------------------------------------------
# Itens do pedido (completos e em montagem, na mesma lista)
# ---------------------------------------------------------------------------

def product_of(deps: AgentDeps, item: CartItem) -> CatalogProduct | None:
    return deps.catalog.product_by_id(item.product_id)


def open_group(deps: AgentDeps, item: CartItem) -> CatalogGroup | None:
    """O grupo obrigatório deste item que ainda não fechou, se houver."""
    product = product_of(deps, item)
    if product is None:
        return None
    for group in product.required_groups:
        escolhidos = [c for c in item.complements if c.group_id == group.id]
        if len(escolhidos) < group.min_choices:
            return group
    return None


def _is_complete(deps: AgentDeps, item: CartItem) -> bool:
    return open_group(deps, item) is None


def pending_index(deps: AgentDeps, session: ConversationSession) -> int | None:
    """O primeiro item que ainda está sendo montado."""
    for i, item in enumerate(session.cart.items):
        if not _is_complete(deps, item):
            return i
    return None


def _pending(deps: AgentDeps, session: ConversationSession) -> CartItem | None:
    i = pending_index(deps, session)
    return session.cart.items[i] if i is not None else None


def _new_item(
    session: ConversationSession, product: CatalogProduct, quantity: int = 1
) -> CartItem:
    item = CartItem(
        product_id=product.id,
        product_name=product.name,
        unit_base_price=product.base_price,
        quantity=max(1, quantity),
    )
    session.cart.items.append(item)
    return item


def adopt_legacy_draft(deps: AgentDeps, session: ConversationSession) -> None:
    """Conversa aberta na versão anterior: traz o rascunho para o carrinho.

    Sem isto, quem estava no meio de um pedido quando o sistema subiu perderia
    o item em montagem — o pior momento possível para perder alguma coisa.
    """
    draft = session.slots.pop(LEGACY_DRAFT, None)
    if not isinstance(draft, dict):
        return
    product = deps.catalog.product_by_id(UUID(draft["product_id"]))
    if product is None:
        return
    item = _new_item(session, product, int(draft.get("quantity", 1)))
    for f in draft.get("flavors", []):
        try:
            item.complements.append(
                CartComplement(
                    id=UUID(f["id"]),
                    group_id=UUID(f["group_id"]),
                    name=f["name"],
                    extra_price=Decimal(f["extra_price"]),
                )
            )
        except (KeyError, ValueError):  # rascunho estranho: melhor perder o sabor
            continue


# ---------------------------------------------------------------------------
# Alvo (qual item a operação atinge)
# ---------------------------------------------------------------------------

#: Quando há dois itens do mesmo produto no carrinho e o cliente aponta qual
#: pelo número de ordem em vez de pelo número da lista ("tira o pistache do
#: PRIMEIRO pote"), isto resolve o empate por aquilo que ele disse em vez de
#: sempre cair no último. Só entra em jogo com mais de um item igual — não
#: exige nada do cliente, só aproveita o sinal quando ele está lá.
_ORDINAIS = {
    "primeiro": 0, "primeira": 0, "1o": 0, "1º": 0,
    "segundo": 1, "segunda": 1, "2o": 1, "2º": 1,
    "terceiro": 2, "terceira": 2, "3o": 2, "3º": 2,
    "ultimo": -1, "ultima": -1,
}


def _achado_por_ordinal(mensagem: str, achados: list[int]) -> int | None:
    if len(achados) < 2 or not mensagem:
        return None
    limpo = normalize(mensagem)
    for termo, posicao in _ORDINAIS.items():
        if termo in limpo.split() and -len(achados) <= posicao < len(achados):
            return achados[posicao]
    return None


def _target(
    deps: AgentDeps,
    session: ConversationSession,
    op: Operation,
    mensagem: str = "",
    *,
    turn: Turno | None = None,
) -> int | None:
    """Índice do item que a operação atinge, ou None quando não dá para saber.

    A ordem importa e cada degrau tem uma história:

    1. o número que a IA mandou, que é o mesmo que o cliente viu na tela;
    2. o produto que ele nomeou, se estiver no pedido;
    3. o item em montagem — é dele que o cliente está falando quando não diz
       qual;
    4. o único item do pedido.

    O degrau que não existe é o perigoso: quando o cliente **nomeia** um
    produto que não está no pedido, não se chuta o item que está. Era assim
    que "tira o médio" removia o pote grande.
    """
    itens = session.cart.items
    if not itens:
        return None

    if op.item_index is not None:
        # O número é sobre o carrinho que o cliente VIU, não sobre o carrinho
        # já mexido por uma operação anterior deste mesmo turno — ver
        # `Turno.cart_no_inicio_do_turno`.
        referencia = (
            turn.cart_no_inicio_do_turno
            if turn is not None and turn.cart_no_inicio_do_turno is not None
            else itens
        )
        if 1 <= op.item_index <= len(referencia):
            alvo = referencia[op.item_index - 1]
            for i, item in enumerate(itens):
                if item is alvo:
                    return i
            # O item que esse número apontava já saiu do carrinho NESTE
            # turno (uma operação anterior do mesmo plano removeu) — não
            # existe mais o que renumerar sozinho para ele.
            return None
        # Índice fora da lista com um item só: ele quis dizer esse.
        return 0 if len(itens) == 1 else None

    if op.product_name:
        alvo = normalize(op.product_name)
        achados = [i for i, item in enumerate(itens) if normalize(item.product_name) == alvo]
        if achados:
            por_ordinal = _achado_por_ordinal(mensagem, achados)
            if por_ordinal is not None:
                return por_ordinal
            # Dois iguais no pedido, sem o cliente apontar qual: mexe no
            # último, como gente espera.
            return achados[-1]
        if deps.catalog.product_by_name(op.product_name) is not None:
            return None

    pendente = pending_index(deps, session)
    if pendente is not None:
        return pendente
    if len(itens) == 1:
        return 0
    return None


def _group_of(deps: AgentDeps, item: CartItem) -> CatalogGroup | None:
    """O grupo de sabores do item — o aberto, ou o primeiro que ele tem."""
    aberto = open_group(deps, item)
    if aberto is not None:
        return aberto
    product = product_of(deps, item)
    if product is None:
        return None
    return product.required_groups[0] if product.required_groups else None


# ---------------------------------------------------------------------------
# Resolução de nomes (a IA propõe, o catálogo decide)
# ---------------------------------------------------------------------------

def _sem_sabores(catalog: CatalogSnapshot, texto: str) -> str:
    """Tira os nomes de sabor da frase, para sobrar só o que fala do produto.

    "quero um G com pistache chocolate e brownie" chegava ao resolvedor como
    "g pistache chocolate brownie" e não casava com nada — o cliente pedia do
    jeito mais natural possível e ouvia "não peguei essa". Sem os sabores,
    sobra "g", que o resolvedor acerta.
    """
    limpo = normalize(texto)
    nomes = {
        normalize(c.name)
        for p in catalog.products
        for g in p.groups
        for c in g.complements
    }
    for nome in sorted(nomes, key=len, reverse=True):
        limpo = limpo.replace(nome, " ")
    return " ".join(limpo.split())


def _find_product(
    deps: AgentDeps, op: Operation, mensagem: str = ""
) -> tuple[CatalogProduct | None, str | None]:
    """Produto da operação, ou o motivo de não ter dado.

    Devolve `(produto, problema)`. O nome vem da IA, mas quem diz se existe,
    se está disponível e se é ambíguo é o catálogo.
    """
    nome = (op.product_name or "").strip()
    if nome:
        product = deps.catalog.product_by_name(nome)
        if product is not None:
            if not product.is_available:
                return None, r.produto_esgotado(product.name)
            return product, None

    texto = (op.raw_text or op.product_name or "").strip()
    if not texto:
        # O modelo não nomeou produto nenhum: a frase do cliente é o que resta.
        # Só vale se o catálogo reconhecer com certeza (ver abaixo) — senão o
        # comportamento é o de antes, e não uma resposta pior.
        if mensagem:
            tentativa = resolve_product(_sem_sabores(deps.catalog, mensagem), deps.catalog)
            if tentativa.ok:
                return tentativa.product, None
        return None, None

    match = resolve_product(_sem_sabores(deps.catalog, texto), deps.catalog)
    if match.ok:
        return match.product, None
    if match.status is MatchStatus.AMBIGUOUS:
        return None, r.produto_ambiguo(match.candidates)
    if match.status is MatchStatus.UNAVAILABLE:
        nome_ = match.candidates[0].name if match.candidates else texto
        return None, r.produto_esgotado(nome_)
    return None, r.produto_inexistente(texto)


def _find_flavors(
    group: CatalogGroup, nomes: Sequence[str]
) -> tuple[list[Any], list[str]]:
    """Casa nomes de sabor com o grupo. Devolve (achados, problemas)."""
    achados, problemas = [], []
    for nome in nomes:
        alvo = normalize(nome)
        escolha = next(
            (c for c in group.complements if normalize(c.name) == alvo), None
        )
        if escolha is None:
            problemas.append(r.complemento_inexistente(nome, group))
            continue
        if not escolha.is_available:
            problemas.append(r.complemento_esgotado(escolha.name))
            continue
        achados.append(escolha)
    return achados, problemas


def _apply_flavors(
    item: CartItem,
    group: CatalogGroup,
    *,
    add: Sequence[Any],
    remove_names: Sequence[str],
    turn: Turno,
) -> None:
    """Tira e põe sabores no MESMO item, respeitando o máximo e sem repetir."""
    atuais = item.complements
    repetidos: list[str] = []
    mexeu = False

    # O modelo às vezes devolve em remove_flavors um sabor que o cliente
    # acabou de PEDIR ("no médio bota coco e banoffe" com o banoffe já lá).
    # Tirar e pôr o mesmo sabor no mesmo turno nunca é o que ele quis.
    pedidos = {normalize(c.name) for c in add}
    remove_names = [n for n in remove_names if normalize(n) not in pedidos]

    # Remoções primeiro: é o que faz "troca X por Y" caber no mesmo item.
    for nome in remove_names:
        alvo = normalize(nome)
        for atual in list(atuais):
            if normalize(atual.name) == alvo:
                atuais.remove(atual)
                turn.say(r.sabor_removido(atual.name))
                turn.changed = True
                mexeu = True
                break

    for escolha in add:
        if len(atuais) >= group.max_choices:
            turn.say(r.grupo_cheio(group))
            break
        if any(c.id == escolha.id for c in atuais):
            # Sabor não se repete no mesmo pote. O modelo costuma REPETIR os
            # já escolhidos junto com o novo ("troca morango por chocolate"
            # volta com Pistache também): aí a repetição é só ruído e some.
            # Só vira aviso quando foi o cliente que pediu duas vezes.
            repetidos.append(escolha.name)
            continue
        atuais.append(
            CartComplement(
                id=escolha.id,
                group_id=escolha.group_id,
                name=escolha.name,
                extra_price=escolha.extra_price,
            )
        )
        turn.changed = True
        mexeu = True

    if repetidos and not mexeu:
        turn.say(r.sabor_repetido(repetidos[0]))


#: Palavras que indicam EXCLUSÃO numa lista de sabores. Com uma delas na
#: mensagem, a varredura do catálogo (`_sabores_ditos`) desliga: "quero tudo
#: menos pistache" cita pistache, e varrer o texto o adicionaria.
_EXCLUINDO = ("menos ", "exceto", "tirando", "nao quero", "sem ser", "fora o")


def _sabores_ditos(group: CatalogGroup, mensagem: str) -> list[Any]:
    """Sabores DESTE grupo que aparecem no texto do cliente, na ordem falada.

    Existe porque o modelo perde itens de uma lista escrita sem vírgula:
    "pistache chocolate e brownie" volta como `["Brownie"]` — só o último. A
    instrução no prompt não resolveu, e o cliente não vê o que sumiu; ele
    acha que pediu três sabores e o pedido sai com um.

    O catálogo é justamente o que existe para contradizer o modelo (mesma
    ideia de `_disse_isso` para endereço). Aqui ele recupera o que o modelo
    deixou cair, sem inventar nada: só entra sabor que está escrito na
    mensagem E existe no grupo.
    """
    limpo = normalize(mensagem)
    if not limpo or any(marca in limpo for marca in _EXCLUINDO):
        return []
    achados = []
    for complemento in group.complements:
        posicao = limpo.find(normalize(complemento.name))
        if posicao >= 0:
            achados.append((posicao, complemento))
    return [c for _, c in sorted(achados, key=lambda par: par[0])]


def _flavors_into(
    deps: AgentDeps, item: CartItem, op: Operation, turn: Turno, mensagem: str = ""
) -> None:
    """Aplica os sabores da operação no item, no grupo certo."""
    if not (op.add_flavors or op.remove_flavors):
        return
    group = _group_of(deps, item)
    if group is None:
        if op.add_flavors:
            turn.say(r.item_sem_sabores(item.product_name))
            turn.answered = True
        return
    achados, problemas = _find_flavors(group, op.add_flavors)

    # O modelo acertou o sabor, mas pode ter perdido o resto da lista. Se o
    # texto do cliente cita MAIS sabores deste grupo do que ele devolveu, o
    # texto manda — tirando os que o próprio plano pediu para remover.
    if achados and mensagem:
        removendo = {normalize(n) for n in op.remove_flavors}
        pelo_texto = [
            c for c in _sabores_ditos(group, mensagem)
            if normalize(c.name) not in removendo
        ]
        if len(pelo_texto) > len(achados):
            achados = pelo_texto
    antes = len(turn.notes)
    turn.say(*problemas)
    _apply_flavors(item, group, add=achados, remove_names=op.remove_flavors, turn=turn)
    if not turn.changed and len(turn.notes) > antes:
        # Sabor repetido, grupo já cheio, sabor que não existe: _apply_flavors
        # e _find_flavors já explicaram o problema sem mudar nada no item. Sem
        # marcar `answered`, o turno caía no fallback genérico de "não
        # entendi" — que APAGA a explicação real e ainda soma uma falha por
        # algo que o sistema entendeu perfeitamente.
        turn.answered = True


#: ---------------------------------------------------------------------------
#: A FALA DO CLIENTE MANDA
#: ---------------------------------------------------------------------------
#: As ações abaixo destroem pedido ou cobram, e nenhuma delas tem catálogo que
#: possa contradizer o modelo — se ele erra a classificação, o estrago é real e
#: o cliente só descobre depois. Por isso cada uma exige um sinal na FALA do
#: cliente, e não só no plano que a IA devolveu.
#:
#: A regra nasceu remendo a remendo, uma trava por bug encontrado em produção
#: (endereço inventado, entrega marcada sozinha, confirmação morna virando Pix,
#: "deixa pra lá" apagando o pedido). `test_ancoragem_das_acoes_destrutivas`
#: existe para que a próxima ação destrutiva não repita o ciclo: se ela entrar
#: em `_EXIGEM_FALA_DO_CLIENTE` sem trava, o teste quebra.
_EXIGEM_FALA_DO_CLIENTE = frozenset(
    {
        Action.CANCEL_ORDER,
        Action.REMOVE_ITEM,
        Action.CLOSE_ORDER,
        Action.CONFIRM_ORDER,
        Action.SET_FULFILLMENT,
        Action.UPDATE_ADDRESS,
    }
)

#: Cancelamento sem margem para outra leitura.
_CANCELAMENTO_CLARO = (
    "cancel", "desist", "anul", "nao quero mais", "nao vou querer",
    "esquece o pedido", "deixa o pedido", "nao precisa mais",
)

#: Tudo o que conta como desistir. Inclui as formas ambíguas ("deixa pra lá"),
#: que no meio de um pedido são desistência de verdade — mas que em
#: atendimento humano costumam ser sobre o ATENDENTE, não sobre a compra. Por
#: isso o handoff usa `_cancelamento_claro`, mais estrito, e a conversa normal
#: usa esta lista.
_SINAIS_CANCELAR = _CANCELAMENTO_CLARO + (
    "deixa pra la", "deixa pra lá", "deixa quieto", "deixa pra proxima",
    "melhor nao", "esquece",
)

#: O que o cliente escreve quando quer tirar alguma coisa do pedido.
_SINAIS_REMOVER = (
    "tira", "tirar", "remove", "remover", "retira", "apaga", "exclui",
    "nao quero", "sem o ", "sem a ", "troca", "trocar", "substitui", "cancela o",
)


def _cancelamento_dito(text: str) -> bool:
    limpo = normalize(text)
    return any(sinal in limpo for sinal in _SINAIS_CANCELAR)


def _cancelamento_claro(text: str) -> bool:
    limpo = normalize(text)
    return any(sinal in limpo for sinal in _CANCELAMENTO_CLARO)


def _remocao_dita(text: str) -> bool:
    limpo = normalize(text)
    return any(sinal in limpo for sinal in _SINAIS_REMOVER)


# ---------------------------------------------------------------------------
# As operações
# ---------------------------------------------------------------------------

async def apply(
    deps: AgentDeps,
    session: ConversationSession,
    op: Operation,
    turn: Turno,
    mensagem: str = "",
) -> None:
    """Aplica UMA operação. Nada aqui responde ao cliente diretamente.

    `mensagem` é o texto cru do cliente. O endereço usa para conferir se cada
    campo foi mesmo dito (ver `_merge_address`); os itens usam para a mesma
    checagem contra um defeito parecido — ver `_duplicates_complete_item`.
    """
    action = op.action

    # O modelo costuma pendurar a forma de entrega e o endereço na MESMA
    # operação do item ("quero um pote G, vou retirar"). Lidos só na operação
    # dedicada, eles se perdiam e o bot perguntava de novo lá na frente.
    if op.fulfillment and action is not Action.SET_FULFILLMENT:
        _set_fulfillment(session, op.fulfillment, turn, mensagem)
    if op.address is not None and action is not Action.UPDATE_ADDRESS:
        _merge_address(session, op.address, turn, mensagem)

    if action is Action.ADD_ITEM:
        _op_add_item(deps, session, op, turn, mensagem)

    elif action in {Action.UPDATE_ITEM, Action.REPLACE_ITEM}:
        _op_update_item(deps, session, op, turn, mensagem)

    elif action is Action.REMOVE_ITEM:
        _op_remove_item(deps, session, op, turn, mensagem)

    elif action is Action.UPDATE_QUANTITY:
        _op_quantity(deps, session, op, turn, mensagem)

    elif action is Action.DUPLICATE_ITEM:
        _op_duplicate(deps, session, op, turn, mensagem)

    elif action is Action.SET_FULFILLMENT:
        _set_fulfillment(session, op.fulfillment, turn, mensagem)

    elif action is Action.UPDATE_ADDRESS:
        _merge_address(session, op.address, turn, mensagem)

    elif action is Action.SHOW_MENU:
        turn.say(menu(deps, session))
        turn.answered = True

    elif action is Action.SHOW_CART:
        if session.cart.is_empty and session.active_order_id is not None:
            turn.say(await pending_order_status(deps, session))
        else:
            turn.say(
                r.resumo_do_pedido(session.cart, pending=pending_index(deps, session))
                if not session.cart.is_empty
                else r.pedido_vazio()
            )
        turn.answered = True

    elif action is Action.SHOW_TOTAL:
        if session.cart.is_empty and session.active_order_id is not None:
            turn.say(await pending_order_status(deps, session))
        else:
            turn.say(_total_reply(deps, session))
        turn.answered = True

    elif action is Action.ANSWER_QUESTION:
        turn.say(_answer_question(deps, session, op))
        turn.answered = True

    elif action is Action.CLOSE_ORDER:
        session.slots[CLOSING] = True

    elif action is Action.CANCEL_ORDER:
        if mensagem and not _cancelamento_dito(mensagem):
            # O modelo classificou como cancelamento algo que não tem uma
            # palavra de cancelamento na frase. Apagar o pedido por um palpite
            # é o estrago mais caro do sistema — pergunta, não executa.
            logger.info("cancel_order descartado, sem sinal em %r", mensagem)
            turn.say(r.confirmar_cancelamento())
            turn.answered = True
        else:
            turn.finished = await cancel(deps, session)

    elif action is Action.REQUEST_HUMAN:
        turn.finished = to_human(session)

    elif action is Action.ASK_CLARIFICATION:
        turn.say(op.clarification or r.pedir_para_repetir())
        turn.answered = True

    # CONFIRM_ORDER e NO_ACTION são tratados em `run`: um mexe em dinheiro, o
    # outro é a ausência de operação.


#: Palavras que indicam entrega/retirada de verdade. Não são para ENTENDER a
#: fala do cliente — isso continua sendo trabalho da IA — só para confirmar
#: que ela tem alguma base antes de fixar um dado com peso financeiro
#: (a taxa de R$5) que o catálogo não tem como contradizer.
_SINAIS_ENTREGA = (
    "entrega", "entregar", "entregam", "manda", "mandar", "leva", "levar",
    "traz", "trazer", "delivery", "em casa", "minha casa",
)
_SINAIS_RETIRADA = (
    "retirada", "retirar", "retiro", "busco", "buscar", "pegar", "passo",
    "vou ai", "vou aí", "na loja", "no local",
)


def _fulfillment_dito(escolha: str, mensagem: str) -> bool:
    """O cliente disse algo sobre como quer receber, ou o modelo inventou?

    fulfillment não tem catálogo para contradizer a IA — mesma classe de
    problema que o endereço (ver `_disse_isso`). Achado em conversa real: o
    modelo marcava "entrega" sem o cliente ter escrito uma palavra sobre
    forma de recebimento, grudando a taxa de R$5 e a exigência de endereço
    num pedido que talvez fosse retirada.
    """
    limpo = normalize(mensagem)
    sinais = _SINAIS_ENTREGA if escolha == "entrega" else _SINAIS_RETIRADA
    return any(sinal in limpo for sinal in sinais)


def _set_fulfillment(
    session: ConversationSession, escolha: str | None, turn: Turno, mensagem: str = ""
) -> None:
    """Entrega ou retirada — e o bot DIZ que anotou.

    Anotar em silêncio fazia o cliente repetir: ele dizia "quero entrega", via
    o resumo do carrinho de volta e achava que tinha sido ignorado.
    """
    if escolha == "retirada":
        kind = FulfillmentType.RETIRADA
    elif escolha == "entrega":
        kind = FulfillmentType.ENTREGA
    else:
        return
    if mensagem and not _fulfillment_dito(escolha, mensagem):
        logger.info(
            "fulfillment=%s descartado, sem sinal na mensagem %r", escolha, mensagem
        )
        return
    mudou = fulfillment_of(session) is not kind
    set_fulfillment(session, kind)
    if mudou:
        turn.say(r.entrega_anotada(kind))
    turn.changed = True


def _disse_isso(valor: str, mensagem: str) -> bool:
    """O cliente realmente escreveu este pedaço de endereço?

    Produto e sabor têm o catálogo para dizer se existem. **Endereço não tem** —
    é texto livre, e por isso é o único campo em que a IA consegue inventar um
    dado sem nada a contradizê-la. E inventou: respondendo "sim" à pergunta
    "qual o bairro?", o modelo preencheu "Jardim América", um bairro que o
    cliente nunca digitou. A entrega iria para o lugar errado.

    A conferência é frouxa de propósito — basta uma palavra do valor aparecer
    na mensagem, e palavra parecida conta (o cliente escreve "flres", o modelo
    normaliza para "Flores"). O que ela barra é o caso que importa: um valor
    que não tem relação nenhuma com o que foi dito.
    """
    limpo = normalize(valor).strip()
    mensagem_limpa = normalize(mensagem)
    if not limpo or not mensagem_limpa:
        return False
    # O valor inteiro aparecendo no texto já resolve — e cobre o nome curto
    # ("Rua X"), que não sobreviveria a uma comparação por palavra.
    if limpo in mensagem_limpa:
        return True
    palavras_msg = [p for p in re.split(r"[^a-z0-9]+", mensagem_limpa) if p]
    palavras_valor = [p for p in limpo.split() if len(p) >= 2]
    if not palavras_valor or not palavras_msg:
        return False
    return any(
        palavra in palavras_msg or get_close_matches(palavra, palavras_msg, n=1, cutoff=0.75)
        for palavra in palavras_valor
    )


def _merge_address(
    session: ConversationSession, address: Any, turn: Turno, mensagem: str = ""
) -> None:
    """Endereço é objeto: o cliente completa em qualquer ordem, em qualquer turno."""
    if address is None:
        return
    endereco = address_of(session)
    salvou = False
    for campo, valor in address.model_dump().items():
        if not valor:
            continue
        if mensagem and not _disse_isso(str(valor), mensagem):
            logger.info(
                "endereço: campo %s=%r descartado, não está na mensagem do cliente",
                campo,
                valor,
            )
            continue
        endereco[campo] = valor
        salvou = True

    if not salvou:
        # Todo campo caiu na checagem: o modelo inventou o endereço inteiro.
        # Marcar "entrega" aqui grudava a taxa de R$ 5 num pedido em que o
        # cliente não falou nem de endereço nem de entrega.
        return

    session.slots["address"] = endereco
    ja_era_entrega = fulfillment_of(session) is FulfillmentType.ENTREGA
    set_fulfillment(session, FulfillmentType.ENTREGA)
    if not missing_address_fields(endereco):
        turn.say(r.endereco_salvo(endereco, novo_para_entrega=not ja_era_entrega))
    turn.changed = True


def _duplicates_complete_item(
    session: ConversationSession, product: CatalogProduct, flavor_names: Sequence[str]
) -> bool:
    """Este produto+sabores já é um item COMPLETO e idêntico no carrinho?"""
    alvo = {normalize(n) for n in flavor_names}
    return any(
        item.product_id == product.id and {normalize(c.name) for c in item.complements} == alvo
        for item in session.cart.items
    )


def _mentioned_in_message(
    product: CatalogProduct, flavor_names: Sequence[str], mensagem: str
) -> bool:
    if not mensagem:
        return False
    if _disse_isso(product.name, mensagem):
        return True
    return any(_disse_isso(nome, mensagem) for nome in flavor_names)


def _op_add_item(
    deps: AgentDeps,
    session: ConversationSession,
    op: Operation,
    turn: Turno,
    mensagem: str = "",
) -> None:
    """Item NOVO no pedido — com uma exceção, que evita item fantasma.

    Se já existe um item EM MONTAGEM do mesmo produto, a operação cai nele. O
    modelo manda `add_item` com frequência para o que é resposta à pergunta
    dos sabores ("pistache e morango" depois de "fechado, G - 500ml!"), e sem
    isto cada resposta dessas criava outro pote vazio: o pedido enchia de
    itens que ninguém pediu e nenhum deles ficava completo.

    Quem quer mesmo um segundo pote igual diz "outro igual" (duplicate_item)
    ou dá a quantidade — e o pote só vira "de verdade" depois de fechado.
    """
    product, problema = _find_product(deps, op, mensagem)
    pendente = _pending(deps, session)

    if product is None:
        # Sem produto identificado, mas com sabores: é resposta à pergunta do
        # item que está aberto.
        if pendente is not None and (op.add_flavors or op.remove_flavors):
            _flavors_into(deps, pendente, op, turn, mensagem)
            if _is_complete(deps, pendente):
                turn.say(r.item_adicionado(pendente))
            return
        if problema:
            turn.say(problema)
            turn.answered = True
        return

    if pendente is not None and pendente.product_id == product.id:
        if op.quantity:
            pendente.quantity = max(1, op.quantity)
            turn.changed = True
        _flavors_into(deps, pendente, op, turn, mensagem)
        if _is_complete(deps, pendente):
            turn.say(r.item_adicionado(pendente))
        return

    # Uma resposta curta ("sim", um pedido de atendente) às vezes faz o
    # modelo devolver add_item RECRIANDO um item que já está completo no
    # carrinho, como se estivesse "confirmando" o que já tinha sido pedido —
    # dobrando o subtotal sem o cliente ter dito nada sobre o item. Só barra
    # quando a mensagem não cita nem o produto nem nenhum dos sabores: quem
    # de fato pede outro igual, cedo ou tarde, nomeia o que quer.
    if _duplicates_complete_item(session, product, op.add_flavors) and not _mentioned_in_message(
        product, op.add_flavors, mensagem
    ):
        logger.info(
            "add_item ignorado: %s %s já está completo no carrinho e não foi citado em %r",
            product.name, op.add_flavors, mensagem,
        )
        return

    item = _new_item(session, product, op.quantity or 1)
    turn.changed = True
    _flavors_into(deps, item, op, turn, mensagem)
    if _is_complete(deps, item):
        turn.say(r.item_adicionado(item))

    if turn.sabores_removidos:
        # Troca de tamanho ("na verdade quero o pequeno") costuma chegar como
        # remove_item + add_item, não como replace_item — e o modelo às vezes
        # só reaproveita UM dos sabores anteriores, sem nunca dizer qual
        # sumiu. Só avisa quando o produto novo tem grupo de sabor (senão
        # "tira o pote, bota uma casquinha" soaria como se tivesse perdido
        # sabor, quando na verdade o cliente só trocou de produto mesmo).
        grupo = _group_of(deps, item)
        if grupo is not None:
            ficaram = {normalize(c.name) for c in item.complements}
            perdidos = [n for n in turn.sabores_removidos if normalize(n) not in ficaram]
            if perdidos:
                turn.say(r.sabores_perdidos_na_troca(perdidos))
        turn.sabores_removidos = []


def _op_update_item(
    deps: AgentDeps,
    session: ConversationSession,
    op: Operation,
    turn: Turno,
    mensagem: str = "",
) -> None:
    """Mexe num item que já existe — nunca cria um novo."""
    # Trocar o produto (replace) tem prioridade sobre mexer em sabor.
    quer_trocar_produto = op.action is Action.REPLACE_ITEM or (
        op.product_name and not op.add_flavors and not op.remove_flavors
    )
    if quer_trocar_produto:
        product, problema = _find_product(deps, op, mensagem)
        if product is None:
            if problema:
                turn.say(problema)
                turn.answered = True
            return
        # Aqui `product_name` é o produto NOVO, não o alvo: procurar o alvo
        # por ele acharia "o Pote 240ml que ainda não existe no pedido".
        index = _target(
            deps, session, Operation(action=op.action, item_index=op.item_index)
        )
        if index is None:
            if session.cart.is_empty:
                # "na verdade quero o médio" sem nada no pedido: é um item novo.
                _op_add_item(deps, session, op, turn, mensagem)
                return
            turn.say(r.perguntar_qual_item(session.cart))
            turn.answered = True
            return
        antigo = session.cart.items[index]
        if antigo.product_id == product.id:
            _flavors_into(deps, antigo, op, turn, mensagem)
            return
        _replace_product(deps, session, index, product, turn)
        return

    index = _target(deps, session, op, mensagem, turn=turn)
    if index is None:
        turn.say(r.perguntar_qual_item(session.cart))
        turn.answered = True
        return

    item = session.cart.items[index]
    estava_completo = _is_complete(deps, item)
    _flavors_into(deps, item, op, turn, mensagem)
    if turn.changed and estava_completo and _is_complete(deps, item):
        turn.say(r.item_alterado(item))


def _replace_product(
    deps: AgentDeps,
    session: ConversationSession,
    index: int,
    product: CatalogProduct,
    turn: Turno,
) -> None:
    """Troca o produto do item mantendo os sabores que ainda existem nele."""
    antigo = session.cart.items[index]
    novo = CartItem(
        product_id=product.id,
        product_name=product.name,
        unit_base_price=product.base_price,
        quantity=antigo.quantity,
    )
    session.cart.items[index] = novo
    group = _group_of(deps, novo)
    if group is not None and antigo.complements:
        achados, _ = _find_flavors(group, [c.name for c in antigo.complements])
        _apply_flavors(novo, group, add=achados, remove_names=[], turn=turn)
        ficaram = {normalize(c.name) for c in novo.complements}
        perdidos = [c.name for c in antigo.complements if normalize(c.name) not in ficaram]
        if perdidos:
            # O tamanho novo cabe menos sabores que o antigo tinha — dizer
            # qual sumiu é o que falta pro cliente não descobrir sozinho lendo
            # o resumo com atenção.
            turn.say(r.sabores_perdidos_na_troca(perdidos))
    turn.say(r.produto_trocado(antigo.product_name, product.name))
    turn.changed = True


#: Palavras que mostram que o cliente está falando da TAXA, não de um produto.
_FALA_DE_TAXA = ("taxa", "frete", "entrega gratis", "entrega gratuita")


def _fala_de_taxa(mensagem: str) -> bool:
    limpo = normalize(mensagem)
    return any(marca in limpo for marca in _FALA_DE_TAXA)


def _op_remove_item(
    deps: AgentDeps,
    session: ConversationSession,
    op: Operation,
    turn: Turno,
    mensagem: str = "",
) -> None:
    if session.cart.is_empty:
        turn.say(r.pedido_vazio())
        turn.answered = True
        return

    # "tira essa taxa aí vai" não é pedido para apagar produto. Vem antes de
    # resolver o alvo de propósito: com um item só no carrinho o alvo é
    # resolvido sozinho, e o pote sumiria sem ninguém perguntar nada.
    if not op.product_name and op.item_index is None and _fala_de_taxa(mensagem):
        turn.say(
            answer(
                topic="taxa_entrega",
                question=mensagem,
                raw_text=mensagem,
                catalog=deps.catalog,
                settings=deps.settings,
                cart=session.cart,
            )
        )
        turn.answered = True
        return

    # Sem alvo nomeado pelo modelo E sem palavra de remoção na frase, isto não
    # é um pedido para apagar nada: "bom dia" com um remove_item do modelo
    # esvaziava o carrinho. Com `item_index` ou `product_name` o modelo
    # apontou para algo concreto, e aí a remoção segue normalmente.
    sem_alvo = op.item_index is None and not op.product_name and not op.remove_flavors
    if sem_alvo and mensagem and not _remocao_dita(mensagem):
        logger.info("remove_item descartado, sem sinal em %r", mensagem)
        return

    index = _target(deps, session, op, mensagem, turn=turn)

    # "tira o pistache" é tirar o sabor, não o item.
    #
    # Esta guarda é a mais importante do módulo: enquanto a operação só citar
    # SABORES — sem número de item e sem nome de produto —, ela não pode
    # apagar item nenhum. O modelo manda remove_item com remove_flavors com
    # alguma frequência (dizer "pistache, morango e pistache" já bastou), e
    # sem isto o cliente perde o pote inteiro por ter repetido um sabor.
    so_fala_de_sabor = bool(op.remove_flavors) and not op.product_name and op.item_index is None
    if op.remove_flavors and index is not None:
        item = session.cart.items[index]
        group = _group_of(deps, item)
        tem_o_sabor = any(
            normalize(c.name) in {normalize(n) for n in op.remove_flavors}
            for c in item.complements
        )
        if group is not None and (tem_o_sabor or so_fala_de_sabor):
            # "tira o brownie e poe coco no lugar" é UMA troca. O `add=[]`
            # fixo daqui jogava fora o sabor novo: o antigo saía, o substituto
            # nunca entrava, e o cliente ficava com o pote faltando sabor sem
            # ninguém avisar. Os sabores passam pelo mesmo caminho do resto
            # (`_flavors_into`), que confere contra o catálogo e ainda recupera
            # o que o modelo tenha deixado cair da lista.
            _flavors_into(deps, item, op, turn, mensagem)
            return
    if so_fala_de_sabor:
        return  # sabor que não está em lugar nenhum: não se apaga o item por isso

    if index is None:
        turn.say(r.perguntar_qual_item(session.cart))
        turn.answered = True
        return

    item = session.cart.items[index]

    # "tira UMA casquinha" com 3 no pedido tira uma, não a linha inteira. O
    # executor ignorava `quantity` e apagava as três — o cliente perdia R$ 18
    # e o bot ainda dizia "Tirei o Casquinha", no singular, escondendo o
    # tamanho do estrago.
    if op.quantity and 0 < op.quantity < item.quantity:
        item.quantity -= op.quantity
        turn.say(r.quantidade_alterada(item))
        turn.changed = True
        return

    removido = session.cart.items.pop(index)
    turn.say(r.item_removido(removido.product_name))
    turn.changed = True
    turn.sabores_removidos = [c.name for c in removido.complements]


def _op_quantity(
    deps: AgentDeps,
    session: ConversationSession,
    op: Operation,
    turn: Turno,
    mensagem: str = "",
) -> None:
    if op.quantity is None:
        return

    index = _target(deps, session, op, mensagem, turn=turn)
    if index is None:
        # "quero 2 cascões" com o cascão fora do pedido é adicionar, não
        # mudar a quantidade do que já está lá — senão o cliente leva dois
        # potes de R$ 50 achando que pediu dois casquinhos.
        if op.product_name and deps.catalog.product_by_name(op.product_name):
            _op_add_item(deps, session, op, turn, mensagem)
            return
        turn.say(r.perguntar_qual_item(session.cart))
        turn.answered = True
        return

    item = session.cart.items[index]
    item.quantity = max(1, op.quantity)
    turn.say(r.quantidade_alterada(item))
    turn.changed = True


def _op_duplicate(
    deps: AgentDeps,
    session: ConversationSession,
    op: Operation,
    turn: Turno,
    mensagem: str = "",
) -> None:
    # "põe também 2 cascões" chega do modelo como duplicate_item com o nome de
    # OUTRO produto. Duplicar aí repetiria o pote de R$ 50 que já estava no
    # carrinho. Quando o nome é de outro item, isto é adicionar, não duplicar.
    if op.product_name:
        alvo = deps.catalog.product_by_name(op.product_name)
        index = _target(
            deps, session, Operation(action=op.action, item_index=op.item_index), turn=turn
        )
        atual = session.cart.items[index] if index is not None else None
        if alvo is not None and (atual is None or alvo.id != atual.product_id):
            _op_add_item(deps, session, op, turn, mensagem)
            return

    if session.cart.is_empty:
        turn.say(r.pedido_vazio())
        turn.answered = True
        return

    # "tira essa taxa aí vai" não é pedido para apagar produto. Vem antes de
    # resolver o alvo de propósito: com um item só no carrinho o alvo é
    # resolvido sozinho, e o pote sumiria sem ninguém perguntar nada.
    if not op.product_name and op.item_index is None and _fala_de_taxa(mensagem):
        turn.say(
            answer(
                topic="taxa_entrega",
                question=mensagem,
                raw_text=mensagem,
                catalog=deps.catalog,
                settings=deps.settings,
                cart=session.cart,
            )
        )
        turn.answered = True
        return

    index = _target(deps, session, op, mensagem, turn=turn)
    if index is None:
        index = len(session.cart.items) - 1
    copia = session.cart.items[index].model_copy(deep=True)
    copia.quantity = op.quantity or 1
    session.cart.items.append(copia)
    turn.say(r.item_adicionado(copia))
    turn.changed = True


# ---------------------------------------------------------------------------
# Respostas que só leem
# ---------------------------------------------------------------------------

def menu(deps: AgentDeps, session: ConversationSession) -> str:
    session.slots[LAST_OFFER] = [p.name for p in deps.catalog.available_products]
    return r.cardapio(deps.catalog)


async def pending_order_status(deps: AgentDeps, session: ConversationSession) -> str:
    """"qual sabor eu escolhi mesmo?", "quanto vou pagar?" depois do Pix emitido.

    `place_order` esvazia o carrinho ao gerar o Pix — sem isto, qualquer
    pergunta sobre o pedido que o cliente ACABOU de fazer caía na resposta de
    carrinho vazio ("o que você vai querer hoje?"), como se o pedido tivesse
    sumido. O pedido não sumiu: só saiu do carrinho para `active_order_id`.
    """
    if session.active_order_id is None:
        return r.pedido_vazio()
    try:
        summary = await deps.order_summary(deps.db, session.active_order_id)
    except Exception:
        logger.exception("falha ao buscar o pedido %s para responder o cliente", session.active_order_id)
        summary = None
    if summary is None:
        return r.pedido_aguardando_pagamento()
    return r.situacao_do_pedido(summary)


def _total_reply(deps: AgentDeps, session: ConversationSession) -> str:
    if session.cart.is_empty:
        return r.pedido_vazio()
    kind = fulfillment_of(session)
    return r.resposta_do_total(
        session.cart,
        deps.settings.delivery_fee,
        is_pickup=None if kind is None else kind is FulfillmentType.RETIRADA,
        pending=pending_index(deps, session),
    )


def _answer_question(
    deps: AgentDeps, session: ConversationSession, op: Operation
) -> str:
    return answer(
        topic=op.question_topic,
        question=op.question_text or "",
        raw_text=op.raw_text,
        catalog=deps.catalog,
        settings=deps.settings,
        cart=session.cart,
    )



# ---------------------------------------------------------------------------
# Atendimento humano
# ---------------------------------------------------------------------------

#: Estados que, se ativos antes do handoff, valem a pena recuperar ao voltar.
#: Perder AGUARDANDO_PAGAMENTO ao retomar era o bug: o congelamento do
#: carrinho com Pix pendente (`_MEXEM_NO_PEDIDO` em machine.py) só vale
#: enquanto o estado for esse — se o retorno do handoff jogasse todo mundo
#: para CONVERSANDO, o cliente conseguia abrir um SEGUNDO pedido por baixo do
#: primeiro, ainda não pago, só por ter passado pelo atendimento humano.
_RETOMAVEL_DO_HANDOFF: frozenset[S] = frozenset(
    {S.CONFIRMANDO_PEDIDO, S.AGUARDANDO_PAGAMENTO}
)


def to_human(session: ConversationSession) -> list[str]:
    logger.info("atendimento humano acionado para %s (estava em %s)", session.phone, session.state.value)
    if not can_transition(session.state, S.ATENDIMENTO_HUMANO):
        _go(session, S.CONVERSANDO)
    if session.state is not S.ATENDIMENTO_HUMANO:
        session.slots["pre_handoff_state"] = session.state.value
    _go(session, S.ATENDIMENTO_HUMANO)
    session.handoff = True
    session.touch_handoff()
    return [r.chamou_atendente()]


def human_on_the_line(session: ConversationSession) -> bool:
    """Alguém da loja deu sinal de vida há pouco tempo."""
    if not session.handoff and session.state is not S.ATENDIMENTO_HUMANO:
        return False
    return session.handoff_idle_minutes() < get_settings().handoff_return_minutes


def resume_from_human(session: ConversationSession) -> None:
    session.handoff = False
    session.slots.pop("handoff_since", None)
    session.slots.pop("handoff_avisado_em", None)
    session.fail_count = 0
    pre_handoff = session.slots.pop("pre_handoff_state", None)
    if session.state is S.ATENDIMENTO_HUMANO:
        destino = next(
            (s for s in _RETOMAVEL_DO_HANDOFF if s.value == pre_handoff), S.CONVERSANDO
        )
        _go(session, destino)


#: O que o cliente diz quando quer o bot de volta. É uma lista curta e ela não
#: obriga ninguém a falar assim: qualquer operação de pedido também traz a
#: conversa de volta. Ela existe para "deixa pra lá, continua você" — que não



async def cancel(deps: AgentDeps, session: ConversationSession) -> list[str]:
    """Cancela a conversa E o pedido real — as duas coisas, não só uma.

    Cancelar só a sessão foi o pior jeito de descobrir isto: o `Order` no
    banco continuava `novo`/pendente com o Pix ainda válido no provedor. Se o
    pagamento chegasse depois (atrasado, ou o cliente pagou sem ver a
    confirmação de cancelamento a tempo), o webhook aprovava normalmente e um
    pedido que a conversa já tratava como morto ia para a cozinha sem
    ninguém perceber.
    """
    if session.state in CANCELLABLE_STATES or session.state is S.ATENDIMENTO_HUMANO:
        if session.state is S.ATENDIMENTO_HUMANO:
            session.handoff = False
        _go(session, S.CANCELADO)

    order_id = session.active_order_id
    if order_id is None:
        pending = session.slots.get("pending_order_id")
        if pending:
            try:
                order_id = UUID(pending)
            except ValueError:
                order_id = None
    if order_id is not None and deps.cancel_order is not None:
        try:
            await deps.cancel_order(deps.db, order_id)
        except (OrderNotFoundError, InvalidStatusTransition):
            # Já saiu do estado em que cancelar faz sentido (cozinha já
            # finalizou, ou já tinha sido cancelado) — a conversa cancela do
            # lado dela mesmo assim; o pedido físico é do Kanban.
            logger.info("cancelamento do pedido %s no banco não se aplicava mais", order_id)
        except Exception:
            logger.exception("não deu para cancelar o pedido %s no banco", order_id)

    session.slots = {}
    session.cart.items.clear()
    session.active_order_id = None
    session.fail_count = 0
    return [r.pedido_cancelado()]


# ---------------------------------------------------------------------------
# A máquina: um turno de conversa do começo ao fim
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)



#: O que o cliente diz quando quer o bot de volta. É uma lista curta e ela não
#: obriga ninguém a falar assim: qualquer operação de pedido também traz a
#: conversa de volta. Ela existe para "deixa pra lá, continua você" — que não
#: é operação nenhuma e, sem isto, virava outra mensagem de espera.
_VOLTAR_PRO_BOT = (
    "deixa pra la",
    "deixa quieto",
    "continua voce",
    "continua vc",
    "pode continuar",
    "segue voce",
    "segue vc",
    "nao precisa",
    "esquece",
    "pode ser com voce",
    "pode ser com vc",
    "com voce mesmo",
    "com vc mesmo",
    "voce mesmo",
    "vc mesmo",
)


def _quer_o_bot_de_volta(text: str) -> bool:
    limpo = normalize(text)
    return any(termo in limpo for termo in _VOLTAR_PRO_BOT)


async def _handoff_turn(
    deps: AgentDeps, session: ConversationSession, plan: AgentPlan, text: str
) -> list[str] | None:
    """Em atendimento humano o bot não conduz o pedido — mas não emudece.

    Devolve `None` quando o cliente mostrou que quer seguir com o bot: aí a
    conversa volta e o turno é processado normalmente, sem obrigar o cliente a
    repetir o que acabou de pedir.

    Ficar mudo era o defeito mais caro do agente: quem pedia atendente (ou
    caía lá por engano) não recebia mais nada, nem "estou chamando alguém",
    nem resposta a "cancela". Aqui ele continua ouvindo: avisa que está
    aguardando, aceita cancelamento e volta a atender se o cliente pedir.
    """
    # A fala do cliente vem antes do palpite do modelo. "deixa pra lá, continua
    # vc mesmo" dispensa o ATENDENTE, não o pedido — e o modelo devolvia
    # cancel_order para essa frase. Em conversa real o cliente perdeu o pedido
    # inteiro assim, e ao reclamar ("eu não mandei cancelar nada") ouviu de
    # novo "cancelei o pedido". Quem pede o bot de volta sem dizer "cancela"
    # não está cancelando.
    cancelou_mesmo = plan.has(Action.CANCEL_ORDER) and (
        _cancelamento_claro(text) or not _quer_o_bot_de_volta(text)
    )
    if cancelou_mesmo:
        return await cancel(deps, session)

    # Qualquer operação que MEXE no pedido significa "quero seguir por aqui
    # mesmo". show_cart/show_total/show_menu ficaram de fora de propósito:
    # perguntar "o que eu pedi mesmo?" enquanto espera um atendente é só
    # curiosidade, não um pedido para dispensar a pessoa que foi chamada — um
    # cliente simulado perguntou isso e o bot tirou ele do atendimento humano
    # sozinho, sem o cliente ter pedido.
    quer_o_bot = any(
        action
        in {
            Action.ADD_ITEM,
            Action.UPDATE_ITEM,
            Action.REPLACE_ITEM,
            Action.REMOVE_ITEM,
            Action.UPDATE_QUANTITY,
            Action.DUPLICATE_ITEM,
            Action.SET_FULFILLMENT,
            Action.UPDATE_ADDRESS,
            Action.CLOSE_ORDER,
            Action.CONFIRM_ORDER,
        }
        for action in plan.actions
    )
    quer_voltar_pela_fala = _quer_o_bot_de_volta(text)
    if quer_o_bot or quer_voltar_pela_fala:
        resume_from_human(session)
        if quer_voltar_pela_fala:
            # "pode continuar comigo mesmo, sem esperar atendente" é um sinal
            # determinístico (a fala, não o modelo) de que o cliente quer
            # DISPENSAR o humano. O modelo às vezes devolve request_human na
            # MESMA mensagem (confunde "atender" com "atendente") — sem isto,
            # o turno seguia normalmente e esse request_human jogava a
            # conversa de volta para o atendimento humano no mesmo turno em
            # que o cliente pediu para sair dele.
            # `cancel_order` sai pelo mesmo motivo do `request_human`: a frase
            # que dispensa o atendente ("deixa pra lá") faz o modelo achar que
            # o cliente desistiu do pedido.
            descartar = {Action.REQUEST_HUMAN}
            if not _cancelamento_claro(text):
                descartar.add(Action.CANCEL_ORDER)
            plan.operations = [
                op for op in plan.operations if op.action not in descartar
            ]
        return None  # o turno segue normalmente; quem chama põe o aviso

    # Avisa que está esperando — mas uma vez a cada tanto, não a cada mensagem.
    #
    # O "a cada tanto" era só promessa: o slot `handoff_avisado` era gravado uma
    # vez e nunca mais limpo, então a partir da TERCEIRA mensagem o turno
    # devolvia lista vazia para sempre. Três clientes simulados bateram nisso —
    # "alooo? tem alguém aí?" ficou sem resposta nenhuma. Era exatamente o que
    # esta função existe para impedir.
    #
    # Agora o silêncio é limitado no tempo: o aviso longo sai de novo depois de
    # `_MINUTOS_ENTRE_AVISOS`, e no intervalo sai um reconhecimento curto. O
    # cliente nunca fala com o vazio.
    ultimo = session.slots.get("handoff_avisado_em")
    agora = datetime.now(timezone.utc)
    if isinstance(ultimo, str):
        try:
            desde = (agora - datetime.fromisoformat(ultimo)).total_seconds() / 60
        except ValueError:
            desde = float("inf")
    else:
        desde = float("inf")

    if desde >= _MINUTOS_ENTRE_AVISOS:
        session.slots["handoff_avisado_em"] = agora.isoformat()
        return [r.ainda_esperando_atendente()]
    return [r.ainda_esperando_atendente_curto()]


#: Operações que mexem no pedido. Enquanto houver Pix pendente elas ficam
#: bloqueadas — cancelar, perguntar e pedir gente seguem valendo.
#: Operações que ALTERAM os itens do pedido. Fechar e confirmar ficam de fora:
#: elas encerram o pedido, não o modificam — e a diferença importa na trava da
#: confirmação, que precisa saber se o cliente ainda estava mexendo em algo.
_EDITAM_OS_ITENS = frozenset(
    {
        Action.ADD_ITEM,
        Action.UPDATE_ITEM,
        Action.REPLACE_ITEM,
        Action.REMOVE_ITEM,
        Action.UPDATE_QUANTITY,
        Action.DUPLICATE_ITEM,
    }
)

_MEXEM_NO_PEDIDO = _EDITAM_OS_ITENS | frozenset(
    {Action.CLOSE_ORDER, Action.CONFIRM_ORDER}
)

#: As mesmas ações de `_EDITAM_OS_ITENS`, mais trocar entrega/retirada: junto
#: com os itens, ela pesa no total (a taxa de R$5) e por isso também não pode
#: ficar pendente quando o cliente confirma NA MESMA mensagem. Sem isto,
#: "muda pra entrega e fecha o pedido" cobrava com a forma de recebimento
#: ANTIGA — `place_order` rodava antes de `set_fulfillment` ser aplicado,
#: porque o gate de confirmação só olhava para operações de item.
_ADIAM_A_COBRANCA = _EDITAM_OS_ITENS | frozenset({Action.SET_FULFILLMENT})


#: De quanto em quanto tempo o aviso longo de "estou aguardando alguém" se
#: repete. No intervalo o bot responde curto — mas responde.
_MINUTOS_ENTRE_AVISOS = 3.0


#: Respostas mornas. A lista é curta e existe por um motivo só: impedir que
#: uma quase-confirmação vire cobrança. Não é o cliente que precisa falar
#: assim — é o sistema que se recusa a cobrar sem um sim claro.
_MORNAS = (
    "pode ser",
    "acho que sim",
    "acho que e isso",
    "talvez",
    "tanto faz",
    "sei la",
    "vamo ver",
    "deve ser",
)


def _hedged(text: str) -> bool:
    """A resposta é morna o bastante para NÃO virar cobrança?

    Olha cada pedaço da frase, e não só o começo. Antes a checagem era
    `limpo == m or limpo.startswith(m + " ")`, e bastava uma vírgula para
    furar: "acho que sim, pode ser" — duas respostas mornas emendadas — passava
    direto e gerava Pix. Foi o que dois testes de conversa encontraram.

    Na dúvida, morna: o custo de errar para este lado é uma pergunta a mais; o
    custo de errar para o outro é cobrar quem não concordou.
    """
    limpo = normalize(text).strip(" .!?")
    pedacos = [p.strip(" .!?") for p in re.split(r"[,;]| e | mas ", limpo)]
    return any(
        pedaco == m or pedaco.startswith(m + " ")
        for pedaco in pedacos
        if pedaco
        for m in _MORNAS
    )


# ---------------------------------------------------------------------------
# Situação (o que a IA recebe junto com a mensagem)
# ---------------------------------------------------------------------------

def describe_situation(deps: AgentDeps, session: ConversationSession) -> str:
    """Retrato do pedido agora, em português, para o modelo.

    A lista é UMA só e numerada como o cliente a vê — item completo e item em
    montagem no mesmo lugar. É isto que deixa "esse mesmo", "o segundo", "tira
    o médio" e "1 e 3" serem resolvidos sem obrigar o cliente a repetir nomes.
    """
    linhas: list[str] = []

    if session.cart.is_empty:
        linhas.append("Pedido vazio — o cliente ainda não escolheu nada.")
    else:
        linhas.append("Itens do pedido (use ESTES números em item_index):")
        faltando: list[str] = []
        for i, item in enumerate(session.cart.items, start=1):
            sabores = (
                f" ({', '.join(c.name for c in item.complements)})"
                if item.complements
                else ""
            )
            group = open_group(deps, item)
            if group is None:
                linhas.append(f"{i}. {item.quantity}x {item.product_name}{sabores} — completo")
                continue
            escolhidos = [c.name for c in item.complements if c.group_id == group.id]
            faltam = max(group.min_choices - len(escolhidos), 0)
            linhas.append(
                f"{i}. {item.quantity}x {item.product_name}{sabores} — EM MONTAGEM, "
                f"falta{'m' if faltam != 1 else ''} {faltam} de {group.min_choices} sabores"
            )
            disponiveis = [
                c.name for c in group.available_complements if c.name not in escolhidos
            ]
            faltando.append(
                f"Sabores que ainda cabem no item {i}: " + ", ".join(disponiveis)
            )
        linhas += faltando

    kind = fulfillment_of(session)
    if kind is not None:
        linhas.append(f"Forma de entrega já definida: {kind.value}.")

    endereco = address_of(session)
    if endereco:
        ausentes = missing_address_fields(endereco)
        linhas.append(
            f"Endereço incompleto, falta: {', '.join(ausentes)}."
            if ausentes
            else "Endereço completo."
        )

    if session.slots.get(AWAITING_CONFIRM):
        linhas.append(
            "ATENÇÃO: acabamos de mostrar o RESUMO FINAL com o total e estamos "
            "esperando o cliente confirmar. Um sim claro aqui é confirm_order."
        )
    elif session.slots.get(CLOSING):
        linhas.append("O cliente já disse que quer fechar o pedido.")

    ultima = session.slots.get(LAST_OFFER)
    if ultima:
        linhas.append(
            "Última lista de opções mostrada a ele: " + ", ".join(ultima)
        )

    return "\n".join(linhas) or "Conversa começando, nada pedido ainda."


# ---------------------------------------------------------------------------
# O turno
# ---------------------------------------------------------------------------

#: "apto 91", "bloco B", "casa 2", "fundos" — o que não é rua nem bairro.
_RE_COMPLEMENTO = re.compile(
    r"\b((?:apto?|apartamento|ap|bloco|bl|casa|cs|fundos|qd|quadra|lote)"
    r"\b[\s.\-º°]*\w*)",
    re.IGNORECASE,
)
_RE_NUMERO = re.compile(r"\b(\d{1,6})\b")

#: Sem uma destas a frase não é endereço. É o que impede "quero 2 potes" de
#: virar rua="quero", numero="2", bairro="potes" quando o bot está esperando
#: o endereço e o modelo devolve um plano vazio.
_RE_LOGRADOURO = re.compile(
    r"\b(rua|r\.|av|av\.|avenida|travessa|tv\.|alameda|al\.|estrada|rodovia|"
    r"rod\.|praca|praça|largo|viela|servidao|servidão|quadra|qd)\b",
    re.IGNORECASE,
)

#: Enfeites antes do endereço: "meu endereço é", "já falei,", "anota aí".
#: Removidos em laço porque vêm empilhados ("meu endereco eh av brasil...").
_LIXO_NA_FRENTE = re.compile(
    r"^(?:meu|endereco|endereço|e|eh|é|ja|já|falei|anota|ai|aí|o|pode|anotar)"
    r"\b[\s:,.\-]*",
    re.IGNORECASE,
)


def _endereco_do_texto(mensagem: str) -> Address | None:
    """Lê o endereço direto da frase, quando o modelo não o enxergou.

    Só é chamado quando o bot ACABOU de pedir o endereço e o plano voltou sem
    nenhum — aí a mensagem é, quase por definição, a resposta a essa pergunta.
    Existe porque o modelo só reconhecia o endereço no formato do exemplo que
    o próprio bot mostra ("Rua das Flores, 123, Centro"): em conversa real,
    "rua das laranjeiras 45 bairro santa rita" foi recusado três vezes
    seguidas e o cliente não teve como concluir o pedido.

    Descrever o formato livre no prompt foi tentado e não mudou nada — por
    isso a leitura aqui é determinística. E conservadora: exige um nome de
    logradouro E um número, senão desiste e deixa o fluxo normal perguntar de
    novo. Preencher errado é pior do que perguntar mais uma vez.
    """
    texto = mensagem.strip()
    if not _RE_LOGRADOURO.search(texto):
        return None

    while True:
        limpo = _LIXO_NA_FRENTE.sub("", texto).strip(" ,.")
        if limpo == texto or not limpo:
            break
        texto = limpo

    numero = _RE_NUMERO.search(texto)
    if not numero:
        return None

    rua = texto[: numero.start()].strip(" ,.-")
    resto = texto[numero.end():].strip(" ,.-")
    if not rua:
        return None

    # "apto 91 bloco B" são dois pedaços; tira todos, não só o primeiro.
    pedacos = [m.group(1).strip(" ,.-") for m in _RE_COMPLEMENTO.finditer(resto)]
    complemento = " ".join(pedacos) if pedacos else None
    resto = _RE_COMPLEMENTO.sub(" ", resto).strip(" ,.-")

    # "bairro santa rita" / "b. centro" — a palavra é dica, não exigência.
    bairro = re.sub(r"^(?:bairro|b\.)\s*", "", resto, flags=re.IGNORECASE)
    bairro = bairro.strip(" ,.-")
    # Sobrou mais de um pedaço separado por vírgula: o bairro é o último.
    if "," in bairro:
        bairro = bairro.split(",")[-1].strip(" ,.-")

    return Address(
        rua=rua or None,
        numero=numero.group(1),
        bairro=bairro or None,
        complemento=complemento or None,
    )

#: Frases em que o cliente diz QUANTOS de um item já pedido ele quer. São
#: propositalmente estreitas: errar para mais aqui muda o valor cobrado, então
#: só entra o que não tem outra leitura. "quero 2 sabores" não casa com
#: nenhuma delas.
_RE_QUANTIDADE = (
    re.compile(r"\bmuda\w*\s+(?:a\s+)?quantidade.*?\b(?:pra|para)\s+(\d{1,2})\b"),
    re.compile(r"\b(?:sao|são|eh|é|era)\s+(\d{1,2})\s+\w*\s*(?:n[aã]o|e n[aã]o)\b"),
    re.compile(r"\b(?:quero|queria|coloca|poe|põe|bota)\s+(\d{1,2})\s+dess[ae]s?\b"),
    re.compile(r"\bna verdade\s+(?:sao|são|quero|queria)\s+(\d{1,2})\b"),
)


def _quantidade_dita(mensagem: str) -> int | None:
    """Quantos itens o cliente disse que quer, quando o modelo não percebeu.

    O modelo classifica "são 2 potes não 1" como pedido de esclarecimento e
    "muda a quantidade do item 1 pra 2" como pergunta — em conversa real o
    cliente tentou as duas formas e o pedido continuou com 1. Descrever isso
    na lista de ações do prompt foi tentado e não mudou o comportamento.
    """
    limpo = normalize(mensagem)
    for padrao in _RE_QUANTIDADE:
        achado = padrao.search(limpo)
        if achado:
            valor = int(achado.group(1))
            if 1 <= valor <= 20:
                return valor
    return None


def _esperando_endereco(session: ConversationSession) -> bool:
    return (
        fulfillment_of(session) is FulfillmentType.ENTREGA
        and bool(missing_address_fields(address_of(session)))
    )


async def run(
    deps: AgentDeps,
    session: ConversationSession,
    plan: AgentPlan,
    text: str,
) -> list[str]:
    """Aplica o plano da IA e devolve o que o bot vai falar."""
    adopt_legacy_draft(deps, session)

    # O bot pediu o endereço e o modelo não viu endereço nenhum na resposta:
    # lê da frase antes de responder "não entendi" a quem respondeu direito.
    if _esperando_endereco(session) and not plan.has(Action.UPDATE_ADDRESS):
        lido = _endereco_do_texto(text)
        if lido is not None:
            plan.operations.append(
                Operation(action=Action.UPDATE_ADDRESS, address=lido)
            )

    # Mesma ideia para a quantidade: "são 2 potes não 1" com um item no
    # carrinho e um plano que não mexe em nada é o cliente corrigindo quantos
    # ele quer, e o bot respondia "qual tamanho você quer?".
    if not session.cart.is_empty and not plan.has_any(_EDITAM_OS_ITENS):
        quantos = _quantidade_dita(text)
        if quantos is not None:
            plan.operations.append(
                Operation(action=Action.UPDATE_QUANTITY, quantity=quantos)
            )

    voltou_do_humano = False
    if session.handoff or session.state is S.ATENDIMENTO_HUMANO:
        if human_on_the_line(session):
            resposta = await _handoff_turn(deps, session, plan, text)
            if resposta is not None:
                return resposta
            voltou_do_humano = True
        else:
            logger.info("handoff sem resposta humana; o bot reassume a conversa")
            resume_from_human(session)

    if session.state in {S.CONCLUIDO, S.CANCELADO}:
        # Mensagem nova depois de um pedido fechado abre um ciclo limpo.
        _go(session, S.CONVERSANDO)
        session.slots = {k: v for k, v in session.slots.items() if k == "customer_name"}
        session.cart.items.clear()
        session.active_order_id = None

    if session.state is S.AGUARDANDO_PAGAMENTO and plan.has_any(_MEXEM_NO_PEDIDO):
        # Com Pix emitido, o carrinho está vazio (`place_order` o esvaziou) e
        # mexer nele montaria um SEGUNDO pedido por baixo do primeiro: o bot
        # dizia "Seu pedido: R$ 9,00" para quem tinha um Pix de R$ 73,00
        # aberto. Um cliente simulado caiu exatamente nisso.
        #
        # A garantia é da máquina de estados: pagamento pendente congela o
        # pedido. Perguntar, cancelar e chamar gente continuam funcionando.
        return [r.pedido_aguardando_pagamento()]

    if plan.customer_name and "customer_name" not in session.slots:
        session.slots["customer_name"] = plan.customer_name

    primeira_vez = not session.slots.get("ja_falamos")
    session.slots["ja_falamos"] = True

    turn = Turno()
    turn.cart_no_inicio_do_turno = list(session.cart.items)

    # A confirmação é a única operação que mexe em dinheiro: ela sai da fila e
    # só vale se houver um resumo na tela esperando resposta.
    #
    # close_order conta como confirmação NESTE ponto específico: com o resumo
    # já na tela, "fechou mano, pode mandar" e "tá certo isso, manda" saem do
    # modelo como close_order, não confirm_order — e sem isto o bot só
    # reexibia o mesmo resumo, obrigando o cliente a repetir a confirmação de
    # um jeito mais formal. A trava da resposta morna (`_hedged`) continua
    # valendo do mesmo jeito para os dois casos.
    # ...mas quem ainda está corrigindo o pedido NÃO está confirmando. Se o
    # mesmo plano traz uma alteração junto do fechamento, o cliente estava
    # mexendo em algo — e alterar e confirmar na mesma frase é contradição.
    # Achado em conversa real, no pior jeito possível: "nao ta certo nao, voce
    # nao mudou nada. no item 2 troca brownie por coco" saiu do modelo como
    # update_item + close_order, e o bot respondeu emitindo um Pix de R$ 165.
    # Uma reclamação virou cobrança. Aqui a alteração é aplicada e o resumo
    # volta para a tela; cobrar espera o próximo turno.
    quer_confirmar = (
        session.slots.get(AWAITING_CONFIRM)
        and (plan.has(Action.CONFIRM_ORDER) or plan.has(Action.CLOSE_ORDER))
        and not any(action in _ADIAM_A_COBRANCA for action in plan.actions)
    )
    if quer_confirmar:
        if _hedged(text):
            # "pode ser", "acho que sim": o modelo classifica isso como
            # confirmação, mas não é um sim. Cobrança não se faz com
            # quase-certeza — o cliente responde uma vez mais, e aí sim.
            return [r.confirmar_de_novo()]
        if pending_index(deps, session) is None:
            session.slots.pop(AWAITING_CONFIRM, None)
            return await place_order(deps, session)

    for index, op in enumerate(plan.operations):
        if op.action is Action.CLOSE_ORDER and _hedged(text):
            # Mesma trava da confirmação final, só que mais cedo: "sei lá,
            # pode ser" respondendo "quer mais alguma coisa ou já posso
            # fechar?" não pode empurrar o pedido para a etapa de fechar
            # (pedir endereço, forma de entrega) sem um "sim" de verdade.
            continue

        await apply(deps, session, op, turn, text)
        if turn.finished is not None:
            havia_mais_operacoes = index + 1 < len(plan.operations)
            if op.action is Action.CANCEL_ORDER and havia_mais_operacoes:
                # "cancela isso... ah deixa, na verdade quero sim, bota um
                # pote de X" — cancelar é de verdade, mas não pode engolir
                # em silêncio o pedido novo que o cliente emendou na MESMA
                # mensagem. O cancelamento em si já respondeu (turn.finished
                # some do carrinho); o resto do plano continua sobre uma
                # conversa livre para recomeçar.
                turn.say(*turn.finished)
                turn.finished = None
                _go(session, S.CONVERSANDO)
                continue
            # Prepend turn.notes: uma operação ANTERIOR no mesmo plano pode
            # já ter confirmado algo (removeu item, respondeu pergunta) antes
            # de uma operação seguinte terminar o turno (chamar atendente,
            # cancelar) — sem isto essa confirmação sumia da resposta, e o
            # cliente não sabia se a primeira parte do pedido realmente
            # aconteceu.
            return turn.notes + turn.finished

    if turn.changed and session.slots.get("pending_order_id"):
        # O pedido que ficou esperando o Pix (falhou ao gerar, cliente ainda
        # não tinha tentado de novo) não corresponde mais ao carrinho depois
        # desta edição — reaproveitá-lo na próxima confirmação cobraria os
        # itens ANTIGOS, descartando a edição em silêncio.
        await _abandon_pending_order(deps, session)

    replies = await _next_step(deps, session, plan, turn, primeira_vez=primeira_vez)
    if voltou_do_humano and replies:
        replies = [r.voltou_do_atendente()] + replies
    if primeira_vez and replies:
        # Bom dia uma vez só, no começo da conversa — como gente faz.
        replies = [r.saudacao()] + replies
    return [reply for reply in replies if reply]


async def _next_step(
    deps: AgentDeps,
    session: ConversationSession,
    plan: AgentPlan,
    turn: Turno,
    *,
    primeira_vez: bool = False,
) -> list[str]:
    """Depois de aplicar tudo: o que o bot fala agora.

    Uma pergunta por turno, sempre a do ponto em que o pedido está. É aqui que
    "pergunta não derruba o fluxo" acontece: se o turno só respondeu algo, o
    bot devolve o cliente exatamente para onde ele estava.
    """
    # 1. O turno só respondeu algo (pergunta, cardápio, carrinho): devolve o
    #    cliente para onde ele estava, com a retomada CURTA — repetir a lista
    #    inteira de sabores a cada dúvida é o que cansava o WhatsApp.
    if turn.answered and not turn.changed:
        session.fail_count = 0
        # Se a própria resposta já terminou em pergunta, não emendar outra:
        # duas perguntas seguidas soam como formulário.
        if turn.notes and turn.notes[-1].rstrip().endswith("?"):
            return turn.notes
        ja_mostrou = any("*Seu pedido*" in nota for nota in turn.notes)
        retomada = _resume_prompt(deps, session, carrinho_na_tela=ja_mostrou)
        return turn.notes + ([retomada] if retomada else [])

    # 2. Tem item em montagem: falta escolher sabor. Vale mesmo que ele tenha
    #    pedido para fechar — não se fecha pedido pela metade.
    index = pending_index(deps, session)
    if index is not None:
        item = session.cart.items[index]
        group = open_group(deps, item)
        product = product_of(deps, item)
        if product is not None and group is not None:
            session.fail_count = 0
            session.slots[LAST_OFFER] = [c.name for c in group.available_complements]
            escolhidos = [c.name for c in item.complements if c.group_id == group.id]
            pergunta = r.perguntar_sabores(
                product,
                group,
                escolhidos,
                posicao=index + 1 if len(session.cart.items) > 1 else None,
            )
            # Ele já pediu para fechar: explica o que está segurando, senão a
            # mesma pergunta repetida parece o bot ignorando o "pode fechar".
            if session.slots.get(CLOSING):
                return turn.notes + [r.falta_para_fechar(product), pergunta]
            return turn.notes + [pergunta]

    # 3. Fechando o pedido.
    if session.slots.get(CLOSING) and not session.cart.is_empty:
        session.fail_count = 0
        return turn.notes + await _checkout_step(deps, session)

    # 4. Mexeu no pedido: confirma e pergunta se quer mais. Carrinho ficou
    #    vazio (tirou tudo) não repete o cardápio inteiro — a lista completa
    #    é só para quem PEDE pra ver (show_menu) ou pra quem chega sem saber
    #    o que tem (passo 5, na primeira mensagem); aqui um convite curto
    #    já basta.
    if turn.changed:
        session.fail_count = 0
        session.slots.pop(AWAITING_CONFIRM, None)
        if session.cart.is_empty:
            return turn.notes + [r.perguntar_o_que_quer()]
        # Escolheu entrega mas ainda não disse o endereço: pergunta agora,
        # não só lá na frente ao fechar. É o mesmo ponto cego do sabor
        # pendente (passo 2) — falta um dado, então é dele que se fala.
        if fulfillment_of(session) is FulfillmentType.ENTREGA:
            faltando = missing_address_fields(address_of(session))
            if faltando:
                return turn.notes + [r.perguntar_endereco(faltando)]
        return turn.notes + [r.perguntar_se_quer_mais(session.cart)]

    # 5. Cumprimento, agradecimento, conversa fiada: abre o atendimento em vez
    #    de dizer "não entendi" a quem só disse oi. O cardápio inteiro só sai
    #    na PRIMEIRA mensagem da conversa — ajuda quem chega sem saber o que
    #    tem — ou quando o cliente pede de propósito (show_menu); mandar a
    #    lista toda de novo a cada "oi" mais tarde é spam. Com um Pix já
    #    emitido e ainda pendente, fala do pedido em aberto em vez de
    #    qualquer uma das duas coisas.
    if plan.has(Action.NO_ACTION) and session.cart.is_empty:
        session.fail_count = 0
        if session.active_order_id is not None:
            return turn.notes + [await pending_order_status(deps, session)]
        if primeira_vez:
            return turn.notes + [menu(deps, session)]
        return turn.notes + [r.perguntar_o_que_quer()]

    # 6. Nada aconteceu mesmo: reparo progressivo, sem cardápio na cara dele.
    return _fallback(deps, session, plan)


async def _checkout_step(deps: AgentDeps, session: ConversationSession) -> list[str]:
    """Entrega ou retirada → endereço → resumo. Nada disso cobra nada."""
    kind = fulfillment_of(session)
    if kind is None:
        return [r.perguntar_entrega_ou_retirada()]

    if kind is FulfillmentType.ENTREGA:
        endereco = address_of(session)
        if not endereco and deps.saved_address is not None:
            salvo = await deps.saved_address()
            if salvo and not missing_address_fields(salvo):
                session.slots["address"] = salvo
        faltando = missing_address_fields(address_of(session))
        if faltando:
            return [r.perguntar_endereco(faltando)]

    _go(session, S.CONFIRMANDO_PEDIDO)
    session.slots[AWAITING_CONFIRM] = True
    return [final_summary(deps, session)]


def _resume_prompt(
    deps: AgentDeps,
    session: ConversationSession,
    *,
    carrinho_na_tela: bool = False,
) -> str | None:
    """A pergunta do ponto em que o pedido está, para retomar depois de uma dúvida.

    `carrinho_na_tela` evita o resumo em duplicata: quem pediu "me mostra o
    carrinho" acabou de recebê-lo, e repetir a lista inteira logo abaixo para
    emendar a pergunta é exatamente o tipo de resposta que parece robô.
    """
    if session.cart.is_empty and session.active_order_id is not None:
        # Carrinho vazio aqui não é "nada pedido ainda" — é o Pix já emitido.
        # `pending_order_status` (chamado por quem pergunta sobre o pedido
        # pago) já disse tudo que importa; emendar "o que você vai querer
        # hoje?" depois soa como se o pedido pago tivesse sido esquecido.
        return None
    index = pending_index(deps, session)
    if index is not None:
        item = session.cart.items[index]
        group = open_group(deps, item)
        product = product_of(deps, item)
        if product is not None and group is not None:
            escolhidos = [c.name for c in item.complements if c.group_id == group.id]
            return r.retomar_sabores(product, group, escolhidos)
    if session.slots.get(AWAITING_CONFIRM):
        return r.perguntar_confirmacao_curta()
    if session.slots.get(CLOSING) and fulfillment_of(session) is None:
        return r.perguntar_entrega_ou_retirada()
    if not session.cart.is_empty:
        return (
            r.perguntar_se_quer_mais_curto()
            if carrinho_na_tela
            else r.perguntar_se_quer_mais(session.cart)
        )
    return r.perguntar_o_que_quer()


def _fallback(
    deps: AgentDeps, session: ConversationSession, plan: AgentPlan
) -> list[str]:
    """Reparo progressivo: reformula, depois oferece gente — nunca cala.

    Antes, a terceira mensagem não entendida jogava o cliente no atendimento
    humano (e no silêncio). Três perguntas banais bastavam.
    """
    session.fail_count += 1
    logger.info("fallback (não entendi) para %s, tentativa %s", session.phone, session.fail_count)
    retomada = _resume_prompt(deps, session)

    if session.fail_count == 1:
        return [r.nao_entendi(), *([retomada] if retomada else [])]
    if session.fail_count == 2:
        return [r.nao_entendi_de_novo(), *([retomada] if retomada else [])]

    session.fail_count = 0
    return [r.oferecer_atendente(), *([retomada] if retomada else [])]


# ---------------------------------------------------------------------------
# Orquestração: quem o mundo externo chama
# ---------------------------------------------------------------------------

# Apelidos que os arquivos originais criavam ao importar um do outro; mantidos
# porque é assim que as seções abaixo chamam estas duas funções.
_go = advance
run_machine = run


logger = logging.getLogger(__name__)

_CHANNEL_TO_ORDER_CHANNEL = {
    "whatsapp": OrderChannel.WHATSAPP,
    "console": OrderChannel.SIMULADOR,
    "simulador": OrderChannel.SIMULADOR,
}


# Indireção nomeada: os testes trocam esta função por um catálogo de mentira.
async def _fetch_catalog(db: Any) -> CatalogSnapshot:
    return await get_catalog_snapshot(db)


async def _build_deps(db: Any, catalog: CatalogSnapshot, session: ConversationSession) -> AgentDeps:
    return await build_deps(
        db,
        catalog,
        phone=session.phone,
        channel=_CHANNEL_TO_ORDER_CHANNEL.get(session.channel, OrderChannel.WHATSAPP),
    )


async def handle_inbound(
    session: Any,
    message: InboundMessage,
    *,
    channel_name: str = "whatsapp",
) -> list[str]:
    """Processa uma mensagem recebida e devolve o que o agente respondeu.

    `session` aqui é a sessão do BANCO (AsyncSession) — o estado da conversa
    é carregado dentro. Em atendimento humano o executor decide o que fazer:
    ele para de conduzir o pedido, mas continua ouvindo (ver `machine`).
    """
    if await already_seen(session, message.provider_message_id):
        logger.info(
            "mensagem %s reentregue pelo canal; já foi atendida",
            message.provider_message_id,
        )
        return []

    if message.media_type == "audio" and not message.text:
        message = await resolve_audio_message(
            message,
            adapter=EvolutionAdapter(get_settings()),
            transcriber=get_audio_transcriber(),
        )

    conversation = await load_or_create(session, message.phone, channel_name)
    state_before = conversation.state

    if message.profile_name and "customer_name" not in conversation.slots:
        conversation.slots["customer_name"] = message.profile_name

    if message.media_type == "audio" and not message.text.strip():
        # Não deu para ouvir (Evolution fora do ar, sem chave da OpenAI, áudio
        # longo ou corrompido). Isto não é "não entendi" do cliente — é falha
        # nossa — então não consome o contador de reparo progressivo nem
        # gasta uma chamada de LLM com uma mensagem que sabemos vazia.
        await log_message(
            session,
            conversation_id=conversation.id,
            direction=MessageDirection.ENTRADA,
            content="[áudio não transcrito]",
            state_before=state_before,
            state_after=conversation.state,
            provider_message_id=message.provider_message_id,
        )
        replies = [r.audio_nao_transcrito()]
        await _deliver(session, conversation, replies, channel_name)
        return replies

    catalog = await _fetch_catalog(session)
    deps = await _build_deps(session, catalog, conversation)
    situation = describe_situation(deps, conversation)
    plan = await _interpret(session, conversation, catalog, message.text, situation)
    replies = await run_machine(deps, conversation, plan, message.text)

    await save_session(session, conversation)
    await log_message(
        session,
        conversation_id=conversation.id,
        direction=MessageDirection.ENTRADA,
        content=message.text,
        state_before=state_before,
        state_after=conversation.state,
        detected_intent=_first_action(plan),
        confidence=plan.confidence,
        llm_model=plan.model,
        llm_usage=plan.usage,
        provider_message_id=message.provider_message_id,
    )

    await _deliver(session, conversation, replies, channel_name)
    return replies


async def handle_outbound_echo(
    session: Any, message: InboundMessage, *, channel_name: str = "whatsapp"
) -> None:
    """Registra uma mensagem que SAIU do número da loja sem passar pelo bot.

    Cobre duas origens, ambas com `key.fromMe=true` no Baileys: o eco do que o
    próprio bot mandou (já registrado em `_deliver`, então aqui só bate no
    `ON CONFLICT` e não duplica) e uma resposta que o lojista digitou na mão no
    celular — essa é nova, e é o que faz o painel espelhar a conversa inteira,
    não só o que o bot conduziu. Nunca chama o LLM nem a máquina de estados.
    """
    conversation = await load_or_create(session, message.phone, channel_name)
    await log_message(
        session,
        conversation_id=conversation.id,
        direction=MessageDirection.SAIDA,
        content=message.text,
        state_after=conversation.state,
        provider_message_id=message.provider_message_id,
    )

    if conversation.handoff:
        # Alguém da loja está respondendo pelo celular: o relógio que devolve a
        # conversa ao bot recomeça a cada fala humana. (Em handoff o bot não
        # envia nada, então todo `fromMe` daqui é gente de verdade.)
        conversation.touch_handoff()
        await save_session(session, conversation)


async def _interpret(
    db: Any,
    conversation: ConversationSession,
    catalog: CatalogSnapshot,
    text: str,
    situation: str,
) -> AgentPlan:
    """Chama o LLM; qualquer falha vira plano vazio e o executor repergunta."""
    try:
        history = await recent_turns(db, conversation.id)
    except Exception:
        logger.warning("sem histórico para o LLM", exc_info=True)
        history = []

    try:
        return await get_llm_client().interpret(
            catalog=catalog,
            history=history,
            message=text,
            situation=situation,
        )
    except Exception:
        # O cliente real já trata os próprios erros; isto é o cinto de segurança.
        logger.exception("cliente de LLM levantou exceção inesperada")
        return AgentPlan()


def _first_action(plan: AgentPlan) -> str | None:
    """O que vai para o painel na coluna de intenção."""
    return plan.operations[0].action.value if plan.operations else None


async def _deliver(
    db: Any,
    conversation: ConversationSession,
    replies: list[str],
    channel_name: str,
) -> None:
    """Envia pelo canal e registra cada resposta em conversation_messages."""
    adapter = get_channel_adapter(channel_name)
    for reply in replies:
        provider_id = None
        try:
            provider_id = await adapter.send_text(conversation.phone, reply)
        except Exception:
            logger.exception("falha ao enviar resposta por %s", channel_name)
        await log_message(
            db,
            conversation_id=conversation.id,
            direction=MessageDirection.SAIDA,
            content=reply,
            state_after=conversation.state,
            provider_message_id=provider_id,
        )


async def notify_payment_approved(session: Any, order_id: UUID) -> None:
    """Avisa o cliente que o Pix caiu e fecha a conversa.

    Chamada pelo webhook do Mercado Pago. Nunca levanta: um erro aqui não pode
    fazer o provedor reenviar a notificação para sempre.
    """
    try:
        conversation = await find_by_active_order(session, order_id)
    except Exception:
        logger.exception("falha ao localizar conversa do pedido %s", order_id)
        return

    if conversation is None:
        logger.info("pagamento aprovado sem conversa associada (pedido %s)", order_id)
        return

    code = await _order_code(session, order_id)
    text = r.pagamento_confirmado(code)

    if conversation.state is ConversationState.AGUARDANDO_PAGAMENTO:
        assert_transition(conversation.state, ConversationState.CONCLUIDO)
        conversation.state = ConversationState.CONCLUIDO
    else:
        logger.info(
            "pagamento aprovado com a conversa em %s; só avisando o cliente",
            conversation.state,
        )

    conversation.slots.pop("options", None)
    conversation.fail_count = 0

    try:
        await save_session(session, conversation)
    except Exception:
        logger.exception("falha ao salvar conversa após pagamento")

    if conversation.handoff:
        return  # atendente humano na linha: ele avisa

    await _deliver(session, conversation, [text], conversation.channel)


async def _order_code(db: Any, order_id: UUID) -> str:
    """Código curto do pedido para a mensagem; cai no id se o serviço falhar."""
    try:
        summary = await get_order_summary(db, order_id)
    except Exception:
        logger.warning("não foi possível ler o pedido %s", order_id, exc_info=True)
        summary = None
    return getattr(summary, "code", None) or str(order_id)[:8]


def settings_snapshot() -> dict[str, Any]:
    """Pequeno diagnóstico usado pela CLI e pelo simulador."""
    settings = get_settings()
    return {
        "fake_mode": settings.fake_mode,
        "llm": get_llm_client().name,
        "model": settings.openai_model,
    }
