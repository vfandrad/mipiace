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

from collections.abc import Iterable, Sequence
from decimal import Decimal
from typing import Any

from app.configuracao import get_settings
from app.dominio import Cart, CartItem, CatalogGroup, CatalogProduct, CatalogSnapshot


def _loja() -> str:
    """O nome da loja vem da configuração, nunca do código.

    A Mi Piace é o primeiro caso de uso, não o sistema: a mesma imagem atende
    uma açaiteria mudando `STORE_NAME` no ambiente.
    """
    return get_settings().store_name


def _emoji() -> str:
    """Emoji da casa, com o espaço já embutido — vazio some sem deixar buraco."""
    emoji = get_settings().store_emoji.strip()
    return f"{emoji} " if emoji else ""


def em_reais(value: Decimal | int | float | str) -> str:
    """R$ 1.234,56 — ponto de milhar e vírgula decimal, como no Brasil."""
    amount = Decimal(str(value)).quantize(Decimal("0.01"))
    inteiro, centavos = f"{amount:,.2f}".split(".")
    return f"R$ {inteiro.replace(',', '.')},{centavos}"


def _com_preco(name: str, price: Decimal) -> str:
    return name if price <= 0 else f"{name} (+{em_reais(price)})"


# ---------------------------------------------------------------------------
# Abertura
# ---------------------------------------------------------------------------

def saudacao() -> str:
    return f"Oi! {_emoji()}Aqui é a *{_loja()}*."


def perguntar_o_que_quer() -> str:
    return "O que você vai querer hoje? 😊"


# ---------------------------------------------------------------------------
# Cardápio — uma mensagem só, organizada
# ---------------------------------------------------------------------------

def _sabores_do_produto(product: CatalogProduct) -> list[Any]:
    """Sabores disponíveis de um tamanho, sem repetir, na ordem do cardápio."""
    vistos: dict[str, Any] = {}
    for group in product.groups:
        for complement in group.available_complements:
            vistos.setdefault(complement.name, complement)
    return list(vistos.values())


#: Quantos sabores cabem numa linha antes de quebrar. Um cardápio de
#: gelateria de verdade passa de 30 sabores — tudo numa linha corrida vira
#: parede que o WhatsApp quebra onde bem entende, e ilegível é ilegível dos
#: dois jeitos (uma linha gigante ou 30 linhas de uma palavra só).
_SABORES_POR_LINHA = 4


def _em_grupos(itens: Sequence[str], tamanho: int) -> list[list[str]]:
    return [list(itens[i : i + tamanho]) for i in range(0, len(itens), tamanho)]


def _bloco_de_sabores(flavors: Sequence[Any], titulo: str = "Sabores de hoje") -> list[str]:
    """Sabores agrupados por categoria, em linhas curtas e escaneáveis.

    Agrupados por "Sem lactose" / "Com lactose" (quando existe mais de uma
    categoria) e quebrados de poucos em poucos por linha — cabe na tela do
    celular sem rolagem horizontal e sem virar uma lista infinita vertical.
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
    varias_categorias = len(por_categoria) > 1
    for categoria, nomes in por_categoria.items():
        if varias_categorias:
            # Negrito, não itálico: é um cabeçalho de seção, e itálico some na
            # tela pequena do WhatsApp — precisa ser o que salta aos olhos ao
            # rolar rápido, não o texto mais discreto da mensagem.
            linhas.append(f"*{categoria}* ({len(nomes)})")
        for grupo in _em_grupos(nomes, _SABORES_POR_LINHA):
            linhas.append("▫ " + ", ".join(grupo))
    return linhas


def cardapio(catalog: CatalogSnapshot) -> str:
    """O cardápio inteiro numa mensagem: tamanhos, preços e sabores."""
    products = catalog.available_products
    if not products:
        return "Hoje estamos sem itens disponíveis. 😔"

    por_produto = {p.name: _sabores_do_produto(p) for p in products}
    conjuntos = {frozenset(f.name for f in v) for v in por_produto.values() if v}
    sabores_iguais = len(conjuntos) == 1

    # Sem numeração: o cliente pede pelo nome ("o grande", "um médio"), e uma
    # lista numerada convida a responder "2" — que é justamente a muleta que
    # este agente não deveria precisar. A ordem continua existindo para quem
    # responder assim mesmo; ela só não é mais a interface.
    # A mensagem inteira do título em negrito, não só o nome da loja: numa
    # tela de WhatsApp, é essa linha que precisa ser reconhecida como
    # cabeçalho num piscar de olhos, antes de o cliente ler qualquer coisa.
    linhas = [f"*{_emoji()}{_loja()} — cardápio de hoje*", "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬", ""]
    for product in products:
        linhas.append(f"• *{product.name}* — {em_reais(product.base_price)}")
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
            linhas.extend(_bloco_de_sabores(comuns))

    linhas.append("")
    linhas.append("É só me dizer o que você quer que eu monto pra você. 😊")
    return "\n".join(linhas)


def cardapio_ja_mostrado() -> str:
    """O cardápio inteiro já saiu nesta conversa — mandar tudo de novo é spam.

    Não ignora o pedido do cliente: convida a perguntar algo específico (um
    sabor, um tamanho) em vez de repetir a parede de texto inteira.
    """
    return "Já te mandei o cardápio aqui em cima! 😊 Quer que eu repita algum sabor ou tamanho específico?"


def lista_de_sabores(flavors: Sequence[Any], titulo: str = "Sabores de hoje") -> str:
    """Só os sabores, sem o cardápio inteiro em volta.

    Para quem perguntou "quais sabores vocês têm?" ou "tem alguma coisa sem
    lactose?" — perguntas que o bot respondia com "não sei", apesar de a
    resposta estar no catálogo que ele imprime duas mensagens depois.
    """
    if not flavors:
        return "Hoje estamos sem sabores disponíveis. 😔"
    return "\n".join(_bloco_de_sabores(flavors, titulo))


# ---------------------------------------------------------------------------
# Escolha do item
# ---------------------------------------------------------------------------

def produto_ambiguo(candidates: Sequence[CatalogProduct]) -> str:
    """Ambiguidade de verdade: perguntar é melhor que chutar caro."""
    nomes = [f"*{c.name}* ({em_reais(c.base_price)})" for c in candidates]
    if len(nomes) == 2:
        return f"Você quer o {nomes[0]} ou o {nomes[1]}?"
    return "Qual desses você quer?\n" + "\n".join(f"• {n}" for n in nomes)


def produto_esgotado(name: str) -> str:
    return f"O *{name}* acabou hoje. 😔 Posso te sugerir outro?"


def produto_inexistente(query: str) -> str:
    """O cliente entendeu-se perfeitamente; é a casa que não tem aquilo.

    É diferente de não entender, e a resposta também tem que ser: "não
    trabalhamos com açaí" resolve; "não entendi" deixa o cliente no escuro.
    """
    return f'Não trabalhamos com "{query}" 🙈 Mas olha o que tem hoje:'


def perguntar_qual_item(cart: Cart) -> str:
    linhas = ["Qual deles?"]
    for index, item in enumerate(cart.items, start=1):
        linhas.append(f"{index}. {item.quantity}x {item.product_name}")
    return "\n".join(linhas)


def pedir_para_repetir() -> str:
    return "Só pra eu não errar: como exatamente você quer?"


# ---------------------------------------------------------------------------
# Sabores
# ---------------------------------------------------------------------------

def perguntar_sabores(
    product: CatalogProduct,
    group: CatalogGroup,
    chosen: Sequence[str] = (),
    *,
    posicao: int | None = None,
) -> str:
    """A pergunta dos sabores: o que falta, e as opções numa mensagem.

    `posicao` só é usada quando o pedido tem mais de um item: aí o cliente
    precisa saber de qual deles estamos falando.
    """
    de_qual = f" do item {posicao}" if posicao else ""
    faltam = max(group.min_choices - len(chosen), 0)
    disponiveis = [c for c in group.available_complements if c.name not in chosen]

    if chosen:
        cabeca = (
            f"Anotei{de_qual}: *{', '.join(chosen)}*. "
            + (f"Falta {faltam} sabor. 😉" if faltam == 1 else f"Faltam {faltam}. 😉")
        )
    else:
        quantos = group.min_choices
        cabeca = (
            f"Fechado, *{product.name}*{de_qual}! "
            + (
                "Me diz o sabor. 😋"
                if quantos == 1
                else f"Me diz os {quantos} sabores. 😋"
            )
        )

    linhas = [cabeca, ""]
    linhas.extend(_bloco_de_sabores(disponiveis, titulo="Opções"))
    return "\n".join(linhas)


def retomar_sabores(
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


def falta_para_fechar(product: CatalogProduct) -> str:
    """Ele pediu para fechar e falta escolher sabor — diga isso, não repita a pergunta."""
    return (
        f"Fecho já — só falta escolher os sabores do seu *{product.name}*. 😊"
    )


def sabor_removido(name: str) -> str:
    return f"Tirei o *{name}*."


def sabor_repetido(name: str) -> str:
    return f"O *{name}* já está nesse item — não dá pra repetir a mesma opção. 😊"


def complemento_inexistente(query: str, group: CatalogGroup) -> str:
    return f'Não achei "{query}" nos sabores de hoje. 🙈'


def complemento_esgotado(name: str) -> str:
    return f"*{name}* acabou hoje. 😔 Escolhe outro pra mim?"


def grupo_cheio(group: CatalogGroup) -> str:
    return f"Esse item já está completo com {group.max_choices} opções. 😉"


def item_sem_sabores(name: str) -> str:
    return f"O *{name}* não leva escolha de sabor. 😊"


# ---------------------------------------------------------------------------
# Carrinho
# ---------------------------------------------------------------------------

def _linha_do_item(index: int, item: CartItem, *, montando: bool = False) -> str:
    line = f"{index}. {item.quantity}x *{item.product_name}* — {em_reais(item.line_total)}"
    if montando:
        line += "  _(montando)_"
    if item.complements:
        line += "\n   " + ", ".join(c.name for c in item.complements)
    if item.details:
        line += f"\n   _{item.details}_"
    return line


def resumo_do_pedido(cart: Cart, *, pending: int | None = None) -> str:
    """O pedido como o cliente vê — inclusive o item que ainda falta fechar.

    `pending` é o índice (base 0) do item em montagem. Ele aparece na lista
    com a mesma numeração que a IA recebe: um item, um número, para todo
    mundo. Antes o item em montagem ficava fora do carrinho, e o cliente
    dizia "tira o médio" olhando para uma lista que o sistema não tinha.
    """
    if cart.is_empty:
        return pedido_vazio()
    linhas = ["*Seu pedido*"]
    for index, item in enumerate(cart.items, start=1):
        linhas.append(_linha_do_item(index, item, montando=pending == index - 1))
    linhas.append(f"\n• Subtotal: *{em_reais(cart.subtotal)}*")
    return "\n".join(linhas)


def pedido_vazio() -> str:
    return "Seu pedido está vazio por enquanto. 🛒"


def item_adicionado(item: CartItem) -> str:
    sabores = f" ({', '.join(c.name for c in item.complements)})" if item.complements else ""
    return f"Anotado: {item.quantity}x *{item.product_name}*{sabores} ✅"


def item_alterado(item: CartItem) -> str:
    sabores = ", ".join(c.name for c in item.complements)
    return f"Ficou assim: *{item.product_name}* — {sabores}. ✅"


def item_removido(name: str) -> str:
    return f"Tirei o *{name}* do pedido. 👍"


def quantidade_alterada(item: CartItem) -> str:
    return f"Ajustei para {item.quantity}x *{item.product_name}*. 👍"


def produto_trocado(antigo: str, novo: str) -> str:
    return f"Sem problema — troquei o *{antigo}* pelo *{novo}*. 👍"


def sabores_perdidos_na_troca(nomes: list[str]) -> str:
    """Trocar de tamanho às vezes deixa sabor de fora — o cliente tem que saber qual."""
    if len(nomes) == 1:
        return f"O tamanho novo não cabe todos os sabores — tirei o *{nomes[0]}*. 😉"
    lista = ", ".join(f"*{nome}*" for nome in nomes)
    return f"O tamanho novo não cabe todos os sabores — tirei {lista}. 😉"


def perguntar_se_quer_mais_curto() -> str:
    """A pergunta sozinha, para quando o carrinho já está na tela."""
    return "Quer mais alguma coisa ou já posso fechar? 😊"


def perguntar_se_quer_mais(cart: Cart, *, pending: int | None = None) -> str:
    resumo = resumo_do_pedido(cart, pending=pending)
    return f"{resumo}\n\nQuer mais alguma coisa ou já posso fechar?"


def resposta_do_total(
    cart: Cart, delivery_fee: Decimal, *, is_pickup: bool | None, pending: int | None = None
) -> str:
    """Quanto deu — com a taxa calculada pelo backend, nunca pela IA.

    `is_pickup=None` é "ainda não perguntamos". Cobrar a taxa de entrega por
    padrão nesse caso inflava o total de quem ia retirar na loja antes de o
    cliente ter dito o que queria — melhor mostrar o subtotal e perguntar.
    """
    linhas = [resumo_do_pedido(cart, pending=pending), ""]
    if is_pickup is None:
        linhas.append(
            f"Isso é sem taxa. Com entrega, some {em_reais(delivery_fee)}. "
            "Vai ser entrega ou retirada? 🛵🏠"
        )
        return "\n".join(linhas)
    total = cart.total(Decimal("0") if is_pickup else delivery_fee)
    if is_pickup:
        linhas.append("• Retirada na loja — sem taxa.")
    elif delivery_fee > 0:
        linhas.append(f"• Taxa de entrega: {em_reais(delivery_fee)}")
    linhas.append(f"*Total: {em_reais(total)}*")
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Entrega e endereço
# ---------------------------------------------------------------------------

_NOMES_DOS_CAMPOS = {
    "rua": "o nome da rua",
    "numero": "o número",
    "bairro": "o bairro",
}


def entrega_anotada(kind: Any) -> str:
    """O bot diz que anotou a forma de entrega.

    Anotar calado fazia o cliente repetir: ele dizia "quero entrega", recebia
    o resumo do carrinho de volta e achava que a mensagem tinha se perdido.
    """
    if getattr(kind, "value", kind) == "retirada":
        return "Beleza, *retirada na loja* — sem taxa de entrega. 🏠"
    return "Anotado: *entrega*. 🛵"


def endereco_salvo(address: dict[str, Any], *, novo_para_entrega: bool = False) -> str:
    inicio = "Perfeito, vou entregar em" if novo_para_entrega else "Endereço anotado"
    return "\n".join([f"{inicio}:", formatar_endereco(address)])


def perguntar_entrega_ou_retirada() -> str:
    """Perguntado antes do endereço: pedir a rua de quem vai buscar irrita."""
    return "Você prefere que a gente entregue ou vai retirar na loja? 🛵🏠"


def perguntar_endereco(missing: Iterable[str]) -> str:
    campos = list(missing)
    if not campos:
        return "Pode me confirmar o endereço da entrega?"
    if len(campos) >= 3:
        return (
            "Me passa o endereço da entrega, por favor. 🛵\n"
            "_Exemplo: Rua das Flores, 123, Centro_"
        )
    labels = [_NOMES_DOS_CAMPOS.get(f, f) for f in campos]
    if len(labels) == 1:
        return f"Só falta {labels[0]}. Pode me mandar?"
    return f"Só faltam {' e '.join(labels)}. Pode me mandar?"



def formatar_endereco(address: dict[str, Any] | None) -> str:
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

def resumo_final(
    cart: Cart,
    *,
    delivery_fee: Decimal,
    address: dict[str, Any] | None,
    is_pickup: bool = False,
) -> str:
    """Resumo antes do Pix — a barreira antes de qualquer cobrança."""
    linhas = ["*Confere pra mim?* 📝", ""]
    for index, item in enumerate(cart.items, start=1):
        linhas.append(_linha_do_item(index, item))
    linhas.append("")
    linhas.append(f"• Subtotal: {em_reais(cart.subtotal)}")
    if is_pickup:
        linhas.append("• Retirada na loja — sem taxa de entrega")
        total = cart.total(Decimal("0"))
    else:
        linhas.append(f"• Taxa de entrega: {em_reais(delivery_fee)}")
        linhas.append(f"• Entregar em: {formatar_endereco(address)}")
        total = cart.total(delivery_fee)
    linhas.append(f"*Total: {em_reais(total)}*")
    linhas.append("")
    linhas.append("Tá certo assim? Se estiver, eu já mando o Pix. 😊")
    return "\n".join(linhas)


def confirmar_de_novo() -> str:
    """Resposta morna na hora de cobrar: pergunta uma vez mais, sem cobrar."""
    return "Só pra eu ter certeza antes de gerar o Pix: pode confirmar o pedido? 😊"


def perguntar_confirmacao_curta() -> str:
    """Relembra a confirmação sem reimprimir dez linhas de resumo."""
    return "Me confirma que está certo que eu mando o Pix. 😊"


def mensagem_do_pix(
    *,
    order_code: str,
    total: Decimal,
    qr_code: str | None,
    expires_minutes: int | None = None,
) -> list[str]:
    """Confirmação numa mensagem, o código Pix sozinho na próxima.

    Copia e cola só funciona bem no WhatsApp quando a bolha tem SÓ o código:
    com qualquer linha de texto junto (valor, prazo, "pague com o Pix
    abaixo"), o toque longo + *Copiar* seleciona a mensagem inteira, e o
    cliente tem que apagar o resto à mão antes de colar no banco.
    """
    linhas = [
        f"🎉 *Pedido {order_code} registrado!*",
        "",
        f"• Valor: *{em_reais(total)}*",
    ]
    if expires_minutes:
        linhas.append(f"• O código Pix vale por {expires_minutes} minutos")
    linhas.append("")
    if qr_code:
        linhas.append(
            "Pague com o código da próxima mensagem — copia e cola direto no "
            "seu banco. Assim que cair, eu te aviso por aqui. 😉"
        )
        return ["\n".join(linhas), qr_code]
    linhas.append("Assim que o pagamento cair, eu te aviso por aqui. 😉")
    return ["\n".join(linhas)]


def pix_falhou() -> str:
    """Provedor de pagamento fora do ar na hora de gerar a cobrança."""
    return (
        "Tive um problema para gerar a cobrança agora. 😔 "
        "Quer que eu tente de novo?"
    )


def pedido_aguardando_pagamento() -> str:
    """O cliente tenta mexer no pedido com o Pix já emitido.

    Antes o carrinho aceitava a mudança e o bot mostrava um pedido novo de
    R$ 9,00 para quem tinha um Pix de R$ 73,00 em aberto.
    """
    return (
        "Seu pedido já está fechado e esperando o pagamento do Pix. 💳\n"
        "Assim que ele cair eu te aviso — e aí a gente monta o próximo. "
        "Se preferir mudar alguma coisa agora, posso chamar alguém do time. 😊"
    )


def situacao_do_pedido(summary: Any) -> str:
    """Resposta a "qual sabor eu escolhi mesmo?" com o pedido já fora do carrinho.

    `place_order` esvazia o carrinho ao emitir o Pix; é o resumo do pedido já
    registrado que sobra para responder por ele — sem isto o cliente ouvia que
    o pedido dele "está vazio", como se tivesse sumido.

    Repetir o copia-e-cola aqui (quando ainda há um Pix pendente) importa mais
    do que parece: se o envio da mensagem original do Pix falhar (throttle,
    canal fora do ar), esta é a única outra porta pela qual o cliente consegue
    pagar sem precisar pedir ajuda de um atendente.
    """
    linhas = [f"Seu pedido *{summary.code}*:"]
    for item in summary.items:
        extras = f" ({', '.join(item.complements)})" if item.complements else ""
        linhas.append(f"{item.quantity}x {item.product_name}{extras} — {em_reais(item.line_total)}")
    linhas.append(f"\nTotal: *{em_reais(summary.total)}*")
    if summary.payment_status == "pago":
        linhas.append("Já está pago e confirmado. ✅")
    else:
        linhas.append("Ainda aguardando o pagamento do Pix. 💳")
        if summary.pix_qr_code:
            linhas.append(f"\nCopia e cola do Pix:\n{summary.pix_qr_code}")
    return "\n".join(linhas)


def pix_lembrete(*, order_code: str, qr_code: str | None, minutos_restantes: int) -> list[str]:
    """Lembrete de Pix pendente, para o cliente que some no meio do pagamento.

    Igual ao Pix original: código sozinho na própria mensagem, sem nenhuma
    linha junto, senão o toque longo + *Copiar* pega a bolha inteira.
    """
    urgente = minutos_restantes <= 10
    if urgente:
        abertura = f"Faltam só {minutos_restantes} minutos para o Pix do pedido *{order_code}* expirar! ⏰"
    else:
        abertura = f"Psst, vi que o Pix do pedido *{order_code}* ainda não caiu. 😉"
    linhas = [abertura]
    if not urgente:
        linhas.append(f"Ainda dá tempo — ele vale por mais {minutos_restantes} minutos.")
    if qr_code:
        linhas.append("")
        linhas.append("Segue o código de novo, copia e cola direto no seu banco:")
        return ["\n".join(linhas), qr_code]
    linhas.append("Me chama se precisar de ajuda para pagar. 😊")
    return ["\n".join(linhas)]


def pagamento_confirmado(order_code: str) -> str:
    return (
        f"Pagamento confirmado! ✅ Pedido *{order_code}* já foi para a produção.\n"
        f"Obrigado pela preferência — já já chega até você. {_emoji()}".rstrip()
    )




# ---------------------------------------------------------------------------
# Reparo e atendimento humano
# ---------------------------------------------------------------------------

def nao_entendi() -> str:
    """Primeira tentativa: pede de outro jeito, sem despejar o cardápio."""
    return "Desculpa, não peguei essa. 😅 Me explica de outro jeito?"


def nao_entendi_de_novo() -> str:
    return "Ainda não consegui entender direito. 🙈 Me diz com outras palavras?"


def oferecer_atendente() -> str:
    """Oferece gente — sem calar o bot, que continua atendendo."""
    return (
        "Quer que eu chame alguém do time pra te ajudar? "
        "Se preferir, a gente continua por aqui mesmo. 🙂"
    )


def audio_nao_transcrito() -> str:
    """Áudio que a gente não conseguiu ouvir — falha nossa, não do cliente.

    Não conta como "não entendi": o problema é da transcrição (Evolution fora
    do ar, áudio longo demais, chave da OpenAI ausente), não de o cliente ter
    falado algo confuso.
    """
    return (
        "Não consegui ouvir seu áudio agora. 🙈 "
        "Pode escrever ou tentar mandar de novo?"
    )


def chamou_atendente() -> str:
    return (
        f"Já chamei uma pessoa do time da {_loja()} pra falar com você. 👋\n"
        "Enquanto isso, se quiser, eu sigo com seu pedido por aqui."
    )


def ainda_esperando_atendente() -> str:
    """O cliente insistiu e ninguém da loja apareceu ainda.

    O silêncio total era o defeito mais caro do agente: quem pedia atendente
    não recebia mais nada, nem resposta a "cancela".
    """
    return (
        "Ainda estou aguardando alguém da equipe aparecer por aqui. 🙏\n"
        "Se preferir, posso continuar seu pedido comigo mesmo — é só me dizer."
    )


def ainda_esperando_atendente_curto() -> str:
    """Resposta curta enquanto o atendente não chega.

    Existe porque a alternativa era silêncio: o aviso longo saía uma vez e
    depois o bot parava de responder. Quem está esperando atendimento precisa
    saber que ainda está sendo ouvido, mesmo que a notícia seja "ainda não".
    """
    return "Ainda por aqui com você — assim que alguém do time aparecer, eu aviso. 🙏"


def voltou_do_atendente() -> str:
    return "Combinado, sigo com você por aqui! 😊"


def pedido_cancelado() -> str:
    return "Tudo bem, cancelei o pedido. 🙂 Quando quiser é só chamar!"


def confirmar_cancelamento() -> str:
    """Quando a IA entendeu "cancelar" e a frase do cliente não disse isso.

    Apagar o pedido por um palpite é o estrago mais caro do sistema: em
    conversa real, "deixa pra lá, continua vc mesmo" — que dispensava o
    atendente — zerou o carrinho. Perguntar custa uma mensagem.
    """
    return "Só confirmando: você quer cancelar o pedido? 🙂"
