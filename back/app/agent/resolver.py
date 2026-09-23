"""Guardrail de grounding: casa texto livre do cliente com o catálogo real.

Este módulo é a fronteira entre "o que o cliente escreveu" e "o que existe de
verdade". O LLM devolve texto (`product_query="pote grande"`); aqui esse texto
vira — ou não — um `CatalogProduct`/`CatalogComplement`. Se não casar com nada,
o resultado diz `NOT_FOUND` e a máquina repergunta, em vez de seguir adiante
com um item inventado.

Estratégia, em ordem: match exato normalizado → substring → similaridade
(`difflib.SequenceMatcher`). Empate entre candidatos vira `AMBIGUOUS`, que a
máquina traduz em "qual dos dois você quer?".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import Enum
from typing import Sequence, TypeVar

from app.domain.catalog import (
    CatalogComplement,
    CatalogGroup,
    CatalogProduct,
    CatalogSnapshot,
    normalize,
)

#: Abaixo disso a similaridade é chute; melhor repreguntar do que errar o pedido.
SIMILARITY_CUTOFF = 0.72

#: Candidatos com score muito próximo do melhor também entram como ambiguidade.
SIMILARITY_TOLERANCE = 0.06

#: Palavras que não ajudam a identificar item nenhum no cardápio.
_STOPWORDS = frozenset(
    {
        "quero", "queria", "gostaria", "de", "do", "da", "dos", "das", "um",
        "uma", "uns", "umas", "o", "a", "os", "as", "por", "favor", "pfv",
        "me", "ve", "ver", "manda", "pode", "ser", "e", "com", "sabor",
        "sabores", "ai", "pra", "para", "vou", "levar", "no",
        # Quantidade escrita por extenso. Sem tirar, "dois potes" casava com a
        # descrição do GG ("Dois potes G") e o cliente que queria dois potes
        # médios recebia, calado, um pote de R$ 90.
        "dois", "duas", "tres", "quatro", "cinco", "meia", "meio",
        # "tem acai?" -> a consulta é "acai"; o resto é a pergunta.
        "tem", "temos", "voces", "vcs", "queria", "tinha",
    }
)


def clean_query(text: str) -> str:
    """O trecho do cliente sem o ruído do pedido — para mostrar de volta a ele.

    `Não trabalhamos com "tem acai"` soa quebrado; `... com "acai"` não.
    """
    return _clean(text)


class MatchStatus(str, Enum):
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

def _clean(query: str) -> str:
    """Normaliza e remove ruído de pedido ("quero um...") do texto."""
    norm = normalize(query)
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


def pick_by_number(text: str, options: Sequence[str]) -> str | None:
    """Resolve resposta numérica ("2") contra a lista que acabamos de oferecer.

    Devolve o id (string) escolhido ou None. Fica aqui, e não na máquina,
    porque também é uma forma de casar texto do cliente com o catálogo.
    """
    stripped = text.strip().lstrip("#").strip().rstrip(".)-").strip()
    if not stripped.isdigit():
        return None
    index = int(stripped)
    if 1 <= index <= len(options):
        return options[index - 1]
    return None


def split_queries(text: str) -> list[str]:
    """Quebra "pistache, morango e limão" em pedaços resolvíveis."""
    normalized = text.replace(" e ", ",").replace("/", ",").replace(" + ", ",")
    parts = [part.strip(" .;") for part in normalized.split(",")]
    return [part for part in parts if part]
