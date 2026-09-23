"""IA falsa: traduz a mensagem em operações por regra, sem chamar ninguém.

Serve a dois usos e a nenhum outro:

* `FAKE_MODE=true`, para rodar o sistema inteiro sem chave de API;
* a suíte de testes, que precisa de um tradutor determinístico.

Ela não tenta ser esperta — quem é esperto é o modelo de verdade. Ela casa
palavras comuns com o catálogo usando o mesmo `resolver` do executor, o que
mantém uma propriedade importante: **o que sai daqui também é nome de
cardápio**, nunca texto inventado.

Aviso que vale para quem for mexer nos testes: esta classe entende muito mais
do que o gpt-4o-mini entende sozinho. Por isso os testes que valem contra o
prompt real são os de `tests/test_agent_phrases.py`, que exercitam o resolver,
e não este arquivo.
"""

from __future__ import annotations

import re
from typing import Sequence

from app.agent.llm import Turn
from app.agent.plan import Action, Address, AgentPlan, Operation
from app.agent.resolver import (
    MatchStatus,
    resolve_complement,
    resolve_product,
    split_queries,
)
from app.domain.catalog import CatalogSnapshot, normalize

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
        history: Sequence[Turn] = (),
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
