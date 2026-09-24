/**
 * Transformações puras entre o formato da API e o formato que os componentes
 * (Recharts, cards do Kanban) esperam. Ficam separadas dos hooks justamente
 * para poderem ser testadas sem React nem rede.
 */

import { toNumber } from './format';
import type { Order } from '@/types/order';
import type {
  DailySales,
  HourlySales,
  HourlyPoint,
  MetricsRange,
  ProductPoint,
  ProductSales,
  SalesPoint,
} from '@/types/metrics';

// --- Pedidos ----------------------------------------------------------------

/**
 * Normaliza o pedido cru. O backend pode mandar o cliente aninhado
 * (`customer.name`) ou achatado (`customer_name`); aceitamos os dois para o
 * front não depender dessa escolha.
 */
export function toOrder(api: Order): Order {
  return {
    ...api,
    code: api.code ?? '',
    status: api.status ?? 'novo',
    payment_status: api.payment_status ?? 'pendente',
    fulfillment_type: api.fulfillment_type ?? 'entrega',
    channel: api.channel ?? 'whatsapp',
    // O backend manda o cliente aninhado OU achatado; o resto do front lê só
    // a forma achatada e não precisa saber dessa escolha.
    customer_name: api.customer?.name ?? api.customer_name ?? '',
    customer_phone: api.customer?.phone ?? api.customer_phone ?? '',
    address: api.address ?? null,
    subtotal: toNumber(api.subtotal),
    delivery_fee: toNumber(api.delivery_fee),
    total: toNumber(api.total),
    notes: api.notes ?? null,
    items: (api.items ?? []).map((item) => ({
      ...item,
      quantity: toNumber(item.quantity, 1),
      unit_base_price: toNumber(item.unit_base_price),
      line_total: toNumber(item.line_total),
      complements: (item.complements ?? []).map((complement) => ({
        ...complement,
        extra_price_snapshot: toNumber(complement.extra_price_snapshot),
      })),
    })),
    payment: api.payment
      ? { ...api.payment, amount: toNumber(api.payment.amount) }
      : null,
  };
}

/** Endereço em uma linha; `null` quando é retirada ou não há endereço. */
export function formatAddress(order: Order): string | null {
  const address = order.address;
  if (!address?.rua) return null;
  const base = [address.rua, address.numero].filter(Boolean).join(', ');
  const withBairro = address.bairro ? `${base} — ${address.bairro}` : base;
  return address.complemento ? `${withBairro} (${address.complemento})` : withBairro;
}

// --- Métricas ---------------------------------------------------------------

/** Quantos dias de histórico pedir para cada período do filtro. */
export const RANGE_TO_DAYS: Record<MetricsRange, number> = {
  hoje: 1,
  semana: 7,
  mes: 30,
};

export const RANGE_LABELS: Record<MetricsRange, string> = {
  hoje: 'hoje',
  semana: 'nos últimos 7 dias',
  mes: 'nos últimos 30 dias',
};

/** `[{dia:"2024-01-26", ...}]` -> `[{label:"sex, 26", ...}]` */
export function toSalesPoints(rows: DailySales[]): SalesPoint[] {
  return (rows ?? []).map((row) => ({
    label: formatDayLabel(row.dia),
    total: toNumber(row.total),
    pedidos: toNumber(row.pedidos),
  }));
}

function formatDayLabel(dia: string): string {
  if (!dia) return '-';
  // Datas puras ("2024-01-26") viram UTC no construtor e podem "voltar" um dia
  // no fuso do Brasil — por isso montamos a data como local explicitamente.
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(dia);
  const date = match
    ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
    : new Date(dia);
  if (Number.isNaN(date.getTime())) return dia;
  return date.toLocaleDateString('pt-BR', { weekday: 'short', day: '2-digit' });
}

/** Ordena por unidades e corta no top N — barra horizontal com 20 itens é ilegível. */
export function toProductPoints(rows: ProductSales[], limit = 8): ProductPoint[] {
  return (rows ?? [])
    .map((row) => ({
      name: row.produto ?? '-',
      unidades: toNumber(row.unidades),
      receita: toNumber(row.receita),
    }))
    .sort((a, b) => b.unidades - a.unidades)
    .slice(0, limit);
}

/** `hora: 14` -> `label: "14h"`, ordenado cronologicamente. */
export function toHourlyPoints(rows: HourlySales[]): HourlyPoint[] {
  return (rows ?? [])
    .map((row) => ({
      hora: toNumber(row.hora),
      pedidos: toNumber(row.pedidos),
      receita: toNumber(row.receita),
    }))
    .sort((a, b) => a.hora - b.hora)
    .map(({ hora, pedidos, receita }) => ({
      label: `${String(hora).padStart(2, '0')}h`,
      pedidos,
      receita,
    }));
}
