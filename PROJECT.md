# O projeto, do começo

Este arquivo é para quem abre o repositório pela primeira vez. Ele explica o
que o sistema faz, como as partes se encaixam e onde mexer para cada tipo de
mudança. Não pressupõe que você conheça FastAPI, React ou agentes de IA — só
que saiba programar um pouco.

Os outros dois documentos da raiz têm papéis diferentes: o `README.md` é a porta
de entrada curta, e o `DEPLOY.md` é o manual de colocar no ar. Este aqui é o que
explica **por quê**.

---

## 1. O que o sistema faz

Uma gelateria (ou açaiteria, ou doceria — ver §13) atende os clientes pelo
**WhatsApp**. O cliente manda mensagem como manda para qualquer pessoa: "boa
noite, queria um pote de 500 de pistache e morango, entrega na Rua das Flores
123". Um agente de IA entende, monta o pedido, calcula o valor, manda o Pix e
avisa quando o pagamento cai.

Do outro lado existe um **painel** onde o lojista:

- **Produção** — acompanha os pedidos num quadro (Kanban) e arrasta conforme
  vão saindo;
- **Produtos** — edita o cardápio, que é o que mais muda: os sabores do dia;
- **Conversas** — lê os atendimentos e assume a conversa quando quiser;
- **Dashboard** — vê números do que vendeu.

**O que o sistema NÃO é:** não é um PDV, não é uma loja online, não tem
carrinho clicável. O canal é a conversa. O painel existe para o lojista, não
para o cliente.

---

## 2. Arquitetura, em uma tela

```
    WhatsApp
       │
       ▼
  Evolution API  (gateway não-oficial; um QR code pareia o número da loja)
       │  webhook
       ▼
  ┌─────────────────────────── BACKEND (FastAPI) ────────────────────────────┐
  │                                                                          │
  │   webhooks.py  ──►  inbox.py  ──►  runner.py                             │
  │   (valida e         (junta os       (orquestra o turno)                  │
  │    responde 200)     balões)             │                               │
  │                                          ▼                               │
  │                              ┌────────────────────────┐                  │
  │                              │  llm_openai.py         │  A IA lê a       │
  │                              │  "o que ele quis?"     │  mensagem e      │
  │                              └───────────┬────────────┘  devolve         │
  │                                          │               OPERAÇÕES       │
  │                                          ▼                               │
  │                              ┌────────────────────────┐                  │
  │                              │  operations.py         │  O código        │
  │                              │  valida e aplica       │  confere contra  │
  │                              │  contra o CATÁLOGO     │  o que existe    │
  │                              └───────────┬────────────┘                  │
  │                                          ▼                               │
  │                              ┌────────────────────────┐                  │
  │                              │  machine.py            │  O que o bot     │
  │                              │  conduz o turno        │  fala agora      │
  │                              └───────────┬────────────┘                  │
  │                                          ▼                               │
  │                         renderer.py (o texto) ──► WhatsApp               │
  │                                                                          │
  │   Postgres  ◄── conversas, pedidos, catálogo, pagamentos                 │
  └──────────────────────────────────────────────────────────────────────────┘
       ▲
       │  HTTP + X-API-Key
  FRONTEND (React) — Produção, Produtos, Conversas, Dashboard
```

**A frase que governa o projeto inteiro:**

> A IA tem liberdade total para interpretar linguagem natural e decidir **qual
> operação** o cliente quer. Ela nunca tem autoridade para inventar produto,
> preço, taxa ou disponibilidade, nem para cobrar. Ela traduz; o backend valida
> contra o catálogo real e aplica.

Tudo que parece estranho no código costuma ser consequência disso.

---

## 3. Estrutura de pastas

```
back/                  o backend (Python, FastAPI)
  app/
    agent/             o agente de WhatsApp — o coração do produto
    api/               as rotas HTTP que o painel consome
    core/              configuração, log, autenticação
    db/                conexão e os modelos SQLAlchemy
    domain/            os objetos de negócio puros (carrinho, catálogo)
    schemas/           os contratos de entrada e saída da API (Pydantic)
    services/          o que fala com o banco e com os provedores externos
    cli/               um chat no terminal, para testar sem WhatsApp
  db/                  schema.sql, seed.sql e as migrações
  tests/               a suíte inteira, incluindo os evals do agente
front/                 o painel (React + Vite + TypeScript)
  src/
    pages/             uma por tela
    components/        pedaços de tela, agrupados pela tela que os usa
    hooks/             o estado de servidor (TanStack Query)
    lib/               cliente HTTP, formatação, tabela de status
    types/             os tipos que espelham o backend
supabase/              um .sql que a imagem do Postgres espera no boot
```

Duas convenções que ajudam a se achar:

- **`domain/` não importa nada de `services/` nem de `db/`.** São objetos puros:
  dá para usá-los num teste sem banco nenhum.
- **As rotas não tocam no SQLAlchemy.** Elas chamam `services/` e são elas que
  decidem a transação (`await session.commit()`).

---

## 4. Arquivo por arquivo

### `back/app/agent/` — o agente

| Arquivo | Responsabilidade |
|---|---|
| `runner.py` | Orquestra **um turno**: carrega a conversa, chama a IA, chama o executor, grava, envia. É o único ponto que o mundo externo precisa chamar. |
| `plan.py` | **O contrato entre a IA e o sistema.** Define `Action` (as operações possíveis) e `Operation`/`AgentPlan`. Leia este arquivo primeiro. |
| `prompts.py` | O que a IA recebe: instruções, o cardápio do dia e a situação do pedido. A descrição de cada ação mora aqui. |
| `llm.py` | O contrato do cliente de LLM e a escolha de qual usar (`FAKE_MODE`). |
| `llm_openai.py` | Fala com a OpenAI via *function calling*. Qualquer falha vira plano vazio — nunca derruba a conversa. |
| `llm_fake.py` | IA falsa, por regra. Serve ao `FAKE_MODE=true` e a parte dos testes. **Não é o agente**: ela entende menos que o modelo real. |
| `operations.py` | **O que cada operação faz com o pedido.** Adicionar, trocar, remover, endereço, cancelar. Valida tudo contra o catálogo. |
| `machine.py` | **O turno.** Depois de aplicar as operações, decide o que o bot fala: qual a próxima pergunta, o fallback, o atendimento humano. |
| `states.py` | A tabela de transições. Pequena de propósito (ver §6). |
| `session.py` | A conversa no banco: carregar, salvar, histórico, idempotência de mensagem. |
| `checkout.py` | O fechamento: endereço, resumo final, criar o pedido, pedir o Pix. É a parte com efeito colateral. |
| `resolver.py` | **O grounding.** Casa o texto do cliente com o catálogo real; se não casar, o agente repergunta em vez de inventar. |
| `renderer.py` | Tudo que o bot fala. Funções puras: texto entra, texto sai. |
| `faq.py` | Respostas para o que não é pedido (pagamento, taxa, horário, endereço). |
| `whatsapp.py` | Os canais: Evolution API (real) e console (simulador, CLI, testes). |
| `inbox.py` | Junta os balões seguidos do mesmo cliente num turno só. |
| `pacing.py` | O ritmo de envio — o que impede o número de ser bloqueado. |

### `back/app/` — o resto

| Arquivo | Responsabilidade |
|---|---|
| `main.py` | Monta a aplicação e as rotas. |
| `core/config.py` | **Toda a configuração.** É aqui que uma segunda empresa é configurada. |
| `core/security.py` | O `X-API-Key` das rotas administrativas. |
| `api/routes/webhooks.py` | As duas portas de entrada: WhatsApp e Mercado Pago. |
| `api/routes/products.py` | O CRUD do cardápio — a única tela que escreve no catálogo. |
| `api/routes/orders.py` | Lista e move pedidos (o Kanban). |
| `api/routes/conversations.py` | Lê conversas e liga/desliga o atendimento humano. |
| `api/routes/metrics.py` | Os números do dashboard. |
| `api/routes/simulator.py` | Conversar sem WhatsApp. Só responde com `FAKE_MODE=true`. |
| `domain/cart.py` | O carrinho **e a conta**. Arredondamento mora aqui, e é único. |
| `domain/catalog.py` | O cardápio como o agente enxerga (imutável). |
| `domain/enums.py` | Os estados e status, espelhando os ENUM do banco. |
| `services/catalog.py` | O CRUD do cardápio e o snapshot que o agente lê. |
| `services/orders.py` | Fecha o carrinho em pedido: congela preço, emite o código. |
| `services/payments.py` | O ciclo do Pix e a idempotência do webhook. |
| `services/pix_provider.py` | Mercado Pago de verdade, e um provedor falso. |
| `services/pricing.py` | O que a conta precisa de `settings`: taxa de entrega e o resumo. |
| `services/metrics.py` | SQL das métricas. |
| `services/conversations.py` | O que o painel lê das conversas. |
| `services/customers.py` | Cliente e endereço. |
| `db/models.py` | Os modelos SQLAlchemy. **`schema.sql` é a fonte da verdade**, não isto. |
| `db/session.py` | Conexão e pool. |
| `db/init_db.py` | `python -m app.db.init_db --seed` para criar o banco sem Docker. |
| `cli/chat.py` | `python -m app.cli.chat` — conversa pelo terminal. |

### `front/src/`

| Arquivo | Responsabilidade |
|---|---|
| `pages/Producao.tsx` | O Kanban. |
| `pages/Produtos.tsx` | O CRUD do cardápio: busca, seleção em massa, diálogos. |
| `pages/Conversas.tsx` | A lista de conversas e o chat. |
| `pages/Dashboard.tsx` | KPIs e gráficos. |
| `components/layout/Page.tsx` | A moldura de toda tela (cabeçalho + `main`) e o bloco de título. |
| `components/layout/StoreMark.tsx` | O logo ou o nome da loja, vindo do ambiente. |
| `components/produtos/ProductCard.tsx` | Um produto e seus grupos de opções. |
| `components/produtos/GroupCard.tsx` | Um grupo e seus itens. |
| `components/produtos/EditItemSheet.tsx` | Edição de produto, grupo ou item. |
| `components/common/SortableList.tsx` | Arrastar para reordenar (dnd-kit). |
| `components/common/QueryState.tsx` | Carregando, erro e vazio — num lugar só. |
| `hooks/use-*.ts` | Um por área. Falam com `lib/api.ts` e cuidam do cache. |
| `lib/api.ts` | **O único lugar que chama `fetch`.** Base, chave, tratamento de erro. |
| `lib/status.ts` | Rótulos e classes de cor dos status. Leia o comentário do topo. |
| `lib/format.ts` | Dinheiro, data, telefone — em pt-BR. |
| `lib/transforms.ts` | Normaliza o pedido e monta os pontos dos gráficos. |

---

## 5. O agente de IA

### Como uma mensagem vira um pedido

**1. Chega.** A Evolution API chama `POST /webhooks/evolution`. A rota valida o
token, descarta o que não é conversa individual e responde `200` na hora —
webhook lento é reentregue, e reentrega vira pedido duplicado.

**2. Espera o cliente parar de digitar.** Quem pede pelo WhatsApp escreve
picado: "quero um pote" / "G" / "de pistache". `inbox.py` segura por
`WA_DEBOUNCE_SECONDS` e junta tudo num texto só.

**3. Já vimos essa mensagem?** `session.already_seen()` consulta o id da
mensagem no provedor. Se já foi atendida, o turno para aqui.

**4. Monta o contexto.** O agente carrega a conversa, o cardápio do dia e
escreve a **situação**: o que está no carrinho (numerado como o cliente vê), o
que falta escolher, se há um resumo aguardando confirmação. É a situação que
permite resolver "esse mesmo", "o segundo" e "tira o médio".

**5. A IA traduz.** `llm_openai.py` chama a OpenAI obrigando um *tool call*. A
resposta é um `AgentPlan`: uma lista de operações. Uma mensagem pode ter várias
— "tira o primeiro, põe um grande de chocolate e quero entrega" são três.

**6. O código valida e aplica.** `operations.py` pega cada operação e confere
contra o catálogo: o produto existe? está disponível? o nome é ambíguo? Só
então mexe no pedido.

**7. O turno decide a resposta.** `machine.py` olha onde o pedido está e faz
**uma** pergunta — a do ponto em que ele parou.

**8. Sai.** `renderer.py` escreve o texto; `pacing.py` segura o envio para o
bot não responder em 200 ms nem disparar três mensagens no mesmo segundo.

### Como ele evita os erros que custam caro

| Risco | Como o sistema barra |
|---|---|
| **Corrigir criar item novo** (o cliente paga duas vezes) | `UPDATE_ITEM`/`REMOVE_ITEM`/`REPLACE_ITEM` são operações distintas de `ADD_ITEM`, e o executor as aplica no item existente. É o teste `trocar_sabor` no eval. |
| **A IA inventar produto ou sabor** | `resolver.py` e `catalog.product_by_name()`: o que não casa com o catálogo é descartado, e o bot repergunta. |
| **A IA decidir preço** | Ela não vê preço nenhum na saída. A conta é `domain/cart.py`, sempre. |
| **Cobrar sem confirmação** | O Pix só sai de `CONFIRMANDO_PEDIDO`, e só depois de o cliente ver o resumo. Resposta morna ("pode ser") faz o bot perguntar uma vez mais. |
| **Sabor repetido no mesmo item** | `apply_flavors` recusa o id que já está lá. |
| **Pergunta derrubar o pedido** | `ANSWER_QUESTION` não mexe no carrinho; no fim do turno o bot devolve o cliente ao ponto em que estava. |
| **Mensagem entregue duas vezes** | Índice único em `conversation_messages.provider_message_id`. |
| **A IA inventar o endereço** | `operations._disse_isso()`: um campo de endereço só entra se aparecer na mensagem do cliente. É o único dado do pedido **sem catálogo** para contradizer o modelo — e ele já preencheu um bairro inventado a partir de um "sim". |
| **"pode fechar" repetir o pedido** | O histórico é contexto, não tarefa: a regra 11 do prompt proíbe reemitir `add_item` do que já está na situação. Um cliente chegou a pagar em dobro por isso. |
| **Ficar mudo** | Nenhum caminho devolve lista vazia: há fallback progressivo e, em atendimento humano, o bot continua ouvindo. |

### Quando a IA falha

`llm_openai.py` **nunca levanta exceção**: timeout, rate limit, chave errada ou
resposta sem tool call viram um plano vazio. O executor então cai no fallback de
`machine.py`, que é progressivo: primeiro reformula, depois reformula de outro
jeito, e só na terceira oferece chamar uma pessoa. Nunca joga o cardápio inteiro
na cara do cliente.

### Atendimento humano

Pedir atendente **não desliga o bot**. Em handoff ele para de conduzir o pedido,
mas continua ouvindo: avisa uma vez que está aguardando, aceita cancelamento e
volta a atender assim que o cliente mostrar que quer seguir — qualquer operação
de pedido já basta. Se ninguém da loja responder em `HANDOFF_RETURN_MINUTES`, o
bot reassume, porque escalar para humano só ajuda se houver humano.

---

## 6. A máquina de estados

São seis estados, e cada um carrega uma **garantia** — não uma etapa da
conversa:

```
CONVERSANDO ──► CONFIRMANDO_PEDIDO ──► AGUARDANDO_PAGAMENTO ──► CONCLUIDO
     │                  │                       │
     └──────────► ATENDIMENTO_HUMANO            └──► CANCELADO
```

| Estado | O que ele garante |
|---|---|
| `CONVERSANDO` | Montando o pedido. **O diálogo inteiro acontece aqui.** |
| `CONFIRMANDO_PEDIDO` | O cliente viu o resumo com o total. É o único lugar de onde se pode cobrar. |
| `AGUARDANDO_PAGAMENTO` | Pix emitido. Só o webhook do provedor tira daqui. |
| `CONCLUIDO` / `CANCELADO` | Fim de ciclo. Mensagem nova recomeça limpo. |
| `ATENDIMENTO_HUMANO` | O bot não conduz o pedido. |

**Por que tão poucos.** Eram dez, um por etapa do diálogo (saudação, escolhendo
produto, personalizando item, revisando carrinho, coletando endereço). Na
prática a etapa já está nos dados — tem item incompleto? falta endereço? — e ter
as duas coisas fazia o agente brigar consigo mesmo: o cliente falava de sabor
num estado que só aceitava produto e ouvia "não entendi".

Nenhum estado significa "esperando o cliente escrever a palavra X". Se você se
pegar querendo criar um `AGUARDANDO_SIM`, o desenho está sendo desfeito.

---

## 7. O banco

Treze tabelas. As que importam:

```
products ──┐
           ├─< product_groups >── complement_groups ──< complements
           │   (a regra de escolha       (a lista            │
           │    DESTE produto)            compartilhada)     │
           │                                                 ▼
           │                                    complement_categories
customers ──< addresses
          └──< orders ──< order_items ──< order_item_complements
                    └──< payments
conversations ──< conversation_messages
webhook_events
```

**O ponto não óbvio: o grupo de complementos é compartilhado.** Uma lista
"Sabores" com 31 itens serve ao pote de 240 ml, ao de 500 ml e ao combo; o que
muda por produto é **quantos** o cliente escolhe, e isso mora em
`product_groups`. É o modelo do Anota Aí e do iFood.

Antes cada produto tinha o seu grupo, então os 31 sabores viravam 93 linhas.
Marcar "pistache acabou" — que é *a* tarefa diária do painel — custava três
cliques, e os três podiam divergir: quem pedia o pote médio via pistache, quem
pedia o grande não via. Se você for mexer no catálogo, é a primeira coisa a
entender.

Outros detalhes que evitam surpresa:

- **`back/db/schema.sql` é a fonte da verdade**, não `models.py`. Não existe
  `create_all()` e não há Alembic: mudança de schema vira um arquivo em
  `back/db/migrations/`, aplicado à mão e anotado no `DEPLOY.md`.
- `order_items` e `order_item_complements` guardam **snapshot** do nome e do
  preço. Renomear um sabor não reescreve o histórico de vendas.
- `conversations.cart` é JSONB: o carrinho em construção vive ali até virar
  pedido.
- `webhook_events` tem `UNIQUE (source, external_id)` — é ela que impede o
  mesmo aviso de pagamento de ser processado duas vezes.

---

## 8. Serviços externos

| Serviço | Para quê | Sem ele |
|---|---|---|
| **Evolution API** | Mandar e receber WhatsApp. Gateway self-hosted; pareia por QR code, não exige conta comercial aprovada. | Com `FAKE_MODE=true` as mensagens vão para um canal em memória. |
| **OpenAI** | Traduzir a mensagem em operações. | Com `FAKE_MODE=true` entra o `llm_fake.py`. |
| **Mercado Pago** | Emitir o Pix e avisar quando cai. | Com `FAKE_MODE=true` entra o `FakePaymentProvider`. |

**Com `FAKE_MODE=true` o sistema inteiro roda sem uma única chave.** É assim
que se desenvolve aqui.

Duas notas de produção:

- A Evolution **não assina** o corpo do webhook; a validação é um token na query
  string (`EVOLUTION_WEBHOOK_TOKEN`). Em produção, sem token configurado, o
  webhook é recusado.
- O Mercado Pago assina (`MP_WEBHOOK_SECRET`), mas o segredo é opcional na
  conta. Sem ele a validação é pulada — configure.
- O corpo do webhook de pagamento **nunca** é a fonte da verdade: ele diz qual
  pagamento mudou, e o sistema consulta a API do provedor para saber o status.

---

## 9. O caminho de uma mensagem

```
"queria um pote de 500 de pistache e morango, entrega rua das flores 123"
   │
   ├─ POST /webhooks/evolution ......... valida o token, responde 200
   ├─ inbox.submit() .................... espera 3s por mais balões
   ├─ already_seen(id)? ................. não; segue
   ├─ load_or_create(telefone) .......... a conversa, do banco
   ├─ get_catalog_snapshot() ............ o cardápio de hoje
   ├─ describe_situation() .............. "Pedido vazio — nada escolhido."
   ├─ OpenAI ............................ 3 operações:
   │       add_item(Pote 500ml, [Pistache, Morango])
   │       set_fulfillment(entrega)
   │       update_address(Rua das Flores, 123)
   ├─ operations.apply() × 3 ............ confere no catálogo e aplica
   ├─ machine._next_step() .............. "falta o bairro"
   ├─ save_session() + log_message() .... grava estado e auditoria
   └─ Evolution sendText ................ com "digitando..." proporcional
```

---

## 10. Como executar

**Com Docker (o caminho normal):**

```bash
cp back/.env.example back/.env      # já vem pronto para rodar sem chave
docker compose up -d
```

- painel: <http://localhost:8080>
- API: <http://localhost:8000/docs>
- banco: `localhost:5432`

O `schema.sql` e o `seed.sql` são aplicados no primeiro boot.

**Sem Docker:**

```bash
cd back
pip install -r requirements.txt
python -m app.db.init_db --seed
uvicorn app.main:app --reload

cd ../front
npm install
npm run dev
```

**Conversar com o agente sem WhatsApp:**

```bash
cd back && python -m app.cli.chat
```

---

## 11. Como testar

```bash
cd back
ruff check .        # lint
pytest              # a suíte inteira

cd ../front
npm run typecheck   # tsc --noEmit
npm run lint
npm test
npm run build
```

**Os evals do agente** merecem parágrafo próprio, porque são a parte que
responde "o agente entende linguagem natural?".

- `tests/eval_cases.py` — a lista de casos: a fala do cliente, o que a IA
  deveria entender, o que tem de acontecer com o pedido.
- `tests/test_agent_eval.py` — roda **sempre**, offline, sem gastar token.
  Alimenta o executor com o plano esperado e confere o efeito.
- `tests/test_agent_eval_live.py` — roda **sob demanda**:

  ```bash
  cd back && FAKE_MODE=false pytest -m eval
  ```

  Manda as mesmas falas para a OpenAI de verdade e confere o que ela entendeu.
  É o único teste que cobre `prompts.py` e `llm_openai.py`. Gasta token, então
  fica fora da execução padrão (`addopts = -m 'not eval'`).

Falha no eval ao vivo **em geral não é bug de código, é o prompt**. O conserto
costuma ser ajustar a descrição da ação em `prompts.py` e rodar de novo.

Uma nota sobre a suíte: os testes do executor escrevem o plano da IA à mão, de
propósito — o que está sob teste ali é o executor. É por isso que os evals
existem separados.

---

## 12. Como adicionar uma funcionalidade

| O que você quer | Onde mexer |
|---|---|
| Uma resposta nova do bot | `agent/renderer.py` (só texto) |
| Uma operação nova do pedido | `agent/plan.py` (a `Action`), `agent/prompts.py` (a descrição para a IA), `agent/operations.py` (o que ela faz) — **e um caso em `tests/eval_cases.py`** |
| Responder uma pergunta nova | `agent/faq.py` e o tópico em `plan.QUESTION_TOPICS` |
| Um campo novo no produto | `db/schema.sql` + migração, `db/models.py`, `schemas/product.py`, `services/catalog.py` e a tela |
| Uma configuração nova | `core/config.py` **e** `back/.env.example` (há um teste que exige os dois) |
| Uma tela nova | `front/src/pages/`, usando `Page`/`PageTitle`, e a rota em `App.tsx` |
| Um endpoint novo | `api/routes/`, o schema em `schemas/`, e a função em `front/src/lib/api.ts` |

Três regras da casa:

1. **Nenhuma classe do Tailwind pode ser montada por concatenação.** O scanner
   não enxerga string montada em tempo de execução e a classe não vai para o
   CSS. Já aconteceu, e o Kanban ficou sem cor em produção — ver o comentário
   no topo de `front/src/lib/status.ts`.
2. **Nenhum nome de loja no código.** Ver §13.
3. **Não rode formatador automático** (`ruff format`, `prettier`). O código é
   formatado à mão, com comentários alinhados em coluna, e o formatador desfaz
   isso em dezenas de arquivos sem ganho.

---

## 13. Como atender uma segunda empresa

O sistema é uma plataforma para casas do mesmo nicho — gelateria, açaiteria,
doceria, cafeteria. A Mi Piace é o primeiro caso de uso, não o produto.

**O desenho é um deploy por loja.** Não há `tenant_id` nem tabela de
configuração: uma instância por cliente é mais simples de operar e de entender
do que multi-tenancy, no tamanho deste produto.

Para subir a segunda casa:

**1. A identidade vai no `.env`** (a lista completa está em
`back/.env.example`):

```bash
STORE_NAME=Açaí do Bairro
STORE_EMOJI=🍧
STORE_SEGMENT=açaiteria      # entra no prompt para situar o modelo
STORE_CITY=PORTO VELHO       # o BR Code do Pix carrega este campo
STORE_HOURS=Seg a sáb, 14h às 22h
STORE_ADDRESS=Rua das Palmeiras, 45 — Centro
STORE_DELIVERY_AREA=Centro e Jardim América
STORE_DELIVERY_ESTIMATE=40 a 60 minutos
DELIVERY_FEE=7.00
```

No painel, o equivalente são `VITE_STORE_NAME` e `VITE_STORE_LOGO_URL` (ver
`front/.env.example`). Eles entram no bundle no **build**.

**2. O cardápio é cadastrado pela tela de Produtos.** Nada de `seed.sql`: o
`back/db/seed.sql` é o cardápio da Mi Piace e só. Crie os produtos, crie um
grupo de opções e reaproveite esse grupo nos produtos que compartilham a mesma
lista — é o que faz "acabou" valer para o cardápio inteiro de uma vez.

**3. As taxonomias também são dado**, não constante: "Sem lactose" numa
gelateria, "Vegetariano" numa hamburgueria. Cadastre em *Categorias de item*.

**4. Os defaults são os da Mi Piace, e isso é proposital.** O que a
generalização trouxe é a OPÇÃO de trocar, não a obrigação de configurar: sem
`.env`, o sistema continua sendo o da casa que ele atende hoje. Deixar os
defaults genéricos foi tentado e deu errado — um deploy sem as variáveis
subiu se apresentando como "Nossa Loja", e configuração esquecida virou perda
de identidade. Trocar a loja é sobrescrever; não é preencher do zero.

**5. O que sobra de específico:** a paleta de cores do painel
(`front/src/index.css`, num bloco de tokens no topo) e o logo em
`front/public/`. Os quatro `STORE_HOURS`/`ADDRESS`/`DELIVERY_*` seguem vazios
por padrão: sem eles o agente **admite que não sabe** em vez de inventar — um
horário inventado numa loja fechada é pior do que "não tenho certeza".

Se você se pegar escrevendo o nome de um cliente dentro de um `.py` ou `.tsx`,
pare: é sinal de que falta um campo de configuração. Há um teste que verifica
isso (`tests/test_config.py::test_a_loja_nao_esta_escrita_no_codigo`).
