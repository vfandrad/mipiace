# Colocar o Mi Piace numa VPS — passo a passo

Do servidor vazio até o cliente mandar "oi" no WhatsApp e pagar o Pix.
Para entender o sistema antes, leia o [README](README.md); para saber onde
cada coisa mora no código, o [PROJECT.md](PROJECT.md).

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
| Um chip dedicado para a loja | operadora | ver a seção 7 antes de usar o número do dono |

4 GB de RAM é o mínimo confortável **com** a Evolution API junto (ela sozinha
come ~500 MB). Sem WhatsApp no mesmo servidor, 2 GB bastam.

---

## 1. Subir no Easypanel

O Easypanel cuida de Docker, HTTPS e deploy. A Hostinger tem um template de VPS
com ele já instalado, e ele sabe subir um serviço do tipo **Compose** direto de
um repositório Git, rodando `docker compose up --build -d` e preenchendo `${VAR}`
com as variáveis que você digita na interface. É o Traefik dele que emite o
certificado — você não instala Docker, não configura firewall nem escreve
arquivo de proxy.

Use o **`docker-compose.easypanel.yml`**, não o `docker-compose.yml`. O de
desenvolvimento tem `container_name`, portas publicadas e `profiles` — as três
coisas que o Easypanel ou recusa ou ignora silenciosamente (um serviço atrás de
profile nunca sobe, porque ele não passa `--profile`).

1. **Suba o repositório para o GitHub.** Pode ser privado; o Easypanel conecta
   pela sua conta do GitHub.
2. **VPS com o template Ubuntu + Easypanel.** O painel responde em
   `http://SEU_IP:3000` — crie a conta de admin na primeira visita.
3. **DNS:** um registro **A** apontando para o IP da VPS, em dois nomes —
   `mipiace.com.br` (painel) e `api.mipiace.com.br` (backend). Faça agora e
   espere propagar (`dig +short mipiace.com.br` tem que devolver o IP da VPS),
   porque o Let's Encrypt confere o DNS no instante em que emite o certificado.
4. **No Easypanel:** novo projeto → **New Service** → **Compose** → source Git,
   apontando para o repositório, branch `main`, arquivo
   `docker-compose.easypanel.yml`.
5. **Environment:** cole as variáveis de `back/.env.example`, deixando marcado
   *Create .env file* — é dele que sai a interpolação. Gere os segredos:

   ```bash
   openssl rand -hex 32    # POSTGRES_PASSWORD
   openssl rand -hex 32    # ADMIN_API_KEY
   openssl rand -hex 24    # EVOLUTION_API_KEY
   openssl rand -hex 24    # EVOLUTION_WEBHOOK_TOKEN
   ```

6. **Deploy.** A primeira subida constrói as duas imagens e aplica
   `back/db/schema.sql` e `back/db/seed.sql`: o banco nasce com o cardápio e
   **nada mais** — sem cliente, sem pedido, sem conversa. Kanban e Dashboard
   começam zerados de propósito.
7. **Domains**, dentro do serviço:

   | Serviço interno | Porta | Domínio |
   |---|---|---|
   | `frontend` | 8080 | `mipiace.com.br` |
   | `backend` | 8000 | `api.mipiace.com.br` |

   Marque HTTPS com o certificate resolver padrão.

**Três variáveis que costumam passar batido:**

- **`EVOLUTION_WEBHOOK_TOKEN`** aparece de novo dentro da URL do webhook. Se
  esquecer de colar o token lá, o WhatsApp conecta e o bot fica mudo — as
  mensagens chegam na Evolution e são descartadas pelo backend.
- **`PUBLIC_BASE_URL`** e **`VITE_API_BASE_URL`** são o endereço `https://` do
  backend. É de `PUBLIC_BASE_URL` que sai a `notification_url` do Pix; errado, a
  cobrança é criada e nunca confirma. E as `VITE_*` entram no bundle em tempo de
  build: mudou, precisa de redeploy — reiniciar não basta.
- **`MP_ACCESS_TOKEN`** precisa ser o de produção. O de conta de teste também
  começa com `APP_USR-`. Confirme antes de confiar:

```bash
curl -s https://api.mercadopago.com/users/me \
  -H "Authorization: Bearer SEU_TOKEN" | grep -o '"nickname":"[^"]*"'
# TESTUSER... = conta de teste, ninguém paga de verdade
```

Confira que subiu:

```bash
curl https://api.mipiace.com.br/health
# {"status":"ok","version":"1.0.0","fake_mode":false,"environment":"production","database":"ok"}
```

`fake_mode:false`, `environment:production` e `database:ok` são o que importa.

---

## 2. Parear o WhatsApp

A Evolution API não tem porta pública (de propósito: o manager dela é acesso
total ao WhatsApp da loja). Abra um túnel SSH da sua máquina:

```bash
# na SUA máquina, não na VPS — deixe rodando
ssh -L 8081:localhost:8081 root@SEU_IP
```

Agora `http://localhost:8081` no seu navegador é a Evolution da VPS.

### Crie a instância pela API, não pelo manager

Criada pelo manager, a instância nasce **sem webhook**: o QR pareia, o WhatsApp
conecta e o bot não responde nada. Pela API já sai configurada. Na VPS:

```bash
source /etc/easypanel/projects/mi-piace/mi-piace/code/.env
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

O nome da instância tem que ser exatamente o `EVOLUTION_INSTANCE` do `.env`
do projeto — é por ele que o backend envia as respostas.

Os quatro ajustes (`groupsIgnore`, `readMessages`, `alwaysOnline=false`,
`syncFullHistory=false`) não são enfeite: estão explicados na seção 7.

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

## 3. Ligar o Mercado Pago

No painel do MP → **Suas integrações** → sua aplicação → **Webhooks**, cadastre
em modo produção:

```
https://SEU_DOMINIO/webhooks/mercadopago
```

Marque o evento **Pagamentos**. O MP faz um `GET` de teste ao salvar; a rota
responde 200. Copie a **Assinatura secreta** que ele mostra para
`MP_WEBHOOK_SECRET` no `.env` do projeto e recrie o backend:

```bash
cd /etc/easypanel/projects/mi-piace/mi-piace/code
docker compose -p mi-piace_mi-piace \
  -f docker-compose.easypanel.yml -f docker-compose.override.yml \
  --env-file .env up -d --no-deps backend
```

Sem a assinatura o sistema ainda funciona — o webhook nunca acredita no corpo
da notificação, sempre consulta a API do MP para saber o status de verdade —
mas qualquer um poderia disparar consultas na sua conta. Configure.

---

## 4. Conferir que está tudo de pé

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
seção 7), a conversa aparecer em **Conversas** no painel, e:

```bash
docker logs -f mi-piace_mi-piace-backend-1 | grep webhooks/evolution
```

---

## 5. Banco de dados

A stack do Easypanel não sobe o Supabase Studio de propósito: administrador de
banco sem senha própria não vale o risco num servidor público. Para olhar o
banco, use o terminal do Easypanel ou o SSH:

```bash
docker exec -it mi-piace_mi-piace-db-1 psql -U postgres
```

**Backup.** O que não pode ser perdido é o volume `pgdata`. Use o
`backup_db.sh` do repositório — ele já resolve o detalhe de que a imagem
`supabase/postgres` precisa de `--no-owner --no-acl` no `pg_dump`, senão a
restauração falha com "must be able to SET ROLE supabase_admin":

```bash
cp backup_db.sh /root/backup_db.sh
chmod +x /root/backup_db.sh
crontab -e
```

```cron
0 3 * * * /root/backup_db.sh >> /root/backup_db.log 2>&1
```

O nome do container do banco muda conforme o deploy (confira com `docker ps`);
o script assume `mi-piace_mi-piace-db-1` (padrão do Easypanel) e aceita
`DB_CONTAINER=outro-nome /root/backup_db.sh` para qualquer outro.

Restaurar:

```bash
gunzip -c /root/backups/mipiace-db-AAAA-MM-DD_HHMMSS.sql.gz \
  | docker exec -i mi-piace_mi-piace-db-1 psql -U postgres -d postgres
```

> Um backup que nunca foi restaurado não é um backup. Teste uma vez.

---

## 6. Dia a dia

```bash
docker logs -f mi-piace_mi-piace-backend-1   # acompanhar o agente
docker ps                                    # o que está de pé
docker stats                                 # CPU e memória
```

**Atualizar o código.** O Easypanel deste projeto não redeploya sozinho a partir
do GitHub, então é na mão — o passo a passo completo (quando usar `--build`, como
conferir) está no [CLAUDE.md](CLAUDE.md):

```bash
cd /etc/easypanel/projects/mi-piace/mi-piace/code
git pull origin main
docker compose -p mi-piace_mi-piace \
  -f docker-compose.easypanel.yml -f docker-compose.override.yml \
  --env-file .env up -d --build --no-deps backend
```

**Voltar atrás:** `git revert HEAD`, `git push`, e rode a mesma sequência acima.

> Não há Alembic. Se a mudança alterou `back/db/schema.sql`, o banco existente
> **não** se atualiza sozinho. Em vez de rodar SQL à mão e confiar na memória
> para saber o que já foi aplicado, copie o arquivo novo para
> `back/db/migrations/` (nome com a data, como os dois que já existem) e, no
> servidor:
>
> ```bash
> ./back/db/apply_migrations.sh
> ```
>
> Ele roda cada migração pendente uma vez e registra o nome dela na tabela
> `schema_migrations` — não tem como aplicar duas vezes por engano nem
> esquecer uma. Ajuste `DB_CONTAINER` se o nome do container do banco não for
> `mi-piace_mi-piace-db-1` (confira com `docker ps`). Faça backup antes
> (`backup_db.sh`), como sempre.

### Alterações de schema já publicadas

As migrações abaixo já estão em `back/db/migrations/` e marcadas como
aplicadas para quem sobe um banco novo a partir do `schema.sql` atual. Ficam
aqui só de histórico/contexto — quem já tinha um banco de antes rodou-as uma
vez via `apply_migrations.sh`.

**Categoria de sabor virou categoria de complemento** (o sistema deixou de
presumir que todo complemento é sabor, para atender outros tipos de loja):

```sql
ALTER TABLE flavor_categories RENAME TO complement_categories;
ALTER TABLE complements RENAME COLUMN flavor_category_id TO category_id;
ALTER INDEX IF EXISTS idx_complements_flavor_category RENAME TO idx_complements_category;
```

**Sabor não cobra a mais** (se quiser o cardápio sem acréscimo por sabor):

```sql
UPDATE complements SET extra_price = 0 WHERE extra_price <> 0;
```

**Grupo de complementos compartilhado entre produtos** — a maior mudança de
schema até hoje, e a que mais muda o dia a dia do lojista.

Antes, cada produto tinha o SEU grupo de sabores, logo a sua cópia da lista: os
31 sabores da casa viravam 93 linhas em `complements`. Marcar "pistache acabou"
custava três cliques, e os três podiam divergir — quem pedia o pote médio via
pistache, quem pedia o grande não via. Agora o grupo é uma lista compartilhada
e a regra de escolha ("escolhe 3") mora no vínculo `product_groups`, que é o
modelo do Anota Aí e do iFood.

O arquivo está em `back/db/migrations/2026-09-grupo-compartilhado.sql`:

```bash
docker compose exec -T db psql -U postgres -d postgres     -v ON_ERROR_STOP=1 < back/db/migrations/2026-09-grupo-compartilhado.sql
```

Ele roda inteiro numa transação — ou passa tudo, ou não muda nada. **Faça
backup antes** (`pg_dump`), como sempre.

O passo delicado está lá dentro e é o terceiro: `order_item_complements`
aponta para `complements` com `ON DELETE RESTRICT`, então o histórico de vendas
é **repontado** para a linha que fica antes de qualquer cópia ser apagada. Sem
isso a migração falharia — e, pior, forçá-la apagaria o que o cliente pediu.

A migração agrupa por **conjunto de sabores**: grupos que oferecem exatamente a
mesma lista viram um só; um grupo com lista diferente (uma "Coberturas" ao lado
de "Sabores") continua separado. Então ela é segura para um cardápio que já
saiu do caso da Mi Piace.

Depois de aplicar, confira:

```sql
SELECT (SELECT count(*) FROM complements)        AS sabores,
       (SELECT count(*) FROM complement_groups)  AS listas,
       (SELECT count(*) FROM product_groups)     AS vinculos;
-- No cardápio da Mi Piace: 31 sabores, 1 lista, 3 vínculos (era 93 / 3 / 0).
```

**Variáveis novas no mesmo deploy.** A identidade da loja saiu do código e
virou configuração; sem estas, o bot se apresenta como "Nossa Loja":

```bash
STORE_NAME=Mi Piace Gelateria
STORE_EMOJI=🍨
STORE_SEGMENT=gelateria
STORE_CITY=SAO PAULO
STORE_LOGO_URL=/logo-mipiace.png
```

`STORE_NAME` e `STORE_LOGO_URL` também entram no bundle do painel
(`VITE_STORE_NAME`, `VITE_STORE_LOGO_URL`), então **o front precisa ser
rebuildado** — não basta reiniciar o container.

**Trocar segredos:**

| Segredo | Como |
|---|---|
| `ADMIN_API_KEY` | edite o `.env` e redeploy **com `--build`** — a chave está no bundle do front |
| `OPENAI_API_KEY`, `MP_ACCESS_TOKEN` | edite e `up -d backend` |
| `POSTGRES_PASSWORD` | não troque depois da primeira subida: a senha está dentro do volume |
| Certificado TLS | o Caddy renova sozinho |

---

## 7. O risco de banimento do WhatsApp — leia antes de abrir a loja

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

## 8. Quando quebrar

**Certificado não emite / site não abre**
```bash
docker service logs easypanel-traefik 2>&1 | grep -i acme
dig +short SEU_DOMINIO      # o DNS aponta mesmo para esta VPS?
```
Quase sempre é DNS que ainda não propagou quando o Traefik pediu o certificado.

**Painel abre mas diz "Chave de acesso inválida"**
A `ADMIN_API_KEY` do backend e a embutida no bundle do front divergiram.
Faça um redeploy do `frontend` com `--build` (seção 6) — a chave só entra no
bundle em tempo de build.

**Painel carrega em `/` mas dá erro em `/produtos` ao recarregar**
Rota de SPA. O nginx dentro da imagem do front já trata isso em
`front/nginx.conf`; se aparecer, foi mexida ali.

**O bot não responde**
```bash
# a instância está conectada?
curl -s http://localhost:8081/instance/connectionState/$EVOLUTION_INSTANCE \
  -H "apikey: $EVOLUTION_API_KEY"        # state tem que ser "open"

# o webhook chega?
docker logs mi-piace_mi-piace-backend-1 | grep webhooks/evolution
```
Se chega e o bot fica calado, veja se a conversa está em **handoff** no painel
(Conversas) — com handoff ligado o bot cala de propósito. Se não chega nada, o
webhook da instância está sem o token certo: recrie a instância (seção 2).

**O Pix não confirma**
```bash
docker logs mi-piace_mi-piace-backend-1 | grep mercadopago
```
`PUBLIC_BASE_URL` errada é a causa mais comum: a cobrança sai com uma
`notification_url` que o MP não consegue chamar. Um 502 aqui significa token
errado ou MP fora do ar.

**Backend não sobe**
```bash
docker ps | grep mi-piace_mi-piace-db-1        # healthy?
docker logs mi-piace_mi-piace-db-1
```

**`OOMKilled` nos logs** — falta memória; aumente os limites em
`docker-compose.easypanel.yml`. **`too many connections`** — ajuste o pool na
`DATABASE_URL`: `...?pool_size=20&max_overflow=40&pool_recycle=3600`.
