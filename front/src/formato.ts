/**
 * Formatacao e conversao: dinheiro, data, rotulos de status e o que vem da API.
 *
 * Nada aqui fala com o servidor nem guarda estado — entra um valor, sai outro.
 */

import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
import type { OrderStatus, PaymentStatus, Order } from '@/tipos';
import type { DailySales, HourlySales, HourlyPoint, MetricsRange, ProductPoint, ProductSales, SalesPoint } from '@/tipos';

// ---------------------------------------------------------------
// utils
// ---------------------------------------------------------------

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// ---------------------------------------------------------------
// format
// ---------------------------------------------------------------

export function toNumber(value: unknown, fallback = 0): number {
  if (typeof value === 'number') return Number.isFinite(value) ? value : fallback;
  if (typeof value === 'string') {
    const parsed = Number(value.replace(',', '.'));
    return Number.isFinite(parsed) ? parsed : fallback;
  }
  return fallback;
}

/** "R$ 42,50" — o Intl usa espaço não separável; normalizamos para espaço comum. */
export function formatCurrency(value: unknown): string {
  return toNumber(value)
    .toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
    .replace(/\s/g, ' ');
}

/** Número inteiro com separador de milhar: 1.234 */
export function formatInteger(value: unknown): string {
  return Math.round(toNumber(value)).toLocaleString('pt-BR');
}

/** "+12,4%" / "-3,0%" — sinal explícito porque é indicador de variação. */
export function formatPercent(value: unknown): string {
  const n = toNumber(value);
  const sign = n > 0 ? '+' : '';
  return `${sign}${n.toFixed(1).replace('.', ',')}%`;
}

/** "14:35" */
export function formatTime(value: Date | string | null | undefined): string {
  const date = toDate(value);
  if (!date) return '--:--';
  return date.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
}

/** "26/01 14:35" */
export function formatDateTime(value: Date | string | null | undefined): string {
  const date = toDate(value);
  if (!date) return '-';
  return `${date.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })} ${formatTime(date)}`;
}

/** Aceita Date, ISO string ou nada; devolve `null` no que for inválido. */
export function toDate(value: Date | string | null | undefined): Date | null {
  if (!value) return null;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** Data em milissegundos, para ordenar. Inválida ou ausente vira 0 (vai ao fim). */
export function toMillis(value: Date | string | null | undefined): number {
  return toDate(value)?.getTime() ?? 0;
}

/** Minutos decorridos desde a data (nunca negativo). */
export function minutesSince(value: Date | string | null | undefined, now = Date.now()): number {
  const date = toDate(value);
  if (!date) return 0;
  return Math.max(0, Math.floor((now - date.getTime()) / 60000));
}

/** "há 3 min" / "há 2 h" / "há 4 d" — resumo curto para listas. */
export function formatRelative(value: Date | string | null | undefined, now = Date.now()): string {
  if (!toDate(value)) return 'sem mensagens';
  const minutes = minutesSince(value, now);
  if (minutes < 1) return 'agora';
  if (minutes < 60) return `há ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `há ${hours} h`;
  return `há ${Math.floor(hours / 24)} d`;
}

/** Telefone E.164 brasileiro em formato legível: 5511999998888 -> (11) 99999-8888 */
export function formatPhone(phone: string | null | undefined): string {
  if (!phone) return '-';
  const digits = phone.replace(/\D/g, '');
  const local = digits.startsWith('55') && digits.length > 11 ? digits.slice(2) : digits;
  if (local.length === 11) return `(${local.slice(0, 2)}) ${local.slice(2, 7)}-${local.slice(7)}`;
  if (local.length === 10) return `(${local.slice(0, 2)}) ${local.slice(2, 6)}-${local.slice(6)}`;
  return phone;
}

// ---------------------------------------------------------------
// status
// ---------------------------------------------------------------

interface StatusInfo {
  /** Texto no singular: "Novo" (badge de um pedido). */
  label: string;
  /** Texto no plural: "Novos" (cabeçalho de coluna/bloco contador). */
  plural: string;
  /** Pílula do badge. */
  pill: string;
  /** Borda inferior do cabeçalho da coluna do Kanban. */
  border: string;
  /** Bloco contador do Dashboard. */
  tile: string;
}

export const ORDER_STATUS_INFO: Record<OrderStatus, StatusInfo> = {
  novo: {
    label: 'Novo',
    plural: 'Novos',
    pill: 'bg-status-new-bg text-status-new font-medium',
    border: 'border-b-status-new',
    tile: 'bg-status-new-bg text-status-new',
  },
  preparando: {
    label: 'Preparando',
    plural: 'Preparando',
    pill: 'bg-status-production-bg text-status-production font-medium',
    border: 'border-b-status-production',
    tile: 'bg-status-production-bg text-status-production',
  },
  entrega: {
    label: 'Saiu p/ entrega',
    plural: 'Em entrega',
    pill: 'bg-status-ready-bg text-status-ready font-medium',
    border: 'border-b-status-ready',
    tile: 'bg-status-ready-bg text-status-ready',
  },
  finalizado: {
    label: 'Finalizado',
    plural: 'Finalizados',
    pill: 'bg-status-delivered-bg text-status-delivered font-medium',
    border: 'border-b-status-delivered',
    tile: 'bg-status-delivered-bg text-status-delivered',
  },
  cancelado: {
    label: 'Cancelado',
    plural: 'Cancelados',
    pill: 'bg-destructive/10 text-destructive font-medium',
    border: 'border-b-destructive',
    tile: 'bg-destructive/10 text-destructive',
  },
};

const PAYMENT_INFO: Record<PaymentStatus, { label: string; className: string }> = {
  pago: { label: 'Pago', className: 'bg-status-ready-bg text-status-ready' },
  pendente: { label: 'Pix pendente', className: 'bg-status-production-bg text-status-production' },
  expirado: { label: 'Pix expirado', className: 'bg-destructive/10 text-destructive' },
  cancelado: { label: 'Pgto. cancelado', className: 'bg-destructive/10 text-destructive' },
  reembolsado: { label: 'Reembolsado', className: 'bg-status-delivered-bg text-status-delivered' },
};

export function paymentInfo(status: PaymentStatus): { label: string; className: string } {
  return (
    PAYMENT_INFO[status] ?? {
      label: status,
      className: 'bg-secondary text-secondary-foreground',
    }
  );
}

/**
 * Próximo status no fluxo do balcão — espelha as transições que o backend
 * aceita em `services/orders.py::ORDER_TRANSITIONS`. `cancelado` não entra no
 * avanço: sai por botão próprio.
 */
const NEXT_STATUS: Record<OrderStatus, OrderStatus | null> = {
  novo: 'preparando',
  preparando: 'entrega',
  entrega: 'finalizado',
  finalizado: null,
  cancelado: null,
};

export function nextOrderStatus(status: OrderStatus): OrderStatus | null {
  return NEXT_STATUS[status];
}

// ---------------------------------------------------------------
// transforms
// ---------------------------------------------------------------

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
