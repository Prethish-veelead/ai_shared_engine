# Bot UI Concept & API Contract

This document explains the architecture, component structure, data flow, and API integration for the End-User Bot UI (`bot-ui`). It serves as a guide for Claude Code when wiring the frontend to the FastAPI backend.

## 1. Component Structure and Layout

The `bot-ui` is built using **Next.js 15 (App Router)** with **Tailwind CSS** and **Lucide React**.

### Global Layout & Auth
- `src/app/layout.tsx`: Root layout that wraps the app with `Providers`.
- `src/components/Providers.tsx`: Provides the `MsalProvider` and handles global 403 (Forbidden) alerts.
- `src/components/layout/AppShell.tsx`: The primary UI shell. 
  - **Login Wall:** If the user is not authenticated via Microsoft Entra ID, it blocks access and displays a full-screen login button.
  - **Header:** Once authenticated, it renders the chat header with the user's name and a sign-out button.

### Pages
- `/` (`src/app/page.tsx`): A simple landing page instructing the user to navigate to a specific bot route.
- `/bot/[botId]` (`src/app/bot/[botId]/page.tsx`): The main chat interface for interacting with a specific bot.

## 2. Microsoft Entra ID Integration

The UI uses `@azure/msal-react` for Single Page Application (SPA) authentication.

### Required Environment Variables
For authentication to work, the following environment variables must be populated in `.env.local`:
- `NEXT_PUBLIC_ENTRA_TENANT_ID`: The Microsoft Entra Tenant ID (or 'common').
- `NEXT_PUBLIC_ENTRA_CLIENT_ID`: The Client ID of the SPA application registered in Entra.
- `NEXT_PUBLIC_API_SCOPE`: The scope used to acquire tokens for the backend (e.g., `api://<guid>/access_as_user`). **Without this exact scope, the backend will reject the token.**
- `NEXT_PUBLIC_API_BASE`: The base URL for the backend API (defaults to `/api`).

*Note: `http://localhost:3000` must be registered as a Redirect URI in the Entra ID SPA configuration.*

## 3. API Layer & The `/ask` Endpoint

**CRITICAL RULE:** All backend communication happens exclusively through `src/lib/api.ts`. 

The single endpoint utilized by this frontend is:

### `POST /api/ask/{botId}`

This endpoint is called whenever a user sends a message in the chat interface.

**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>` (Token is acquired silently via MSAL before every request).

**Request Body:**
```json
{
  "question": "<user text>"
}
```

**Expected Response:**
```json
{
  "answer": "The generated answer from the RAG pipeline.",
  "citations": [
    {
      "index": 1,
      "source": "HR_Policy.pdf",
      "page": 12
    }
  ],
  "model": "gpt-4-turbo",
  "total_tokens": 450,
  "cost_usd": 0.002,
  "response_time_ms": 1250
}
```

*Note on Citations:* If a source document does not have a page number (e.g., a `.docx` file or a web page), the backend should return `null` for the `page` field. The UI gracefully handles `page: null` and omits the `(p.N)` text.

### Error Handling
- **401 Unauthorized:** If the API returns 401 (e.g. token expired), `api.ts` automatically triggers an MSAL `loginRedirect` to force the user to authenticate again.
- **403 Forbidden:** If the API returns 403 (e.g. the user's Entra Group is not in the bot's `allowed_groups`), `api.ts` dispatches a `bot-forbidden` event. The `Providers` component catches this and displays a "You don't have access to this bot" overlay.
