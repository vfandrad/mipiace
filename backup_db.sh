#!/bin/sh
# Backup diario do Postgres do Mi Piace, com rotacao de 7 dias.
# Roda pg_dump DENTRO do container do banco (mesma versao do pg_dump/pg_restore
# do servidor), grava comprimido fora do container, e apaga o que passou de 7 dias.
#
# Instalar no servidor (nome do container muda conforme o deploy — confira com
# `docker ps`; no Easypanel costuma ser algo como "mi-piace_mi-piace-db-1"):
#
#   crontab -e
#   0 3 * * * /root/backup_db.sh >> /root/backup_db.log 2>&1
#
# Restaurar (teste isso pelo menos uma vez — um backup nunca restaurado não é
# um backup):
#
#   gunzip -c /root/backups/mipiace-db-AAAA-MM-DD_HHMMSS.sql.gz \
#     | docker exec -i mi-piace_mi-piace-db-1 psql -U postgres -d postgres
set -eu

DB_CONTAINER="${DB_CONTAINER:-mi-piace_mi-piace-db-1}"
DIA=$(date +%Y-%m-%d_%H%M%S)
DESTINO=/root/backups
ARQUIVO="$DESTINO/mipiace-db-$DIA.sql.gz"

mkdir -p "$DESTINO"

# --no-owner/--no-acl: a imagem supabase/postgres cria tabelas com owner
# "supabase_admin" — restaurar como "postgres" sem essas flags falha com
# "must be able to SET ROLE supabase_admin". Sem dono/permissão no dump,
# a restauração vira owner de tudo e funciona em qualquer banco de destino.
docker exec "$DB_CONTAINER" pg_dump -U postgres -d postgres --no-owner --no-acl | gzip > "$ARQUIVO"

# Mantem só os últimos 7 dias — sem isso o disco da VPS enche sozinho.
find "$DESTINO" -name 'mipiace-db-*.sql.gz' -mtime +7 -delete

echo "Backup ok: $ARQUIVO ($(du -h "$ARQUIVO" | cut -f1))"
