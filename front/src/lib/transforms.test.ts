import { describe, expect, it } from 'vitest';
import {
  formatAddress,
  RANGE_TO_DAYS,
  toHourlyPoints,
  toOrder,
  toProductPoints,
  toSalesPoints,
} from './transforms';
import type { ApiOrder } from '@/types/order';

const baseOrder: ApiOrder = {
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
    expect(order.deliveryFee).toBe(5);
    expect(order.customerName).toBe('Ana');
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
    expect(order.customerName).toBe('Bruno');
    expect(order.customerPhone).toBe('5511888887777');
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
