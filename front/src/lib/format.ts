/**
 * Formatação para exibição. Tudo pt-BR e tolerante a `null`, porque valores
 * numéricos podem chegar como string do backend (Decimal serializado).
 */

/** Converte com segurança o que vier do JSON num número finito. */
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
