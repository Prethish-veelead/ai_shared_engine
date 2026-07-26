# Engine Concept — Multi-Bot RAG Search Engine (Backend)

This document explains what the backend is and how it works, so the admin
portal (and Claude Code, when wiring the two together) knows exactly what it is
talking to. The admin portal **never** touches the database or vector store
directly — it only calls the HTTP endpoints listed in `API_CONTRACT.md`.

## What it is

One FastAPI backend that hosts many independent RAG chatbots. Every bot shares
the same code and the same AI engine, but each bot has:

- its own SharePoint document source,
- its own Qdrant collection (vectors are isolated per bot),
- its own prompt, model, and indexing schedule.

**Adding a bot = adding one YAML file in `config/bots/`. No code changes.**

## The two flows

**1. Ingestion (background, scheduled, per bot).** A scheduler runs each bot's
sync on its own cron. It asks SharePoint (via Microsoft Graph *delta query*) for
only the documents that changed since last time, downloads them, extracts text
(PDF/DOCX, with OCR for scanned pages), splits the text into token-sized chunks,
turns chunks into embeddings, and stores them in that bot's Qdrant collection.
Each chunk is tagged with `doc_id` + `bot_id` so updates and deletes are precise
and one bot can never read another bot's data.

**2. Query (live, per user request).** A user asks a question at
`POST /ask/{bot_id}`. The engine loads that bot's config, embeds the question,
searches **only that bot's collection** for the most relevant chunks, builds a
prompt (system prompt + retrieved chunks + question), sends it to Azure OpenAI,
and returns the answer with citations. On every request it writes one chat-log
row and one usage-log row — this is what powers all admin dashboards.

## Where the data lives

- **Qdrant** — document chunks / embeddings, one collection per bot. (Not read
  by the admin directly.)
- **PostgreSQL** — the system of record the admin reads from:
  - `chat_logs` — one row per answered question (question, answer, tokens, cost,
    latency, user, bot, timestamp, citations).
  - `usage_logs` — one row per billable AI call (chat **and** embedding), with
    tokens + computed cost. All cost/usage numbers come from `GROUP BY` on this.
  - `sync_state` — per-library SharePoint delta token + index version.
  - `bots` — optional DB metadata (source of truth for config stays in YAML).

## What the admin can read today

Bots list, chat history (filter by bot / user / date / keyword), cost by bot,
cost by model, and a reload trigger. See `API_CONTRACT.md` for exact shapes and
for the endpoints that still need to be **added** to fully power every dashboard
in the spec (usage summary, user analytics, logs, single-bot CRUD).

## What is NOT built yet (so the admin design plans for it)

- **Entra ID auth** — right now the caller passes `user_id`; later it comes from
  a validated token. The admin will sit behind Entra ID sign-in.
- **SharePoint credentials** — the delta-sync code is ready but needs each
  tenant's app registration to run.
- Several admin dashboard endpoints (listed in `API_CONTRACT.md`).

## How the admin portal connects (same VM)

Nginx on the VM routes:
- `https://hellobot.com/`      → admin portal (Next.js, port 3000)
- `https://hellobot.com/api/`  → backend (FastAPI, port 8000)

So from the admin's point of view, the backend base URL is simply `/api`.
