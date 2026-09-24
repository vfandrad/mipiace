import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { OrderCard } from './OrderCard';
import { toOrder } from '@/lib/transforms';
import type { Order } from '@/types/order';

const apiOrder: Order = {
  id: 'o1',
  code: 'MP-0007',
  status: 'novo',
  payment_status: 'pendente',
  fulfillment_type: 'entrega',
  subtotal: 45,
  delivery_fee: 5,
  total: 50,
  created_at: new Date().toISOString(),
  customer: { name: 'Ana', phone: '5511999998888' },
  address: { rua: 'Rua das Flores', numero: '123', bairro: 'Centro' },
  items: [
    {
      id: 'i1',
      product_name_snapshot: 'Pote 500ml',
      unit_base_price: 45,
      quantity: 2,
      line_total: 90,
      complements: [{ complement_name_snapshot: 'Pistache', extra_price_snapshot: 0 }],
    },
  ],
  payment: { amount: 50, status: 'pendente', qr_code: '00020126580014BR.GOV.BCB.PIX' },
};

function renderCard(overrides: Partial<Order> = {}, onStatusChange = vi.fn()) {
  render(<OrderCard order={toOrder({ ...apiOrder, ...overrides })} onStatusChange={onStatusChange} />);
  return onStatusChange;
}

describe('OrderCard', () => {
  it('mostra código, cliente, itens e total formatado', () => {
    renderCard();
    expect(screen.getByText('MP-0007')).toBeInTheDocument();
    expect(screen.getByText('Ana')).toBeInTheDocument();
    expect(screen.getByText('(11) 99999-8888')).toBeInTheDocument();
    expect(screen.getByText('2x Pote 500ml')).toBeInTheDocument();
    expect(screen.getByText('R$ 50,00')).toBeInTheDocument();
    expect(screen.getByText('Rua das Flores, 123 — Centro')).toBeInTheDocument();
  });

  it('resolve o nome do complemento sem depender do catálogo', () => {
    renderCard();
    expect(screen.getByText('Pistache')).toBeInTheDocument();
  });

  it('destaca o Pix pendente com o copia-e-cola', () => {
    renderCard();
    expect(screen.getByText('Pix pendente')).toBeInTheDocument();
    expect(screen.getByText('Pix aguardando')).toBeInTheDocument();
    expect(screen.getByText(/00020126580014BR.GOV.BCB.PIX/)).toBeInTheDocument();
  });

  it('não mostra bloco de Pix quando o pedido já está pago', () => {
    renderCard({ payment_status: 'pago', payment: { amount: 50, status: 'pago' } });
    expect(screen.getByText('Pago')).toBeInTheDocument();
    expect(screen.queryByText('Pix aguardando')).not.toBeInTheDocument();
  });

  it('avança novo -> preparando pelo botão de ação', () => {
    const onStatusChange = renderCard();
    fireEvent.click(screen.getByRole('button', { name: /iniciar preparo/i }));
    expect(onStatusChange).toHaveBeenCalledWith('o1', 'preparando');
  });

  it('não oferece ações em pedido finalizado', () => {
    renderCard({ status: 'finalizado' });
    expect(screen.queryByRole('button', { name: /cancelar pedido/i })).not.toBeInTheDocument();
  });
});
