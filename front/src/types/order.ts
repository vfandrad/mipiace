/**
 * Tipos de pedido.
 *
 * O contrato novo já entrega tudo resolvido: nome do produto congelado no item
 * e nome do complemento no complemento. O Kanban não precisa mais carregar o
 * catálogo inteiro só para traduzir ids.
 */

export const ORDER_STATUSES = [
  'novo',
  'preparando',
  'entrega',
  'finalizado',
  'cancelado',
] as const;

export type OrderStatus = (typeof ORDER_STATUSES)[number];

export type PaymentStatus =
  | 'pendente'
  | 'pago'
  | 'expirado'
  | 'cancelado'
  | 'reembolsado';

export type FulfillmentType = 'entrega' | 'retirada';

export type OrderChannel = 'whatsapp' | 'admin' | 'simulador';

/** Complemento escolhido, já com o nome congelado na venda. */
export interface OrderItemComplement {
  id?: string;
  complement_id?: string | null;
  complement_name_snapshot: string;
  extra_price_snapshot: number;
}

export interface OrderItem {
  id: string;
  product_id?: string | null;
  product_name_snapshot: string;
  unit_base_price: number;
  quantity: number;
  line_total: number;
  details?: string | null;
  complements: OrderItemComplement[];
}

/** Cobrança Pix associada ao pedido (pode não existir). */
export interface OrderPayment {
  id?: string;
  provider?: string;
  method?: string;
  amount: number;
  status: PaymentStatus;
  qr_code?: string | null;
  qr_code_base64?: string | null;
  ticket_url?: string | null;
  expires_at?: string | null;
}

export interface OrderAddress {
  rua?: string | null;
  numero?: string | null;
  bairro?: string | null;
  complemento?: string | null;
  referencia?: string | null;
}

/** Pedido cru como vem de `GET /api/orders`. */
export interface ApiOrder {
  id: string;
  code: string;
  status: OrderStatus;
  payment_status: PaymentStatus;
  fulfillment_type: FulfillmentType;
  channel?: OrderChannel;
  subtotal: number;
  delivery_fee: number;
  total: number;
  notes?: string | null;
  created_at: string;
  paid_at?: string | null;
  /** O back pode mandar o cliente aninhado ou achatado; aceitamos os dois. */
  customer?: { id?: string; name?: string | null; phone?: string | null } | null;
  customer_name?: string | null;
  customer_phone?: string | null;
  address?: OrderAddress | null;
  items: OrderItem[];
  payment?: OrderPayment | null;
}

/** Pedido normalizado para consumo dos componentes. */
export interface Order {
  id: string;
  code: string;
  status: OrderStatus;
  paymentStatus: PaymentStatus;
  fulfillmentType: FulfillmentType;
  channel: OrderChannel;
  customerName: string;
  customerPhone: string;
  address: OrderAddress | null;
  subtotal: number;
  deliveryFee: number;
  total: number;
  notes: string | null;
  createdAt: Date;
  items: OrderItem[];
  payment: OrderPayment | null;
}
