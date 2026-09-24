# Atendimento e pedidos pelo WhatsApp

Sistema de atendimento para casas de gelato, açaí, doces e afins. O cliente
conversa com um agente de IA **pelo WhatsApp**, monta o pedido e paga por Pix;
o lojista acompanha tudo por um painel web. A Mi Piace Gelateria é o primeiro
caso de uso — a identidade da loja é configuração, não código.

- **Agente de WhatsApp** — entende linguagem natural, monta o pedido e cobra.
- **API FastAPI + Postgres** — a única dona das regras de negócio.
- **Painel React** — produção (Kanban), cardápio, conversas e dashboard.

Com `FAKE_MODE=true` o projeto roda inteiro na sua máquina **sem nenhuma chave
de API**: o LLM e o Mercado Pago são substituídos por implementações falsas.

> **O que este sistema não é:** não é um PDV e não tem loja online. O pedido
> nasce na conversa; o painel é ferramenta interna do lojista.

## Documentação

| | |
|---|---|
| 📘 **[PROJECT.md](PROJECT.md)** | Como o sistema funciona, arquivo por arquivo. **Comece por aqui.** |
| 🚀 **[DEPLOY.md](DEPLOY.md)** | Colocar no ar, e as migrações de banco. |

---

## Como rodar

### Docker (recomendado)

```bash
cp back/.env.example back/.env      # já vem com FAKE_MODE=true
docker compose up --build
```

| Serviço | URL |
|---|---|
| Painel | <http://localhost:8080> |
| API | <http://localhost:8000> — documentação em `/docs` |
| Postgres | `localhost:5432` |

O banco aplica `back/db/schema.sql` e `back/db/seed.sql` na primeira subida.
Para recomeçar do zero: `docker compose down -v`.

Pedidos, clientes e conversas nascem vazios — só o cardápio é semeado. Kanban e
Dashboard ficam zerados até o agente atender o primeiro cliente de verdade: não
existe dado fabricado em lugar nenhum.

### Sem Docker

```bash
cd back && pip install -r requirements.txt
python -m app.db.init_db --seed
uvicorn app.main:app --reload

cd ../front && npm install && npm run dev
```

### Conversar com o agente sem WhatsApp

```bash
cd back && python -m app.cli.chat
```

---

## Verificar

```bash
cd back  && ruff check . && pytest
cd front && npm run typecheck && npm run lint && npm test && npm run build
```

Para exercitar o agente contra o modelo **de verdade** (gasta token, precisa de
`OPENAI_API_KEY`):

```bash
cd back && FAKE_MODE=false pytest -m eval
```

É o único teste que cobre o prompt. O porquê está em
[PROJECT.md §11](PROJECT.md#11-como-testar).

---

## Configuração

Toda variável lida pelo sistema está em **`back/.env.example`**, na mesma ordem
de `app/core/config.py` — e há um teste que quebra se as duas listas
divergirem. O painel tem as suas em `front/.env.example`.

Para atender uma segunda empresa, veja
[PROJECT.md §13](PROJECT.md#13-como-atender-uma-segunda-empresa): é um bloco de
`.env` e o cardápio cadastrado pela tela, sem tocar em código.
