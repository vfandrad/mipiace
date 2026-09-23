"""Todo o texto que o agente fala, num lugar só.

São funções puras (dados → string). Ficam separadas da máquina de estados por
dois motivos: dá para ajustar o tom da gelateria sem mexer em regra de negócio,
e dá para testar mensagem sem rodar o fluxo inteiro.

Formatação pensada para WhatsApp: linhas curtas, *negrito* com asterisco único,
emoji com parcimônia.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable, Sequence

from app.domain.cart import Cart, CartItem
from app.domain.catalog import CatalogGroup, CatalogProduct, CatalogSnapshot

# ---------------------------------------------------------------------------
# Formatação de valores
# ---------------------------------------------------------------------------

def money(value: Decimal | int | float | str) -> str:
    """Formata dinheiro no padrão brasileiro: R$ 12,50."""
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    quantized = amount.quantize(Decimal("0.01"))
    return f"R$ {quantized:.2f}".replace(".", ",")


def _bullet_price(name: str, price: Decimal) -> str:
    if price > 0:
        return f"{name} (+{money(price)})"
    return name


# ---------------------------------------------------------------------------
# Cardápio e abertura
# ---------------------------------------------------------------------------

def greeting() -> str:
    return (
        "Oi! 🍨 Aqui é a *Mi Piace Gelateria*.\n"
        "Vou te ajudar a montar seu pedido."
    )


def _flavors_of(product: CatalogProduct) -> list[str]:
    """Sabores disponíveis de um tamanho, na ordem do cardápio."""
    nomes: list[str] = []
    for group in product.groups:
        for complement in group.available_complements:
            if complement.name not in nomes:
                nomes.append(complement.name)
    return nomes


def menu(catalog: CatalogSnapshot) -> str:
    """Cardápio que o cliente recebe no WhatsApp.

    Duas decisões de formato, ambas pensadas para a tela do celular:

    * **Os sabores vêm junto.** Quem recebe só "M, G e COMBO" precisa
      perguntar "quais sabores tem?" — uma ida e volta a mais em toda
      conversa. Com a lista já no primeiro contato, o cliente responde
      "G de pistache e limão" de uma vez.
    * **Sabores em linha corrida, separados por ·**, e não um por linha.
      Trinta e um sabores em bullets viram uma parede de texto que se rola
      sem ler.

    A lista aparece uma vez só quando todos os tamanhos oferecem os mesmos
    sabores (o caso da casa). Se algum tamanho tiver sabores diferentes,
    cada um mostra os seus: repetir é feio, mas anunciar sabor que aquele
    tamanho não tem custa um pedido frustrado.
    """
    products = catalog.available_products
    if not products:
        return "Estamos sem itens disponíveis no momento. 😔"

    por_produto = {p.name: _flavors_of(p) for p in products}
    conjuntos = {frozenset(v) for v in por_produto.values() if v}
    sabores_iguais = len(conjuntos) == 1
    sabores_comuns = list(por_produto[products[0].name]) if sabores_iguais else []

    lines = ["🍨 *Mi Piace Gelateria* — cardápio de hoje", ""]
    for index, product in enumerate(products, start=1):
        lines.append(f"{index}. *{product.name}* — {money(product.base_price)}")
        if product.description:
            lines.append(f"   _{product.description}_")
        if not sabores_iguais and por_produto[product.name]:
            lines.append(f"   Sabores: {' · '.join(por_produto[product.name])}")

    if sabores_comuns:
        lines.append("")
        lines.append(f"*Sabores de hoje* ({len(sabores_comuns)})")
        lines.append(" · ".join(sabores_comuns))

    lines.append("")
    lines.append(
        "Me diz o tamanho pelo nome ou pelo número que eu já pergunto os "
        "sabores. 😊"
    )
    return "\n".join(lines)


def ask_product() -> str:
    return "O que você vai querer? Pode falar o nome ou o número do cardápio."


def product_ambiguous(candidates: Sequence[CatalogProduct]) -> str:
    lines = ["Temos mais de uma opção parecida. Qual delas?"]
    for index, product in enumerate(candidates, start=1):
        lines.append(f"{index}. *{product.name}* — {money(product.base_price)}")
    return "\n".join(lines)


def product_unavailable(name: str) -> str:
    return f"Poxa, *{name}* acabou por hoje. 😅 Quer escolher outro?"


# ---------------------------------------------------------------------------
# Personalização (grupos de complementos)
# ---------------------------------------------------------------------------

def group_question(
    product: CatalogProduct,
    group: CatalogGroup,
    chosen: Sequence[str] = (),
) -> str:
    """Pergunta de um grupo, com as opções numeradas e o quanto ainda falta."""
    options = group.available_complements
    remaining = max(group.min_choices - len(chosen), 0)

    if group.min_choices == group.max_choices and group.min_choices > 0:
        header = f"*{product.name}* — escolha {group.min_choices} de *{group.name}*:"
    elif group.max_choices > 1:
        header = f"*{product.name}* — escolha até {group.max_choices} de *{group.name}*:"
    else:
        header = f"*{product.name}* — qual *{group.name}*?"

    lines = [header]
    for index, complement in enumerate(options, start=1):
        lines.append(f"{index}. {_bullet_price(complement.name, complement.extra_price)}")

    if chosen:
        lines.append("\nJá anotei: " + ", ".join(chosen))
    if remaining > 0 and chosen:
        lines.append(f"Falta{'m' if remaining > 1 else ''} {remaining}. 😉")
    return "\n".join(lines)


def complement_not_found(query: str, group: CatalogGroup) -> str:
    names = ", ".join(c.name for c in group.available_complements)
    return (
        f'Não temos "{query}" em *{group.name}*. 🙈\n'
        f"As opções são: {names}."
    )


def complement_ambiguous(candidates: Sequence[Any]) -> str:
    lines = ["Qual desses você quis dizer?"]
    for index, complement in enumerate(candidates, start=1):
        lines.append(f"{index}. {complement.name}")
    return "\n".join(lines)


def complement_unavailable(name: str) -> str:
    return f"*{name}* está em falta hoje. 😔 Escolhe outro pra mim?"


def group_extra_choice(group: CatalogGroup, chosen: Sequence[str]) -> str:
    return (
        f"Anotado: {', '.join(chosen)}.\n"
        f"Quer mais alguma coisa em *{group.name}*? "
        "Responda *não* para seguir."
    )


def item_incomplete(product: CatalogProduct, group: CatalogGroup, remaining: int) -> str:
    """Cliente quis fechar/entregar antes de terminar o item em construção.

    Sem isto, "quero fechar" no meio dos sabores era tratado como sabor e o bot
    respondia 'Não temos "quero fechar" em Escolha 3 sabores' — verdadeiro e
    inútil. O que o cliente precisa saber é quanto falta.
    """
    plural = "m" if remaining > 1 else ""
    return (
        f"Falta{plural} {remaining} em *{group.name}* para eu fechar "
        f"o *{product.name}*. 😉"
    )


def too_many_choices(group: CatalogGroup) -> str:
    return f"Em *{group.name}* dá pra escolher no máximo {group.max_choices}. 😉"


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
        return "Seu carrinho está vazio. 🛒"
    lines = ["*Seu pedido até agora*"]
    for index, item in enumerate(cart.items, start=1):
        lines.append(_item_line(index, item))
    lines.append(f"\nSubtotal: *{money(cart.subtotal)}*")
    return "\n".join(lines)


def cart_added(item: CartItem, cart: Cart) -> str:
    return (
        f"Adicionei {item.quantity}x *{item.product_name}* ✅\n\n"
        f"{cart_summary(cart)}\n\n"
        "Quer *mais alguma coisa* ou posso *fechar* o pedido?"
    )


def ask_more_or_close(cart: Cart) -> str:
    return (
        f"{cart_summary(cart)}\n\n"
        "Quer adicionar mais alguma coisa ou posso *fechar*?"
    )


def cart_empty_on_close() -> str:
    return "Seu carrinho ainda está vazio. 🛒 Me diz o que você quer primeiro!"


# ---------------------------------------------------------------------------
# Entrega e endereço
# ---------------------------------------------------------------------------

_FIELD_LABELS = {
    "rua": "o nome da rua",
    "numero": "o número",
    "bairro": "o bairro",
}


def ask_fulfillment() -> str:
    """Entrega ou retirada — perguntado antes do endereço.

    Vem antes de propósito: pedir a rua de quem já disse que vai buscar na
    loja é a pergunta que mais irrita num atendimento de balcão.
    """
    return (
        "Você prefere *entrega* ou *retirada* na loja? 🛵🏠\n"
        "_Responda *entrega* ou *retirada*._"
    )


def ask_address(missing: Iterable[str]) -> str:
    fields = list(missing)
    if not fields:
        return "Pode me confirmar o endereço de entrega?"
    if len(fields) == 3:
        return (
            "Me passa o endereço da entrega, por favor. 🛵\n"
            "_Exemplo: Rua das Flores, 123, Centro_"
        )
    labels = [_FIELD_LABELS.get(f, f) for f in fields]
    if len(labels) == 1:
        return f"Só falta {labels[0]}. Pode me mandar?"
    return f"Só faltam {', '.join(labels[:-1])} e {labels[-1]}. Pode me mandar?"


def confirm_saved_address(address: dict[str, Any]) -> str:
    return (
        f"Vi que seu último endereço foi:\n{format_address(address)}\n\n"
        "Pode ser esse mesmo? (*sim* / *não*)"
    )


def format_address(address: dict[str, Any] | None) -> str:
    if not address:
        return "—"
    parts = [f"{address.get('rua', '')}, {address.get('numero', '')}"]
    if address.get("bairro"):
        parts.append(address["bairro"])
    if address.get("complemento"):
        parts.append(address["complemento"])
    text = " - ".join(p for p in parts if p and p.strip(" ,"))
    if address.get("referencia"):
        text += f"\n_Referência: {address['referencia']}_"
    return text


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
    """Resumo antes do Pix.

    Na retirada não existe taxa nem endereço, e mostrar "Taxa de entrega:
    R$ 0,00" com um endereço vazio só levanta dúvida em quem já disse que vai
    buscar na loja.
    """
    lines = ["*Confirma o pedido?* 📝", ""]
    for index, item in enumerate(cart.items, start=1):
        lines.append(_item_line(index, item))
    lines.append("")
    lines.append(f"Subtotal: {money(cart.subtotal)}")
    if is_pickup:
        lines.append("Retirada na loja — sem taxa de entrega")
        total = cart.total(Decimal("0"))
    else:
        lines.append(f"Taxa de entrega: {money(delivery_fee)}")
        lines.append(f"Entregar em: {format_address(address)}")
        total = cart.total(delivery_fee)
    lines.append(f"*Total: {money(total)}*")
    lines.append("")
    lines.append("Responda *sim* para confirmar ou *não* para ajustar.")
    return "\n".join(lines)


def pix_message(
    *,
    order_code: str,
    total: Decimal,
    qr_code: str | None,
    expires_minutes: int | None = None,
) -> str:
    lines = [
        f"Pedido *{order_code}* registrado! 🎉",
        f"Valor: *{money(total)}*",
        "",
        "Pague com o Pix copia e cola abaixo:",
    ]
    if qr_code:
        lines.append("")
        lines.append(qr_code)
        lines.append("")
    if expires_minutes:
        lines.append(f"_O código vale por {expires_minutes} minutos._")
    lines.append("Assim que o pagamento cair, eu te aviso por aqui. 😉")
    return "\n".join(lines)


def pix_failed() -> str:
    """Provedor de pagamento fora do ar na hora de gerar a cobrança."""
    return (
        "Tive um problema para gerar a cobrança agora. 😔 "
        "Pode tentar de novo em instantes ou digitar *atendente*."
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
    lines = [f"Pedido *{code}*", f"Situação: *{status}*", f"Pagamento: *{payment}*"]
    if total is not None:
        lines.append(f"Total: {money(total)}")
    return "\n".join(lines)


def no_active_order() -> str:
    return "Não achei nenhum pedido em aberto no seu número. Quer fazer um agora? 🍨"


# ---------------------------------------------------------------------------
# Saídas do fluxo
# ---------------------------------------------------------------------------

def cancelled() -> str:
    return "Tudo bem, cancelei o pedido. 🙂 Quando quiser é só chamar!"


def handoff() -> str:
    return (
        "Claro! Já chamei uma pessoa do time da Mi Piace pra te atender por aqui. 👋\n"
        "Só um instante."
    )


def fallback(attempt: int = 1, *, with_reprompt: bool = False) -> str:
    """Texto de incompreensão.

    Quando vem acompanhado da pergunta do estado (`with_reprompt`), ele não
    pede para o cliente "escrever de outro jeito" no vazio: a mensagem seguinte
    repete a pergunta com as opções na tela. Repetir "não entendi" sem mostrar
    saída nenhuma é o que empurrou o cliente do teste real para o atendimento
    humano em três mensagens.
    """
    if attempt <= 1:
        if with_reprompt:
            return "Desculpa, não peguei essa. 😅 Deixa eu repetir:"
        return "Desculpa, não entendi. 😅 Pode escrever de outro jeito?"
    return (
        "Ainda não consegui entender. 🙈 "
        "Você pode digitar *cardápio* para ver as opções ou *atendente* "
        "para falar com uma pessoa."
    )
