#!/usr/bin/env bash
# =============================================================================
# Sobe (ou atualiza) o Mi Piace em produção.
#
#   ./deploy.sh                 # painel + API + banco
#   PROFILE=whatsapp ./deploy.sh  # ... e a Evolution API junto
#
# Não mexe em git: quem decide o que vai para o ar é você, com `git pull` antes
# de chamar isto. O script só constrói as imagens e troca os containers.
# =============================================================================
set -euo pipefail

ENV_FILE=".env.prod"
PROFILE="${PROFILE:-}"

COMPOSE=(docker compose --env-file "$ENV_FILE" -f docker-compose.yml -f docker-compose.prod.yml)
if [ -n "$PROFILE" ]; then
    COMPOSE+=(--profile "$PROFILE")
fi

if [ ! -f "$ENV_FILE" ]; then
    echo "Erro: $ENV_FILE não existe. Copie .env.prod.example e preencha." >&2
    exit 1
fi

# Um .env.prod pela metade sobe um sistema que parece saudável e não cobra
# ninguém. Falhar aqui é mais barato do que descobrir no primeiro pedido.
faltando=()
for var in DOMAIN POSTGRES_PASSWORD ADMIN_API_KEY OPENAI_API_KEY \
           EVOLUTION_API_KEY EVOLUTION_WEBHOOK_TOKEN MP_ACCESS_TOKEN; do
    valor="$(grep -E "^${var}=" "$ENV_FILE" | cut -d= -f2- || true)"
    [ -z "$valor" ] && faltando+=("$var")
done
if [ ${#faltando[@]} -gt 0 ]; then
    echo "Erro: sem valor em $ENV_FILE: ${faltando[*]}" >&2
    exit 1
fi

if grep -qE '^FAKE_MODE=true' "$ENV_FILE"; then
    echo "Erro: FAKE_MODE=true em $ENV_FILE — o Pix e a IA seriam falsos." >&2
    exit 1
fi

echo "==> Construindo imagens"
"${COMPOSE[@]}" build

echo "==> Subindo"
"${COMPOSE[@]}" up -d --remove-orphans

echo "==> Esperando o backend responder"
for _ in $(seq 1 30); do
    if "${COMPOSE[@]}" exec -T backend \
        python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3)" \
        2>/dev/null; then
        echo "backend ok"
        break
    fi
    sleep 2
done

"${COMPOSE[@]}" ps
echo
echo "Painel: https://$(grep -E '^DOMAIN=' "$ENV_FILE" | cut -d= -f2-)"
echo "Logs:   docker compose --env-file $ENV_FILE logs -f backend"
