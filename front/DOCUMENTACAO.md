# Frontend — Mi Piace

Painel do lojista: Kanban de produção, cardápio, monitoramento do agente de
WhatsApp e dashboard. React 18 + Vite + TypeScript + Tailwind/shadcn + TanStack
Query + Recharts.

Para rodar o projeto inteiro (banco, API e painel), veja o
[README na raiz](../README.md). Aqui ficam só os detalhes do front.

---

## Como rodar

```bash
cp .env.example .env.local   # VITE_API_BASE_URL e VITE_ADMIN_API_KEY
npm install
npm run dev                  # http://localhost:8080
```

| Script | O que faz |
|---|---|
| `npm run dev` | Servidor de desenvolvimento na porta 8080 |
| `npm run build` | Build de produção em `dist/` |
| `npm run preview` | Serve o `dist/` localmente |
| `npm run test` | Testes com Vitest |
| `npm run lint` | ESLint |

### Variáveis de ambiente

| Variável | Padrão | Para quê |
|---|---|---|
| `VITE_API_BASE_URL` | `http://localhost:8000` | Base da API FastAPI |
| `VITE_ADMIN_API_KEY` | `dev-local-key` | Vai no header `X-API-Key` de toda rota `/api/*`; precisa bater com `ADMIN_API_KEY` do backend |

As duas são embutidas no bundle **em tempo de build** — em Docker elas chegam
como `--build-arg`, não como variável de runtime. Por isso nada de segredo real
aqui: o que está no bundle está visível no navegador.

---

## Estrutura

```
src/
├── components/
│   ├── common/QueryState.tsx  # loading / erro com "tentar de novo" / vazio
│   ├── conversations/         # lista, thread de chat e badge de estado
│   ├── dashboard/             # KPIs, gráficos, filtro de período
│   ├── layout/Header.tsx      # navegação
│   ├── production/            # Kanban (coluna + card de pedido)
│   ├── products/              # diálogos de CRUD do cardápio
│   └── ui/                    # shadcn/ui
├── hooks/
│   ├── use-orders.ts          # pedidos + mudança de status otimista
│   ├── use-products.ts        # árvore do catálogo + mutações otimistas
│   ├── use-metrics.ts         # quatro queries do dashboard
│   └── use-conversations.ts   # conversas, mensagens e handoff (poll de 10s)
├── lib/
│   ├── api.ts                 # cliente HTTP — única porta de saída
│   ├── config.ts              # leitura de import.meta.env
│   ├── format.ts              # moeda, data, telefone (funções puras)
│   └── transforms.ts          # API -> formato dos componentes/gráficos
├── pages/                     # Loja, Produtos, Conversas, Admin, NotFound
└── types/                     # espelham back/db/schema.sql
```

### Onde mexer para cada coisa

| Quero... | Arquivo |
|---|---|
| Adicionar/alterar uma chamada de API | `src/lib/api.ts` |
| Mudar o formato de exibição de dinheiro/data | `src/lib/format.ts` |
| Mudar como um dado da API vira ponto de gráfico | `src/lib/transforms.ts` |
| Mudar o cache/poll de uma tela | o hook correspondente em `src/hooks/` |
| Mudar cores, tokens ou classes utilitárias | `src/index.css` e `tailwind.config.ts` |

---

## Convenções

- **Nenhuma URL nem chave hardcoded.** Tudo passa por `src/lib/config.ts`.
- **Nenhum componente chama `fetch` direto.** Só `src/lib/api.ts` fala HTTP;
  os componentes falam com hooks.
- **Todo erro de API vira mensagem legível.** `api.ts` extrai o `detail` do
  FastAPI (string ou lista de erros do Pydantic) e embrulha em `ApiError`.
- **Toda tela trata os três estados**: carregando (Skeleton), erro (mensagem +
  botão de tentar de novo) e vazio (texto explicando que não há dado ainda).
  O componente `QueryState` existe para não repetir isso.
- **Mutações de lista são otimistas** com rollback no erro (mover pedido de
  coluna, alternar disponibilidade, excluir item do cardápio).
- **Lógica pura fora do React.** Formatação e transformação vivem em `lib/` e
  são o que os testes cobrem.

---

## Testes

```bash
npm run test
```

Vitest + Testing Library, ambiente jsdom (`vitest.config.ts`, setup em
`src/test/setup.ts`). Cobertura atual:

| Arquivo | O que verifica |
|---|---|
| `src/lib/format.test.ts` | Moeda, percentual, telefone, tempo relativo, valores nulos e decimais que chegam como string |
| `src/lib/transforms.test.ts` | Normalização do pedido, endereço, e a conversão das métricas para o formato dos gráficos |
| `src/lib/api.test.ts` | Header `X-API-Key`, query string, extração do `detail` do FastAPI e erro de rede |
| `src/components/production/OrderCard.test.tsx` | Render do card: código, itens com complementos, total, Pix pendente e avanço de status |
