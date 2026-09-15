# Quick Start — Mi Piace em Produção

## TL;DR (2 minutos)

```bash
# 1. Configurar variáveis
cp .env.prod.example .env.prod
nano .env.prod  # Editar DOMAIN, POSTGRES_PASSWORD, API keys, etc.

# 2. Deploy
chmod +x deploy.sh
PROFILE=whatsapp ./deploy.sh main

# 3. Acessar
# https://seu-dominio.com         (cliente)
# https://seu-dominio.com/docs    (admin API)
# https://admin.seu-dominio.com   (banco - usuário: admin, senha: studio_pass)
```

## Checklist de Produção

### Antes de deploy

- [ ] VPS/servidor com Docker 24+ instalado
- [ ] Domínio apontando para IP do servidor
- [ ] SSH access configurado
- [ ] Arquivo `.env.prod` com valores reais (não defaults)
- [ ] Backup strategy pensada (Postgres volumes)

### Variáveis críticas no .env.prod

```
DOMAIN=seu-dominio.com
POSTGRES_PASSWORD=<senha-aleatoria-40-chars>
ADMIN_API_KEY=<chave-aleatoria-50-chars>
ANTHROPIC_API_KEY=sk-ant-...   # ou OPENAI_API_KEY
MP_ACCESS_TOKEN=APP_USR-...    # Mercado Pago (Pix)
EVOLUTION_API_KEY=...          # Só se usar WhatsApp
```

## Arquitetura

```
Internet (80, 443)
    ↓
  Caddy (HTTPS + reverse proxy)
    ├→ frontend:8080 (React)
    └→ backend:8000 (FastAPI + agente)
         ├→ postgres:5432 (não exposto)
         ├→ evolution-api:8080 (WhatsApp, opcional)
         └→ supabase-studio:3000 (admin.seu-dominio)
```

## Monitoramento

```bash
# Status
docker compose ps

# Logs backend (pedidos, conversas)
docker compose logs -f backend

# Verificar health
curl https://seu-dominio.com/health
curl https://seu-dominio.com/docs

# Ver uso de recursos
docker stats
```

## Troubleshooting

| Problema | Solução |
|----------|---------|
| 502 Bad Gateway | `docker compose restart caddy && docker compose logs caddy` |
| Backend timeout | `docker compose logs backend \| grep error` |
| Postgres OOMKilled | Aumentar `memory: 2G` em docker-compose.prod.yml |
| WhatsApp não recebe msgs | `curl http://localhost:8081/instance/fetch/mipiace_prod -H "apikey: ..."`|
| Certificado SSL falha | `docker compose logs caddy \| grep acme` |

## Backup

```bash
# Backup diário do banco
docker compose exec -T db pg_dump -U postgres mipiace_prod | gzip > backup-$(date +%Y%m%d).sql.gz

# Restore
gunzip < backup-20260915.sql.gz | docker compose exec -T db psql -U postgres mipiace_prod
```

## Updates

```bash
git pull origin main
docker compose -f docker-compose.yml -f docker-compose.prod.yml build --no-cache
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
docker compose logs -f backend
```

---

Para mais detalhes, ver `DEPLOYMENT.md`.
