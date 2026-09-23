# Mi Piace — Gelateria

Sistema de atendimento de uma gelateria **pelo WhatsApp**. O cliente conversa
com um agente (máquina de estados + IA), monta o pedido e paga por Pix. O
lojista acompanha tudo por um painel web.

- **Agente de WhatsApp** — atende, monta o pedido e cobra por Pix.
- **API FastAPI + Postgres** — a única dona das regras de negócio.
- **Painel web (React)** — produção (Kanban), cardápio, conversas e dashboard.

Com `FAKE_MODE=true` o projeto roda inteiro na sua máquina **sem nenhuma chave
de API**: o LLM e o Mercado Pago são substituídos por implementações falsas
determinísticas.

> **O que este sistema não é:** não é um PDV e não tem loja online. O pedido
> nasce na conversa do WhatsApp; o painel é uma ferramenta interna do lojista.

📄 Onde cada coisa mora no código: **[PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)**
🚀 Colocar no ar: **[DEPLOY.md](DEPLOY.md)**

---

## Como rodar

### Docker (recomendado)

```bash
cp back/.env.example back/.env      # já vem com FAKE_MODE=true
docker compose up --build
```

| Serviço | URL |
|---|---|
| Painel | http://localhost:8080 |
| API | http://localhost:8000 — documentação em `/docs` |
| Postgres | `localhost:5432` |

O banco aplica `back/db/schema.sql` e `back/db/seed.sql` na primeira subida:
o cardápio já nasce com os três tamanhos (M 240ml, G 500ml e COMBO 2 G 1000ml)
e os 31 sabores. Para recomeçar do zero: `docker compose down -v`.

Pedidos, clientes e conversas nascem vazios: só o cardápio é semeado. Kanban e
Dashboard aparecem zerados até o agente atender o primeiro cliente de verdade —
não existe dado fabricado em lugar nenhum.

Para subir também o gateway de WhatsApp:
`docker compose --profile whatsapp up -d`.

### Sem Docker

Precisa de Python 3.12+, Node 20+ e Postgres 14+.

```bash
# banco
createdb mipiace
psql -d mipiace -f back/db/schema.sql
psql -d mipiace -f back/db/seed.sql

# backend
cd back
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload                        # http://localhost:8000/docs

# frontend (outro terminal)
cd front
cp .env.example .env.local
npm install && npm run dev                           # http://localhost:8080
```

> A `VITE_ADMIN_API_KEY` do front precisa ser igual à `ADMIN_API_KEY` do back —
> toda rota `/api/*` exige o header `X-API-Key`. Se o painel disser "Chave de
> acesso inválida", é isso.

---

## Testar o agente sem WhatsApp

Com `FAKE_MODE=true` o agente usa um LLM falso determinístico que casa palavras
com o catálogo real. Duas formas de conversar com ele:

**CLI interativa**

```bash
cd back && python -m app.cli.chat
```

**Endpoint do simulador** (bom para script)

```bash
curl -X POST localhost:8000/api/simulator/message \
  -H "Content-Type: application/json" -H "X-API-Key: dev-local-key" \
  -d '{"phone":"5511999998888","text":"oi"}'
# -> {"replies": ["Oi! 🍨 Aqui é a *Mi Piace Gelateria*..."], "state": "escolhendo_produto"}

# recomeçar a conversa desse telefone
curl -X POST localhost:8000/api/simulator/reset \
  -H "Content-Type: application/json" -H "X-API-Key: dev-local-key" \
  -d '{"phone":"5511999998888"}'

# "pagar" o Pix falso e ver o pedido entrar na produção
curl -X POST localhost:8000/api/simulator/payments/SEU_ORDER_ID/approve \
  -H "X-API-Key: dev-local-key"
```

---

## Testes

```bash
cd back  && pytest          # 191 testes
cd front && npm run test    # 40 testes
cd front && npm run lint    # eslint
```

---

## Telas do painel

| Rota | Tela | O que faz |
|---|---|---|
| `/producao` | Produção | Kanban dos pedidos: preparando → entrega → finalizado |
| `/produtos` | Produtos | CRUD do cardápio — liga e desliga o item do dia, arrasta a ordem, define as regras de escolha |
| `/conversas` | Conversas | Espelho das conversas do WhatsApp + botão de assumir o atendimento |
| `/dashboard` | Dashboard | Vendas, ticket médio, pedidos por status |

Só a tela de **Produtos** escreve no banco. As outras três leem.

---

## Como o agente funciona

A IA **traduz**, o backend **decide**. Cada mensagem vira uma lista de
operações — o que o cliente quer fazer com o pedido — e o executor aplica cada
uma contra o catálogo real.

```
   "tira o primeiro, põe um grande de chocolate e quero entrega"
                              │
                              ▼
                    ┌───────────────────┐
                    │        IA         │  lê a mensagem COM o retrato
                    │  (traduz, só isso)│  do pedido (o que já tem no
                    └─────────┬─────────┘  carrinho, o que falta, etc.)
                              ▼
        REMOVE_ITEM(1) · ADD_ITEM(G, [chocolate]) · SET_FULFILLMENT(entrega)
                              │
                              ▼
                    ┌───────────────────┐
                    │     EXECUTOR      │  valida contra o catálogo,
                    │ (decide e aplica) │  calcula preço em Decimal,
                    └─────────┬─────────┘  nunca aceita item inventado
                              ▼
                        estado do pedido
```

A IA nunca inventa produto, preço, taxa ou disponibilidade, e nunca cobra.

### Os estados

```
   ┌──────────────────────────────────────────────┐
   │                CONVERSANDO                   │  monta o pedido:
   │  (escolher, sabores, editar, tirar, endereço)│  tudo acontece aqui
   └───────────────────┬──────────────────────────┘
                       │ cliente quer fechar e o pedido está completo
                       ▼
   ┌──────────────────────────────────────────────┐
   │             CONFIRMANDO_PEDIDO               │  resumo + taxa + total
   └───────────────────┬──────────────────────────┘
                       │ confirmação CLARA ("pode ser" não passa)
                       ▼
   ┌──────────────────────────────────────────────┐
   │            AGUARDANDO_PAGAMENTO              │  Pix enviado
   └───────────────────┬──────────────────────────┘
                       │ webhook do Mercado Pago
                       ▼
                   CONCLUIDO

   De qualquer ponto:
     • ATENDIMENTO_HUMANO — o cliente pede uma pessoa, ou o lojista assume
       pelo painel. O bot para de conduzir o pedido, mas continua ouvindo:
       avisa que está aguardando, aceita cancelamento e devolve a conversa
       a si mesmo se o cliente preferir seguir por ali. Sem resposta da loja
       por HANDOFF_RETURN_MINUTES, ele reassume sozinho.
     • CANCELADO — o cliente desiste ou o Pix expira.
```

A etapa do diálogo não é estado: está nos dados do pedido (falta escolher
sabor? falta endereço?). Isso é o que deixa o cliente perguntar o horário no
meio da escolha de sabores sem perder nada.

O item que ainda está sendo montado fica no pedido como qualquer outro, com o
mesmo número que o cliente vê na tela — é o que faz "tira o médio" acertar o
médio quando existem dois itens em jogo.

A única transição que existe para proteger alguém é a do meio: **não se cobra
quem não viu o resumo com o total e concordou**.

A tabela executável está em `back/app/agent/states.py`; os nomes dos estados,
em `back/app/domain/enums.py`. O passo a passo de uma mensagem está no
[PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md).

---

## Integrações

| O quê | Como | Quando é obrigatório |
|---|---|---|
| **IA** | OpenAI (function calling) | `FAKE_MODE=false` |
| **WhatsApp** | Evolution API (self-hosted, Baileys) | `FAKE_MODE=false` |
| **Pix** | Mercado Pago | `FAKE_MODE=false` |

Com `FAKE_MODE=true` os três são substituídos por implementações falsas e nada
sai da máquina.

---

## Trancar o sistema em um contato

`ALLOWED_PHONES` vazia é o estado normal: o agente atende quem chegar. Com
números dentro (separados por vírgula), o sistema vira uma sala fechada —
mensagem de qualquer outro número é descartada na entrada do webhook, antes de
virar conversa no banco, e o `EvolutionAdapter` se recusa a enviar para fora da
lista. São dois cadeados de propósito: o segundo garante que nenhum caminho do
sistema, nem o aviso de Pix pago, alcance um terceiro.

Serve para deixar a loja no ar e testar pelo WhatsApp de verdade sem o risco de
atender um cliente pela metade. Para abrir a loja, esvazie a variável.

```bash
ALLOWED_PHONES=5569993061196
```

A comparação normaliza o número: DDI + DDD + os 8 últimos dígitos. É o que faz
`+55 69 99306-1196` e `556993061196` (sem o nono dígito, como o WhatsApp às
vezes entrega) valerem como a mesma linha, sem confundir com o mesmo final em
outro DDD.

---

## Manter o número do WhatsApp vivo

O canal é um cliente não-oficial (Evolution API, Baileys por baixo). O que
derruba um número nesse cenário quase nunca é o conteúdo: é o padrão de envio.
Três defesas, em ordem de importância:

1. **O sistema não tem como enviar mensagem para quem não escreveu primeiro.**
   O agente só é acionado pelo webhook de mensagem recebida, e o aviso de Pix
   pago só vai para quem tem pedido aberto. Não existe disparo em massa, lista
   de transmissão nem envio para número frio — é isso, mais do que qualquer
   ajuste, que mantém o número no ar.
2. **O bot demora como gente demora.** `back/app/agent/pacing.py` simula
   digitação a ~45 palavras por minuto (sorteadas, não fixas) e manda o status
   "digitando..." pelo tempo correspondente, entre 1,2s e 8s.
3. **Existe um teto.** No máximo uma mensagem a cada 3s para o mesmo contato e
   12 por minuto na instância inteira, contra o caso patológico — um laço ou
   uma tempestade de webhooks é o que perde o número de verdade.

Ajustáveis por `WA_TYPING_WPM`, `WA_MIN_SECONDS_BETWEEN_MESSAGES` e
`WA_MAX_MESSAGES_PER_MINUTE`.

Na instância da Evolution: `groupsIgnore=true` (o bot nem recebe grupo),
`readMessages=true`, `alwaysOnline=false` e `syncFullHistory=false`.

> Nada disso torna o banimento impossível. Usar cliente não-oficial contraria
> os termos do WhatsApp, e o risco é da conta. Pareie um chip dedicado à loja,
> nunca o número pessoal do dono.

---

## Segurança

- Todas as rotas `/api/*` exigem `X-API-Key` (`ADMIN_API_KEY`).
- Os webhooks são públicos mas validam o remetente: HMAC no Mercado Pago, token
  na query string na Evolution API.
- CORS é restrito à lista de `CORS_ORIGINS` — nunca `*`.
- Nenhum segredo no código: tudo passa por `back/app/core/config.py`.
- A chave do front é embutida no bundle em tempo de build e **é visível no
  navegador**. Trate o painel como aplicação interna.
