"""Respostas para o que o cliente pergunta e não é pedido.

No teste com dez clientes simulados, quatro perguntaram coisas triviais —
"vcs aceitam cartão?", "quanto fica a entrega?", "tem sorvete sem açúcar?",
"que horas vocês abrem?" — e as quatro ouviram "não entendi". Uma delas chegou
a derrubar a conversa para atendimento humano.

O princípio aqui é estreito de propósito: **só responde o que o sistema já
sabe de verdade**. Forma de pagamento e taxa de entrega são fato do sistema
(Pix, `DELIVERY_FEE`); sabor sem açúcar/sem lactose sai de uma busca no
catálogo do dia. Horário e área de entrega o sistema não conhece — e aí a
resposta honesta é dizer isso e oferecer uma pessoa, não inventar.

Regras determinísticas, sem LLM: isto precisa funcionar igual quando o modelo
estiver fora do ar.
"""

from __future__ import annotations

from decimal import Decimal

from app.domain.catalog import CatalogSnapshot, normalize

#: Como o cliente pergunta cada coisa. Ordem importa: a primeira que casar
#: responde.
_PAGAMENTO = ("cartao", "credito", "debito", "dinheiro", "pagamento", "paga", "pix")
_ENTREGA = ("entrega", "frete", "taxa", "delivery", "entregam")
_RESTRICAO = ("sem acucar", "sem açucar", "diet", "sem lactose", "zero lactose")
_HORARIO = ("horario", "que horas", "abrem", "fecham", "aberto", "funciona")


def _tem(texto: str, termos: tuple[str, ...]) -> bool:
    return any(termo in texto for termo in termos)


def answer(text: str, catalog: CatalogSnapshot, delivery_fee: Decimal) -> str | None:
    """Resposta pronta para a pergunta, ou None se não for uma delas."""
    texto = normalize(text)

    # Só responde pergunta. "quero entrega" é escolha, não dúvida.
    if "?" not in text and not _abre_pergunta(texto):
        return None

    if _tem(texto, _PAGAMENTO):
        return (
            "Por aqui o pagamento é *só no Pix* 💳\n"
            "Quando você fechar o pedido eu já mando o código para copiar e colar."
        )

    if _tem(texto, _RESTRICAO):
        return _restricao(texto, catalog)

    if _tem(texto, _ENTREGA):
        return (
            f"A taxa de entrega é de *R$ {delivery_fee:.2f}*".replace(".", ",")
            + ".\nSe preferir, dá para retirar na loja e não paga taxa. 🛵🏠"
        )

    if _tem(texto, _HORARIO):
        # O sistema não sabe o horário da loja; fingir que sabe é pior.
        return (
            "Do horário eu não sei te dizer com certeza 🙈\n"
            "Digite *atendente* que alguém do time confirma pra você."
        )

    return None


_PALAVRAS_DE_PERGUNTA = (
    "quanto", "qual", "quais", "como", "onde", "quando", "tem ", "voces",
    "vcs", "aceita", "da pra", "sera que",
)


def _abre_pergunta(texto: str) -> bool:
    return texto.startswith(_PALAVRAS_DE_PERGUNTA) or " tem " in f" {texto} "


def _restricao(texto: str, catalog: CatalogSnapshot) -> str:
    """"tem sem açúcar?" — a resposta está no cardápio do dia, não numa tabela.

    Os sabores mudam todo dia; procurar no catálogo é o único jeito de a
    resposta continuar verdadeira amanhã.
    """
    sem_acucar = "acucar" in texto or "diet" in texto
    alvo = "sem acucar" if sem_acucar else "sem lactose"
    rotulo = "sem açúcar" if sem_acucar else "sem lactose"
    achados = sorted(
        {
            complement.name
            for product in catalog.available_products
            for group in product.groups
            for complement in group.available_complements
            if alvo in normalize(complement.name)
        }
    )
    if not achados:
        return (
            f"Hoje não temos sabor *{rotulo}* no cardápio. 😔\n"
            "Se quiser, digite *cardápio* para ver o que tem."
        )
    return f"Temos sim! Hoje de *{rotulo}*: " + ", ".join(achados) + ". 😊"
