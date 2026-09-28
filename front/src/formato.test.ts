/**
 * Testes de formato.ts — os dois arquivos que testavam format e transforms,
 * agora que as duas funcoes moram no mesmo modulo.
 */


import { describe, expect, it } from 'vitest';
import { RANGE_TO_DAYS, formatAddress, formatCurrency, formatDateTime, formatInteger, formatPercent, formatPhone, formatRelative, formatTime, minutesSince, toHourlyPoints, toNumber, toOrder, toProductPoints, toSalesPoints } from '@/formato';
import type { Order } from '@/tipos';

// ---------------------------------------------------------------
// Dinheiro, data e telefone
// ---------------------------------------------------------------

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

// ---------------------------------------------------------------
// O que vem da API
// ---------------------------------------------------------------

const baseOrder: Order = {
  id: 'o1',
  code: 'MP-0007',
  status: 'novo',
  payment_status: 'pendente',
  fulfillment_type: 'entrega',
  subtotal: 45,
  delivery_fee: 5,
  total: 50,
  created_at: '2024-01-26T14:35:00Z',
  customer: { name: 'Ana', phone: '5511999998888' },
  address: { rua: 'Rua das Flores', numero: '123', bairro: 'Centro' },
  items: [
    {
      id: 'i1',
      product_name_snapshot: 'Pote 500ml',
      unit_base_price: 45,
      quantity: 1,
      line_total: 45,
      complements: [
        { complement_name_snapshot: 'Pistache', extra_price_snapshot: 0 },
        { complement_name_snapshot: 'Cobertura', extra_price_snapshot: '2.50' as never },
      ],
    },
  ],
  payment: { amount: 50, status: 'pendente', qr_code: '00020126...' },
};

describe('toOrder', () => {
  it('normaliza os campos do novo contrato', () => {
    const order = toOrder(baseOrder);
    expect(order.code).toBe('MP-0007');
    expect(order.total).toBe(50);
    expect(order.delivery_fee).toBe(5);
    expect(order.customer_name).toBe('Ana');
    expect(order.items[0].product_name_snapshot).toBe('Pote 500ml');
    expect(order.payment?.qr_code).toBe('00020126...');
  });

  it('converte valores monetários que chegam como string', () => {
    const order = toOrder({ ...baseOrder, total: '50.00' as never });
    expect(order.total).toBe(50);
    expect(order.items[0].complements[1].extra_price_snapshot).toBe(2.5);
  });

  it('aceita cliente achatado além do aninhado', () => {
    const order = toOrder({
      ...baseOrder,
      customer: null,
      customer_name: 'Bruno',
      customer_phone: '5511888887777',
    });
    expect(order.customer_name).toBe('Bruno');
    expect(order.customer_phone).toBe('5511888887777');
  });

  it('sobrevive a pedido sem itens, sem endereço e sem pagamento', () => {
    const order = toOrder({
      ...baseOrder,
      items: undefined as never,
      address: null,
      payment: null,
    });
    expect(order.items).toEqual([]);
    expect(order.address).toBeNull();
    expect(order.payment).toBeNull();
  });
});

describe('formatAddress', () => {
  it('monta o endereço em uma linha', () => {
    expect(formatAddress(toOrder(baseOrder))).toBe('Rua das Flores, 123 — Centro');
  });

  it('inclui o complemento quando existe', () => {
    const order = toOrder({
      ...baseOrder,
      address: { rua: 'Rua A', numero: '1', bairro: 'Centro', complemento: 'ap 22' },
    });
    expect(formatAddress(order)).toBe('Rua A, 1 — Centro (ap 22)');
  });

  it('devolve null quando é retirada', () => {
    const order = toOrder({ ...baseOrder, fulfillment_type: 'retirada', address: null });
    expect(formatAddress(order)).toBeNull();
  });
});

describe('transformações de métricas para os gráficos', () => {
  it('mapeia vendas diárias em pontos com rótulo legível', () => {
    const points = toSalesPoints([
      { dia: '2024-01-26', pedidos: 12, total: 480.5 },
      { dia: '2024-01-27', pedidos: 8, total: '310.00' as never },
    ]);
    expect(points).toHaveLength(2);
    expect(points[0].total).toBe(480.5);
    expect(points[1].total).toBe(310);
    // Data pura não pode "voltar um dia" por causa do fuso.
    expect(points[0].label).toContain('26');
  });

  it('ordena produtos por unidades e corta no limite', () => {
    const points = toProductPoints(
      [
        { produto: 'Casquinha', unidades: 5, receita: 25 },
        { produto: 'Pote 500ml', unidades: 20, receita: 900 },
        { produto: 'Milkshake', unidades: 12, receita: 240 },
      ],
      2,
    );
    expect(points.map((p) => p.name)).toEqual(['Pote 500ml', 'Milkshake']);
    expect(points[0].unidades).toBe(20);
  });

  it('ordena horas cronologicamente e rotula com dois dígitos', () => {
    const points = toHourlyPoints([
      { hora: 20, pedidos: 4, receita: 160 },
      { hora: 9, pedidos: 1, receita: 30 },
    ]);
    expect(points.map((p) => p.label)).toEqual(['09h', '20h']);
  });

  it('devolve lista vazia quando a API não manda nada', () => {
    expect(toSalesPoints(undefined as never)).toEqual([]);
    expect(toProductPoints(undefined as never)).toEqual([]);
    expect(toHourlyPoints(undefined as never)).toEqual([]);
  });

  it('mapeia o período do filtro para a janela de dias', () => {
    expect(RANGE_TO_DAYS.hoje).toBe(1);
    expect(RANGE_TO_DAYS.semana).toBe(7);
    expect(RANGE_TO_DAYS.mes).toBe(30);
  });
});
