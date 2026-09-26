#!/bin/sh
# Aplica, em ordem, cada .sql de back/db/migrations que ainda não rodou nesse
# banco — registrado na tabela schema_migrations (criada por schema.sql).
# Não é Alembic: não gera migração, não detecta divergência de schema.sql,
# só evita repetir ou esquecer uma migração porque ninguém lembrava se ela já
# tinha sido aplicada. Roda de dentro do servidor, contra o container do
# banco (ajuste DB_CONTAINER se o nome não for o do Easypanel).
set -eu

DB_CONTAINER="${DB_CONTAINER:-mi-piace_mi-piace-db-1}"
DIR="$(cd "$(dirname "$0")/migrations" && pwd)"

psql_exec() {
    docker exec -i "$DB_CONTAINER" psql -v ON_ERROR_STOP=1 -U postgres -d postgres "$@"
}

psql_exec -c "CREATE TABLE IF NOT EXISTS schema_migrations (filename text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());" > /dev/null

for arquivo in "$DIR"/*.sql; do
    [ -e "$arquivo" ] || continue
    nome=$(basename "$arquivo")
    ja_aplicada=$(psql_exec -tAc "SELECT 1 FROM schema_migrations WHERE filename = '$nome';")
    if [ "$ja_aplicada" = "1" ]; then
        echo "já aplicada: $nome"
        continue
    fi
    echo "aplicando: $nome"
    docker cp "$arquivo" "$DB_CONTAINER:/tmp/migration.sql"
    psql_exec -f /tmp/migration.sql
    psql_exec -c "INSERT INTO schema_migrations (filename) VALUES ('$nome');" > /dev/null
    echo "ok: $nome"
done
