-- =============================================================================
-- Mi Piace — dados reais de catálogo (nível MVP)
-- =============================================================================
-- Roda depois de schema.sql (no Docker, via /docker-entrypoint-initdb.d).
--
-- É idempotente: todo bloco tem guarda (ids fixos + ON CONFLICT, ou NOT EXISTS),
-- então rodar duas vezes não duplica nada. Isso importa porque o mesmo arquivo
-- é usado no `python -m app.db.init_db --seed` de quem roda sem Docker.
--
-- Só o cardápio real: os três tamanhos (M/G/COMBO) e os 31 sabores da casa,
-- cada um marcado como com ou sem lactose. Os sabores são UMA lista, que os
-- três tamanhos usam — o que muda por tamanho é quantos se escolhe.
-- Nada de cliente, pedido, pagamento ou conversa fabricados: clientes, pedidos
-- e o histórico do dashboard nascem vazios e são preenchidos pelo uso real do
-- agente/painel. Isso troca "gráfico bonito desde o dia 1" por "nenhum dado
-- fica em produção fingindo ser venda de verdade".
-- =============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- Produtos — os três tamanhos da casa
-- ----------------------------------------------------------------------------
INSERT INTO products (id, name, description, base_price, is_available, sort_order) VALUES
    ('11111111-1111-4111-8111-000000000010', 'M 240ml',
     'Pote médio: escolha 2 sabores.', 30.00, true, 1),
    ('11111111-1111-4111-8111-000000000011', 'G 500ml',
     'Pote grande: escolha 3 sabores.', 50.00, true, 2),
    ('11111111-1111-4111-8111-000000000012', 'COMBO 2 G 1000ml',
     'Dois potes G: escolha 6 sabores.', 90.00, true, 3)
ON CONFLICT (id) DO NOTHING;

-- ----------------------------------------------------------------------------
-- O grupo de sabores — UM, compartilhado pelos três tamanhos
-- ----------------------------------------------------------------------------
INSERT INTO complement_groups (id, name, sort_order) VALUES
    ('22222222-2222-4222-8222-000000000010', 'Sabores', 1)
ON CONFLICT (id) DO NOTHING;

-- ----------------------------------------------------------------------------
-- Quantos sabores cada tamanho escolhe — a regra mora no vínculo
-- ----------------------------------------------------------------------------
-- A lista é a mesma nos três; só muda o quanto. É por isso que "pistache
-- acabou" é um clique e vale para o cardápio inteiro.
INSERT INTO product_groups (product_id, group_id, min_choices, max_choices, is_required, sort_order) VALUES
    ('11111111-1111-4111-8111-000000000010', '22222222-2222-4222-8222-000000000010', 2, 2, true, 1),
    ('11111111-1111-4111-8111-000000000011', '22222222-2222-4222-8222-000000000010', 3, 3, true, 1),
    ('11111111-1111-4111-8111-000000000012', '22222222-2222-4222-8222-000000000010', 6, 6, true, 1)
ON CONFLICT (product_id, group_id) DO NOTHING;

-- ----------------------------------------------------------------------------
-- Categorias de sabor
-- ----------------------------------------------------------------------------
INSERT INTO complement_categories (id, name, sort_order) VALUES
    ('66666666-6666-4666-8666-000000000001', 'Sem lactose', 1),
    ('66666666-6666-4666-8666-000000000002', 'Com lactose', 2)
ON CONFLICT (id) DO NOTHING;

-- ----------------------------------------------------------------------------
-- Sabores — uma linha por sabor
-- ----------------------------------------------------------------------------
-- Antes isto era um CROSS JOIN entre os três grupos e a lista: 93 linhas para
-- 31 sabores. Com o grupo compartilhado, são 31.
--
-- Nenhum sabor cobra a mais: o preço do pote é o preço do pote, qualquer que
-- seja a escolha. A coluna `extra_price` continua existindo (o painel deixa
-- cobrar por um complemento, e o pedido congela o valor da venda), mas o
-- cardápio da casa não usa.
INSERT INTO complements (group_id, name, extra_price, is_available, sort_order, category_id)
SELECT '22222222-2222-4222-8222-000000000010'::uuid, s.nome, s.extra, true, s.ordem, s.categoria_id
FROM (VALUES
        -- 1. Sem lactose
        ('Morango',                                   0.00,  1, '66666666-6666-4666-8666-000000000001'::uuid),
        ('Frutas vermelhas',                           0.00,  2, '66666666-6666-4666-8666-000000000001'::uuid),
        ('Limão siciliano',                            0.00,  3, '66666666-6666-4666-8666-000000000001'::uuid),
        -- 2. Com lactose
        ('Maracujá',                                   0.00,  4, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Fior di latte',                              0.00,  5, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Chocolate sem açúcar',                       0.00,  6, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Chocolate',                                  0.00,  7, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Fior di latte sem açúcar',                   0.00,  8, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Doce de leite',                              0.00,  9, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Coco',                                       0.00, 10, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Castanha de caju',                           0.00, 11, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Pistache',                                   0.00, 12, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Pistache sem açúcar',                        0.00, 13, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Caramelo salgado',                           0.00, 14, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Paçoquinha',                                 0.00, 15, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Maçã e canela',                              0.00, 16, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Franui',                                     0.00, 17, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Biscoff',                                    0.00, 18, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Geleia de maçã com pimenta',                 0.00, 19, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Romeu e Julieta',                            0.00, 20, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Cupuaçu',                                    0.00, 21, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Iogurte com amarena',                        0.00, 22, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Ninho com Nutella',                          0.00, 23, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Banoffe',                                    0.00, 24, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Café robusta',                               0.00, 25, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Torta de limão',                             0.00, 26, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Brownie',                                    0.00, 27, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Pavlova',                                    0.00, 28, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Castanha do Brasil com caramelo salgado',    0.00, 29, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Morango cravejado',                          0.00, 30, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Kinder Bueno',                               0.00, 31, '66666666-6666-4666-8666-000000000002'::uuid)
     ) AS s(nome, extra, ordem, categoria_id)
WHERE NOT EXISTS (
    SELECT 1 FROM complements c
    WHERE c.group_id = '22222222-2222-4222-8222-000000000010'::uuid AND c.name = s.nome
);

COMMIT;
