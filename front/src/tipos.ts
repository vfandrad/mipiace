/**
 * Os tipos que espelham o JSON da API.
 *
 * Cada campo aqui tem o mesmo nome do campo em `back/app/esquemas.py`.
 * Renomear de um lado sem renomear do outro quebra a tela.
 */



// ---------------------------------------------------------------
// catalog
// ---------------------------------------------------------------

export interface ComplementCategory {
  id: string;
  name: string;
  sort_order?: number;
}

export interface Complement {
  id: string;
  group_id: string;
  name: string;
  extra_price: number;
  is_available: boolean;
  sort_order?: number;
  /** null = complemento sem classificação. */
  category_id?: string | null;
}

/**
 * Um grupo COMO ESTE PRODUTO O USA.
 *
 * A lista de complementos ("Sabores") é compartilhada: os três tamanhos de pote
 * usam a mesma, e por isso marcar um sabor como esgotado vale para todos. O que
 * muda por produto é quantas escolhas ele pede — e é isso que mora no vínculo.
 *
 * `id` é do vínculo (é o que se edita ou se remove para tirar o grupo DESTE
 * produto); `group_id` é da lista compartilhada.
 */
export interface ComplementGroup {
  id: string;
  group_id: string;
  name: string;
  min_choices: number;
  max_choices: number;
  is_required: boolean;
  sort_order?: number;
  complements: Complement[];
}

export interface Product {
  id: string;
  name: string;
  description?: string | null;
  base_price: number;
  is_available: boolean;
  sort_order?: number;
  groups: ComplementGroup[];
}

/** Resposta de `GET /api/products`. */
export interface ProductListResponse {
  products: Product[];
}

// --- Payloads de escrita -----------------------------------------------------

export interface ProductInput {
  name: string;
  description?: string | null;
  base_price: number;
  is_available: boolean;
}

/**
 * Payload de "usar um grupo neste produto".
 *
 * Ou aponta uma lista existente (`group_id`) — o "importar grupo" — ou cria uma
 * nova pelo nome. Nunca os dois: o backend recusa.
 */
export interface GroupInput {
  group_id?: string;
  name?: string;
  min_choices: number;
  max_choices: number;
  is_required: boolean;
}

/** Uma lista da biblioteca, como `GET /api/groups` devolve. */
export interface GroupLibraryEntry {
  id: string;
  name: string;
  sort_order?: number;
  complements: Complement[];
}

export interface ComplementCategoryInput {
  name: string;
  sort_order?: number;
}

export interface ComplementInput {
  name: string;
  extra_price: number;
  is_available: boolean;
  category_id?: string | null;
}

/** O que pode ser reordenado arrastando no painel. */
export type ReorderKind = 'product' | 'product_group' | 'complement' | 'category';

/** Tipo de entidade do catálogo — usado nas rotas genéricas de PATCH/DELETE. */
export type CatalogEntity = 'product' | 'group' | 'complement' | 'category';

// ---------------------------------------------------------------
// order
// ---------------------------------------------------------------

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
/** Um item do lançamento manual: produto e complementos pelo `id` do cardápio. */
export interface OrderItemInput {
  product_id: string;
  quantity: number;
  complement_ids: string[];
}

/**
 * Payload de `POST /api/orders` — lançamento manual pelo painel.
 *
 * Fallback para quando o agente de WhatsApp está fora do ar: o lojista monta
 * o pedido pelo mesmo cardápio, e ele entra direto em "preparando".
 */
export interface OrderCreateInput {
  items: OrderItemInput[];
  customer_name?: string | null;
  phone: string;
  fulfillment_type: FulfillmentType;
  address?: OrderAddress | null;
  payment_status: PaymentStatus;
  notes?: string | null;
}

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

// ---------------------------------------------------------------
// conversation
// ---------------------------------------------------------------

export type ConversationState =
  | 'conversando'
  | 'confirmando_pedido'
  | 'aguardando_pagamento'
  | 'concluido'
  | 'atendimento_humano'
  | 'cancelado';

export type MessageDirection = 'entrada' | 'saida';

export interface Conversation {
  id: string;
  phone: string;
  /** String livre no banco; tratamos valores desconhecidos sem quebrar a tela. */
  state: ConversationState | string;
  handoff: boolean;
  channel?: string;
  customer_name?: string | null;
  last_message_at?: string | null;
  last_message_preview?: string | null;
  active_order_id?: string | null;
  fail_count?: number;
}

export interface ConversationMessage {
  id?: string;
  direction: MessageDirection;
  content: string;
  detected_intent?: string | null;
  state_before?: string | null;
  state_after?: string | null;
  created_at: string;
}

// ---------------------------------------------------------------
// metrics
// ---------------------------------------------------------------

export type MetricsRange = 'hoje' | 'semana' | 'mes';

export interface MetricsSummary {
  total_vendas: number;
  total_pedidos: number;
  ticket_medio: number;
  variacao_percentual: number;
  por_status: Partial<Record<string, number>>;
}

/** `GET /api/metrics/daily-sales` */
export interface DailySales {
  dia: string;
  pedidos: number;
  total: number;
}

/** `GET /api/metrics/product-sales` */
export interface ProductSales {
  produto: string;
  unidades: number;
  receita: number;
}

/** `GET /api/metrics/hourly-sales` */
export interface HourlySales {
  hora: number;
  pedidos: number;
  receita: number;
}

// --- Formatos prontos para o Recharts ---------------------------------------

export interface SalesPoint {
  label: string;
  total: number;
  pedidos: number;
}

export interface ProductPoint {
  name: string;
  unidades: number;
  receita: number;
}

export interface HourlyPoint {
  label: string;
  pedidos: number;
  receita: number;
}
