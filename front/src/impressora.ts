/**
 * Ficha do pedido na impressora térmica (EPSON, protocolo ePOS-Print XML).
 *
 * Manda o comando direto da tela para o IP da impressora, pela rede local do
 * balcão — sem driver nem plugin instalado. Funciona em qualquer impressora
 * EPSON "Smart"/Omni-link ligada por Ethernet ou Wi-Fi na mesma rede do
 * computador que roda o painel (TM-m30, TM-T20III/M352A e afins).
 *
 * Duas pegadinhas de quem for depurar isto no balcão:
 * 1. O painel roda em HTTPS e a impressora só fala HTTP — o navegador bloqueia
 *    isso como "conteúdo misto". No Chrome/Edge DESSE computador, abra as
 *    configurações do site do painel e permita "conteúdo não seguro" uma vez.
 * 2. `VITE_PRINTER_IP` é embutido no build do Vite — trocar o IP exige
 *    rebuildar a imagem do painel, não só reiniciar o container.
 */

import { PRINTER_IP } from '@/api';
import { formatAddress, formatCurrency, formatPhone } from '@/formato';
import type { Order } from '@/tipos';

function esc(texto: string): string {
  return texto.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/** Uma linha de texto normal, com quebra ao final. */
function l(texto = ''): string {
  return `${esc(texto)}\n`;
}

const SEPARADOR = '--------------------------------';

function montarConteudo(order: Order): string {
  const dataHora = new Intl.DateTimeFormat('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(order.created_at));

  const linhas: string[] = [];
  linhas.push(l(`Pedido ${order.code || '—'}`));
  linhas.push(l(dataHora));
  linhas.push(l(SEPARADOR));
  linhas.push(l(`Cliente: ${order.customer_name || 'Sem nome'}`));
  if (order.customer_phone) linhas.push(l(`Tel: ${formatPhone(order.customer_phone)}`));
  if (order.fulfillment_type === 'retirada') {
    linhas.push(l('Retirada na loja'));
  } else {
    const endereco = formatAddress(order);
    linhas.push(l(`Entrega: ${endereco ?? '(endereço não informado)'}`));
  }
  linhas.push(l(SEPARADOR));

  for (const item of order.items) {
    linhas.push(l(`${item.quantity}x ${item.product_name_snapshot} - ${formatCurrency(item.line_total)}`));
    if (item.complements.length > 0) {
      const sabores = item.complements.map((c) => c.complement_name_snapshot).join(', ');
      linhas.push(l(`  ${sabores}`));
    }
    if (item.details) linhas.push(l(`  ${item.details}`));
  }

  linhas.push(l(SEPARADOR));
  if (order.delivery_fee > 0) {
    linhas.push(l(`Subtotal: ${formatCurrency(order.subtotal)}`));
    linhas.push(l(`Taxa de entrega: ${formatCurrency(order.delivery_fee)}`));
  }
  linhas.push(l(`TOTAL: ${formatCurrency(order.total)}`));
  linhas.push(l(SEPARADOR));
  linhas.push(l(`Pagamento: ${order.payment_status === 'pago' ? 'PAGO' : 'PENDENTE'}`));
  if (order.notes) linhas.push(l(`Obs.: ${order.notes}`));

  return linhas.join('');
}

function buildEposXml(order: Order): string {
  const corpo = montarConteudo(order);
  return (
    '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">' +
    '<s:Body>' +
    '<epos-print xmlns="http://www.epson-pos.com/schemas/2011/03/epos-print">' +
    '<text lang="pt" align="center" width="2" height="2" em="true">' +
    l(order.code ? `PEDIDO ${order.code}` : 'PEDIDO') +
    '</text>' +
    `<text align="left" width="1" height="1" em="false">${corpo}</text>` +
    '<feed line="3"/>' +
    '<cut type="feed"/>' +
    '</epos-print>' +
    '</s:Body>' +
    '</s:Envelope>'
  );
}

export class PrinterError extends Error {}

/**
 * Manda a ficha para a impressora. Lança `PrinterError` se não deu — quem
 * chama decide se isso vira um toast (impressão manual) ou se é só logado
 * (impressão automática de pedido novo, que não pode travar a tela).
 */
export async function printOrder(order: Order): Promise<void> {
  if (!PRINTER_IP) {
    throw new PrinterError('Impressora não configurada (VITE_PRINTER_IP vazio).');
  }

  const url = `http://${PRINTER_IP}/cgi-bin/epos/service.cgi?devid=local_printer&timeout=10000`;
  let response: Response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'text/xml; charset=utf-8', SOAPAction: '""' },
      body: buildEposXml(order),
    });
  } catch {
    throw new PrinterError(
      `Não consegui falar com a impressora em ${PRINTER_IP}. Ela está ligada e na mesma rede? ` +
        'Se o painel abre em HTTPS, confira se o navegador não bloqueou como "conteúdo não seguro".',
    );
  }
  if (!response.ok) {
    throw new PrinterError(`A impressora respondeu com erro (HTTP ${response.status}).`);
  }
}
