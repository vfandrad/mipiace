#!/bin/bash
set -e

# =============================================================================
# Script de deploy do Mi Piace para produção
# =============================================================================
# Uso:
#   ./deploy.sh              # Deploy da branch atual
#   ./deploy.sh main         # Deploy da branch main
#   PROFILE=whatsapp ./deploy.sh # Com Evolution API
#
# Prerequisitos:
#   - Docker e docker-compose instalados
#   - Arquivo .env.prod na raiz do projeto
#   - Git configurado
# =============================================================================

set -o pipefail

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

BRANCH="${1:-master}"
PROFILE="${PROFILE:-}"
ENV_FILE=".env.prod"

echo -e "${YELLOW}=== Mi Piace Deployment ===${NC}"
echo "Branch: $BRANCH"
echo "Compose profile: ${PROFILE:-none}"
echo "Environment file: $ENV_FILE"
echo ""

# 1. Verificar arquivo .env.prod
if [ ! -f "$ENV_FILE" ]; then
    echo -e "${RED}Erro: arquivo $ENV_FILE não encontrado${NC}"
    echo "Copie .env.prod.example para .env.prod e configure as variáveis"
    exit 1
fi

# 2. Validar Git
echo -e "${YELLOW}[1/7] Validando repositório Git...${NC}"
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    echo -e "${RED}Erro: não está em um repositório Git${NC}"
    exit 1
fi

if git status --porcelain | grep -q .; then
    echo -e "${YELLOW}Aviso: há mudanças não commitadas. Stashando...${NC}"
    git stash
fi

git fetch origin

# 3. Checkout branch
echo -e "${YELLOW}[2/7] Checkout de branch: $BRANCH${NC}"
git checkout "$BRANCH"
git pull origin "$BRANCH"

# 4. Build das imagens
echo -e "${YELLOW}[3/7] Building Docker images...${NC}"
if [ -z "$PROFILE" ]; then
    docker-compose -f docker-compose.yml -f docker-compose.prod.yml build --no-cache
else
    docker-compose -f docker-compose.yml -f docker-compose.prod.yml --profile "$PROFILE" build --no-cache
fi

# 5. Stop dos containers antigos
echo -e "${YELLOW}[4/7] Parando containers antigos...${NC}"
if [ -z "$PROFILE" ]; then
    docker-compose -f docker-compose.yml -f docker-compose.prod.yml down --remove-orphans
else
    docker-compose -f docker-compose.yml -f docker-compose.prod.yml --profile "$PROFILE" down --remove-orphans
fi

# 6. Start dos novos containers
echo -e "${YELLOW}[5/7] Iniciando containers...${NC}"
if [ -z "$PROFILE" ]; then
    docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
else
    docker-compose -f docker-compose.yml -f docker-compose.prod.yml --profile "$PROFILE" up -d
fi

# 7. Verificação de saúde
echo -e "${YELLOW}[6/7] Aguardando containers ficarem healthy...${NC}"
sleep 5

# Espera até 60s pelos health checks passarem
TIMEOUT=60
START_TIME=$(date +%s)
while true; do
    CURRENT_TIME=$(date +%s)
    ELAPSED=$((CURRENT_TIME - START_TIME))

    if [ $ELAPSED -gt $TIMEOUT ]; then
        echo -e "${YELLOW}Timeout aguardando health checks (continuando mesmo assim)${NC}"
        break
    fi

    # Verifica backend
    if docker-compose exec -T backend curl -f http://localhost:8000/health 2>/dev/null; then
        echo -e "${GREEN}✓ Backend é healthy${NC}"
        break
    fi

    echo "Aguardando... ($ELAPSED/$TIMEOUT s)"
    sleep 2
done

# 8. Logs finais
echo -e "${YELLOW}[7/7] Status dos containers:${NC}"
docker-compose ps

echo ""
echo -e "${GREEN}=== Deploy concluído com sucesso ===${NC}"
echo ""
echo "URLs:"
echo "  Frontend:       https://${DOMAIN:-mipiace.example.com}"
echo "  Backend Swagger: https://${DOMAIN:-mipiace.example.com}/docs"
echo "  Admin Studio:    https://admin.${DOMAIN:-mipiace.example.com} (user: ${STUDIO_USER:-admin})"
echo ""
echo "Para ver logs:"
echo "  docker-compose logs -f backend"
echo "  docker-compose logs -f frontend"
echo ""
