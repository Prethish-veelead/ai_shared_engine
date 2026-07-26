# AI Search Engine — Multi-Bot RAG Platform

A single FastAPI backend that hosts many independent RAG chatbots. Each bot has
its own SharePoint source and its own Qdrant collection, but they all share one
codebase and one AI engine.

**Add a new bot = add one YAML file in `config/bots/`. No code changes.**

## What's implemented in this skeleton

- `POST /ask/{bot_id}` — full RAG flow: embed → retrieve (bot's own collection)
  → build prompt → generate → return answer + citations, and log tokens/cost.
- Bot registry that loads + validates every `config/bots/*.yaml` at startup.
- `VectorStore` and `LLMClient` abstractions (swap Qdrant/Azure Search or model
  provider via settings — no code changes).
- Document loaders: PDF (with OCR fallback), DOCX. PPTX/XLSX/TXT are stubs.
- Incremental indexer (add / update = delete-then-insert / delete by doc_id).
- SharePoint Graph client using delta queries (app-only auth skeleton).
- Postgres tables for chat history + usage/cost + sync state, with admin
  read endpoints and per-bot / per-model cost aggregation.
- APScheduler worker to run each bot's sync on its own cron.
- Docker Compose: api + worker + postgres + qdrant.

## Not yet wired (by design — next phases)

- Entra ID token validation (`app/core/security.py` is a placeholder).
- Real SharePoint credentials + drive-id resolution in the scheduler.
- Semantic question cache (phase 2).
- The admin UI itself (built separately in Lovable/Antigravity, calls `/admin/*`).

## Run it

```bash
cp .env.example .env      # fill in Azure OpenAI keys
cd docker
docker compose up --build
```

Then:

```bash
# one-time: create tables + a bot's Qdrant collection
docker compose exec api python -m scripts.init_db
docker compose exec api python -m scripts.create_collection hr

# health
curl localhost:8000/health
curl localhost:8000/ready          # lists loaded bots

# ask a bot (once documents are indexed)
curl -X POST localhost:8000/ask/hr \
  -H "Content-Type: application/json" \
  -d '{"question":"How many annual leave days do I get?","user_id":"u1"}'
```

API docs at http://localhost:8000/docs

## Adding a new bot (the 1–4 hour path)

1. Create the SharePoint library + a Qdrant collection.
2. Copy an existing file in `config/bots/` (e.g. `hr.yaml`) → `newbot.yaml`.
3. Edit id, name, route, sharepoint site/libraries, collection, prompt.
4. `POST /admin/bots/reload` (or restart). Done — other bots untouched.

## Layout

```
app/
  core/         config, logging, exceptions, security(placeholder)
  api/routes/   ask, health, admin
  bots/         registry + config schema
  rag/          retriever, prompt_builder, generator, pipeline
  ingestion/    sharepoint_client, loaders/, chunker, embedder, indexer
  vectorstore/  base + qdrant + azure_search(stub)
  llm/          base + azure_openai
  tracking/     usage_tracker, cost_calculator, chat_history
  db/           models, session, repositories/
  workers/      sync_scheduler, sync_job
config/
  bots/*.yaml   ← one file per bot
  models.yaml   ← model + price registry
```
