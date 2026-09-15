# Deploy do Mi Piace em produção

Este documento cobre o deploy inteiro. Para entender o sistema antes, leia
o [README](README.md); para saber onde cada coisa mora no código, leia o
[PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md).

---

## 1. Pré-requisitos

- VPS com Docker 24+ e Compose v2
- Domínio apontando para o IP do servidor (o Caddy emite o certificado sozinho)
- Acesso SSH
- Uma estratégia de backup decidida (ver seção 7)

---

## 2. Arquitetura em produção

```
Internet
   ↓ 80 / 443
Caddy — proxy reverso, HTTPS automático (Let's Encrypt)
   ├─ /              → frontend (nginx, SPA React)
   ├─ /api/*         → backend (FastAPI)  — exige X-API-Key
   ├─ /webhooks/*    → backend            — valida o próprio remetente
   └─ admin.<dominio>→ Supabase Studio    — protegido por basic auth

backend (FastAPI :8000)
   ├─ Postgres :5432          — NÃO exposto para fora
   └─ Evolution API :8081     — WhatsApp (profile "whatsapp")
         ├─ evolution-db (Postgres próprio)
         └─ evolution-redis

Volumes que importam:
   pgdata               → o banco. Backup diário, é o que não pode perder.
   evolution_instances  → a sessão do WhatsApp pareada. Perder = parear de novo.
   caddy_data           → certificados TLS.
```

---

## 3. Configuração

```bash
cd /opt
git clone <repo> mipiace && cd mipiace

cp .env.prod.example .env.prod
nano .env.prod
```

Variáveis que **precisam** de valor real (o resto tem default utilizável):

| Variável | O que é |
|---|---|
| `DOMAIN` | seu domínio, sem `https://` |
| `POSTGRES_PASSWORD` | senha do banco — gere 40 caracteres aleatórios |
| `ADMIN_API_KEY` | chave do header `X-API-Key` — gere 50 caracteres |
| `OPENAI_API_KEY` | o cérebro do agente |
| `MP_ACCESS_TOKEN` | Mercado Pago, para cobrar Pix de verdade |
| `MP_WEBHOOK_SECRET` | assinatura do webhook do Mercado Pago |
| `EVOLUTION_API_KEY` | chave da Evolution API |
| `EVOLUTION_WEBHOOK_TOKEN` | token que valida o webhook do WhatsApp |
| `STUDIO_PASS` | senha do Supabase Studio |

> `FAKE_MODE` tem que ser `false` em produção. Com `true` o sistema usa LLM e
> Pix falsos — ninguém paga nada.

A chave do front (`VITE_ADMIN_API_KEY`) é embutida no bundle **em tempo de
build** e fica visível no navegador. Ela dá acesso a `/api/*`, então trate o
painel como uma aplicação interna, atrás de uma rede ou de autenticação do
proxy.

---

## 4. Subir

```bash
chmod +x deploy.sh
PROFILE=whatsapp ./deploy.sh main
```

Sem `PROFILE=whatsapp` a Evolution API não sobe (útil se o WhatsApp ainda não
vai ser usado).

### Parear o WhatsApp (só na primeira vez)

```bash
curl -X POST http://localhost:8081/instance/create \
  -H "apikey: $EVOLUTION_API_KEY" -H "Content-Type: application/json" \
  -d '{"instanceName":"mipiace_prod","integration":"WHATSAPP-BAILEYS","qrcode":true}'

curl http://localhost:8081/instance/connect/mipiace_prod -H "apikey: $EVOLUTION_API_KEY"
```

O segundo comando devolve o QR code. Escaneie com o celular da loja. A sessão
fica no volume `evolution_instances`.

Cadastre o webhook apontando para:
`https://<dominio>/webhooks/evolution?token=<EVOLUTION_WEBHOOK_TOKEN>`

### Cadastrar o webhook do Mercado Pago

No painel do Mercado Pago, aponte para `https://<dominio>/webhooks/mercadopago`.
O MP faz um `GET` de teste ao cadastrar — a rota responde 200.

---

## 5. Conferir que subiu

```bash
curl https://<dominio>/health          # {"status":"ok", "fake_mode":false}
curl https://<dominio>/                # o painel
docker compose ps                      # tudo Up/healthy
```

Depois, no painel: abra **Produtos** e confirme que o cardápio carrega, e
**Conversas** para ver as mensagens chegando.

---

## 6. Operação do dia a dia

```bash
docker compose logs -f backend         # acompanhar o agente
docker compose ps                      # status
docker stats                           # CPU e memória
```

### Atualizar o código

```bash
git pull origin main
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
docker compose logs -f backend
```

### Voltar atrás

```bash
git revert HEAD
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

> Não há sistema de migração (Alembic). Se a mudança alterou
> `back/db/schema.sql`, o banco existente **não** é atualizado sozinho — a
> alteração precisa ser aplicada à mão com `psql`.

---

## 7. Backup

O que não pode ser perdido é o volume `pgdata`.

```bash
mkdir -p /opt/mipiace/backups

# Dump
docker compose exec -T db pg_dump -U postgres postgres \
  | gzip > backups/backup-$(date +%Y%m%d-%H%M%S).sql.gz

# Restaurar
gunzip < backups/backup-XXXX.sql.gz | docker compose exec -T db psql -U postgres postgres
```

A sessão do WhatsApp vive em `evolution_instances`; sem ela é preciso parear o
QR code de novo (não há perda de dados, só de conveniência).

---

## 8. Rotação de segredos

| Segredo | Como trocar |
|---|---|
| `ADMIN_API_KEY` | edite `.env.prod`, `docker compose restart backend`, **rebuild do front** (a chave está no bundle) |
| `MP_ACCESS_TOKEN` | gere no painel do MP, edite `.env.prod`, `restart backend` |
| `OPENAI_API_KEY` | edite `.env.prod`, `restart backend` |
| Certificado TLS | o Caddy renova sozinho 30 dias antes de vencer |

---

## 9. Limites e escala

Definidos em `docker-compose.prod.yml`:

| Serviço | CPU | Memória | Serve até |
|---|---|---|---|
| backend | 2 vCPU | 1 GB | ~1k req/min |
| frontend | 1 vCPU | 512 MB | ~10k conexões |
| db | 2 vCPU | 2 GB | ~100 GB |

Se aparecer `OOMKilled` em `docker compose logs`, aumente a memória. Se o
backend reclamar de `too many connections`, ajuste o pool na `DATABASE_URL`:
`...?pool_size=20&max_overflow=40&pool_recycle=3600`.

---

## 10. Quando algo quebra

**Backend não sobe / "Connection refused"**
```bash
docker compose ps db          # o banco está healthy?
docker compose logs db
```

**Painel em branco ou 502**
```bash
docker compose exec -T backend curl http://localhost:8000/health
docker compose restart frontend caddy
```

**O bot não responde no WhatsApp**
```bash
# a instância está conectada?
curl http://localhost:8081/instance/fetch/mipiace_prod -H "apikey: $EVOLUTION_API_KEY"

# o webhook está chegando?
docker compose logs backend | grep webhooks/evolution
```
Se a instância caiu, refaça o pareamento da seção 4. Se o webhook chega mas o
bot fica calado, veja se a conversa está em **handoff** no painel (Conversas) —
com o handoff ligado o bot fica calado de propósito.

**O Pix não confirma**
```bash
docker compose logs backend | grep mercadopago
```
O webhook consulta a API do MP antes de aceitar qualquer coisa; um 502 aqui
significa que o token está errado ou o MP está fora.

**Certificado TLS não renova**
```bash
docker compose logs caddy | grep acme
docker compose exec caddy caddy reload
```
