# Mi Piace — Gelateria

Sistema de gestão e vendas de uma gelateria artesanal. Junta em um só projeto:

- um **painel web** para o balcão (Kanban de produção, cardápio, dashboard e
  monitoramento das conversas);
- uma **API FastAPI** com Postgres, que é a única dona das regras de negócio;
- um **agente de WhatsApp** que atende o cliente, monta o pedido e cobra por Pix
  — escrito como máquina de estados em Python + LLM, no lugar do workflow de n8n
  que existia antes.

O objetivo do MVP é rodar inteiro na sua máquina, **sem nenhuma chave de API**:
com `FAKE_MODE=true` o LLM e o Mercado Pago são substituídos por implementações
falsas determinísticas.

---

## Arquitetura

```
                        ┌──────────────────────────────┐
   WhatsApp Cloud API   │  navegador (painel do lojista)│
        (Meta)          │  React 18 + Vite + shadcn/ui  │
           │            └───────────────┬───────────────┘
           │  webhook                   │ REST + X-API-Key
           ▼                            ▼
   ┌─────────────────────────────────────────────────────┐
   │                    FastAPI (:8000)                  │
   │                                                     │
   │  api/routes/         services/          agent/      │
   │   products            catalog            machine    │
   │   orders              orders             resolver   │
   │   metrics             pricing            renderer   │
   │   conversations       metrics            runner     │
   │   whatsapp            payments/          llm/       │
   │   simulator            ├ mercadopago     channels/  │
   │   dev                  └ fake                       │
   └───────────────┬───────────────────────┬─────────────┘
                   │                       │
                   ▼                       ▼
          ┌─────────────────┐    ┌────────────────────────┐
          │  PostgreSQL 16  │    │  Anthropic (Claude)    │
          │  catálogo,      │    │  ou FakeLLMClient      │
          │  pedidos,       │    ├────────────────────────┤
          │  pagamentos,    │    │  Mercado Pago (Pix)    │
          │  conversas      │    │  ou FakePaymentProvider│
          └─────────────────┘    └────────────────────────┘
```

Três decisões que explicam o resto do código:

1. **O LLM não decide fluxo, não calcula preço e não inventa item.** Ele só
   devolve intenção + texto extraído (`NluResult`). Quem resolve esse texto
   contra o catálogo real e soma o carrinho em `Decimal` é a máquina de estados.
2. **O estado da conversa vive no banco** (tabela `conversations`), não na
   memória do processo nem dentro de um workflow visual. É isso que permite
   reiniciar o servidor sem perder o pedido em andamento.
3. **Preços são congelados na venda** (`product_name_snapshot`,
   `unit_base_price`, `complement_name_snapshot`). Renomear um sabor hoje não
   reescreve o histórico de vendas de ontem.

### Stack

| Camada | Tecnologia |
|---|---|
| Frontend | React 18, Vite, TypeScript, Tailwind + shadcn/ui, TanStack Query, Recharts |
| Backend | FastAPI, SQLAlchemy async, Pydantic v2 |
| Banco | PostgreSQL 16 |
| IA | Anthropic Claude (tool use para saída estruturada) ou LLM falso |
| Pagamento | Mercado Pago Pix ou provedor falso |
| Mensageria | WhatsApp Cloud API (Meta) ou console/simulador |

### Telas do painel

| Rota | O que faz |
|---|---|
| `/loja` | Kanban de produção: novo → preparando → entrega → finalizado (+ cancelados). Mostra código do pedido, itens com complementos, total e o Pix pendente para reenviar ao cliente. |
| `/produtos` | CRUD do cardápio: produto > categoria (grupo de escolhas) > complementos, com disponibilidade em tempo real. |
| `/conversas` | Monitoramento do agente: lista de conversas com estado da máquina, histórico em formato de chat com a intenção detectada pela IA e botão de "assumir atendimento". |
| `/admin` | Dashboard: vendas, ticket médio, vendas por dia, produtos mais vendidos e pedidos por horário, com filtro de período. |

---

## Máquina de estados do agente

Cada mensagem recebida passa pelo LLM (que só classifica), é resolvida contra o
catálogo e então a máquina decide a transição. Saltos fora desta tabela levantam
erro de propósito — é o que impede, por exemplo, gerar Pix sem endereço.

```
                            ┌──────────────┐
              (1ª mensagem) │   SAUDACAO   │
                            └──────┬───────┘
                                   │ cumprimenta + cardápio resumido
                                   ▼
                        ┌────────────────────────┐
              ┌────────►│  ESCOLHENDO_PRODUTO    │◄────────┐
              │         └───┬────────────────┬───┘         │
              │             │                │             │
              │  produto com│                │ produto sem │ "quero mais
              │  grupo      │                │ grupo       │  uma coisa"
              │  obrigatório│                │ obrigatório │
              │             ▼                │             │
              │  ┌────────────────────────┐  │             │
              │  │  PERSONALIZANDO_ITEM   │  │             │
              │  │ (valida min/max por    │  │             │
              │  │  grupo, um de cada vez)│  │             │
              │  └───────────┬────────────┘  │             │
              │              │ todos os grupos OK          │
              │              ▼                ▼            │
              │         ┌─────────────────────────┐        │
              └─────────┤   REVISANDO_CARRINHO    ├────────┘
                        └───┬──────────────────┬──┘
                    entrega │                  │ retirada
                            ▼                  │
                ┌────────────────────────┐     │
                │  COLETANDO_ENDERECO    │     │
                │ (pede só o que falta:  │     │
                │  rua / número / bairro)│     │
                └───────────┬────────────┘     │
                            │                  │
                            ▼                  ▼
                     ┌──────────────────────────────┐
                     │     CONFIRMANDO_PEDIDO       │
                     │ resumo + taxa + total        │
                     └──────────────┬───────────────┘
                                    │ cliente confirma
                                    │ → cria pedido, gera Pix,
                                    │   envia copia-e-cola
                                    ▼
                     ┌──────────────────────────────┐
                     │    AGUARDANDO_PAGAMENTO      │  ← estado passivo
                     └──────────────┬───────────────┘
                                    │ webhook do Mercado Pago
                                    │ (ou POST /api/dev/payments/{id}/approve)
                                    ▼
                     ┌──────────────────────────────┐
                     │          CONCLUIDO           │──┐
                     └──────────────────────────────┘  │ cliente volta
                                                       └─► SAUDACAO

  Saídas possíveis de quase todos os estados:
    • ATENDIMENTO_HUMANO — o cliente pede atendente, OU a IA falha
      `MAX_NLU_FAILURES` vezes seguidas, OU o lojista clica em
      "assumir atendimento" em /conversas. Com handoff=true o agente
      não responde mais nada automaticamente.
    • CANCELADO — cliente desiste ou o Pix expira.
```

A tabela executável dessas transições está em `back/app/agent/states.py`; os
nomes dos estados, em `back/app/domain/enums.py`.

---

## Como rodar

### Opção A — Docker (recomendado)

Pré-requisito: Docker Desktop (ou Docker Engine + Compose v2).

```bash
git clone <repo> mipiace
cd mipiace

cp back/.env.example back/.env      # já vem com FAKE_MODE=true
docker compose up --build
```

Sobe três serviços:

| Serviço | URL |
|---|---|
| Frontend (nginx) | http://localhost:8080 |
| API (FastAPI) | http://localhost:8000 — docs em `/docs` |
| Postgres | `localhost:5432` (usuário/senha/base: `mipiace`) |

O banco aplica `back/db/schema.sql` e `back/db/seed.sql` automaticamente na
primeira subida, então o cardápio já nasce populado e o dashboard já nasce com
gráficos. Para recomeçar do zero: `docker compose down -v`.

### Opção B — sem Docker

Você precisa de **Python 3.12+**, **Node 20+** e um **PostgreSQL 14+** rodando.

**1. Banco**

```bash
createdb mipiace
psql -d mipiace -f back/db/schema.sql
psql -d mipiace -f back/db/seed.sql
```

**2. Backend**

```bash
cd back
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # ajuste DATABASE_URL se precisar
uvicorn app.main:app --reload      # http://localhost:8000/docs
```

**3. Frontend** (em outro terminal)

```bash
cd front
cp .env.example .env.local         # aponta para http://localhost:8000
npm install
npm run dev                        # http://localhost:8080
```

> A `VITE_ADMIN_API_KEY` do front precisa ser igual à `ADMIN_API_KEY` do back —
> toda rota `/api/*` exige o header `X-API-Key`. Se o painel mostrar
> "Chave de acesso inválida", é isso.

**Comandos úteis do front**

```bash
npm run dev      # servidor de desenvolvimento na porta 8080
npm run build    # build de produção em dist/
npm run test     # testes (vitest)
npm run lint     # eslint
```

**Testes do back**

```bash
cd back && pytest
```

---

## Testar o agente sem WhatsApp nenhum

Com `FAKE_MODE=true` o agente usa um LLM falso determinístico que casa palavras
com o catálogo real. Dá para conversar com ele de duas formas.

### 1. CLI interativa

```bash
cd back
python -m app.cli.chat
```

Abre um chat no terminal que fala com a mesma máquina de estados que o WhatsApp
usaria. Um roteiro que percorre o fluxo inteiro:

```
oi
quero um pote de 500ml
pistache, chocolate e morango
não, é só isso
rua das flores, 123, centro
sim
```

No fim ele devolve o Pix copia-e-cola falso. Para aprovar o pagamento e ver a
conversa chegar em `CONCLUIDO`:

```bash
curl -X POST http://localhost:8000/api/dev/payments/<order_id>/approve \
     -H "X-API-Key: dev-local-key"
```

### 2. Endpoint de simulador (bom para script e para o painel)

```bash
curl -X POST http://localhost:8000/api/simulator/message \
     -H "Content-Type: application/json" \
     -H "X-API-Key: dev-local-key" \
     -d '{"phone": "5511999998888", "text": "oi"}'
# -> {"replies": ["Oi! Aqui é a Mi Piace ..."], "state": "escolhendo_produto"}

# recomeçar a conversa desse telefone
curl -X POST http://localhost:8000/api/simulator/reset \
     -H "Content-Type: application/json" \
     -H "X-API-Key: dev-local-key" \
     -d '{"phone": "5511999998888"}'
```

Enquanto você conversa, abra **http://localhost:8080/conversas**: a conversa
aparece na lista, o histórico atualiza sozinho a cada 10 segundos e cada
mensagem do cliente mostra a intenção que a IA detectou. Quando o pedido for
confirmado, ele aparece no Kanban em **/loja**.

---

## Sair do FAKE_MODE (ir para produção)

Coloque `FAKE_MODE=false` em `back/.env` e preencha as chaves abaixo. Enquanto
alguma faltar, o serviço correspondente não funciona — mas o resto do sistema
continua de pé.

### Anthropic (o cérebro do agente)

```env
FAKE_MODE=false
ANTHROPIC_API_KEY=sk-ant-...
LLM_MODEL=claude-haiku-4-5
```

Chave em https://console.anthropic.com. O agente usa *tool use* para forçar
saída estruturada e aplica prompt caching no bloco do cardápio; em qualquer
erro ou timeout ele devolve intenção `desconhecido` e a máquina repergunta, em
vez de derrubar a requisição.

### WhatsApp Cloud API (Meta)

```env
WHATSAPP_TOKEN=EAAG...              # token permanente do app
WHATSAPP_PHONE_NUMBER_ID=1234567890 # id do número de teste ou do número real
WHATSAPP_VERIFY_TOKEN=algo-secreto  # o que você digitar no painel da Meta
WHATSAPP_APP_SECRET=...             # usado para validar a assinatura do webhook
PUBLIC_BASE_URL=https://seu-dominio.com
```

Passos no painel da Meta (developers.facebook.com):

1. Crie um app do tipo *Business* e adicione o produto **WhatsApp**.
2. Em *Configuration > Webhook*, aponte para
   `https://seu-dominio.com/webhooks/whatsapp` e informe o mesmo
   `WHATSAPP_VERIFY_TOKEN`. A Meta faz um `GET` de verificação e o backend
   devolve o `hub.challenge`.
3. Assine o campo `messages`.
4. Para testar localmente, exponha a porta 8000 com um túnel
   (`ngrok http 8000`) e use a URL do túnel como `PUBLIC_BASE_URL`.

### Mercado Pago (Pix)

```env
MP_ACCESS_TOKEN=APP_USR-...
MP_WEBHOOK_SECRET=...
```

O token sai de https://www.mercadopago.com.br/developers > *Suas integrações >
Credenciais*. Configure a notificação de webhook para
`https://seu-dominio.com/webhooks/mercadopago`. O backend registra cada evento
em `webhook_events` com `UNIQUE (source, external_id)` — reenvio do mesmo evento
não credita o pedido duas vezes.

### Frontend em produção

As variáveis `VITE_*` são embutidas no bundle **em tempo de build**, não em
runtime. Ao construir a imagem, passe-as como build args:

```bash
docker build ./front \
  --build-arg VITE_API_BASE_URL=https://api.seu-dominio.com \
  --build-arg VITE_ADMIN_API_KEY=<chave-do-painel>
```

E lembre de incluir a origem do painel em `CORS_ORIGINS` no `back/.env`.

---

## Segurança

**Nada de `.env` no Git.** Os arquivos `back/.env` e `front/.env*` estão no
`.gitignore` e devem continuar lá. O que se versiona é apenas o `.env.example`,
com placeholders vazios. Se um segredo entrar num commit, considere-o vazado —
apagar o arquivo num commit seguinte não remove o valor do histórico.

> **Rotacione o token do Mercado Pago.** O repositório antigo tinha um
> `MP_ACCESS_TOKEN` de produção commitado em texto puro. Esse token precisa ser
> **revogado e regenerado** no painel do Mercado Pago (*Suas integrações >
> Credenciais > renovar*), mesmo que o arquivo já tenha sido removido: qualquer
> pessoa com acesso ao histórico do repositório consegue recuperá-lo e criar
> cobranças em nome da loja. O mesmo vale para qualquer token do WhatsApp ou
> chave da Anthropic que tenha passado pelo repositório.

Outros pontos que valem atenção:

- **`ADMIN_API_KEY` não é autenticação de usuário.** É uma chave única, embutida
  no bundle do front — protege contra acesso casual à API, não contra alguém que
  abra o DevTools. Para um deploy público de verdade, o próximo passo é login
  por usuário (sessão/JWT) e restringir o painel por rede ou VPN. Enquanto isso
  não existe, use uma chave longa e aleatória e sirva o painel só para quem
  precisa.
- **`CORS_ORIGINS` deve listar só as origens reais** do painel. Nada de `*`.
- **Webhooks são verificados por assinatura** (`WHATSAPP_APP_SECRET`,
  `MP_WEBHOOK_SECRET`), e por isso não exigem `X-API-Key`. Se essas variáveis
  estiverem vazias em produção, qualquer um consegue forjar uma aprovação de
  pagamento.
- **Rotas de desenvolvimento** (`/api/simulator/*`, `/api/dev/*`) só existem com
  `FAKE_MODE=true`/`DEBUG=true`. Confirme que estão desligadas em produção.
- **Dados pessoais**: o banco guarda telefone, nome e endereço de clientes, além
  do histórico completo das conversas. Trate backups com o mesmo cuidado.

---

## Estrutura do repositório

```
.
├── docker-compose.yml        # Postgres + API + painel
├── back/
│   ├── app/
│   │   ├── api/routes/       # HTTP: produtos, pedidos, métricas, conversas,
│   │   │                     #       webhooks, simulador
│   │   ├── agent/            # máquina de estados, resolver, renderer,
│   │   │   ├── llm/          #   cliente Anthropic + LLM falso
│   │   │   └── channels/     #   WhatsApp, console
│   │   ├── cli/chat.py       # simulador de conversa no terminal
│   │   ├── core/             # config (env), segurança, logging
│   │   ├── db/               # models SQLAlchemy e sessão
│   │   ├── domain/           # enums, catálogo, carrinho (regras puras)
│   │   ├── repositories/     # acesso a dados
│   │   ├── schemas/          # DTOs Pydantic da API
│   │   └── services/         # catálogo, pedidos, preço, métricas, pagamentos
│   ├── db/schema.sql         # fonte de verdade do modelo
│   ├── db/seed.sql           # cardápio e pedidos de exemplo
│   └── tests/
└── front/
    ├── src/
    │   ├── components/       # dashboard, production, products,
    │   │                     # conversations, layout, ui (shadcn)
    │   ├── hooks/            # use-orders, use-products, use-metrics,
    │   │                     # use-conversations
    │   ├── lib/              # api.ts (cliente HTTP), config, format, transforms
    │   ├── pages/            # Loja, Produtos, Conversas, Admin
    │   └── types/            # tipos espelhando o schema do banco
    ├── Dockerfile            # build Node -> nginx na porta 8080
    └── .env.example
```

---

## API em resumo

Todas as rotas `/api/*` exigem `X-API-Key`. Erros seguem
`{"detail": "mensagem"}` com o status HTTP adequado.

```
GET    /health

GET    /api/products                       POST   /api/products
PATCH  /api/products/{id}                  DELETE /api/products/{id}
POST   /api/products/{id}/groups           PATCH/DELETE /api/groups/{id}
POST   /api/groups/{id}/complements        PATCH/DELETE /api/complements/{id}

GET    /api/orders?status=&limit=          GET    /api/orders/{id}
PATCH  /api/orders/{id}/status

GET    /api/metrics/summary?range=hoje|semana|mes
GET    /api/metrics/daily-sales?days=7
GET    /api/metrics/product-sales
GET    /api/metrics/hourly-sales

GET    /api/conversations
GET    /api/conversations/{id}/messages
POST   /api/conversations/{id}/handoff     # {handoff: bool}

POST   /webhooks/mercadopago
GET|POST /webhooks/whatsapp

POST   /api/simulator/message              # só com FAKE_MODE=true
POST   /api/simulator/reset
POST   /api/dev/payments/{order_id}/approve
```

Documentação interativa completa em http://localhost:8000/docs.
