-- ============================================================================
-- Migração: flavor_categories/flavor_category_id -> complement_categories/category_id
-- ============================================================================
-- Banco NOVO não precisa disto: `schema.sql` já nasce com o nome novo. Isto é
-- para quem tem um banco de antes do complemento ganhar esse nome — só o nome
-- mudou, a coluna sempre classificou o SABOR ("sem lactose"/"com lactose"),
-- nunca o grupo de escolha nem o produto.
--
-- SEGURANÇA
--   Só RENAME — nenhuma linha é criada, apagada ou reescrita. Roda numa
--   transação: ou passa tudo, ou não muda nada. Faça backup antes (`pg_dump`),
--   como sempre.
-- ============================================================================

BEGIN;

ALTER TABLE flavor_categories RENAME TO complement_categories;

ALTER TABLE complements RENAME COLUMN flavor_category_id TO category_id;
ALTER TABLE complements RENAME CONSTRAINT complements_flavor_category_id_fkey
    TO complements_category_id_fkey;

ALTER INDEX idx_complements_flavor_category RENAME TO idx_complements_category;

COMMIT;
