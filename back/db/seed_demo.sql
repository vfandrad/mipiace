-- =============================================================================
-- Mi Piace — dados de DEMONSTRAÇÃO (pedidos fabricados)
-- =============================================================================
-- Serve para olhar o Kanban e o Dashboard com dado dentro. NÃO roda sozinho:
-- o boot do Docker só aplica schema.sql e seed.sql. Aplique à mão quando quiser:
--
--     docker compose exec -T db psql -U postgres -d postgres < back/db/seed_demo.sql
--
-- Para apagar tudo que este arquivo criou (e só isso):
--
--     docker compose exec -T db psql -U postgres -d postgres \
--       -c "DELETE FROM orders WHERE notes LIKE '[demo]%';" \
--       -c "DELETE FROM customers WHERE phone LIKE '5511900%';"
--
-- Nada aqui toca em `conversations` nem em `conversation_messages`: o histórico
-- do WhatsApp continua sendo só o que o agente realmente conversou.
--
-- Todo pedido leva `notes` começando com '[demo]' — é a marca que permite
-- distinguir venda fabricada de venda real e apagar depois sem levar junto o
-- que o agente criou.
-- =============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- Clientes fictícios (DDD 11, prefixo 900 — não colide com número real)
-- ----------------------------------------------------------------------------
INSERT INTO customers (id, phone, name) VALUES
    ('99999999-0000-4000-8000-000000000001', '5511900000001', 'Ana Souza'),
    ('99999999-0000-4000-8000-000000000002', '5511900000002', 'Bruno Lima'),
    ('99999999-0000-4000-8000-000000000003', '5511900000003', 'Carla Dias'),
    ('99999999-0000-4000-8000-000000000004', '5511900000004', 'Diego Martins'),
    ('99999999-0000-4000-8000-000000000005', '5511900000005', 'Elisa Rocha'),
    ('99999999-0000-4000-8000-000000000006', '5511900000006', 'Felipe Gomes'),
    ('99999999-0000-4000-8000-000000000007', '5511900000007', 'Gabriela Nunes'),
    ('99999999-0000-4000-8000-000000000008', '5511900000008', 'Henrique Alves')
ON CONFLICT (id) DO NOTHING;

INSERT INTO addresses (id, customer_id, rua, numero, bairro, is_default) VALUES
    ('99999999-1111-4000-8000-000000000001', '99999999-0000-4000-8000-000000000001', 'Rua das Flores',   '123', 'Centro',     true),
    ('99999999-1111-4000-8000-000000000002', '99999999-0000-4000-8000-000000000002', 'Av. Brasil',       '456', 'Jardins',    true),
    ('99999999-1111-4000-8000-000000000003', '99999999-0000-4000-8000-000000000003', 'Rua Sete',         '78',  'Vila Nova',  true),
    ('99999999-1111-4000-8000-000000000004', '99999999-0000-4000-8000-000000000004', 'Rua do Sol',       '900', 'Boa Vista',  true),
    ('99999999-1111-4000-8000-000000000005', '99999999-0000-4000-8000-000000000005', 'Alameda Santos',   '221', 'Centro',     true),
    ('99999999-1111-4000-8000-000000000006', '99999999-0000-4000-8000-000000000006', 'Rua Bahia',        '45',  'Jardins',    true),
    ('99999999-1111-4000-8000-000000000007', '99999999-0000-4000-8000-000000000007', 'Rua Minas',        '310', 'Vila Nova',  true),
    ('99999999-1111-4000-8000-000000000008', '99999999-0000-4000-8000-000000000008', 'Rua Ceará',        '88',  'Boa Vista',  true)
ON CONFLICT (id) DO NOTHING;

-- ----------------------------------------------------------------------------
-- 40 pedidos espalhados por 14 dias
-- ----------------------------------------------------------------------------
-- A distribuição é proposital, não aleatória:
--   * os mais antigos já estão finalizados (o histórico do dashboard);
--   * os de hoje ficam abertos, para o Kanban ter carta em cada coluna;
--   * alguns cancelados e um Pix pendente, senão as telas só mostram o caminho
--     feliz e ninguém descobre que a coluna de cancelado existe.
-- O horário concentra em 15h-21h, que é quando gelateria vende.
-- ----------------------------------------------------------------------------
WITH gerados AS (
    SELECT
        n,
        -- dia: 0 = hoje, 13 = duas semanas atrás.
        -- Os 10 primeiros são de hoje, para o Kanban ter carta em toda coluna.
        (ARRAY[0,0,0,0,0,0,0,0,0,0,
               1,1,1, 2,2,2, 3,3, 4,4,4, 5,5, 6,6,6, 7,7,
               8,8, 9,9, 10,10, 11,11, 12,12, 13,13])[n] AS dias_atras,
        (ARRAY[15,16,17,18,19,20,21,16,18,20,15,19,21,17,19,20,16,21,18,20,
               17,19,15,20,18,21,16,19,17,20,18,21,16,19,17,20,22,14,22,14])[n] AS hora,
        -- produto: 1=M, 2=G, 3=COMBO. O G é o carro-chefe.
        (ARRAY[2,1,2,3,2,1,2,2,3,1,2,2,1,3,2,1,2,2,3,1,
               2,1,3,2,2,1,2,3,1,2,2,1,2,3,2,1,2,2,1,3])[n] AS produto,
        (ARRAY[1,2,3,4,5,6,7,8,1,2,3,4,5,6,7,8,1,2,3,4,
               5,6,7,8,1,2,3,4,5,6,7,8,1,2,3,4,5,6,7,8])[n] AS cliente
    FROM generate_series(1, 40) AS n
),
definidos AS (
    SELECT
        g.*,
        p.id   AS product_id,
        p.name AS product_name,
        p.base_price,
        -- status: hoje fica aberto; passado fica fechado
        CASE
            WHEN n IN (3, 17)                 THEN 'cancelado'
            WHEN g.dias_atras = 0 AND n <= 2  THEN 'novo'
            WHEN g.dias_atras = 0 AND n <= 6  THEN 'preparando'
            WHEN g.dias_atras = 0 AND n <= 10 THEN 'entrega'
            ELSE 'finalizado'
        END::order_status AS status,
        CASE
            WHEN n IN (3, 17) THEN 'cancelado'
            WHEN g.dias_atras = 0 AND n <= 2 THEN 'pendente'
            ELSE 'pago'
        END::payment_status AS payment_status,
        (date_trunc('day', now()) - make_interval(days => g.dias_atras))
            + make_interval(hours => g.hora, mins => (n * 7) % 60) AS criado_em
    FROM gerados g
    JOIN products p ON p.sort_order = g.produto
),
inseridos AS (
    INSERT INTO orders (
        id, code, customer_id, address_id, fulfillment_type, channel,
        status, payment_status, subtotal, delivery_fee, total,
        notes, created_at, updated_at, paid_at, cancelled_at
    )
    SELECT
        -- id derivado do n: o INSERT dos itens logo abaixo casa por ele, sem
        -- depender de preço nem de código (que mudariam ao editar o cardápio).
        ('99999999-2222-4000-8000-' || lpad(d.n::text, 12, '0'))::uuid,
        'MP-' || lpad((9000 + d.n)::text, 4, '0'),
        ('99999999-0000-4000-8000-00000000000' || d.cliente)::uuid,
        ('99999999-1111-4000-8000-00000000000' || d.cliente)::uuid,
        'entrega', 'whatsapp',
        d.status, d.payment_status,
        d.base_price, 5.00, d.base_price + 5.00,
        '[demo] pedido de demonstração',
        d.criado_em, d.criado_em,
        CASE WHEN d.payment_status = 'pago' THEN d.criado_em + interval '4 minutes' END,
        CASE WHEN d.status = 'cancelado'    THEN d.criado_em + interval '9 minutes' END
    FROM definidos d
    WHERE NOT EXISTS (
        SELECT 1 FROM orders o
        WHERE o.code = 'MP-' || lpad((9000 + d.n)::text, 4, '0')
    )
    RETURNING id
)
INSERT INTO order_items (order_id, product_id, product_name_snapshot, unit_base_price, quantity, line_total)
SELECT i.id, d.product_id, d.product_name, d.base_price, 1, d.base_price
FROM inseridos i
JOIN definidos d
  ON i.id = ('99999999-2222-4000-8000-' || lpad(d.n::text, 12, '0'))::uuid;

-- ----------------------------------------------------------------------------
-- Sabores de cada pedido (é o que alimenta o gráfico de mais vendidos)
-- ----------------------------------------------------------------------------
-- Cada item recebe tantos sabores quanto o tamanho pede (M=2, G=3, COMBO=6),
-- sorteados de forma estável a partir do id do item: o gráfico fica com
-- distribuição variada mas o resultado é o mesmo toda vez que o arquivo roda.
INSERT INTO order_item_complements (order_item_id, complement_id, complement_name_snapshot, extra_price_snapshot)
SELECT oi.id, c.id, c.name, c.extra_price
FROM order_items oi
JOIN orders o ON o.id = oi.order_id AND o.notes LIKE '[demo]%'
JOIN complement_groups g ON g.product_id = oi.product_id
CROSS JOIN LATERAL (
    SELECT c.id, c.name, c.extra_price
    FROM complements c
    WHERE c.group_id = g.id
    ORDER BY md5(oi.id::text || c.id::text)
    LIMIT g.min_choices
) c
WHERE NOT EXISTS (
    SELECT 1 FROM order_item_complements x WHERE x.order_item_id = oi.id
);

-- ----------------------------------------------------------------------------
-- Cobrança Pix de cada pedido
-- ----------------------------------------------------------------------------
INSERT INTO payments (order_id, provider, provider_payment_id, method, amount, status, qr_code, created_at, updated_at)
SELECT
    o.id, 'fake', 'demo-' || o.code, 'pix', o.total, o.payment_status,
    '00020126580014BR.GOV.BCB.PIX-DEMO-' || o.code,
    o.created_at, o.created_at
FROM orders o
WHERE o.notes LIKE '[demo]%'
  AND NOT EXISTS (SELECT 1 FROM payments p WHERE p.order_id = o.id);

COMMIT;
