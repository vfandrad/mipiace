"""Respostas para o que o cliente pergunta e não é pedido.

No teste com dez clientes simulados, quatro fizeram perguntas triviais — "vcs
aceitam cartão?", "quanto fica a entrega?", "tem sorvete sem açúcar?", "que
horas vocês abrem?" — e as quatro ouviram "não entendi". Uma delas foi parar no
atendimento humano por causa disso.

O princípio aqui é estreito de propósito: **só responde o que o sistema sabe
de verdade**. Forma de pagamento e taxa de entrega são fato do sistema (Pix,
`DELIVERY_FEE`); preço e disponibilidade saem do catálogo do dia. O que o
sistema não conhece — horário, área de entrega, endereço da loja — só é
respondido se o lojista tiver configurado; senão o bot admite que não sabe e
oferece uma pessoa. Inventar horário de loja é pior do que não responder.

Quem classifica a pergunta é a IA (`question_topic`); quem responde é este
módulo, com dado real. A IA nunca é a autoridade sobre preço ou taxa.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.agent import renderer as r
from app.domain.cart import Cart
from app.domain.catalog import CatalogSnapshot, normalize


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
    texto = normalize(question or "")

    if topic == "pagamento":
        return (
            "O pagamento é no *Pix* 💳\n"
            "Quando fechar o pedido eu já mando o código para copiar e colar."
        )

    if topic == "taxa_entrega":
        taxa: Decimal = settings.delivery_fee
        return (
            f"A taxa de entrega é *{r.money(taxa)}*, fixa para toda a região que "
            "atendemos.\nSe preferir retirar na loja, não tem taxa. 🛵🏠"
        )

    if topic == "preco":
        return _precos(catalog, texto)

    if topic in {"restricao", "disponibilidade"}:
        return _tem_isso(catalog, raw_text or question)

    if topic == "prazo":
        return (
            "Assim que o Pix cai a gente já começa a montar. 🍨\n"
            "O tempo exato depende do movimento — se quiser, eu chamo alguém do "
            "time pra te dar uma previsão certinha."
        )

    if topic in {"horario", "area_entrega", "endereco_loja"}:
        return _nao_sei(topic)

    return (
        "Essa eu não sei responder com certeza. 🙈 "
        "Quer que eu chame alguém do time pra te ajudar?"
    )


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


def _precos(catalog: CatalogSnapshot, texto: str) -> str:
    """Preço vem do catálogo, sempre. A IA nunca diz valor."""
    produtos = catalog.available_products
    if not produtos:
        return "Hoje estamos sem itens disponíveis. 😔"

    # "quanto custa o maior?" / "e o pequeno?" — se der para identificar um,
    # responde só ele; senão manda a tabela inteira, que é curta.
    if any(p in texto for p in ("maior", "grande", "mais caro")):
        alvo = max(produtos, key=lambda p: p.base_price)
        return f"O *{alvo.name}* sai {r.money(alvo.base_price)}. 😊"
    if any(p in texto for p in ("menor", "pequeno", "mais barato")):
        alvo = min(produtos, key=lambda p: p.base_price)
        return f"O *{alvo.name}* sai {r.money(alvo.base_price)}. 😊"

    linhas = ["Os preços de hoje:"]
    linhas += [f"• *{p.name}* — {r.money(p.base_price)}" for p in produtos]
    return "\n".join(linhas)


def _tem_isso(catalog: CatalogSnapshot, procurado: str) -> str:
    """"tem sem açúcar?", "tem açaí?" — a resposta está no cardápio do dia.

    Os sabores mudam todo dia; procurar no catálogo é o único jeito de a
    resposta continuar verdadeira amanhã.
    """
    alvo = normalize(procurado or "").strip()
    if not alvo:
        return "Me diz o que você procura que eu vejo se temos hoje. 😊"

    sabores = {
        c.name: c
        for p in catalog.available_products
        for g in p.groups
        for c in g.available_complements
    }

    achados = [nome for nome in sabores if alvo in normalize(nome)]
    if not achados:
        # Talvez seja um produto, não um sabor.
        produtos = [p.name for p in catalog.available_products if alvo in normalize(p.name)]
        if produtos:
            return f"Temos sim: *{', '.join(produtos)}*. 😊"
        return (
            f'Hoje não temos *{procurado}* no cardápio. 🙈\n'
            "Quer ver o que tem?"
        )

    if len(achados) == 1:
        return f"Temos sim: *{achados[0]}*. 😊"
    return "Temos sim! Hoje: *" + "*, *".join(achados) + "*. 😊"
