-- Zera todos os DADOS de negocio, mantendo o schema intacto.
--
-- Uso: cliente novo, ou reset de ambiente sujo de teste. NAO apaga tabela
-- nenhuma nem mexe em `schema_migrations` (isso e' controle de versao do
-- schema, nao dado de negocio) -- so esvazia o que o dia a dia da loja gera.
--
-- Irreversivel. Faca um backup antes se houver qualquer duvida sobre os
-- dados (ver back/../backup_db.sh na raiz do projeto).
--
-- Rodar dentro do container do banco:
--   docker exec -i <container-do-db> psql -U postgres -d postgres < back/db/wipe_data.sql

TRUNCATE TABLE
    conversation_messages,
    conversations,
    webhook_events,
    payments,
    order_item_complements,
    order_items,
    orders,
    addresses,
    customers,
    complements,
    product_groups,
    complement_groups,
    complement_categories,
    products
RESTART IDENTITY CASCADE;
