"""LLM falso, determinístico e sem rede.

Não é um brinquedo: é o que faz `FAKE_MODE=true` rodar o fluxo inteiro de
pedido no terminal e nos testes, sem chave de API. Ele faz matching por
palavra-chave *contra o catálogo recebido*, então acompanha o seed do banco
sem precisar de ajuste.
"""

from __future__ import annotations

import re
from typing import Sequence

from app.agent.llm import ExtractedAddress, LLMClient, NluResult, Turn
from app.domain.catalog import CatalogSnapshot, normalize
from app.domain.enums import ConversationState, Intent

# ---------------------------------------------------------------------------
# Léxico
# ---------------------------------------------------------------------------

_GREETINGS = (
    "oi", "ola", "opa", "eae", "e ai", "bom dia", "boa tarde", "boa noite",
    "hey", "alo", "tudo bem", "menu inicial",
)
_CANCEL = ("cancelar", "cancela", "desisti", "desistir", "nao quero mais nada", "esquece o pedido")
_HUMAN = ("atendente", "humano", "pessoa", "gerente", "falar com alguem", "suporte")
_MENU = ("cardapio", "cardapios", "menu", "opcoes", "o que tem", "o que voces tem", "sabores tem")
_STATUS = ("status", "cade meu pedido", "cade o pedido", "meu pedido ja", "ja saiu",
           "quanto tempo", "demora", "chegou meu")
# Cuidado: aqui só entram trechos que não aparecem dentro de outra palavra
# ("so" casaria com "sorvete", por exemplo).
_CLOSE = ("fechar", "fecha o", "finalizar", "finaliza", "encerrar", "e so isso",
          "so isso", "mais nada", "nada mais", "e tudo", "pode fechar")
_MORE = ("mais um", "mais uma", "quero mais", "tambem quero", "adicionar", "outro", "outra")
_YES = ("sim", "isso", "claro", "pode ser", "confirmo", "confirmar", "ok", "okay", "blz",
        "beleza", "certo", "positivo", "aham", "com certeza", "perfeito", "bora", "s")
_NO = ("nao", "nao quero", "negativo", "nem", "de jeito nenhum", "n")
_PICKUP = ("retirada", "retirar", "vou buscar", "buscar ai", "pegar na loja", "na loja")
_DELIVERY = ("entrega", "entregar", "delivery", "trazer", "em casa")

_NUMBER_WORDS = {
    "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5,
    "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10, "meia duzia": 6,
}

_STREET_PREFIX = r"(?:rua|r\.|av|av\.|avenida|travessa|alameda|estrada|rodovia|praca|beco)"
_ADDRESS_RE = re.compile(
    rf"\b({_STREET_PREFIX})\s+(?P<rua>[^,\d]{{2,60}}?)[,\s]+(?P<numero>\d+[a-z]?)"
    r"(?:[,\s]+(?:bairro\s+)?(?P<bairro>[^,]{2,40}))?",
    re.IGNORECASE,
)
_BAIRRO_RE = re.compile(r"bairro\s+(?P<bairro>[^,.]{2,40})", re.IGNORECASE)
_NAME_RE = re.compile(r"\b(?:meu nome e|me chamo|sou o|sou a|aqui e o|aqui e a)\s+(?P<nome>[^,.]{2,40})")


def _has(text: str, words: Sequence[str]) -> bool:
    return any(word in text for word in words)


def _is_token(text: str, words: Sequence[str]) -> bool:
    """Casa a mensagem inteira (ou quase) — evita que "nao" dentro de frase decida."""
    stripped = text.strip(" .!?")
    return stripped in words


def _extract_quantity(text: str) -> int | None:
    digit = re.search(r"\b(\d{1,2})\s*(?:x|un|unidades?)?\b", text)
    tokens = text.split()
    for word, value in _NUMBER_WORDS.items():
        if word in tokens:
            return value
    if digit:
        value = int(digit.group(1))
        # Números soltos pequenos costumam ser escolha de opção, não quantidade.
        if 2 <= value <= 20:
            return value
    return None


def _extract_address(raw: str) -> ExtractedAddress | None:
    text = normalize(raw)
    match = _ADDRESS_RE.search(text)
    if match:
        bairro = (match.group("bairro") or "").strip(" .")
        if not bairro:
            bairro_match = _BAIRRO_RE.search(text)
            bairro = bairro_match.group("bairro").strip(" .") if bairro_match else ""
        return ExtractedAddress(
            rua=f"{match.group(1).rstrip('.')} {match.group('rua').strip()}".strip().title(),
            numero=match.group("numero"),
            bairro=bairro.title() or None,
        )
    # Endereço em partes soltas: "123", "Centro" (respostas a "o que falta").
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) >= 3 and any(p.isdigit() for p in parts):
        numero = next(p for p in parts if p.isdigit())
        rest = [p for p in parts if p != numero]
        return ExtractedAddress(rua=rest[0].title(), numero=numero, bairro=rest[1].title())
    return None


# ---------------------------------------------------------------------------
# Casamento com o catálogo (só para *escolher a intenção*; quem resolve de
# verdade é o resolver.py)
# ---------------------------------------------------------------------------

def _product_names(catalog: CatalogSnapshot) -> list[tuple[str, str]]:
    return [(normalize(p.name), p.name) for p in catalog.available_products]


def _complement_names(catalog: CatalogSnapshot) -> list[tuple[str, str]]:
    seen: dict[str, str] = {}
    for product in catalog.available_products:
        for group in product.groups:
            for complement in group.available_complements:
                seen.setdefault(normalize(complement.name), complement.name)
    return list(seen.items())


def _find_mentions(
    text: str, names: Sequence[tuple[str, str]]
) -> tuple[list[str], list[str]]:
    """Separa citações fortes das fracas.

    Forte = o nome inteiro (ou todas as palavras distintivas) aparece na frase.
    Fraca = só uma palavra genérica bate ("pote" casa com dois potes) — nesse
    caso vale mais devolver o texto do cliente e deixar o resolver decidir se é
    ambíguo, em vez de o LLM falso escolher por conta própria.
    """
    message_tokens = set(text.split())
    strong: list[str] = []
    weak: list[str] = []
    for norm_name, original in sorted(names, key=lambda pair: -len(pair[0])):
        if not norm_name:
            continue
        distinctive = [t for t in norm_name.split() if len(t) >= 5]
        if norm_name in text or (distinctive and all(t in text for t in distinctive)):
            if original not in strong:
                strong.append(original)
            continue
        if any(t in message_tokens for t in norm_name.split() if len(t) >= 4):
            if original not in weak:
                weak.append(original)
    return strong, weak


def _split_fragments(text: str) -> list[str]:
    return [
        part.strip(" .;")
        for part in text.replace(" e ", ",").replace("/", ",").replace("+", ",").split(",")
        if part.strip(" .;")
    ]


class FakeLLMClient:
    """Implementa `LLMClient` por regras. Mesma entrada, mesma saída, sempre."""

    name = "fake"

    async def extract(
        self,
        *,
        state: ConversationState,
        catalog: CatalogSnapshot,
        history: Sequence[Turn],
        message: str,
    ) -> NluResult:
        return self.extract_sync(state=state, catalog=catalog, message=message)

    # Versão síncrona: útil em teste e na CLI, sem precisar de event loop.
    def extract_sync(
        self,
        *,
        state: ConversationState,
        catalog: CatalogSnapshot,
        message: str,
    ) -> NluResult:
        raw = message.strip()
        text = normalize(raw)
        result = self._classify(state, catalog, raw, text)
        result.model = "fake-rules-v1"
        result.usage = {"input_tokens": 0, "output_tokens": 0}
        return result

    # -- regras ------------------------------------------------------------

    def _classify(
        self,
        state: ConversationState,
        catalog: CatalogSnapshot,
        raw: str,
        text: str,
    ) -> NluResult:
        if not text:
            return NluResult(intent=Intent.DESCONHECIDO, confidence=0.0)

        # 1. Intenções globais têm prioridade sobre qualquer coisa.
        if _has(text, _CANCEL):
            return NluResult(intent=Intent.CANCELAR, confidence=0.95)
        if _has(text, _HUMAN):
            return NluResult(intent=Intent.FALAR_COM_HUMANO, confidence=0.95)
        if _has(text, _MENU):
            return NluResult(intent=Intent.VER_CARDAPIO, confidence=0.9)
        if _has(text, _STATUS):
            return NluResult(intent=Intent.CONSULTAR_STATUS, confidence=0.85)

        # 2. Endereço: formato reconhecível ganha de tudo.
        address = _extract_address(raw)
        if address is not None and (address.rua or address.numero):
            return NluResult(
                intent=Intent.INFORMAR_ENDERECO,
                confidence=0.9,
                address=address,
                customer_name=self._name(text),
            )

        products = _product_names(catalog)
        complements = _complement_names(catalog)

        # 3. No meio da personalização, sabor vem antes de produto.
        if state is ConversationState.PERSONALIZANDO_ITEM:
            queries = self._complement_queries(raw, text, complements)
            if queries:
                return NluResult(
                    intent=Intent.ESCOLHER_COMPLEMENTOS,
                    confidence=0.9,
                    complement_queries=queries,
                )
            if _is_token(text, _NO) or _has(text, _CLOSE):
                return NluResult(intent=Intent.NEGAR, confidence=0.8)
            if _is_token(text, _YES):
                return NluResult(intent=Intent.CONFIRMAR, confidence=0.8)
            if text.isdigit():  # escolha por número da lista oferecida
                return NluResult(
                    intent=Intent.ESCOLHER_COMPLEMENTOS,
                    confidence=0.7,
                    complement_queries=[text],
                )
            return NluResult(intent=Intent.DESCONHECIDO, confidence=0.2)

        # 4. Entrega x retirada.
        if _has(text, _PICKUP):
            return NluResult(intent=Intent.ESCOLHER_RETIRADA, confidence=0.9)

        # 5. Fechar o pedido.
        if _has(text, _CLOSE):
            return NluResult(intent=Intent.FINALIZAR_PEDIDO, confidence=0.9)

        # 6. Produto citado explicitamente.
        strong_products, weak_products = _find_mentions(text, products)
        if strong_products or weak_products:
            # Citação fraca vira texto do cliente: o resolver é quem diz se é
            # ambíguo ("quero um pote" -> 500ml ou 240ml?).
            query = strong_products[0] if len(strong_products) == 1 else raw
            return NluResult(
                intent=Intent.ESCOLHER_PRODUTO,
                confidence=0.9 if strong_products else 0.6,
                product_query=query,
                complement_queries=self._complement_queries(raw, text, complements),
                quantity=_extract_quantity(text),
                customer_name=self._name(text),
            )

        # 7. Saudação (só quando não pediu nada junto).
        if _has(text, _GREETINGS):
            return NluResult(intent=Intent.SAUDAR, confidence=0.9)

        # 8. Sabor citado fora da personalização (cliente adiantado).
        complement_hits = self._complement_queries(raw, text, complements)
        if complement_hits:
            # Se complemento vem com tamanho ("grande pote de pistache"),
            # trata como ESCOLHER_PRODUTO + complementos, não só complemento.
            size_hint = self._infer_size(text, catalog)
            if size_hint:
                return NluResult(
                    intent=Intent.ESCOLHER_PRODUTO,
                    confidence=0.8,
                    product_query=size_hint,
                    complement_queries=complement_hits,
                )
            return NluResult(
                intent=Intent.ESCOLHER_COMPLEMENTOS,
                confidence=0.7,
                complement_queries=complement_hits,
            )

        # 9. Sim/não e "quero mais".
        if _has(text, _MORE):
            return NluResult(intent=Intent.ADICIONAR_MAIS, confidence=0.8)
        if _is_token(text, _YES) or _has(text, ("pode ser", "com certeza", "isso mesmo")):
            return NluResult(intent=Intent.CONFIRMAR, confidence=0.85)
        if _is_token(text, _NO) or _has(text, ("nao quero", "nao obrigado")):
            return NluResult(intent=Intent.NEGAR, confidence=0.85)
        if _has(text, _DELIVERY):
            return NluResult(intent=Intent.CONFIRMAR, confidence=0.7)

        # 10. Número solto: escolha da lista que acabou de ser oferecida.
        if text.isdigit():
            return NluResult(
                intent=Intent.ESCOLHER_PRODUTO, confidence=0.6, product_query=text
            )

        name = self._name(text)
        if name:
            return NluResult(intent=Intent.INFORMAR_NOME, confidence=0.7, customer_name=name)

        return NluResult(intent=Intent.DESCONHECIDO, confidence=0.1)

    @staticmethod
    def _complement_queries(
        raw: str, text: str, complements: Sequence[tuple[str, str]]
    ) -> list[str]:
        """Devolve os pedaços da frase que citam complementos existentes."""
        hits, weak = _find_mentions(text, complements)
        if not hits:
            hits = weak
        if not hits:
            return []
        # Preserva a ordem em que o cliente falou.
        fragments = _split_fragments(text)
        ordered: list[str] = []
        for fragment in fragments:
            for hit in hits:
                if hit in ordered:
                    continue
                if normalize(hit) in fragment or fragment in normalize(hit):
                    ordered.append(hit)
        for hit in hits:
            if hit not in ordered:
                ordered.append(hit)
        return ordered

    @staticmethod
    def _infer_size(text: str, catalog: CatalogSnapshot) -> str | None:
        """Adivinha o produto quando o cliente cita só o tamanho.

        "quero pistache grande" -> devolve o nome do maior produto do cardápio,
        para o resultado virar ESCOLHER_PRODUTO com esse produto mais
        complement_queries=["pistache"].

        Sai tudo do catálogo, nada escrito na mão: primeiro tenta casar um
        volume citado ("500", "240") com o nome do produto; depois cai em
        "grande/pequeno", que viram o mais caro e o mais barato do cardápio.
        Assim o cardápio pode mudar de nome e de tamanho sem mexer aqui.
        """
        products = catalog.available_products
        if not products:
            return None

        # 1. Volume explícito: "500", "1000" — o número aparece no nome.
        for numero in re.findall(r"\d{2,4}", text):
            for product in products:
                if numero in normalize(product.name):
                    return product.name

        # 2. A palavra de tamanho pode estar no próprio cardápio: o produto
        #    "G 500ml" se descreve como "Pote grande". Vale mais que o preço.
        for palavra in ("grande", "pequeno", "medio", "individual", "familia"):
            if palavra not in text:
                continue
            for product in products:
                descricao = normalize(f"{product.name} {product.description or ''}")
                if palavra in descricao:
                    return product.name

        # 3. Sem pista no cardápio, "grande" é o mais caro e "pequeno" o mais barato.
        por_preco = sorted(products, key=lambda p: p.base_price)
        if any(palavra in text for palavra in ("grande", "maior", "familia")):
            return por_preco[-1].name
        if any(palavra in text for palavra in ("pequeno", "menor", "individual")):
            return por_preco[0].name

        return None

    @staticmethod
    def _name(text: str) -> str | None:
        match = _NAME_RE.search(text)
        return match.group("nome").strip().title() if match else None


# Checagem estática: se a assinatura do protocolo mudar, quebra aqui.
_: LLMClient = FakeLLMClient()
