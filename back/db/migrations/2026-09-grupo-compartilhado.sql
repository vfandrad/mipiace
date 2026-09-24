-- ============================================================================
-- Migração: grupo de complementos compartilhado entre produtos
-- ============================================================================
-- Banco NOVO não precisa disto: `schema.sql` já nasce assim. Isto é para quem
-- já tem dados.
--
-- O QUE MUDA
--   Antes: complement_groups.product_id — cada produto tinha o SEU grupo, logo
--          a sua cópia dos sabores. 3 tamanhos x 31 sabores = 93 linhas.
--   Depois: o grupo é uma lista compartilhada e a regra de escolha (quantos
--          sabores) vai para product_groups, o vínculo. 31 linhas.
--
--   O ganho é operacional: "pistache acabou" vira UM clique e vale para o
--   cardápio inteiro, em vez de três cliques que podiam divergir entre si.
--
-- A ORDEM IMPORTA
--   order_item_complements.complement_id é FK com ON DELETE RESTRICT. Apagar as
--   linhas duplicadas sem antes repontar o histórico para a linha que fica
--   falha a migração — e, pior, se alguém contornar o RESTRICT, perde o que o
--   cliente pediu. O passo 3 existe só por causa disso.
--
-- SEGURANÇA
--   Roda inteiro numa transação: ou passa tudo, ou não muda nada.
--   Faça backup antes (`pg_dump`), como sempre.
-- ============================================================================

BEGIN;

-- 1. A tabela do vínculo.
CREATE TABLE product_groups (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id  uuid NOT NULL REFERENCES products (id) ON DELETE CASCADE,
    group_id    uuid NOT NULL REFERENCES complement_groups (id) ON DELETE CASCADE,
    min_choices integer NOT NULL DEFAULT 0 CHECK (min_choices >= 0),
    max_choices integer NOT NULL DEFAULT 1 CHECK (max_choices >= 1),
    is_required boolean NOT NULL DEFAULT false,
    sort_order  integer NOT NULL DEFAULT 0,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chk_choices_range CHECK (max_choices >= min_choices),
    CONSTRAINT uq_product_group UNIQUE (product_id, group_id)
);
CREATE INDEX idx_product_groups_product ON product_groups (product_id);
CREATE INDEX idx_product_groups_group   ON product_groups (group_id);

-- 2. Elege um grupo canônico por CONJUNTO DE SABORES.
--    Grupos que oferecem exatamente a mesma lista de nomes viram um só; grupos
--    com listas diferentes (uma "Coberturas" ao lado de "Sabores") continuam
--    separados, cada um virando seu próprio canônico. É o que torna esta
--    migração segura para um cardápio que já saiu do caso da Mi Piace.
CREATE TEMP TABLE _canonico ON COMMIT DROP AS
WITH assinatura AS (
    SELECT g.id AS group_id,
           coalesce(
               (SELECT string_agg(lower(c.name), '|' ORDER BY lower(c.name))
                FROM complements c WHERE c.group_id = g.id),
               ''
           ) AS sabores
    FROM complement_groups g
)
SELECT a.group_id,
       first_value(a.group_id) OVER (
           PARTITION BY a.sabores ORDER BY a.group_id
       ) AS canonico
FROM assinatura a;

-- 3. Reponta o histórico ANTES de apagar qualquer coisa.
--    O nome é a chave: é o mesmo sabor, só que na cópia que vai ficar.
UPDATE order_item_complements oic
SET complement_id = novo.id
FROM complements velho
JOIN _canonico k ON k.group_id = velho.group_id
JOIN complements novo
      ON novo.group_id = k.canonico
     AND lower(novo.name) = lower(velho.name)
WHERE oic.complement_id = velho.id
  AND k.group_id <> k.canonico;

-- 4. Cria um vínculo por (produto, grupo canônico), levando a regra de escolha
--    que estava no grupo daquele produto.
INSERT INTO product_groups (product_id, group_id, min_choices, max_choices, is_required, sort_order)
SELECT g.product_id, k.canonico, g.min_choices, g.max_choices, g.is_required, g.sort_order
FROM complement_groups g
JOIN _canonico k ON k.group_id = g.id
ON CONFLICT (product_id, group_id) DO NOTHING;

-- 5. Agora que ninguém mais aponta para elas, apaga as cópias.
DELETE FROM complements c
USING _canonico k
WHERE c.group_id = k.group_id AND k.group_id <> k.canonico;

DELETE FROM complement_groups g
USING _canonico k
WHERE g.id = k.group_id AND k.group_id <> k.canonico;

-- 6. O grupo deixa de pertencer a um produto e perde a regra de escolha, que
--    agora mora no vínculo. O nome perde o número ("Escolha 3 sabores" era o
--    nome do grupo DE UM tamanho; a lista compartilhada chama-se "Sabores").
ALTER TABLE complement_groups
    DROP CONSTRAINT IF EXISTS chk_choices_range,
    DROP COLUMN product_id,
    DROP COLUMN min_choices,
    DROP COLUMN max_choices,
    DROP COLUMN is_required;

DROP INDEX IF EXISTS idx_groups_product;

-- "Escolha 3 sabores" era o nome do grupo DE UM tamanho; a lista compartilhada
-- se chama só "Sabores". `initcap` da primeira letra para não sobrar minúscula.
UPDATE complement_groups
SET name = overlay(
        regexp_replace(name, '^Escolha\s+\d+\s+', '', 'i')
        placing upper(left(regexp_replace(name, '^Escolha\s+\d+\s+', '', 'i'), 1))
        from 1 for 1
    )
WHERE name ~* '^Escolha\s+\d+\s+';

CREATE TRIGGER trg_product_groups_updated BEFORE UPDATE ON product_groups
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 7. Views de métricas que nunca foram consultadas (o `services/metrics.py`
--    reimplementa o que precisa, porque as views não têm recorte de período).
DROP VIEW IF EXISTS vw_product_sales;
DROP VIEW IF EXISTS vw_hourly_sales;
DROP VIEW IF EXISTS vw_complement_sales;
DROP VIEW IF EXISTS vw_category_sales;

-- 8. 'saudacao' saiu de ConversationState na redução da máquina de estados.
ALTER TABLE conversations ALTER COLUMN state SET DEFAULT 'conversando';

COMMIT;
