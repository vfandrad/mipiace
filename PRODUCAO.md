# 🚀 Deploy em Produção - Mi Piace

## Checklist Pré-Deploy

- [ ] VPS/Servidor com Docker 24+
- [ ] Domínio apontando para IP do servidor
- [ ] SSH acesso configurado
- [ ] Backup strategy definida

## 1. Preparar Servidor

```bash
ssh user@seu-dominio.com

# Clonar repositório
cd /opt
git clone https://github.com/seu-user/mipiace.git
cd mipiace

# Criar .env.prod com variáveis reais
cp .env.prod.example .env.prod
nano .env.prod
```

## 2. Variáveis Críticas (.env.prod)

```bash
DOMAIN=seu-dominio.com
POSTGRES_PASSWORD=<senha-aleatoria-40-chars>
ADMIN_API_KEY=<chave-aleatoria-50-chars>
ANTHROPIC_API_KEY=sk-ant-...
MP_ACCESS_TOKEN=APP_USR-...
EVOLUTION_WEBHOOK_ENABLED=true
```

## 3. Deploy com Profile WhatsApp

```bash
chmod +x deploy.sh

# Com Evolution API (WhatsApp self-hosted)
PROFILE=whatsapp ./deploy.sh main

# Ou sem Evolution (apenas simulator)
./deploy.sh main
```

## 4. Verificar Status

```bash
# Containers rodando
docker compose ps

# Logs backend
docker compose logs -f backend

# Health check
curl https://seu-dominio.com/health
curl https://seu-dominio.com/docs
```

## 5. QR Code WhatsApp

Se usando Evolution API:

```bash
# Ver QR code
curl http://localhost:8081/qrcode/mipiace

# Ou acessar
http://seu-dominio-interno:8081/qrcode/mipiace
```

Escaneie com seu WhatsApp pessoal.

## 6. URLs de Produção

- **Cliente (app WhatsApp Web)**: https://seu-dominio.com/cliente
- **Admin Painel**: https://seu-dominio.com/loja
- **API Swagger**: https://seu-dominio.com/docs
- **Banco Admin**: https://admin.seu-dominio.com (user: admin, pass: from .env.prod)

## 7. Backup Diário

```bash
# Backup Postgres
docker compose exec -T db pg_dump -U postgres mipiace_prod | \
  gzip > backups/db-$(date +%Y%m%d).sql.gz

# Backup Evolution Sessions (se usando)
tar -czf backups/evolution-$(date +%Y%m%d).tar.gz \
  docker_volumes/evolution_instances/
```

## 8. Monitoramento

```bash
# Watch logs
docker compose logs -f backend caddy

# Resource usage
docker stats

# Disk usage
df -h docker_volumes/
```

## 9. Updates & Rollback

```bash
# Pull latest
git pull origin main

# Rebuild & deploy
PROFILE=whatsapp ./deploy.sh main

# Rollback if needed
git revert HEAD
PROFILE=whatsapp ./deploy.sh main
```

## ⚠️ Troubleshooting

### 502 Bad Gateway
```bash
docker compose restart caddy
docker compose logs caddy
```

### Backend crash
```bash
docker compose logs backend | grep -i error
docker compose restart backend
```

### WhatsApp não recebe
```bash
curl http://localhost:8081/instance/fetch/mipiace -H "apikey: ..."
# Se disconnected, gere novo QR code
```

## Suporte

- Issues: GitHub
- Logs: `docker compose logs -f`
- Status: `docker compose ps`
