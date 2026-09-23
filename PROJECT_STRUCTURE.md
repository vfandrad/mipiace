# Mapa do projeto Mi Piace

Este documento é para quem acabou de abrir o repositório. Ele diz **onde cada
coisa mora** e **por onde passa uma mensagem**, arquivo por arquivo.

Para rodar o projeto, veja o [README](README.md). Para colocar no ar, o
[DEPLOY.md](DEPLOY.md).

---

## 1. O que é o sistema

Uma gelateria atende seus clientes pelo WhatsApp. Um agente automático (máquina
de estados + IA) conversa com o cliente, monta o pedido, coleta o endereço e
cobra por Pix. O lojista acompanha e intervém por um painel web.

**O que o sistema NÃO é** — importante para não construir a coisa errada:

- **não é um PDV.** Não há caixa, não há venda de balcão, não há impressão de
  cupom.
- **não é uma loja online.** O cliente não navega num catálogo e não aperta
  "comprar". Ele conversa.
- **o painel não é um produto de analytics.** O dashboard mostra números
  simples lidos do banco.

O pedido nasce sempre na conversa. O painel é ferramenta interna.

---

## 2. Arquitetura geral

```
   Cliente no WhatsApp
          │
          ▼
   Evolution API  (gateway self-hosted que fala o protocolo do WhatsApp)
          │  POST /webhooks/evolution?token=...
          ▼
   ┌─────────────────────────────────────────────┐
   │             Backend — FastAPI                │
   │                                              │
   │   api/routes/   →   services/   →   db/      │
   │   (traduz HTTP)     (regra +        (tabelas)│
   │                      SQL)                    │
   │                                              │
   │   agent/  — a conversa: estados, IA, textos  │
   └─────────────────────────────────────────────┘
          │                         │
          ▼                         ▼
     PostgreSQL              Mercado Pago (Pix)
          ▲
          │  GET /api/*  (header X-API-Key)
          │
   Painel React (Vite) — produção, produtos, conversas, dashboard
```

Duas camadas no backend, e a regra é curta:

> **A rota traduz HTTP. O service decide e fala com o banco.**

Não existe camada de "repository": os services usam SQLAlchemy diretamente.
Quem abre a requisição é quem fecha a transação — **a rota chama
`session.commit()`**, o service nunca. (Uma única exceção, documentada na
seção 9.)

---

## 3. Estrutura de pastas

```
mipiace/
├── README.md                 o que é e como rodar
├── DEPLOY.md                 produção
├── PROJECT_STRUCTURE.md      este arquivo
├── docker-compose.yml        stack local (db, backend, frontend, whatsapp)
├── docker-compose.prod.yml   limites de recurso para produção
├── Caddyfile                 proxy reverso + HTTPS
├── deploy.sh                 script de deploy
│
├── back/
│   ├── db/schema.sql         AS TABELAS — fonte de verdade do banco
│   ├── db/seed.sql           cardápio real (3 tamanhos + 31 sabores)
│   ├── requirements.txt
│   ├── tests/                168 testes, nenhum precisa de Postgres no ar
│   └── app/
│       ├── main.py           cria o app e monta as rotas
│       ├── agent/            a conversa do WhatsApp
│       ├── api/routes/       endpoints HTTP
│       ├── services/         regra de negócio + acesso ao banco
│       ├── domain/           tipos puros (sem banco, sem HTTP)
│       ├── schemas/          o que entra e sai da API (Pydantic)
│       ├── db/               modelos SQLAlchemy e conexão
│       ├── core/             config, log, segurança
│       └── cli/chat.py       conversar com o agente pelo terminal
│
└── front/
    └── src/
        ├── pages/            uma tela por arquivo
        ├── components/       pedaços de tela, agrupados por tela
        ├── hooks/            busca de dados (TanStack Query)
        ├── lib/              API, formatação, status
        └── types/            os tipos que o backend devolve
```

---

## 4. O fluxo de uma mensagem

É o caminho mais importante do sistema. O cliente manda "oi" e:

| # | Onde | O que acontece |
|---|---|---|
| 1 | `api/routes/webhooks.py` → `evolution_webhook()` | Chega o POST da Evolution API. Valida o token da query string. |
| 2 | `agent/whatsapp.py` → `EvolutionAdapter.parse_webhook()` | Extrai a mensagem do payload do Baileys. Ignora grupo, status e transmissão. |
| 2b | `agent/inbox.py` → `submit()` | Espera ~3s por mais balões do mesmo cliente e junta tudo num turno só. O webhook responde 200 na hora. |
| 3 | `agent/runner.py` → `handle_inbound()` | Daqui em diante é o agente. Mensagem reentregue pelo canal (mesmo `provider_message_id`) para aqui. |
| 4 | `agent/session.py` → `load_or_create()` | Carrega o estado da conversa do Postgres. Sessão vencida recomeça do zero. |
| 5 | `agent/machine.py` → `describe_situation()` | Monta o retrato do pedido agora: o que está no carrinho, que sabores faltam, se há um resumo esperando confirmação. |
| 6 | `agent/llm.py` + `agent/prompts.py` | A IA lê a mensagem COM esse retrato e devolve um `AgentPlan`: a lista de **operações** que o cliente quis fazer. |
| 7 | `agent/machine.py` → `run()` | **O executor.** Valida cada operação contra o catálogo real e aplica ao pedido. |
| 8 | `agent/faq.py` | Responde as perguntas que não são pedido, com dado do sistema (Pix, taxa, cardápio do dia). |
| 9 | `agent/renderer.py` | Transforma o resultado em texto de WhatsApp. |
| 10 | `agent/session.py` → `save_session()` + `log_message()` | Grava o novo estado e a mensagem no histórico. |
| 11 | `agent/whatsapp.py` → `send_text()` | Envia a resposta. |

**Se o pedido for fechado**, o passo 7 chama `agent/checkout.py`, que cria o
pedido (`services/orders.py`) e pede o Pix (`services/payments.py`).

---

## 5. A IA e a máquina de estados

### A divisão de trabalho

O ponto central do desenho:

> A IA tem **liberdade** para interpretar linguagem natural e decidir qual
> operação o cliente quer. Ela não tem **autoridade** para inventar produto,
> preço, taxa ou disponibilidade, nem para cobrar. Ela traduz; o backend
> valida contra o catálogo real e aplica.

| A IA faz | O backend faz |
|---|---|
| entender "troca o morango por chocolate" | decidir que isso é editar o item 1, e não criar outro |
| dizer a qual item do cardápio o cliente se referiu | conferir se ele existe e está disponível |
| extrair endereço, quantidade, sabores, forma de entrega | calcular preço, taxa e total em `Decimal` |
| apontar ambiguidade em vez de chutar | recusar cobrança sem confirmação clara |

### Operações, não intenções

A IA devolve um `AgentPlan` — uma lista de operações (`agent/plan.py`):

```
ADD_ITEM        UPDATE_ITEM      REPLACE_ITEM     REMOVE_ITEM
UPDATE_QUANTITY DUPLICATE_ITEM   SET_FULFILLMENT  UPDATE_ADDRESS
SHOW_MENU       SHOW_CART        SHOW_TOTAL       ANSWER_QUESTION
CLOSE_ORDER     CONFIRM_ORDER    CANCEL_ORDER     REQUEST_HUMAN
ASK_CLARIFICATION                NO_ACTION
```

Uma mensagem pode trazer várias: *"tira o primeiro, põe um grande de chocolate
e quero entrega"* são três operações num turno só. Antes existia só uma
intenção por mensagem, e "editar" não existia — por isso toda correção virava
item novo e a conta subia.

O `strict` das structured outputs da OpenAI garante o formato. Sem ele o
modelo devolvia operação sem o campo `action` e o pedido inteiro virava "não
entendi".

### Os 6 estados

`CONVERSANDO` → `CONFIRMANDO_PEDIDO` → `AGUARDANDO_PAGAMENTO` → `CONCLUIDO`,
mais `ATENDIMENTO_HUMANO` e `CANCELADO`.

Eram dez: havia um estado para cada etapa do diálogo (saudação, escolhendo
produto, personalizando item, revisando carrinho, coletando endereço). A etapa
já estava nos `slots` — tem rascunho? o carrinho está vazio? falta endereço? —
e ter as duas coisas fazia o agente brigar consigo mesmo: o cliente falava de
sabor num estado que só aceitava produto e ouvia "não entendi".

Sobraram os estados que carregam **garantia**, não etapa. A que importa é uma
só, e está em `agent/states.py`: só se chega a `AGUARDANDO_PAGAMENTO` vindo de
`CONFIRMANDO_PEDIDO` — ninguém é cobrado sem ter visto o resumo com o total e
concordado. Resposta morna ("pode ser") não passa: o executor pergunta de novo.

Conversas gravadas com os nomes antigos continuam abrindo (`parse_state` em
`domain/enums.py`).

### O rascunho do item

O item em construção vive em `slots["draft"]` e é **mutável**: "pote médio" →
"pistache" → "não, troca por chocolate" → "na verdade quero o grande" mexem
todos no mesmo objeto. Ele só vira item do carrinho quando está completo, e é
por isso que nada entra no pedido pela metade.

---

## 6. CRUD do cardápio

O modelo tem três níveis:

```
Produto            "Pote 500ml"        R$ 39,90
  └─ Grupo         "Sabores"           escolha 3, obrigatório
       └─ Complemento  "Pistache"      + R$ 0,00
```

O cardápio da casa são três tamanhos — **M 240ml** (2 sabores, R$ 30),
**G 500ml** (3 sabores, R$ 50) e **COMBO 2 G 1000ml** (6 sabores, R$ 90) — e os
mesmos 31 sabores disponíveis em todos.

Existe porque **os sabores mudam todo dia**. É a única tela do painel que
escreve no banco: o lojista liga e desliga `is_available` conforme o que saiu
do freezer, e o agente enxerga a mudança na próxima mensagem (ele lê o catálogo
a cada turno).

Cada sabor carrega uma **categoria de lactose** ("Sem lactose" / "Com lactose"),
editável no painel ao criar ou editar o sabor. É atributo do sabor, não do
grupo — por isso mora em `flavor_categories` e não no grupo de escolha.

Sabor indisponível não some do catálogo que o agente recebe — ele precisa saber
que existe para responder *"hoje não tem pistache"* em vez de *"não entendi"*.

| Ação | Rota |
|---|---|
| listar | `GET /api/products` |
| criar / editar / apagar produto | `POST`, `PATCH`, `DELETE /api/products[/{id}]` |
| criar grupo | `POST /api/products/{id}/groups` |
| editar / apagar grupo | `PATCH`, `DELETE /api/groups/{id}` |
| criar complemento | `POST /api/groups/{id}/complements` |
| editar / apagar complemento | `PATCH`, `DELETE /api/complements/{id}` |

---

## 7. Pedidos e Kanban

Cinco status: `novo` → `preparando` → `entrega` → `finalizado`, mais
`cancelado`.

- **`novo`** = pedido criado, Pix ainda não pago. **Não aparece no Kanban** —
  o quadro começa em `preparando`.
- Quem move `novo → preparando` é o **pagamento**, não o lojista:
  `services/payments.py::apply_payment_result()` faz isso quando o Pix cai.
- O lojista move o resto arrastando no quadro (`PATCH /api/orders/{id}/status`).
- As transições são validadas em `services/orders.py::ORDER_TRANSITIONS`. Um
  salto inválido devolve **409**, não 500.

O nome do produto e do complemento são **congelados** no item do pedido no
momento da venda. Renomear um sabor depois não altera pedidos antigos.

---

## 8. Pagamento Pix

`services/pix_provider.py` tem o contrato e os dois provedores (Mercado Pago e
o falso), e escolhe entre eles por `FAKE_MODE`.

Três garantias do webhook (`api/routes/webhooks.py`):

1. **Idempotência** — a tabela `webhook_events` (UNIQUE `source`+`external_id`)
   decide se a notificação já foi processada. O Mercado Pago reenvia.
2. **Nunca confiar no payload** — o corpo do webhook só diz *qual* pagamento
   mudou. O status vem de uma consulta à API do provedor.
3. **Nunca derrubar por causa do agente** — se avisar o cliente falhar, o
   pagamento continua registrado.

---

## 9. Transações (quem faz `commit`)

**Regra: a rota comita, o service não.** Os services usam `flush()`, que
escreve no banco dentro da transação sem fechá-la.

**Única exceção:** `services/payments.py::notify_agent_payment_approved()`.
Ela roda *depois* do commit da rota, já fora do ciclo de resposta, e grava o
novo estado da conversa. Sem o commit dela, a conversa fica presa em
"aguardando_pagamento" e o cliente nunca recebe a confirmação. Há um teste que
protege isso (`tests/test_orders.py`).

---

## 10. Variáveis de ambiente

Todas em `back/app/core/config.py`. Com `FAKE_MODE=true` nenhuma chave externa
é necessária.

| Variável | Padrão | Para quê |
|---|---|---|
| `FAKE_MODE` | `true` | `true` = LLM e Pix falsos, roda sem chave nenhuma |
| `ENVIRONMENT` | `development` | aparece no `/health` |
| `DEBUG` | `true` | nível do log |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | URL de retorno do Pix |
| `DATABASE_URL` | Postgres local | conexão |
| `ADMIN_API_KEY` | `dev-local-key` | header `X-API-Key` das rotas `/api/*` |
| `CORS_ORIGINS` | `http://localhost:8080` | lista separada por vírgula |
| `OPENAI_API_KEY` | — | **obrigatória** com `FAKE_MODE=false` |
| `OPENAI_MODEL` | `gpt-4o-mini` | modelo usado |
| `LLM_MAX_TOKENS` | `1024` | teto da resposta |
| `LLM_TIMEOUT_SECONDS` | `20` | timeout da chamada |
| `EVOLUTION_API_URL` | `http://localhost:8081` | gateway do WhatsApp |
| `EVOLUTION_API_KEY` | — | **obrigatória** para enviar WhatsApp |
| `EVOLUTION_INSTANCE` | `mipiace` | nome da instância pareada |
| `EVOLUTION_WEBHOOK_TOKEN` | — | valida o webhook de entrada |
| `MP_ACCESS_TOKEN` | — | **obrigatória** para Pix real |
| `MP_WEBHOOK_SECRET` | — | assinatura do webhook do MP (opcional) |
| `DELIVERY_FEE` | `5.00` | taxa de entrega |
| `PIX_EXPIRATION_MINUTES` | `30` | validade do QR |
| `SESSION_TTL_MINUTES` | `60` | depois disso a conversa recomeça |
| `MAX_NLU_FAILURES` | `3` | incompreensões seguidas antes de OFERECER uma pessoa (o bot nunca cala) |
| `WA_DEBOUNCE_SECONDS` | `3` | espera por mais balões antes de responder; `0` desliga |
| `HANDOFF_RETURN_MINUTES` | `15` | silêncio máximo em atendimento humano antes de o bot reassumir |

**Frontend** (`front/.env.local`) — embutidas no bundle em tempo de build,
visíveis no navegador:

| Variável | Padrão | Para quê |
|---|---|---|
| `VITE_API_BASE_URL` | `http://localhost:8000` | base da API |
| `VITE_ADMIN_API_KEY` | `dev-local-key` | precisa bater com `ADMIN_API_KEY` |

---

## 11. Arquivo por arquivo

### `back/app/agent/` — a conversa

| Arquivo | Linhas | O que faz |
|---|---|---|
| `plan.py` | 147 | **O contrato com a IA:** as operações (`Action`) e o `AgentPlan`. |
| `machine.py` | 1037 | **O executor.** Valida cada operação contra o catálogo e aplica ao pedido. |
| `runner.py` | 258 | Orquestra um turno: sessão → situação → IA → executor → banco → canal. |
| `checkout.py` | 192 | O fechamento: `AgentDeps`, criar o pedido, gerar o Pix, consultar status. É a parte com efeito colateral. |
| `states.py` | 93 | A tabela de transições e `advance()` — hoje só o que garante que não se cobra sem confirmação. |
| `resolver.py` | 260 | Casa texto livre com o catálogo real, por nome E descrição (exato → termo → substring → descrição → similaridade). |
| `renderer.py` | 483 | **Todo texto que o bot fala.** Funções puras. Mude o tom aqui, sem tocar em regra. |
| `faq.py` | 138 | Responde pergunta que não é pedido, só com dado que o sistema tem de verdade. |
| `session.py` | 432 | O estado da conversa no Postgres, e o log de mensagens. Usa SQL textual de propósito. |
| `whatsapp.py` | 336 | Os canais: `EvolutionAdapter` (WhatsApp real) e `ConsoleAdapter` (fake/testes). |
| `inbox.py` | 109 | Junta os balões seguidos do mesmo cliente num turno só (debounce de borda final). |
| `llm.py` | 78 | O contrato do cliente de IA e a escolha entre real e falso. |
| `prompts.py` | 301 | As instruções e o schema das operações. É aqui que se ajusta o que a IA pode dizer. |
| `llm_openai.py` | 244 | Cliente OpenAI com function calling e structured outputs (`strict`). |
| `llm_fake.py` | 291 | IA falsa determinística. É o padrão em `FAKE_MODE` e nos testes. |
| `pacing.py` | 115 | O ritmo de envio no WhatsApp (digitação, teto por minuto). |

### `back/app/services/` — regra de negócio + banco

| Arquivo | Linhas | O que faz |
|---|---|---|
| `catalog.py` | 165 | CRUD do cardápio **e** o snapshot que o agente lê. |
| `orders.py` | 318 | Criar pedido a partir do carrinho, mudar status, montar resumos. |
| `payments.py` | 255 | Ciclo do Pix: criar cobrança, aplicar resultado, avisar o agente. |
| `pix_provider.py` | 334 | Contrato + Mercado Pago + provedor falso + a escolha entre eles. |
| `customers.py` | 149 | Clientes e endereços. O telefone é a identidade. |
| `metrics.py` | 251 | O SQL e os números do dashboard. |
| `conversations.py` | 100 | Leitura das conversas para o painel + o toggle de handoff. |
| `pricing.py` | 96 | **A única fonte de verdade de preço.** Sempre `Decimal`, sempre arredondado uma vez. |

### `back/app/api/routes/` — HTTP

| Arquivo | Linhas | Rotas |
|---|---|---|
| `products.py` | 182 | `/api/products`, `/api/groups`, `/api/complements`, `/api/flavor-categories` |
| `orders.py` | 62 | `/api/orders` — lista, detalhe, resumo, mudar status |
| `metrics.py` | 49 | `/api/metrics/*` — dashboard |
| `conversations.py` | 64 | `/api/conversations` — lista, mensagens, handoff |
| `webhooks.py` | 231 | `/webhooks/evolution` (WhatsApp) e `/webhooks/mercadopago` (Pix) |
| `simulator.py` | 95 | `/api/simulator/*` — só com `FAKE_MODE=true` |
| `health.py` | 30 | `/health` |

### `back/app/` — o resto

| Arquivo | Linhas | O que faz |
|---|---|---|
| `main.py` | 86 | Cria o app, monta as rotas, configura CORS. |
| `domain/cart.py` | 55 | O carrinho em construção (vive em JSONB na conversa). |
| `domain/catalog.py` | 77 | O cardápio como o agente enxerga. Imutável. |
| `domain/enums.py` | 78 | Todos os enums. Espelham `db/schema.sql`. |
| `db/models.py` | 505 | As 13 tabelas em SQLAlchemy. O `schema.sql` continua sendo a fonte de verdade. |
| `db/session.py` | 94 | Engine e sessão. |
| `db/init_db.py` | 71 | Aplica `schema.sql` e `seed.sql` no primeiro boot. |
| `core/config.py` | 82 | Todas as variáveis de ambiente. |
| `core/security.py` | 48 | Validação do `X-API-Key`. |
| `schemas/*.py` | — | O que entra e sai de cada rota (Pydantic). |
| `cli/chat.py` | 150 | Conversar com o agente pelo terminal. |

### `front/src/`

| Arquivo | Linhas | O que faz |
|---|---|---|
| `App.tsx` | 45 | Rotas e providers. |
| `pages/Producao.tsx` | 88 | Kanban dos pedidos. |
| `pages/Produtos.tsx` | 210 | CRUD do cardápio. |
| `pages/Conversas.tsx` | 160 | Lista de conversas + histórico + handoff. |
| `pages/Dashboard.tsx` | 180 | KPIs e gráficos. |
| `lib/api.ts` | 298 | **Toda a saída HTTP do front.** Um `fetch` com `X-API-Key` + as funções por domínio. |
| `lib/status.ts` | 85 | A **única** tabela de status: rótulo, cor e qual status vem depois. |
| `lib/format.ts` | 82 | Formatação pt-BR (moeda, data, telefone). |
| `lib/transforms.ts` | 131 | Converte o que a API devolve no que a tela usa. |
| `hooks/use-*.ts` | — | Um hook por domínio, com TanStack Query. As telas não chamam a API direto. |
| `components/ui/` | — | Primitivos (shadcn). Raramente se mexe. |
| `components/<tela>/` | — | Componentes de cada tela, na pasta com o nome dela. |

---

## 12. Por onde começar

> "Quero mexer em X — qual arquivo?"

| Quero… | Arquivo |
|---|---|
| **mudar o que o bot fala** | `back/app/agent/renderer.py` |
| **adicionar/tirar sabor** | não é código: tela **Produtos** do painel |
| **marcar sabor como sem lactose** | tela **Produtos**, ao criar ou editar o sabor |
| **mudar a taxa de entrega** | variável `DELIVERY_FEE` |
| **mudar quantas falhas até oferecer humano** | variável `MAX_NLU_FAILURES` |
| **adicionar um estado à conversa** | `domain/enums.py` (o nome) + `agent/states.py` (as transições) + `agent/machine.py` (o handler) |
| **mudar o que a IA extrai** | `back/app/agent/prompts.py` |
| **mudar as colunas do Kanban** | `front/src/pages/Producao.tsx` + `front/src/lib/status.ts` |
| **adicionar uma métrica** | `back/app/services/metrics.py` → `api/routes/metrics.py` → `front/src/hooks/use-metrics.ts` |
| **mudar uma cor/rótulo de status** | `front/src/lib/status.ts` (só lá) |
| **adicionar um endpoint** | `api/routes/` (HTTP) + `services/` (a regra) |

---

## 13. Dívidas conhecidas

Coisas reais que um dev novo vai esbarrar. As que sobraram mudam
comportamento ou exigem decisão de produto — por isso estão documentadas em vez
de corrigidas.

| # | Dívida | Risco |
|---|---|---|
| 1 | **Divergência de centavo.** `domain/cart.py` calcula sem arredondar (é o que o cliente lê no WhatsApp); `services/pricing.py` arredonda por etapa (é o que grava no pedido). Hoje é latente — todos os preços do cardápio têm 2 casas, então os dois resultados batem. Aparece se algum `extra_price` tiver fração de centavo. Corrigir exige mover `money()` para `domain/`, senão vira import circular. | Médio |
| 2 | **Não há sistema de migração.** `db/models.py` e `db/schema.sql` descrevem as mesmas tabelas e só divergem em runtime. Mudança de schema exige `psql` na mão. | Médio |
| 3 | **Retirada na loja está pela metade.** `Intent.ESCOLHER_RETIRADA` existe e o prompt fala dele, mas nenhum handler trata e `checkout.py` fixa `ENTREGA`. Decidir: remover ou implementar. | Baixo |
| 4 | **4 das 5 views SQL não são usadas.** `services/metrics.py` reimplementa as mesmas agregações. Mexer exige recriar o banco (ver dívida 2). | Baixo |

### Corrigidas

- **Conversa em atendimento humano nunca voltava para o bot** — `set_handoff()`
  agora devolve o estado para `SAUDACAO`. Coberto por `tests/test_conversations.py`.
- **Caminho de pagamento sem teste** — `tests/test_payments.py` cobre
  idempotência, transições de status, tradução do vocabulário do Mercado Pago,
  validação da assinatura e o provedor falso.
