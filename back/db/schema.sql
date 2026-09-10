-- =============================================================================
-- Mi Piace Gelateria — Esquema do banco (PostgreSQL 14+)
-- =============================================================================
-- Reescrita do modelo antigo. Principais mudanças em relação ao esquema legado:
--
--   1. Preços "congelados" (snapshot) nos itens de pedido. No modelo antigo o
--      pedido só guardava total_price; se o lojista mudasse o preço de um sabor,
--      o histórico de vendas passava a mentir. Agora cada item guarda o preço
--      praticado no momento da venda.
--   2. Complementos de um item viraram tabela relacional (order_item_complements)
--      em vez de um array de ids em JSONB, o que torna possível responder
--      "qual sabor mais vendeu?" com SQL simples.
--   3. Cliente e endereço viraram entidades próprias (customers/addresses),
--      permitindo reconhecer quem já pediu antes pelo telefone do WhatsApp.
--   4. Pagamentos viraram tabela própria (payments) com histórico de tentativas,
--      em vez de três colunas achatadas dentro de orders.
--   5. Estado do agente de WhatsApp passa a viver no banco (conversations),
--      que é o que permite trocar o n8n por uma máquina de estados em código.
--   6. webhook_events dá idempotência: o Mercado Pago reenvia notificações e
--      hoje isso reprocessaria o mesmo pagamento várias vezes.
--   7. flavor_categories separa os sabores em "sem lactose" / "com lactose".
--      É um atributo do sabor, não do grupo de escolha: o mesmo sabor pode
--      aparecer em vários produtos (pote, casquinha, milkshake) e continuar
--      na mesma categoria. Sem isso o agente de WhatsApp não consegue
--      responder "quais sabores são sem lactose?" sem adivinhar pelo nome.
-- =============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- Tipos enumerados
-- ----------------------------------------------------------------------------
CREATE TYPE order_status AS ENUM ('novo', 'preparando', 'entrega', 'finalizado', 'cancelado');
CREATE TYPE payment_status AS ENUM ('pendente', 'pago', 'expirado', 'cancelado', 'reembolsado');
CREATE TYPE fulfillment_type AS ENUM ('entrega', 'retirada');
CREATE TYPE order_channel AS ENUM ('whatsapp', 'admin', 'simulador');
CREATE TYPE message_direction AS ENUM ('entrada', 'saida');

-- ----------------------------------------------------------------------------
-- Função utilitária: mantém updated_at sempre correto
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $fn$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$fn$ LANGUAGE plpgsql;

-- ============================================================================
-- CATÁLOGO
-- ============================================================================

-- Produto base: "Pote 500ml", "Casquinha", "Milkshake"
CREATE TABLE products (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name         text NOT NULL,
    description  text,
    base_price   numeric(10, 2) NOT NULL CHECK (base_price >= 0),
    is_available boolean NOT NULL DEFAULT true,
    sort_order   integer NOT NULL DEFAULT 0,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_products_available ON products (is_available) WHERE is_available;

-- Categoria de sabor: "Sem lactose" / "Com lactose". Existe fora de products/
-- complement_groups porque é um atributo do SABOR em si (vale em qualquer
-- produto que o venda), não do grupo de escolha de um produto específico.
CREATE TABLE flavor_categories (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name       text NOT NULL UNIQUE,
    sort_order integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Grupo de escolhas dentro de um produto: "Escolha 2 sabores", "Cobertura"
CREATE TABLE complement_groups (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id  uuid NOT NULL REFERENCES products (id) ON DELETE CASCADE,
    name        text NOT NULL,
    min_choices integer NOT NULL DEFAULT 0 CHECK (min_choices >= 0),
    max_choices integer NOT NULL DEFAULT 1 CHECK (max_choices >= 1),
    is_required boolean NOT NULL DEFAULT false,
    sort_order  integer NOT NULL DEFAULT 0,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chk_choices_range CHECK (max_choices >= min_choices)
);
CREATE INDEX idx_groups_product ON complement_groups (product_id);

-- Item escolhível dentro de um grupo: "Pistache", "Chocolate Belga"
CREATE TABLE complements (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id           uuid NOT NULL REFERENCES complement_groups (id) ON DELETE CASCADE,
    name               text NOT NULL,
    extra_price        numeric(10, 2) NOT NULL DEFAULT 0 CHECK (extra_price >= 0),
    is_available       boolean NOT NULL DEFAULT true,
    sort_order         integer NOT NULL DEFAULT 0,
    -- NULL para complementos que não são sabores (cobertura, adicional, calda).
    flavor_category_id uuid REFERENCES flavor_categories (id) ON DELETE SET NULL,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_complements_group           ON complements (group_id);
CREATE INDEX idx_complements_flavor_category ON complements (flavor_category_id) WHERE flavor_category_id IS NOT NULL;

-- ============================================================================
-- CLIENTES
-- ============================================================================

-- O telefone é a identidade natural: é por ele que o WhatsApp chega.
CREATE TABLE customers (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    phone      text NOT NULL UNIQUE,   -- E.164 normalizado: 5511999998888
    name       text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Endereços reutilizáveis: cliente recorrente não precisa ditar tudo de novo.
CREATE TABLE addresses (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id uuid NOT NULL REFERENCES customers (id) ON DELETE CASCADE,
    rua         text NOT NULL,
    numero      text NOT NULL,
    bairro      text NOT NULL,
    complemento text,
    referencia  text,
    is_default  boolean NOT NULL DEFAULT false,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_addresses_customer ON addresses (customer_id);

-- ============================================================================
-- PEDIDOS
-- ============================================================================

-- Código curto e legível para o cliente/balcão, separado do uuid interno.
CREATE SEQUENCE order_code_seq START 1;

CREATE TABLE orders (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code             text NOT NULL UNIQUE,
    customer_id      uuid REFERENCES customers (id) ON DELETE SET NULL,
    address_id       uuid REFERENCES addresses (id) ON DELETE SET NULL,
    fulfillment_type fulfillment_type NOT NULL DEFAULT 'entrega',
    channel          order_channel NOT NULL DEFAULT 'whatsapp',
    status           order_status NOT NULL DEFAULT 'novo',
    payment_status   payment_status NOT NULL DEFAULT 'pendente',
    subtotal         numeric(10, 2) NOT NULL DEFAULT 0 CHECK (subtotal >= 0),
    delivery_fee     numeric(10, 2) NOT NULL DEFAULT 0 CHECK (delivery_fee >= 0),
    total            numeric(10, 2) NOT NULL DEFAULT 0 CHECK (total >= 0),
    notes            text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    paid_at          timestamptz,
    cancelled_at     timestamptz
);
-- Índices pensados nas duas telas que mais rodam: Kanban e Dashboard.
CREATE INDEX idx_orders_status   ON orders (status) WHERE status <> 'finalizado';
CREATE INDEX idx_orders_created  ON orders (created_at DESC);
CREATE INDEX idx_orders_customer ON orders (customer_id);
CREATE INDEX idx_orders_paid_at  ON orders (paid_at) WHERE paid_at IS NOT NULL;

-- Item do pedido, com o preço praticado congelado no momento da venda.
CREATE TABLE order_items (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id              uuid NOT NULL REFERENCES orders (id) ON DELETE CASCADE,
    product_id            uuid REFERENCES products (id) ON DELETE RESTRICT,
    product_name_snapshot text NOT NULL,
    unit_base_price       numeric(10, 2) NOT NULL CHECK (unit_base_price >= 0),
    quantity              integer NOT NULL DEFAULT 1 CHECK (quantity > 0),
    line_total            numeric(10, 2) NOT NULL CHECK (line_total >= 0),
    details               text,
    created_at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_order_items_order   ON order_items (order_id);
CREATE INDEX idx_order_items_product ON order_items (product_id);

-- Complementos escolhidos, relacionais (permite "sabor mais vendido" em SQL).
CREATE TABLE order_item_complements (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_item_id            uuid NOT NULL REFERENCES order_items (id) ON DELETE CASCADE,
    complement_id            uuid REFERENCES complements (id) ON DELETE RESTRICT,
    complement_name_snapshot text NOT NULL,
    extra_price_snapshot     numeric(10, 2) NOT NULL DEFAULT 0
);
CREATE INDEX idx_oic_item       ON order_item_complements (order_item_id);
CREATE INDEX idx_oic_complement ON order_item_complements (complement_id);

-- ============================================================================
-- PAGAMENTOS
-- ============================================================================

-- Histórico de cobranças: um pedido pode ter um Pix expirado e outro pago.
CREATE TABLE payments (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id            uuid NOT NULL REFERENCES orders (id) ON DELETE CASCADE,
    provider            text NOT NULL,              -- 'mercadopago' | 'fake'
    provider_payment_id text,                       -- id da cobrança no provedor
    method              text NOT NULL DEFAULT 'pix',
    amount              numeric(10, 2) NOT NULL CHECK (amount > 0),
    status              payment_status NOT NULL DEFAULT 'pendente',
    qr_code             text,                       -- Pix copia-e-cola
    qr_code_base64      text,                       -- imagem do QR
    ticket_url          text,
    expires_at          timestamptz,
    raw_payload         jsonb,                      -- resposta crua do provedor
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_provider_payment UNIQUE (provider, provider_payment_id)
);
CREATE INDEX idx_payments_order ON payments (order_id);

-- Idempotência de webhooks: o Mercado Pago reenvia a mesma notificação.
CREATE TABLE webhook_events (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source       text NOT NULL,        -- 'mercadopago' | 'whatsapp'
    external_id  text NOT NULL,        -- id do evento no provedor
    payload      jsonb NOT NULL,
    processed_at timestamptz,
    error        text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_webhook_event UNIQUE (source, external_id)
);

-- ============================================================================
-- AGENTE DE WHATSAPP (substitui o estado que hoje vive dentro do n8n)
-- ============================================================================

-- Uma linha por telefone/canal. É a memória da máquina de estados.
CREATE TABLE conversations (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    phone           text NOT NULL,
    channel         text NOT NULL DEFAULT 'whatsapp',
    state           text NOT NULL DEFAULT 'saudacao',
    slots           jsonb NOT NULL DEFAULT '{}'::jsonb,   -- dados coletados
    cart            jsonb NOT NULL DEFAULT '[]'::jsonb,   -- carrinho em construção
    customer_id     uuid REFERENCES customers (id) ON DELETE SET NULL,
    active_order_id uuid REFERENCES orders (id) ON DELETE SET NULL,
    handoff         boolean NOT NULL DEFAULT false,       -- pausado p/ atendente
    fail_count      integer NOT NULL DEFAULT 0,           -- erros seguidos de NLU
    last_message_at timestamptz,
    expires_at      timestamptz,                          -- sessão expira e reinicia
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_conversation_phone_channel UNIQUE (phone, channel)
);
CREATE INDEX idx_conversations_state ON conversations (state);

-- Log de mensagens: essencial para depurar o agente e auditar o que a IA disse.
CREATE TABLE conversation_messages (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id     uuid NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    direction           message_direction NOT NULL,
    content             text NOT NULL,
    state_before        text,
    state_after         text,
    detected_intent     text,
    confidence          numeric(4, 3),
    llm_model           text,
    llm_usage           jsonb,       -- tokens de entrada/saída p/ controle de custo
    provider_message_id text,
    created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_messages_conversation ON conversation_messages (conversation_id, created_at);
-- Evita duplicar mensagem quando o eco do WhatsApp (fromMe) chega pelo webhook
-- com o mesmo id que já foi gravado no envio (ver app/agent/runner.py).
CREATE UNIQUE INDEX uq_messages_provider_id ON conversation_messages (provider_message_id)
    WHERE provider_message_id IS NOT NULL;

-- ============================================================================
-- Triggers de updated_at
-- ============================================================================
CREATE TRIGGER trg_flavor_categories_updated BEFORE UPDATE ON flavor_categories FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_products_updated      BEFORE UPDATE ON products          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_groups_updated        BEFORE UPDATE ON complement_groups FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_complements_updated   BEFORE UPDATE ON complements       FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_customers_updated     BEFORE UPDATE ON customers         FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_orders_updated        BEFORE UPDATE ON orders            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_payments_updated      BEFORE UPDATE ON payments          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_conversations_updated BEFORE UPDATE ON conversations     FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================================
-- Views de métricas — substituem o mock-data.ts do dashboard
-- ============================================================================

-- Vendas por dia (apenas pedidos pagos e não cancelados)
CREATE VIEW vw_daily_sales AS
SELECT date_trunc('day', o.created_at)::date AS dia,
       count(*)                              AS pedidos,
       coalesce(sum(o.total), 0)             AS total
FROM orders o
WHERE o.payment_status = 'pago' AND o.status <> 'cancelado'
GROUP BY 1;

-- Produtos mais vendidos
CREATE VIEW vw_product_sales AS
SELECT oi.product_name_snapshot AS produto,
       sum(oi.quantity)         AS unidades,
       sum(oi.line_total)       AS receita
FROM order_items oi
JOIN orders o ON o.id = oi.order_id
WHERE o.payment_status = 'pago' AND o.status <> 'cancelado'
GROUP BY 1;

-- Distribuição de pedidos por hora do dia
CREATE VIEW vw_hourly_sales AS
SELECT extract(hour FROM o.created_at)::int AS hora,
       count(*)                             AS pedidos,
       coalesce(sum(o.total), 0)            AS receita
FROM orders o
WHERE o.payment_status = 'pago' AND o.status <> 'cancelado'
GROUP BY 1;

-- Sabores/complementos mais pedidos
CREATE VIEW vw_complement_sales AS
SELECT oic.complement_name_snapshot AS complemento,
       count(*)                     AS escolhas
FROM order_item_complements oic
JOIN order_items oi ON oi.id = oic.order_item_id
JOIN orders o       ON o.id = oi.order_id
WHERE o.payment_status = 'pago' AND o.status <> 'cancelado'
GROUP BY 1;

-- Escolhas por categoria de sabor (sem lactose x com lactose)
CREATE VIEW vw_flavor_category_sales AS
SELECT fc.name    AS categoria,
       count(*)   AS escolhas
FROM order_item_complements oic
JOIN order_items oi        ON oi.id = oic.order_item_id
JOIN orders o               ON o.id = oi.order_id
JOIN complements c          ON c.id = oic.complement_id
JOIN flavor_categories fc   ON fc.id = c.flavor_category_id
WHERE o.payment_status = 'pago' AND o.status <> 'cancelado'
GROUP BY 1;

COMMIT;
