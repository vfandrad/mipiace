-- =============================================================================
-- Mi Piace — dados reais de catálogo (nível MVP)
-- =============================================================================
-- Roda depois de schema.sql (no Docker, via /docker-entrypoint-initdb.d).
--
-- É idempotente: todo bloco tem guarda (ids fixos + ON CONFLICT, ou NOT EXISTS),
-- então rodar duas vezes não duplica nada. Isso importa porque o mesmo arquivo
-- é usado no `python -m app.db.init_db --seed` de quem roda sem Docker.
--
-- Só o cardápio real (produtos, grupos de escolha, sabores por categoria).
-- Nada de cliente, pedido, pagamento ou conversa fabricados: clientes, pedidos
-- e o histórico do dashboard nascem vazios e são preenchidos pelo uso real do
-- agente/painel. Isso troca "gráfico bonito desde o dia 1" por "nenhum dado
-- fica em produção fingindo ser venda de verdade".
-- =============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- Produtos
-- ----------------------------------------------------------------------------
INSERT INTO products (id, name, description, base_price, is_available, sort_order) VALUES
    ('11111111-1111-4111-8111-000000000001', 'Pote 500ml',
     'Nosso pote grande: escolha 3 sabores e leve uma cobertura de brinde.', 39.90, true, 1),
    ('11111111-1111-4111-8111-000000000002', 'Pote 240ml',
     'Pote individual com 2 sabores à sua escolha.', 22.90, true, 2),
    ('11111111-1111-4111-8111-000000000003', 'Casquinha',
     'Casquinha crocante com 1 sabor.', 12.00, true, 3),
    ('11111111-1111-4111-8111-000000000004', 'Milkshake 400ml',
     'Milkshake cremoso feito com o gelato da casa.', 24.90, true, 4),
    ('11111111-1111-4111-8111-000000000005', 'Taça Mi Piace',
     'Taça com 2 sabores, calda e chantilly.', 29.90, true, 5)
ON CONFLICT (id) DO NOTHING;

-- ----------------------------------------------------------------------------
-- Grupos de escolha
-- ----------------------------------------------------------------------------
INSERT INTO complement_groups (id, product_id, name, min_choices, max_choices, is_required, sort_order) VALUES
    ('22222222-2222-4222-8222-000000000001', '11111111-1111-4111-8111-000000000001', 'Escolha 3 sabores', 3, 3, true,  1),
    ('22222222-2222-4222-8222-000000000002', '11111111-1111-4111-8111-000000000001', 'Cobertura',         0, 1, false, 2),
    ('22222222-2222-4222-8222-000000000003', '11111111-1111-4111-8111-000000000002', 'Escolha 2 sabores', 2, 2, true,  1),
    ('22222222-2222-4222-8222-000000000004', '11111111-1111-4111-8111-000000000003', 'Escolha 1 sabor',   1, 1, true,  1),
    ('22222222-2222-4222-8222-000000000005', '11111111-1111-4111-8111-000000000004', 'Sabor do milkshake',1, 1, true,  1),
    ('22222222-2222-4222-8222-000000000006', '11111111-1111-4111-8111-000000000004', 'Adicionais',        0, 2, false, 2),
    ('22222222-2222-4222-8222-000000000007', '11111111-1111-4111-8111-000000000005', 'Escolha 2 sabores', 2, 2, true,  1),
    ('22222222-2222-4222-8222-000000000008', '11111111-1111-4111-8111-000000000005', 'Calda',             0, 1, false, 2)
ON CONFLICT (id) DO NOTHING;

-- ----------------------------------------------------------------------------
-- Categorias de sabor
-- ----------------------------------------------------------------------------
INSERT INTO flavor_categories (id, name, sort_order) VALUES
    ('66666666-6666-4666-8666-000000000001', 'Sem lactose', 1),
    ('66666666-6666-4666-8666-000000000002', 'Com lactose', 2)
ON CONFLICT (id) DO NOTHING;

-- ----------------------------------------------------------------------------
-- Sabores (o cardápio completo da casa, repetido em todo grupo de sabor) e extras
-- ----------------------------------------------------------------------------
-- Cross join entre os grupos de sabor e a lista de sabores, com guarda por nome
-- para o arquivo continuar idempotente sem precisar de id fixo por linha.
INSERT INTO complements (group_id, name, extra_price, is_available, sort_order, flavor_category_id)
SELECT g.id, s.nome, s.extra, true, s.ordem, s.categoria_id
FROM (VALUES
        ('22222222-2222-4222-8222-000000000001'::uuid),
        ('22222222-2222-4222-8222-000000000003'::uuid),
        ('22222222-2222-4222-8222-000000000004'::uuid),
        ('22222222-2222-4222-8222-000000000005'::uuid),
        ('22222222-2222-4222-8222-000000000007'::uuid)
     ) AS g(id)
CROSS JOIN (VALUES
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
        ('Pistache',                                   4.00, 12, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Pistache sem açúcar',                        4.00, 13, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Caramelo salgado',                           0.00, 14, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Paçoquinha',                                 0.00, 15, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Maçã e canela',                              0.00, 16, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Franui',                                     3.00, 17, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Biscoff',                                    3.00, 18, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Geleia de maçã com pimenta',                 0.00, 19, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Romeu e Julieta',                            0.00, 20, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Cupuaçu',                                    0.00, 21, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Iogurte com amarena',                        0.00, 22, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Ninho com Nutella',                          3.00, 23, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Banoffe',                                    0.00, 24, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Café robusta',                               0.00, 25, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Torta de limão',                             0.00, 26, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Brownie',                                    0.00, 27, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Pavlova',                                    0.00, 28, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Castanha do Brasil com caramelo salgado',    4.00, 29, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Morango cravejado',                          0.00, 30, '66666666-6666-4666-8666-000000000002'::uuid),
        ('Kinder Bueno',                               4.00, 31, '66666666-6666-4666-8666-000000000002'::uuid)
     ) AS s(nome, extra, ordem, categoria_id)
WHERE NOT EXISTS (
    SELECT 1 FROM complements c WHERE c.group_id = g.id AND c.name = s.nome
);

INSERT INTO complements (group_id, name, extra_price, is_available, sort_order)
SELECT g.id, s.nome, s.extra, true, s.ordem
FROM (VALUES
        ('22222222-2222-4222-8222-000000000002'::uuid),
        ('22222222-2222-4222-8222-000000000008'::uuid)
     ) AS g(id)
CROSS JOIN (VALUES
        ('Calda de Chocolate',   0.00, 1),
        ('Calda de Morango',     0.00, 2),
        ('Caramelo Salgado',     3.00, 3),
        ('Frutas Vermelhas',     5.00, 4)
     ) AS s(nome, extra, ordem)
WHERE NOT EXISTS (
    SELECT 1 FROM complements c WHERE c.group_id = g.id AND c.name = s.nome
);

INSERT INTO complements (group_id, name, extra_price, is_available, sort_order)
SELECT '22222222-2222-4222-8222-000000000006'::uuid, s.nome, s.extra, true, s.ordem
FROM (VALUES
        ('Paçoca',      3.00, 1),
        ('Nutella',     5.00, 2),
        ('Chantilly',   2.00, 3)
     ) AS s(nome, extra, ordem)
WHERE NOT EXISTS (
    SELECT 1 FROM complements c
    WHERE c.group_id = '22222222-2222-4222-8222-000000000006'::uuid AND c.name = s.nome
);

COMMIT;
