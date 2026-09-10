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


def menu(catalog: CatalogSnapshot) -> str:
    """Cardápio numerado — o número é uma forma válida de resposta."""
    products = catalog.available_products
    if not products:
        return "Estamos sem itens disponíveis no momento. 😔"

    lines = ["*Cardápio de hoje*"]
    for index, product in enumerate(products, start=1):
        line = f"{index}. *{product.name}* — {money(product.base_price)}"
        if product.description:
            line += f"\n   _{product.description}_"
        lines.append(line)
    lines.append("\nÉ só me dizer o nome ou o número do que você quer. 😊")
    return "\n".join(lines)


def ask_product() -> str:
    return "O que você vai querer? Pode falar o nome ou o número do cardápio."


def product_not_found(query: str) -> str:
    return (
        f'Não achei "{query}" no nosso cardápio. 🤔\n'
        "Pode conferir e me dizer de novo? Digite *cardápio* para ver as opções."
    )


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
) -> str:
    """A loja só trabalha com entrega — resumo sempre mostra taxa e endereço."""
    lines = ["*Confirma o pedido?* 📝", ""]
    for index, item in enumerate(cart.items, start=1):
        lines.append(_item_line(index, item))
    lines.append("")
    lines.append(f"Subtotal: {money(cart.subtotal)}")
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


def payment_pending_reminder(order_code: str) -> str:
    return (
        f"Seu pedido *{order_code}* está aguardando o pagamento do Pix. 💳\n"
        "Assim que cair, eu te aviso na hora!"
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


def fallback(attempt: int = 1) -> str:
    if attempt <= 1:
        return "Desculpa, não entendi. 😅 Pode escrever de outro jeito?"
    return (
        "Ainda não consegui entender. 🙈 "
        "Você pode digitar *cardápio* para ver as opções ou *atendente* "
        "para falar com uma pessoa."
    )


def already_paid_flow() -> str:
    return (
        "Seu pedido já está pago e em preparo. 😄 "
        "Se quiser fazer outro, é só mandar *oi*!"
    )
