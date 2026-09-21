# Colocar o Mi Piace numa VPS — passo a passo

Do servidor vazio até o cliente mandar "oi" no WhatsApp e pagar o Pix.
Para entender o sistema antes, leia o [README](README.md); para saber onde
cada coisa mora no código, o [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md).

Tudo que está aqui roda como um usuário comum com acesso ao Docker. O que
aparece depois de `#` é comentário, não precisa digitar.

---

## 0. Antes de começar, tenha em mãos

| O quê | Onde consegue | Sem isso… |
|---|---|---|
| VPS Linux, 2 vCPU / 4 GB / 40 GB | qualquer provedor | — |
| Domínio | registrador | não há HTTPS, e sem HTTPS o Mercado Pago não chama o webhook |
| Chave da OpenAI | platform.openai.com | o agente não entende nada |
| Credenciais **de produção** do Mercado Pago | painel do MP | o Pix não cobra de verdade |
| Um chip dedicado para a loja | operadora | ver a seção 9 antes de usar o número do dono |

4 GB de RAM é o mínimo confortável **com** a Evolution API junto (ela sozinha
come ~500 MB). Sem WhatsApp no mesmo servidor, 2 GB bastam.

---

## 1. Preparar o servidor

```bash
ssh root@SEU_IP

# Docker (script oficial)
curl -fsSL https://get.docker.com | sh

# Um usuário que não seja root para rodar a aplicação
adduser mipiace
usermod -aG docker mipiace

# Firewall: só SSH e web. O banco, a API e a Evolution NÃO ficam expostos —
# o docker-compose.prod.yml prende as portas deles em 127.0.0.1.
ufw allow OpenSSH
ufw allow 80
ufw allow 443
ufw enable
```

> **Atenção com o firewall e o Docker.** O Docker escreve direto no iptables e
> consegue furar o `ufw` ao publicar uma porta. É por isso que toda porta
> interna deste projeto é publicada como `127.0.0.1:porta:porta` em produção —
> confira com `ss -tlnp` depois de subir: só 80, 443 e 22 podem aparecer em
> `0.0.0.0`.

### DNS — faça agora, não depois

No painel do seu domínio, um registro **A** apontando para o IP da VPS:

```
mipiace.com.br.   A   203.0.113.10
```

O Caddy pede o certificado ao Let's Encrypt na primeira subida, e o Let's
Encrypt confere o DNS naquele instante. Se o domínio ainda não resolver, a
emissão falha e você fica com o site fora do ar por minutos até ele tentar de
novo. Espere propagar:

```bash
dig +short mipiace.com.br    # tem que devolver o IP da VPS
```

---

## 2. Código e configuração

```bash
su - mipiace
git clone <URL_DO_REPO> mipiace && cd mipiace

cp .env.prod.example .env.prod

# Gere os segredos (rode cada linha e cole o resultado no .env.prod)
openssl rand -hex 32    # POSTGRES_PASSWORD
openssl rand -hex 32    # ADMIN_API_KEY
openssl rand -hex 24    # EVOLUTION_API_KEY
openssl rand -hex 24    # EVOLUTION_WEBHOOK_TOKEN

nano .env.prod
chmod 600 .env.prod
```

O arquivo `.env.prod.example` explica cada variável. Três que costumam passar
batido:

- **`EVOLUTION_WEBHOOK_URL`** repete o `EVOLUTION_WEBHOOK_TOKEN` dentro da URL.
  Se esquecer de colar o token lá, o WhatsApp conecta e o bot fica mudo — as
  mensagens chegam na Evolution e são descartadas pelo backend.
- **`PUBLIC_BASE_URL`** é o endereço `https://` do seu domínio. É dele que sai a
  `notification_url` do Pix; errado, a cobrança é criada e nunca confirma.
- **`MP_ACCESS_TOKEN`** precisa ser o de produção. O de conta de teste também
  começa com `APP_USR-`. Confirme antes de confiar:

```bash
curl -s https://api.mercadopago.com/users/me \
  -H "Authorization: Bearer SEU_TOKEN" | grep -o '"nickname":"[^"]*"'
# TESTUSER... = conta de teste, ninguém paga de verdade
```

---

## 3. Subir

```bash
chmod +x deploy.sh
PROFILE=whatsapp ./deploy.sh
```

O script recusa subir com variável obrigatória em branco ou com
`FAKE_MODE=true` — as duas formas de pôr no ar um sistema que parece saudável e
não cobra ninguém. Sem `PROFILE=whatsapp` tudo sobe menos a Evolution API
(útil para preparar o painel antes de ter o chip).

Na primeira subida o Postgres aplica `back/db/schema.sql` e `back/db/seed.sql`:
nasce com o cardápio (3 tamanhos, 31 sabores) e **nada mais** — sem cliente,
sem pedido, sem conversa. Kanban e Dashboard começam zerados de propósito.

Confira:

```bash
curl https://SEU_DOMINIO/health
# {"status":"ok","version":"1.0.0","fake_mode":false,"environment":"production"}
```

`fake_mode:false` e `environment:production` são o que importa aqui.

---

## 4. Parear o WhatsApp

A Evolution API não tem porta pública (de propósito: o manager dela é acesso
total ao WhatsApp da loja). Abra um túnel SSH da sua máquina:

```bash
# na SUA máquina, não na VPS — deixe rodando
ssh -L 8081:localhost:8081 mipiace@SEU_IP
```

Agora `http://localhost:8081` no seu navegador é a Evolution da VPS.

### Crie a instância pela API, não pelo manager

Criada pelo manager, a instância nasce **sem webhook**: o QR pareia, o WhatsApp
conecta e o bot não responde nada. Pela API já sai configurada. Na VPS:

```bash
source .env.prod
curl -X POST http://localhost:8081/instance/create \
  -H "apikey: $EVOLUTION_API_KEY" -H "Content-Type: application/json" \
  -d "{\"instanceName\":\"$EVOLUTION_INSTANCE\",
       \"integration\":\"WHATSAPP-BAILEYS\",
       \"qrcode\":true,
       \"groupsIgnore\":true,
       \"readMessages\":true,
       \"alwaysOnline\":false,
       \"syncFullHistory\":false,
       \"webhook\":{\"url\":\"http://backend:8000/webhooks/evolution?token=$EVOLUTION_WEBHOOK_TOKEN\",
                    \"byEvents\":false,
                    \"events\":[\"MESSAGES_UPSERT\"]}}"
```

O nome da instância tem que ser exatamente o `EVOLUTION_INSTANCE` do
`.env.prod` — é por ele que o backend envia as respostas.

Os quatro ajustes (`groupsIgnore`, `readMessages`, `alwaysOnline=false`,
`syncFullHistory=false`) não são enfeite: estão explicados na seção 9.

### Escaneie o QR

Pelo túnel, abra `http://localhost:8081/manager/` e faça login com
**Server URL** `http://localhost:8081` e a **API Key** igual ao
`EVOLUTION_API_KEY`. A instância aparece na lista com um botão de QR code.

> O manager guarda a chave no navegador. Se você já usou outra chave antes, ele
> insiste na antiga e a tela mostra lista vazia ou "não autorizado" — abra numa
> janela anônima.

Sem navegador, dá para salvar o QR como imagem:

```bash
curl -s http://localhost:8081/instance/connect/$EVOLUTION_INSTANCE \
  -H "apikey: $EVOLUTION_API_KEY" \
  | python3 -c "import sys,json,base64;d=json.load(sys.stdin);open('qr.png','wb').write(base64.b64decode(d['base64'].split(',',1)[1]))"
```

Confirme que pareou:

```bash
curl -s http://localhost:8081/instance/connectionState/$EVOLUTION_INSTANCE \
  -H "apikey: $EVOLUTION_API_KEY"
# {"instance":{"instanceName":"mipiace","state":"open"}}   <- "open" é conectado
```

A sessão fica no volume `evolution_instances`. Perder esse volume não perde
dado nenhum do negócio, só obriga a parear de novo.

---

## 5. Ligar o Mercado Pago

No painel do MP → **Suas integrações** → sua aplicação → **Webhooks**, cadastre
em modo produção:

```
https://SEU_DOMINIO/webhooks/mercadopago
```

Marque o evento **Pagamentos**. O MP faz um `GET` de teste ao salvar; a rota
responde 200. Copie a **Assinatura secreta** que ele mostra para
`MP_WEBHOOK_SECRET` no `.env.prod` e reinicie o backend:

```bash
docker compose --env-file .env.prod -f docker-compose.yml -f docker-compose.prod.yml \
  up -d backend
```

Sem a assinatura o sistema ainda funciona — o webhook nunca acredita no corpo
da notificação, sempre consulta a API do MP para saber o status de verdade —
mas qualquer um poderia disparar consultas na sua conta. Configure.

---

## 6. Conferir que está tudo de pé

```bash
# só 22, 80 e 443 podem estar em 0.0.0.0
ss -tlnp | grep -v 127.0.0.1

curl https://SEU_DOMINIO/health          # fake_mode:false
curl -I https://SEU_DOMINIO/             # 200, e HTTP redireciona para HTTPS
curl -s -o /dev/null -w "%{http_code}\n" https://SEU_DOMINIO/api/products
# 401 — sem a chave TEM que recusar
```

No navegador, abra `https://SEU_DOMINIO`: o painel carrega, **Produtos** mostra
o cardápio, **Produção** e **Dashboard** aparecem zerados.

O teste que vale por todos: mande "oi" do seu celular para o número da loja.
Deve chegar resposta do agente em alguns segundos (ele demora de propósito, ver
seção 9), a conversa aparecer em **Conversas** no painel, e:

```bash
docker compose --env-file .env.prod logs -f backend | grep webhooks/evolution
```

---

## 7. Banco de dados

O Supabase Studio não é publicado. Para usar, mesmo túnel SSH da seção 4
(`ssh -L 54323:localhost:54323 mipiace@SEU_IP`) e abra `http://localhost:54323`.

**Backup.** O que não pode ser perdido é o volume `pgdata`. Um cron diário:

```bash
mkdir -p ~/mipiace/backups
crontab -e
```

```cron
0 4 * * * cd ~/mipiace && docker compose --env-file .env.prod exec -T db pg_dump -U postgres postgres | gzip > backups/$(date +\%Y\%m\%d).sql.gz && find backups -name '*.sql.gz' -mtime +14 -delete
```

Restaurar:

```bash
gunzip < backups/20260921.sql.gz \
  | docker compose --env-file .env.prod exec -T db psql -U postgres postgres
```

> Um backup que nunca foi restaurado não é um backup. Teste uma vez.

---

## 8. Dia a dia

```bash
docker compose --env-file .env.prod logs -f backend   # acompanhar o agente
docker compose --env-file .env.prod ps                # o que está de pé
docker stats                                          # CPU e memória
```

**Atualizar o código:**

```bash
cd ~/mipiace
git pull origin main
PROFILE=whatsapp ./deploy.sh
```

**Voltar atrás:** `git revert HEAD && PROFILE=whatsapp ./deploy.sh`.

> Não há sistema de migração (Alembic). Se a mudança alterou
> `back/db/schema.sql`, o banco existente **não** se atualiza sozinho — a
> alteração tem que ser aplicada à mão com `psql`.

**Trocar segredos:**

| Segredo | Como |
|---|---|
| `ADMIN_API_KEY` | edite, `./deploy.sh` — **precisa rebuildar o front**, a chave está no bundle |
| `OPENAI_API_KEY`, `MP_ACCESS_TOKEN` | edite e `up -d backend` |
| `POSTGRES_PASSWORD` | não troque depois da primeira subida: a senha está dentro do volume |
| Certificado TLS | o Caddy renova sozinho |

---

## 9. O risco de banimento do WhatsApp — leia antes de abrir a loja

O canal é um cliente **não-oficial** (Evolution API, Baileys por baixo). Isso
contraria os termos do WhatsApp, e o risco é da conta. Três coisas mudam a
probabilidade de verdade:

**Use um chip dedicado da loja.** Nunca o número pessoal do dono. Se cair, cai
o que dá para perder.

**Aqueça número novo.** Chip recém-comprado que começa disparando para dezenas
de pessoas é o perfil clássico de banimento. A referência da comunidade é uma
rampa de uns 7 dias começando em ~20 mensagens/dia.

**O IP da VPS é uma piora em relação a rodar em casa.** IP de datacenter é
marcado com muito mais agressividade que o residencial da sua conexão. Se o
número for banido depois da migração, é o primeiro suspeito — e o remédio é
configurar um proxy residencial na instância da Evolution.

O que o sistema já faz sozinho (`back/app/agent/pacing.py`): nunca envia
mensagem para quem não escreveu primeiro, demora para responder como um humano
demoraria (digitação sorteada em torno de 45 ppm, com o "digitando..." visível)
e respeita um teto de 12 mensagens por minuto. Na instância:
`groupsIgnore=true` (o bot nem recebe grupo), `readMessages=true`,
`alwaysOnline=false`.

---

## 10. Quando quebrar

**Certificado não emite / site não abre**
```bash
docker compose --env-file .env.prod logs caddy | grep -i acme
dig +short SEU_DOMINIO      # o DNS aponta mesmo para esta VPS?
```
Quase sempre é DNS que ainda não propagou quando o Caddy subiu.

**Painel abre mas diz "Chave de acesso inválida"**
A `ADMIN_API_KEY` do backend e a embutida no bundle do front divergiram.
Rode `./deploy.sh` de novo — ele reconstrói o front com a chave atual.

**Painel carrega em `/` mas dá erro em `/produtos` ao recarregar**
Rota de SPA. O nginx do front já trata; se aparecer, foi mexida no `Caddyfile`
— o bloco `handle` sem caminho tem que ser o último.

**O bot não responde**
```bash
# a instância está conectada?
curl -s http://localhost:8081/instance/connectionState/$EVOLUTION_INSTANCE \
  -H "apikey: $EVOLUTION_API_KEY"        # state tem que ser "open"

# o webhook chega?
docker compose --env-file .env.prod logs backend | grep webhooks/evolution
```
Se chega e o bot fica calado, veja se a conversa está em **handoff** no painel
(Conversas) — com handoff ligado o bot cala de propósito. Se não chega nada, o
webhook da instância está sem o token certo: recrie a instância (seção 4).

**O Pix não confirma**
```bash
docker compose --env-file .env.prod logs backend | grep mercadopago
```
`PUBLIC_BASE_URL` errada é a causa mais comum: a cobrança sai com uma
`notification_url` que o MP não consegue chamar. Um 502 aqui significa token
errado ou MP fora do ar.

**Backend não sobe**
```bash
docker compose --env-file .env.prod ps db       # healthy?
docker compose --env-file .env.prod logs db
```

**`OOMKilled` nos logs** — falta memória; aumente os limites em
`docker-compose.prod.yml`. **`too many connections`** — ajuste o pool na
`DATABASE_URL`: `...?pool_size=20&max_overflow=40&pool_recycle=3600`.
