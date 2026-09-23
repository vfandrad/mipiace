"""Regras determinísticas de intenção — a primeira das duas etapas da NLU.

Um punhado de palavras não é ambíguo em português e não precisa de modelo
nenhum para ser entendido: quem escreve "retirada" quer retirar, quem escreve
"cardápio" quer ver o cardápio. Classificar isso por regra, antes do LLM, faz
duas coisas que o modelo sozinho não garante:

1. **Tira do modelo o erro bobo.** Em produção, "retirada" foi classificado
   como `finalizar_pedido`, e o checkout repetiu "entrega ou retirada?" em
   laço — o cliente não tinha como sair.
2. **Mantém o atendimento de pé quando o LLM cai.** Timeout, rate limit ou
   chave vencida viram `desconhecido` no `runner`; com as regras, as palavras
   que mais importam continuam funcionando.

O critério é conservador de propósito: só vale em mensagem curta (o cliente
respondendo à pergunta do bot) e só quando UMA intenção casa. "não quero
entrega" tem `nao` e `entrega`, dá empate, e aí quem decide é o modelo.
"""

from __future__ import annotations

from app.domain.catalog import normalize
from app.domain.enums import Intent

#: Acima disso é frase, não resposta seca — o modelo lê melhor que a regra.
MAX_TOKENS = 5

#: Palavra (já normalizada) -> intenção. Uma palavra só aparece uma vez.
_KEYWORDS: dict[str, Intent] = {
    # Ver o cardápio
    "cardapio": Intent.VER_CARDAPIO,
    "cardapios": Intent.VER_CARDAPIO,
    "menu": Intent.VER_CARDAPIO,
    "opcoes": Intent.VER_CARDAPIO,
    "sabores": Intent.VER_CARDAPIO,
    # Falar com gente
    "atendente": Intent.FALAR_COM_HUMANO,
    "humano": Intent.FALAR_COM_HUMANO,
    "pessoa": Intent.FALAR_COM_HUMANO,
    "gerente": Intent.FALAR_COM_HUMANO,
    # Desistir
    "cancelar": Intent.CANCELAR,
    "cancela": Intent.CANCELAR,
    "desistir": Intent.CANCELAR,
    # Retirada x entrega
    "retirada": Intent.ESCOLHER_RETIRADA,
    "retirar": Intent.ESCOLHER_RETIRADA,
    "buscar": Intent.ESCOLHER_RETIRADA,
    "retiro": Intent.ESCOLHER_RETIRADA,
    "entrega": Intent.ESCOLHER_ENTREGA,
    "entregar": Intent.ESCOLHER_ENTREGA,
    "delivery": Intent.ESCOLHER_ENTREGA,
    # Fechar
    "fechar": Intent.FINALIZAR_PEDIDO,
    "finalizar": Intent.FINALIZAR_PEDIDO,
    # Mais um item ("quero mais um", "mais um pote")
    "mais": Intent.ADICIONAR_MAIS,
    # Rever o que já foi pedido ("me mostra o carrinho")
    "carrinho": Intent.CONSULTAR_STATUS,
    # Sim / não
    "sim": Intent.CONFIRMAR,
    "isso": Intent.CONFIRMAR,
    "confirmo": Intent.CONFIRMAR,
    "confirmar": Intent.CONFIRMAR,
    "nao": Intent.NEGAR,
}


#: Abre pergunta. "quanto fica a entrega?" NÃO é escolher entrega — e antes
#: desta checagem era: a regra respondia "escolher_entrega", o estado não
#: esperava isso, virava falha, e três dessas mandavam o cliente para o
#: atendimento humano por ter feito uma pergunta banal.
_INTERROGATIVAS = frozenset(
    {
        "quanto", "qual", "quais", "como", "onde", "quando", "quem", "porque",
        "pq", "tem", "teria", "aceita", "aceitam", "voces", "vcs", "da",
    }
)


def _e_pergunta(text: str, tokens: list[str]) -> bool:
    return "?" in text or bool(tokens) and tokens[0] in _INTERROGATIVAS


def rule_intent(text: str) -> Intent | None:
    """Intenção inequívoca da mensagem, ou None para o LLM decidir."""
    tokens = normalize(text).replace("!", " ").replace("?", " ").replace(",", " ").split()
    if not tokens or len(tokens) > MAX_TOKENS:
        return None

    if _e_pergunta(text, tokens):
        return None

    found = {_KEYWORDS[token] for token in tokens if token in _KEYWORDS}
    if len(found) != 1:
        return None
    return found.pop()
