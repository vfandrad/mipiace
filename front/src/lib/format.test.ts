import { describe, expect, it } from 'vitest';
import {
  formatCurrency,
  formatDateTime,
  formatInteger,
  formatPercent,
  formatPhone,
  formatRelative,
  formatTime,
  minutesSince,
  toNumber,
} from './format';

describe('toNumber', () => {
  it('aceita número, string e string com vírgula decimal', () => {
    expect(toNumber(12.5)).toBe(12.5);
    expect(toNumber('12.50')).toBe(12.5);
    expect(toNumber('12,50')).toBe(12.5);
  });

  it('cai no fallback para valores inválidos', () => {
    expect(toNumber(undefined)).toBe(0);
    expect(toNumber(null)).toBe(0);
    expect(toNumber('abc')).toBe(0);
    expect(toNumber(Number.NaN)).toBe(0);
    expect(toNumber({}, 7)).toBe(7);
  });
});

describe('formatCurrency', () => {
  it('formata em reais no padrão pt-BR', () => {
    expect(formatCurrency(42.5)).toBe('R$ 42,50');
    expect(formatCurrency(1234.5)).toBe('R$ 1.234,50');
  });

  it('trata decimal serializado como string', () => {
    expect(formatCurrency('19.90')).toBe('R$ 19,90');
  });

  it('não quebra com nulo', () => {
    expect(formatCurrency(null)).toBe('R$ 0,00');
  });
});

describe('formatInteger e formatPercent', () => {
  it('formata inteiros com separador de milhar', () => {
    expect(formatInteger(1234)).toBe('1.234');
    expect(formatInteger('42')).toBe('42');
  });

  it('coloca sinal explícito na variação', () => {
    expect(formatPercent(12.4)).toBe('+12,4%');
    expect(formatPercent(-3)).toBe('-3,0%');
    expect(formatPercent(0)).toBe('0,0%');
  });
});

describe('datas', () => {
  const base = new Date('2024-01-26T14:35:00');

  it('formata hora e data/hora', () => {
    expect(formatTime(base)).toBe('14:35');
    expect(formatDateTime(base)).toBe('26/01 14:35');
  });

  it('devolve placeholder para data inválida', () => {
    expect(formatTime(null)).toBe('--:--');
    expect(formatDateTime('não é data')).toBe('-');
  });

  it('conta minutos decorridos sem ficar negativo', () => {
    const now = base.getTime() + 20 * 60_000;
    expect(minutesSince(base, now)).toBe(20);
    expect(minutesSince(base, base.getTime() - 60_000)).toBe(0);
  });

  it('resume o tempo relativo', () => {
    const now = base.getTime();
    expect(formatRelative(base, now)).toBe('agora');
    expect(formatRelative(new Date(now - 5 * 60_000), now)).toBe('há 5 min');
    expect(formatRelative(new Date(now - 3 * 3600_000), now)).toBe('há 3 h');
    expect(formatRelative(new Date(now - 48 * 3600_000), now)).toBe('há 2 d');
    expect(formatRelative(null, now)).toBe('sem mensagens');
  });
});

describe('formatPhone', () => {
  it('formata E.164 brasileiro', () => {
    expect(formatPhone('5511999998888')).toBe('(11) 99999-8888');
    expect(formatPhone('1133334444')).toBe('(11) 3333-4444');
  });

  it('devolve o original quando não reconhece o formato', () => {
    expect(formatPhone('+1 555 0100')).toBe('+1 555 0100');
    expect(formatPhone(null)).toBe('-');
  });
});
