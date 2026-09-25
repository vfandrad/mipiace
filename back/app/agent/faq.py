"""Respostas para o que o cliente pergunta e não é pedido.

No teste com dez clientes simulados, quatro fizeram perguntas triviais — "vcs
aceitam cartão?", "quanto fica a entrega?", "tem sorvete sem açúcar?", "que
horas vocês abrem?" — e as quatro ouviram "não entendi". Uma delas foi parar no
atendimento humano por causa disso.

Duas regras governam este módulo:

1. **Só responde o que o sistema sabe de verdade.** Forma de pagamento e taxa
   de entrega são fato do sistema (Pix, `DELIVERY_FEE`); preço e
   disponibilidade saem do catálogo do dia. Horário, endereço da loja e área
   de entrega só são respondidos se o lojista tiver configurado (`STORE_*`);
   senão o bot admite que não sabe. Inventar horário de loja é pior do que
   não responder.
2. **O assunto que a IA classificou é palpite; o texto do cliente é prova.**
   O modelo classificou "qual a forma de pagamento?" como `horario` e
   "aceitam cartão?" como `outro`, e o cliente ouviu "não sei responder" sobre
   a única forma de pagamento que o sistema tem. Quando a pergunta diz
   claramente do que se trata, é o texto que manda.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.agent import renderer as r
from app.domain.cart import Cart
from app.domain.catalog import CatalogSnapshot, normalize

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
            f"A taxa de entrega é *{r.money(taxa)}*, fixa para toda a região que "
            "atendemos.\nSe preferir retirar na loja, não tem taxa. 🛵🏠"
        )

    if assunto == "preco":
        return _precos(catalog, texto)

    if assunto in {"restricao", "disponibilidade"}:
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
