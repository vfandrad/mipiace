# Deployment do Mi Piace para Produção

## Pré-requisitos

- VPS/servidor com Docker e docker-compose instalados
- Domínio apontando para o IP do servidor
- Arquivo `.env.prod` com todas as variáveis configuradas
- SSH access ao servidor

## Arquitetura de Produção

```
Internet
   ↓ (80, 443)
┌─ Caddy (reverse proxy + HTTPS/TLS automático)
│   ├─ HTTP → HTTPS redirect
│   └─ Rotas:
│       ├─ / → Frontend (nginx)
│       ├─ /api → Backend (FastAPI)
│       ├─ /admin.* → Supabase Studio (autenticação básica)
│       └─ Health checks
│
├─ Frontend (nginx:8080) - SPA React
├─ Backend (FastAPI:8000)
│   ├─ /api/* (admin)
│   ├─ /client/* (público - cliente WhatsApp)
│   ├─ /webhooks/* (webhooks de Pix e WhatsApp)
│   └─ /docs (Swagger)
│
├─ Database (PostgreSQL:5432) - não exposto
├─ Evolution API:8081 (WhatsApp self-hosted) - opcional
│   ├─ evolution-db (Postgres privado)
│   └─ evolution-redis (Cache)
│
├─ Supabase Studio:3000 (UI de banco)
│   ├─ pg-meta (introspecção)
│   └─ postgres-meta

Volume Management:
  ├─ pgdata/ → Backup diário crítico
  ├─ evolution_instances/ → Sessões WhatsApp pareadas
  ├─ caddy_data/ → Certificados Let's Encrypt
  └─ caddy_config/ → Configuração Caddy
```

## Setup Inicial

### 1. Clonar repositório no servidor

```bash
cd /opt
git clone https://github.com/seu-user/mipiace.git
cd mipiace
```

### 2. Configurar variáveis de produção

```bash
cp .env.prod.example .env.prod
# Editar com seus valores reais
nano .env.prod
```

**Variáveis críticas:**

```bash
DOMAIN=seu-dominio.com
POSTGRES_PASSWORD=<gerar-senha-aleatoria-40-chars>
ADMIN_API_KEY=<gerar-chave-aleatoria-50-chars>
JWT_SECRET=<gerar-jwt-50-chars>
ANTHROPIC_API_KEY=sk-ant-...  # ou OPENAI_API_KEY
MP_ACCESS_TOKEN=APP_USR-...   # Mercado Pago
EVOLUTION_API_KEY=<chave>     # Se usar WhatsApp
STUDIO_PASS=<senha-admin>
```

### 3. Executar deploy

```bash
chmod +x deploy.sh
./deploy.sh main
```

Ou com Evolution API (WhatsApp):

```bash
PROFILE=whatsapp ./deploy.sh main
```

## Monitoramento

### Health checks

```bash
# Backend
curl https://seu-dominio.com/health

# Frontend
curl https://seu-dominio.com/

# Evolution API (se ativado)
curl http://localhost:8081/health
```

### Logs

```bash
# Todos
docker-compose logs -f

# Serviço específico
docker-compose logs -f backend
docker-compose logs -f frontend
docker-compose logs -f caddy
```

### Diagnóstico

```bash
# Status dos containers
docker-compose ps

# Uso de recursos
docker stats

# Verificar volumes
docker volume ls
```

## Backup

### Backup automático do banco

```bash
# Criar diretório de backup
mkdir -p /opt/mipiace/backups

# Executar dump manual
docker-compose exec -T db pg_dump -U postgres mipiace_prod | gzip > backups/backup-$(date +%Y%m%d-%H%M%S).sql.gz

# Restaurar
gunzip < backups/backup-latest.sql.gz | docker-compose exec -T db psql -U postgres mipiace_prod
```

### Backup de sessões Evolution API

```bash
# Se usando WhatsApp Evolution
tar -czf backups/evolution-instances-$(date +%Y%m%d).tar.gz docker_volumes/evolution_instances/

# As sessões pareadas são salvas neste volume
docker volume inspect mipiace_evolution_instances
```

## Rotação de Secrets

### Mudar Admin API Key

1. Atualizar `.env.prod`:
   ```bash
   ADMIN_API_KEY=<nova-chave>
   ```

2. Restart backend:
   ```bash
   docker-compose restart backend
   ```

### Rotação de certificado SSL

Caddy gerencia automaticamente via Let's Encrypt. Verifica 30 dias antes de vencer.

### Rotação de token Mercado Pago

Se suspeitar comprometimento:

1. Gerar novo token no painel Mercado Pago
2. Atualizar `.env.prod`: `MP_ACCESS_TOKEN=...`
3. Restart backend: `docker-compose restart backend`
4. Verificar operações: `curl https://seu-dominio.com/api/metrics/orders`

## Escala e Performance

### Limites de recursos

Definidos em `docker-compose.prod.yml`:

| Serviço | CPU Limit | Memory Limit | Recomendado para |
|---------|-----------|--------------|------------------|
| Backend | 2 vCPU | 1 GB | até 1k req/min |
| Frontend | 1 vCPU | 512 MB | até 10k concurrent |
| Database | 2 vCPU | 2 GB | até 100 GB dados |

Aumentar se:
- OOMKilled: `docker-compose logs | grep OOMKilled`
- CPU throttled: Aumentar vCPU da VM

### Conexões do banco

Default: 20 conexões pool. Aumentar em `DATABASE_URL` se backend tiver `too many connections`:

```bash
# No .env.prod
DATABASE_URL=postgresql+psycopg://...?max_overflow=40&pool_size=20&pool_recycle=3600
```

## Troubleshooting

### Backend não sobe: "Connection refused"

```bash
# Verificar se Postgres está healthy
docker-compose ps db

# Ver logs
docker-compose logs db
```

### Frontend em branco / 502 Bad Gateway

```bash
# Verificar backend está respondendo
docker-compose exec -T backend curl http://localhost:8000/health

# Restart frontend
docker-compose restart frontend caddy
```

### Evolution API não recebe mensagens

```bash
# Verificar status da instância
curl -X GET http://localhost:8081/instance/fetch/mipiace_prod \
  -H "apikey: ${EVOLUTION_API_KEY}"

# Ver webhook logs
docker-compose logs evolution-api | grep webhook

# Recriar instância se necessário
curl -X POST http://localhost:8081/instance/create \
  -H "apikey: ${EVOLUTION_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"instanceName":"mipiace_prod","integration":"WHATSAPP-BAILEYS","qrcode":true}'
```

### Certificado SSL não renova

```bash
# Verificar status Caddy
docker-compose logs caddy | grep acme

# Forçar renovação
docker-compose exec caddy caddy reload

# Verificar certificado
docker-compose exec caddy ls /data/caddy/certificates
```

## Updates de código

```bash
# Puxar última versão
git pull origin main

# Rebuild e restart
docker-compose -f docker-compose.yml -f docker-compose.prod.yml build --no-cache
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Verificar
docker-compose logs -f backend
```

## Rollback

Se novo código tiver problema:

```bash
# Volta para commit anterior
git revert HEAD

# Rebuild e restart
docker-compose -f docker-compose.yml -f docker-compose.prod.yml build --no-cache
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

## Contato e Suporte

- Issues: GitHub
- Logs: `docker-compose logs -f`
- Status: `docker-compose ps`
