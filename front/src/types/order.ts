/**
 * Tipos de pedido.
 *
 * O contrato novo já entrega tudo resolvido: nome do produto congelado no item
 * e nome do complemento no complemento. O Kanban não precisa mais carregar o
 * catálogo inteiro só para traduzir ids.
 */

/** Espelha `back/app/domain/enums.py::OrderStatus`. */
export type OrderStatus =
  | 'novo'
  | 'preparando'
  | 'entrega'
  | 'finalizado'
  | 'cancelado';

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

/**
 * O pedido, em snake_case do backend ao JSX.
 *
 * Eram duas interfaces — `ApiOrder` e `Order` — com a mesma lista de ~18
 * campos em duas grafias, mais o `toOrder` reescrevendo essa lista pela
 * terceira vez. Só que `items[]` e `complements[]` atravessavam sem tradução,
 * então `product_name_snapshot` e `line_total` chegavam ao JSX em snake_case de
 * qualquer jeito: o front era misto, que é o pior dos dois mundos. `catalog.ts`
 * e `conversation.ts` já viviam em snake_case e provam que dá.
 *
 * `toOrder` continua existindo, e agora só faz o que realmente era trabalho
 * dele: converter dinheiro que chega como string, e conciliar o cliente que o
 * backend manda ora aninhado, ora achatado.
 */
export interface Order {
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
  /** ISO do backend; use `formatTime`/`toMillis`, que aceitam string. */
  created_at: string;
  paid_at?: string | null;
  /** Forma aninhada que o backend às vezes manda; `toOrder` a concilia abaixo. */
  customer?: { id?: string; name?: string | null; phone?: string | null } | null;
  customer_name?: string | null;
  customer_phone?: string | null;
  address?: OrderAddress | null;
  items: OrderItem[];
  payment?: OrderPayment | null;
}
