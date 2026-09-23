"""Tudo que o bot fala. Funções puras: texto entra, texto sai.

Duas regras deste arquivo, as duas vindas de teste com cliente de verdade:

1. **Nunca exigir uma palavra ou um número.** Nada de "digite *cardápio*",
   "responda *entrega* ou *retirada*", "responda com o número". Quem entende o
   cliente é a IA; o texto daqui convida, não comanda. O número continua
   existindo ao lado de cada opção porque ajuda quem quer ser rápido — mas
   "pistache", "o de pistache" e "12" chegam no mesmo lugar.
2. **Uma pergunta por mensagem, e nada de parede de texto.** O cardápio sai
   numa mensagem só, com os sabores agrupados; a lista de sabores não é
   repetida a cada engano.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable, Sequence

from app.domain.cart import Cart, CartItem
from app.domain.catalog import CatalogGroup, CatalogProduct, CatalogSnapshot

LOJA = "Mi Piace Gelateria"


def money(value: Decimal | int | float | str) -> str:
    """R$ 1.234,56 — ponto de milhar e vírgula decimal, como no Brasil."""
    amount = Decimal(str(value)).quantize(Decimal("0.01"))
    inteiro, centavos = f"{amount:,.2f}".split(".")
    return f"R$ {inteiro.replace(',', '.')},{centavos}"


def _com_preco(name: str, price: Decimal) -> str:
    return name if price <= 0 else f"{name} (+{money(price)})"


# ---------------------------------------------------------------------------
# Abertura
# ---------------------------------------------------------------------------

def greeting() -> str:
    return f"Oi! 🍨 Aqui é a *{LOJA}*."


def ask_what_they_want() -> str:
    return "O que você vai querer hoje? 😊"


# ---------------------------------------------------------------------------
# Cardápio — uma mensagem só, organizada
# ---------------------------------------------------------------------------

def _flavors_of(product: CatalogProduct) -> list[Any]:
    """Sabores disponíveis de um tamanho, sem repetir, na ordem do cardápio."""
    vistos: dict[str, Any] = {}
    for group in product.groups:
        for complement in group.available_complements:
            vistos.setdefault(complement.name, complement)
    return list(vistos.values())


def _flavor_block(flavors: Sequence[Any], titulo: str = "Sabores de hoje") -> list[str]:
    """Sabores agrupados por categoria, em linha corrida.

    Trinta e um sabores, um por linha, viram uma parede que ninguém lê — e no
    WhatsApp ainda custa rolagem a cada erro. Agrupados por "Sem lactose" /
    "Com lactose" e separados por ·, cabem em poucas linhas e ainda respondem
    de antemão a pergunta mais comum da gelateria.
    """
    if not flavors:
        return []

    por_categoria: dict[str, list[str]] = {}
    for flavor in flavors:
        categoria = getattr(flavor, "category", None) or "Sabores"
        por_categoria.setdefault(categoria, []).append(
            _com_preco(flavor.name, flavor.extra_price)
        )

    linhas = [f"*{titulo}* ({len(flavors)})"]
    if len(por_categoria) == 1:
        linhas.append(" · ".join(next(iter(por_categoria.values()))))
        return linhas

    for categoria, nomes in por_categoria.items():
        linhas.append(f"_{categoria}_: " + " · ".join(nomes))
    return linhas


def menu(catalog: CatalogSnapshot) -> str:
    """O cardápio inteiro numa mensagem: tamanhos, preços e sabores."""
    products = catalog.available_products
    if not products:
        return "Hoje estamos sem itens disponíveis. 😔"

    por_produto = {p.name: _flavors_of(p) for p in products}
    conjuntos = {frozenset(f.name for f in v) for v in por_produto.values() if v}
    sabores_iguais = len(conjuntos) == 1

    linhas = [f"🍨 *{LOJA}* — cardápio de hoje", ""]
    for index, product in enumerate(products, start=1):
        linhas.append(f"{index}. *{product.name}* — {money(product.base_price)}")
        if product.description:
            linhas.append(f"   _{product.description}_")
        if not sabores_iguais and por_produto[product.name]:
            linhas.append(
                "   " + " · ".join(f.name for f in por_produto[product.name])
            )

    if sabores_iguais:
        # O primeiro produto pode não ter sabor nenhum (o cascão), e a lista
        # comum tem que sair do primeiro que tem — senão o bloco vem vazio.
        comuns = next((v for v in por_produto.values() if v), [])
        if comuns:
            linhas.append("")
            linhas.extend(_flavor_block(comuns))

    linhas.append("")
    linhas.append("É só me dizer o que você quer que eu monto pra você. 😊")
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Escolha do item
# ---------------------------------------------------------------------------

def product_ambiguous(candidates: Sequence[CatalogProduct]) -> str:
    """Ambiguidade de verdade: perguntar é melhor que chutar caro."""
    nomes = [f"*{c.name}* ({money(c.base_price)})" for c in candidates]
    if len(nomes) == 2:
        return f"Você quer o {nomes[0]} ou o {nomes[1]}?"
    return "Qual desses você quer?\n" + "\n".join(f"• {n}" for n in nomes)


def product_unavailable(name: str) -> str:
    return f"O *{name}* acabou hoje. 😔 Posso te sugerir outro?"


def product_not_found(query: str) -> str:
    """O cliente entendeu-se perfeitamente; é a casa que não tem aquilo.

    É diferente de não entender, e a resposta também tem que ser: "não
    trabalhamos com açaí" resolve; "não entendi" deixa o cliente no escuro.
    """
    return f'Não trabalhamos com "{query}" 🙈 Mas olha o que tem hoje:'


def ask_which_item(cart: Cart) -> str:
    linhas = ["Qual deles?"]
    for index, item in enumerate(cart.items, start=1):
        linhas.append(f"{index}. {item.quantity}x {item.product_name}")
    return "\n".join(linhas)


def ask_clarification() -> str:
    return "Só pra eu não errar: como exatamente você quer?"


# ---------------------------------------------------------------------------
# Sabores
# ---------------------------------------------------------------------------

def ask_flavors(
    product: CatalogProduct, group: CatalogGroup, chosen: Sequence[str] = ()
) -> str:
    """A pergunta dos sabores: o que falta, e as opções numa mensagem."""
    faltam = max(group.min_choices - len(chosen), 0)
    disponiveis = [c for c in group.available_complements if c.name not in chosen]

    if chosen:
        cabeca = (
            f"Anotei: *{', '.join(chosen)}*. "
            + (f"Falta {faltam} sabor. 😉" if faltam == 1 else f"Faltam {faltam}. 😉")
        )
    else:
        quantos = group.min_choices
        cabeca = (
            f"Fechado, *{product.name}*! "
            + (
                "Me diz o sabor. 😋"
                if quantos == 1
                else f"Me diz os {quantos} sabores. 😋"
            )
        )

    linhas = [cabeca, ""]
    linhas.extend(_flavor_block(disponiveis, titulo="Opções"))
    return "\n".join(linhas)


def resume_flavors(
    product: CatalogProduct, group: CatalogGroup, chosen: Sequence[str] = ()
) -> str:
    """Retomada curta depois de uma pergunta — sem repetir a lista inteira."""
    faltam = max(group.min_choices - len(chosen), 0)
    if not chosen:
        return f"Voltando ao seu *{product.name}*: me diz os sabores. 😊"
    if faltam <= 0:
        return f"Voltando ao seu *{product.name}*: quer mais alguma coisa?"
    return (
        f"Voltando: no seu *{product.name}* já tenho *{', '.join(chosen)}*. "
        + ("Falta 1 sabor." if faltam == 1 else f"Faltam {faltam} sabores.")
    )


def flavor_removed(name: str) -> str:
    return f"Tirei o *{name}*."


def flavor_already_chosen(name: str) -> str:
    return f"O *{name}* já está nesse pote — não dá pra repetir o mesmo sabor. 😊"


def complement_not_found(query: str, group: CatalogGroup) -> str:
    return f'Não achei "{query}" nos sabores de hoje. 🙈'


def complement_unavailable(name: str) -> str:
    return f"*{name}* acabou hoje. 😔 Escolhe outro pra mim?"


def group_full(group: CatalogGroup) -> str:
    return f"Esse pote já está completo com {group.max_choices} sabores. 😉"


def item_has_no_flavors(name: str) -> str:
    return f"O *{name}* não leva escolha de sabor. 😊"


# ---------------------------------------------------------------------------
# Carrinho
# ---------------------------------------------------------------------------

def _item_line(index: int, item: CartItem) -> str:
    line = f"{index}. {item.quantity}x *{item.product_name}* — {money(item.line_total)}"
    if item.complements:
        line += "\n   " + ", ".join(c.name for c in item.complements)
    if item.details:
        line += f"\n   _{item.details}_"
    return line


def cart_summary(cart: Cart) -> str:
    if cart.is_empty:
        return cart_empty()
    linhas = ["*Seu pedido*"]
    for index, item in enumerate(cart.items, start=1):
        linhas.append(_item_line(index, item))
    linhas.append(f"\nSubtotal: *{money(cart.subtotal)}*")
    return "\n".join(linhas)


def cart_empty() -> str:
    return "Seu pedido está vazio por enquanto. 🛒"


def item_added(item: CartItem) -> str:
    sabores = f" ({', '.join(c.name for c in item.complements)})" if item.complements else ""
    return f"Anotado: {item.quantity}x *{item.product_name}*{sabores} ✅"


def item_updated(item: CartItem) -> str:
    sabores = ", ".join(c.name for c in item.complements)
    return f"Ficou assim: *{item.product_name}* — {sabores}. ✅"


def item_removed(name: str) -> str:
    return f"Tirei o *{name}* do pedido. 👍"


def quantity_updated(item: CartItem) -> str:
    return f"Ajustei para {item.quantity}x *{item.product_name}*. 👍"


def product_switched(antigo: str, novo: str) -> str:
    return f"Sem problema — troquei o *{antigo}* pelo *{novo}*. 👍"


def ask_more_or_close(cart: Cart) -> str:
    return f"{cart_summary(cart)}\n\nQuer mais alguma coisa ou já posso fechar?"


def total_reply(cart: Cart, delivery_fee: Decimal, *, is_pickup: bool) -> str:
    """Quanto deu — com a taxa calculada pelo backend, nunca pela IA."""
    total = cart.total(Decimal("0") if is_pickup else delivery_fee)
    linhas = [cart_summary(cart), ""]
    if is_pickup:
        linhas.append("Retirada na loja — sem taxa.")
    elif delivery_fee > 0:
        linhas.append(f"Taxa de entrega: {money(delivery_fee)}")
    linhas.append(f"*Total: {money(total)}*")
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Entrega e endereço
# ---------------------------------------------------------------------------

_FIELD_LABELS = {
    "rua": "o nome da rua",
    "numero": "o número",
    "bairro": "o bairro",
}


def ask_fulfillment() -> str:
    """Perguntado antes do endereço: pedir a rua de quem vai buscar irrita."""
    return "Você prefere que a gente entregue ou vai retirar na loja? 🛵🏠"


def ask_address(missing: Iterable[str]) -> str:
    campos = list(missing)
    if not campos:
        return "Pode me confirmar o endereço da entrega?"
    if len(campos) >= 3:
        return (
            "Me passa o endereço da entrega, por favor. 🛵\n"
            "_Exemplo: Rua das Flores, 123, Centro_"
        )
    labels = [_FIELD_LABELS.get(f, f) for f in campos]
    if len(labels) == 1:
        return f"Só falta {labels[0]}. Pode me mandar?"
    return f"Só faltam {' e '.join(labels)}. Pode me mandar?"


def confirm_saved_address(address: dict[str, Any]) -> str:
    return f"Seu último endereço foi:\n{format_address(address)}\n\nPode ser esse mesmo?"


def format_address(address: dict[str, Any] | None) -> str:
    if not address:
        return "—"
    partes = [f"{address.get('rua', '')}, {address.get('numero', '')}"]
    if address.get("bairro"):
        partes.append(address["bairro"])
    if address.get("complemento"):
        partes.append(address["complemento"])
    texto = " - ".join(p for p in partes if p and p.strip(" ,"))
    if address.get("referencia"):
        texto += f"\n_Referência: {address['referencia']}_"
    return texto


# ---------------------------------------------------------------------------
# Confirmação, Pix e pós-pagamento
# ---------------------------------------------------------------------------

def final_summary(
    cart: Cart,
    *,
    delivery_fee: Decimal,
    address: dict[str, Any] | None,
    is_pickup: bool = False,
) -> str:
    """Resumo antes do Pix — a barreira antes de qualquer cobrança."""
    linhas = ["*Confere pra mim?* 📝", ""]
    for index, item in enumerate(cart.items, start=1):
        linhas.append(_item_line(index, item))
    linhas.append("")
    linhas.append(f"Subtotal: {money(cart.subtotal)}")
    if is_pickup:
        linhas.append("Retirada na loja — sem taxa de entrega")
        total = cart.total(Decimal("0"))
    else:
        linhas.append(f"Taxa de entrega: {money(delivery_fee)}")
        linhas.append(f"Entregar em: {format_address(address)}")
        total = cart.total(delivery_fee)
    linhas.append(f"*Total: {money(total)}*")
    linhas.append("")
    linhas.append("Tá certo assim? Se estiver, eu já mando o Pix. 😊")
    return "\n".join(linhas)


def confirm_once_more() -> str:
    """Resposta morna na hora de cobrar: pergunta uma vez mais, sem cobrar."""
    return "Só pra eu ter certeza antes de gerar o Pix: pode confirmar o pedido? 😊"


def ask_confirm_short() -> str:
    """Relembra a confirmação sem reimprimir dez linhas de resumo."""
    return "Me confirma que está certo que eu mando o Pix. 😊"


def pix_message(
    *,
    order_code: str,
    total: Decimal,
    qr_code: str | None,
    expires_minutes: int | None = None,
) -> str:
    linhas = [
        f"Pedido *{order_code}* registrado! 🎉",
        f"Valor: *{money(total)}*",
        "",
        "Pague com o Pix copia e cola abaixo:",
    ]
    if qr_code:
        linhas.append("")
        linhas.append(qr_code)
        linhas.append("")
    if expires_minutes:
        linhas.append(f"_O código vale por {expires_minutes} minutos._")
    linhas.append("Assim que o pagamento cair, eu te aviso por aqui. 😉")
    return "\n".join(linhas)


def pix_failed() -> str:
    """Provedor de pagamento fora do ar na hora de gerar a cobrança."""
    return (
        "Tive um problema para gerar a cobrança agora. 😔 "
        "Quer que eu tente de novo?"
    )


def payment_confirmed(order_code: str) -> str:
    return (
        f"Pagamento confirmado! ✅ Pedido *{order_code}* já foi para a produção.\n"
        "Obrigado pela preferência — logo mais o gelato chega até você. 🍨"
    )


def order_status(summary: Any) -> str:
    """Status do pedido a partir do OrderSummary do serviço de pedidos."""
    code = getattr(summary, "code", "—")
    status = getattr(summary, "status", "—")
    payment = getattr(summary, "payment_status", "—")
    total = getattr(summary, "total", None)
    linhas = [f"Pedido *{code}*", f"Situação: *{status}*", f"Pagamento: *{payment}*"]
    if total is not None:
        linhas.append(f"Total: {money(total)}")
    return "\n".join(linhas)


def no_active_order() -> str:
    return "Não achei nenhum pedido em aberto no seu número. Quer fazer um agora? 🍨"


# ---------------------------------------------------------------------------
# Reparo e atendimento humano
# ---------------------------------------------------------------------------

def didnt_get_it() -> str:
    """Primeira tentativa: pede de outro jeito, sem despejar o cardápio."""
    return "Desculpa, não peguei essa. 😅 Me explica de outro jeito?"


def didnt_get_it_again() -> str:
    return "Ainda não consegui entender direito. 🙈 Me diz com outras palavras?"


def offer_human() -> str:
    """Oferece gente — sem calar o bot, que continua atendendo."""
    return (
        "Quer que eu chame alguém do time pra te ajudar? "
        "Se preferir, a gente continua por aqui mesmo. 🙂"
    )


def handoff() -> str:
    return (
        f"Já chamei uma pessoa do time da {LOJA} pra falar com você. 👋\n"
        "Enquanto isso, se quiser, eu sigo com seu pedido por aqui."
    )


def still_waiting_human() -> str:
    """O cliente insistiu e ninguém da loja apareceu ainda.

    O silêncio total era o defeito mais caro do agente: quem pedia atendente
    não recebia mais nada, nem resposta a "cancela".
    """
    return (
        "Ainda estou aguardando alguém da equipe aparecer por aqui. 🙏\n"
        "Se preferir, posso continuar seu pedido comigo mesmo — é só me dizer."
    )


def back_from_human() -> str:
    return "Combinado, sigo com você por aqui! 😊"


def cancelled() -> str:
    return "Tudo bem, cancelei o pedido. 🙂 Quando quiser é só chamar!"
