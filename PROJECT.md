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
  │                         textos.py (o texto)  ──► WhatsApp               │
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
    agente.py          o agente de WhatsApp — o coração do produto
    textos.py          TUDO que o cliente lê no WhatsApp
    api.py             as rotas HTTP que o painel consome
    esquemas.py        o contrato de dados entre backend e painel
    servicos.py        o que fala com o banco e com o Mercado Pago
    banco.py           as tabelas, a conexão e a criação inicial
    dominio.py         carrinho, cardápio e enums — objetos puros
    configuracao.py    configuração, log e a chave de API
    main.py            monta o app; no fim, a conversa pelo terminal
  db/                  schema.sql, seed.sql e as migrações
  tests/               a suíte inteira, incluindo os evals do agente
front/                 o painel (React + Vite + TypeScript)
  src/
    pagina-*.tsx       uma por tela, com os componentes dela dentro
    ui.tsx             as pecinhas de interface (shadcn)
    comuns.tsx         moldura, cabeçalho, estados de carregando/erro
    dados.ts           os hooks que buscam e gravam (react-query)
    api.ts             o único lugar que faz fetch
    formato.ts         dinheiro, data, status, conversões
    tipos.ts           os tipos que espelham o backend
supabase/              um .sql que a imagem do Postgres espera no boot
```

Três convenções que ajudam a se achar:

- **A seta aponta para um lado só.** `agente.py` e `api.py` chamam
  `servicos.py`; `servicos.py` não chama nenhum dos dois. Abaixo de todos,
  `dominio.py` e `configuracao.py` não chamam ninguém.
- **As rotas não tocam no SQLAlchemy.** Elas chamam `servicos.py` e são elas
  que decidem a transação (`await session.commit()`).
- **Nomes em português, menos onde é contrato.** Ficaram em inglês os nomes
  que algo de fora lê: colunas do banco, campos do JSON da API, variáveis de
  ambiente e os campos que a LLM preenche. Traduzir esses quebraria o banco,
  o painel, o deploy ou o comportamento do modelo.

---

## 4. Arquivo por arquivo

### `back/app/` — nove arquivos

| Arquivo | Linhas | O que tem dentro |
|---|---|---|
| `agente.py` | ~4.400 | O agente inteiro, em seções, na ordem das dependências: o plano que a LLM devolve, os estados e transições, o resolvedor que casa o texto do cliente com o cardápio, o FAQ, o ritmo de envio, o prompt, os clientes de LLM (real e falso), o WhatsApp, o agrupador de balões, a sessão, o fechamento com Pix, as operações, a máquina de um turno e a orquestração. Quem chama de fora usa só o fim: `handle_inbound`, `handle_outbound_echo`, `notify_payment_approved`. |
| `textos.py` | ~600 | Toda frase que o cliente lê. Funções puras: entra dado, sai texto. **É o arquivo que se abre para mudar o que o bot fala** — nenhuma lógica mora aqui. |
| `api.py` | ~900 | As 38 rotas HTTP e as dependências delas. Sete routers com nome próprio (`rotas_produtos`, `rotas_pedidos`, `rotas_saude`…), que o `main.py` liga. |
| `esquemas.py` | ~480 | Os schemas Pydantic de entrada e saída. **Os nomes dos campos aqui são as chaves do JSON** que o painel lê. Ficam separados das rotas porque os serviços também os montam. |
| `servicos.py` | ~1.630 | Catálogo, pedidos, pagamentos, clientes, conversas, métricas, preços e o provedor de Pix — nessa ordem, que é a ordem das dependências. |
| `banco.py` | ~720 | As 14 tabelas (SQLAlchemy), a conexão e o `init_db`. **O nome do atributo é o nome da coluna**: não há nome explícito em `mapped_column`. |
| `dominio.py` | ~280 | Carrinho, cardápio e enums. Não importa nada do projeto — dá para usar num teste sem banco. A conta do pedido mora aqui, e é uma só. |
| `configuracao.py` | ~260 | `Settings` (todo segredo vem do ambiente), o log e a checagem da chave de API. Os nomes dos campos viram as variáveis de ambiente. |
| `main.py` | ~280 | Monta o FastAPI, o CORS, os cabeçalhos de segurança e o tratamento de erro; liga os sete routers. No fim, a conversa pelo terminal (`python -m app.main`). |

### `front/src/` — quatorze arquivos

| Arquivo | Linhas | O que tem dentro |
|---|---|---|
| `pagina-produtos.tsx` | ~1.560 | A tela de Produtos e os nove diálogos e cartões dela. É a única tela que grava dados: o CRUD do cardápio, que muda todo dia. |
| `pagina-dashboard.tsx` | ~555 | Os números do dia e os gráficos. Só leitura. |
| `pagina-conversas.tsx` | ~400 | O histórico das conversas e o botão que chama um atendente humano. |
| `pagina-producao.tsx` | ~366 | O Kanban dos pedidos: só muda o status. |
| `ui.tsx` | ~694 | Botão, card, diálogo, tabela… vieram do shadcn/ui e quase nunca mudam. |
| `comuns.tsx` | ~419 | Moldura da página, cabeçalho com as abas, estados de carregando/erro/vazio, botão de recarregar e a lista que se arrasta. |
| `dados.ts` | ~501 | Os hooks de react-query. As telas não chamam a API direto: chamam um hook daqui. |
| `api.ts` | ~381 | O único lugar do painel que faz `fetch`. Põe a chave no header e traduz erro em mensagem legível. |
| `formato.ts` | ~310 | Dinheiro, data, telefone, rótulos e cores de status, e o que converte a resposta da API. |
| `tipos.ts` | ~306 | Os tipos que espelham `back/app/esquemas.py`, campo por campo. |
| `App.tsx` | ~55 | As rotas do painel e a página 404. |
| `main.tsx` | 8 | O ponto de entrada. |
| `api.test.ts`, `formato.test.ts`, `pagina-producao.test.tsx` | ~400 | Os 40 testes do painel. |

---

## 5. O agente de IA

### Como uma mensagem vira um pedido

**1. Chega.** A Evolution API chama `POST /webhooks/evolution`. A rota valida o
token, descarta o que não é conversa individual e responde `200` na hora —
webhook lento é reentregue, e reentrega vira pedido duplicado.

**2. Espera o cliente parar de digitar.** Quem pede pelo WhatsApp escreve
picado: "quero um pote" / "G" / "de pistache". `inbox.py` segura por
`WA_DEBOUNCE_SECONDS` e junta tudo num texto só. Um cadeado por telefone (na
mesma seção) garante que o turno de UM cliente nunca rode duas vezes ao mesmo
tempo — sem isso, uma mensagem que chega enquanto o turno anterior ainda está
salvando o estado dispararia um segundo `handle_inbound` sobre a mesma
conversa, e um dos dois apagaria o que o outro escreveu.

**2b. Nota de voz também vira texto.** Se a mensagem é um áudio
(`audioMessage`), o agente baixa o conteúdo pela Evolution API
(`getBase64FromMediaMessage`) e transcreve com a OpenAI antes de seguir — daí
em diante é um turno normal, como se o cliente tivesse escrito. Áudio longo
demais (`AUDIO_MAX_SECONDS`) ou que não deu para transcrever (Evolution fora
do ar, sem chave da OpenAI) não conta como "não entendi": o bot avisa que não
conseguiu ouvir e pede para o cliente escrever, sem gastar uma chamada de IA
nem consumir o contador de reparo progressivo.

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

**8. Sai.** `textos.py` escreve o texto; o ritmo de envio segura a entrega para o
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
| **Evolution API** | Mandar e receber WhatsApp, e baixar o conteúdo de uma nota de voz recebida. Gateway self-hosted; pareia por QR code, não exige conta comercial aprovada. | Com `FAKE_MODE=true` as mensagens vão para um canal em memória. |
| **OpenAI** | Traduzir a mensagem em operações, e transcrever nota de voz do cliente. | Com `FAKE_MODE=true` entra o `llm_fake.py`; a transcrição usa `FakeAudioTranscriber`, que só decodifica os bytes recebidos como texto (não reconhece voz de verdade). |
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
python -m app.banco --seed
uvicorn app.main:app --reload

cd ../front
npm install
npm run dev
```

**Conversar com o agente sem WhatsApp:**

```bash
cd back && python -m app.main
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
| Uma resposta nova do bot | `textos.py` (só texto) |
| Uma operação nova do pedido | `agente.py`: a `Action` no plano, a descrição dela no prompt, e o que ela faz nas operações — **e um caso em `tests/eval_cases.py`** |
| Responder uma pergunta nova | a seção de FAQ do `agente.py` e o tópico em `QUESTION_TOPICS` |
| Um campo novo no produto | `db/schema.sql` + migração, `db/models.py`, `schemas/product.py`, `services/catalog.py` e a tela |
| Uma configuração nova | `core/config.py` **e** `back/.env.example` (há um teste que exige os dois) |
| Uma tela nova | um `front/src/pagina-*.tsx`, usando `Page`/`PageTitle` de `comuns.tsx`, e a rota em `App.tsx` |
| Um endpoint novo | `back/app/api.py`, o schema em `esquemas.py`, e a função em `front/src/api.ts` |

Três regras da casa:

1. **Nenhuma classe do Tailwind pode ser montada por concatenação.** O scanner
   não enxerga string montada em tempo de execução e a classe não vai para o
   CSS. Já aconteceu, e o Kanban ficou sem cor em produção — ver o comentário
   no topo de `front/src/formato.ts`.
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
