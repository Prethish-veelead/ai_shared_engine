# Admin Portal Design Concept

This document explains the architecture, component structure, data flow, and API integration for the Admin Portal. It serves as a guide for Claude Code when wiring the Next.js frontend to the FastAPI backend.

## 1. Component Structure and Layout

The portal is built using **Next.js 15 (App Router)** with **Tailwind CSS**, **Recharts** (for data visualization), and **Lucide React** (for icons).

### The UI Shell
- `src/app/layout.tsx`: The root layout wraps the entire application. It establishes a `flex` layout containing the Sidebar and Header.
- `src/components/layout/Sidebar.tsx`: The left-hand navigation menu linking to all 7 core pages.
- `src/components/layout/Header.tsx`: The top bar, currently containing a placeholder for Microsoft Entra ID authentication.

### Page Routing
- `/` (`src/app/page.tsx`): Main Dashboard
- `/bots` (`src/app/bots/page.tsx`): Bot Management (CRUD)
- `/usage` (`src/app/usage/page.tsx`): Usage Dashboard
- `/cost` (`src/app/cost/page.tsx`): Cost Dashboard
- `/users` (`src/app/users/page.tsx`): User Analytics
- `/history` (`src/app/history/page.tsx`): Chat History
- `/logs` (`src/app/logs/page.tsx`): Logs & Monitoring

## 2. API Layer & Data Flow

**CRITICAL RULE:** The UI never calls `fetch()` directly from a page or component. **All backend communication happens exclusively through `src/lib/api.ts`.** 

When wiring the backend, Claude Code should **only** need to edit `src/lib/api.ts`. The UI components will automatically adapt as long as the typescript interfaces in that file are respected.

### The `NEXT_PUBLIC_USE_MOCKS` Toggle
The `api.ts` file checks the `NEXT_PUBLIC_USE_MOCKS` environment variable. 
- If `"true"`, the functions return realistic mock data (useful for frontend development and testing).
- If `"false"` (or undefined in production), the functions make `fetch()` calls to `process.env.NEXT_PUBLIC_API_BASE` (which defaults to `/api`).

## 3. Page Mapping to API Contract

Here is exactly which `API_CONTRACT.md` endpoints each page calls:

### 1. Dashboard (`/`)
**Purpose:** High-level overview of system health and metrics.
- `GET /api/admin/usage/summary` (Currently Mocked)
- `GET /api/admin/usage/trend` (Currently Mocked)
- `GET /api/admin/cost/by-bot` (Live endpoint)

### 2. Bot Management (`/bots`)
**Purpose:** Table of bots and a form to create/edit/delete bots and configure their settings.
- `GET /api/admin/bots` (Live endpoint)
- `POST /api/admin/bots` (Currently Mocked)
- `PUT /api/admin/bots/{bot_id}` (Currently Mocked)
- `PATCH /api/admin/bots/{bot_id}` (Currently Mocked)
- `DELETE /api/admin/bots/{bot_id}` (Currently Mocked)
- `POST /api/admin/bots/{bot_id}/reindex` (Currently Mocked)

### 3. Usage Dashboard (`/usage`)
**Purpose:** Token consumption and request volume analysis with filters.
- `GET /api/admin/usage/summary` (Currently Mocked)
- `GET /api/admin/usage/trend` (Currently Mocked)
- `GET /api/admin/bots` (Live endpoint - used for the filter dropdown)

### 4. Cost Dashboard (`/cost`)
**Purpose:** Analyze spending by bot, model, and user.
- `GET /api/admin/cost/summary` (Currently Mocked)
- `GET /api/admin/cost/by-bot` (Live endpoint)
- `GET /api/admin/cost/by-model` (Live endpoint)
- `GET /api/admin/cost/by-user` (Currently Mocked)

### 5. User Analytics (`/users`)
**Purpose:** View activity, questions asked, and tokens used across the user base.
- `GET /api/admin/users` (Currently Mocked)

### 6. Chat History (`/history`)
**Purpose:** Searchable and filterable table of raw chat logs.
- `GET /api/admin/chat-history` (Live endpoint)
- `GET /api/admin/bots` (Live endpoint - used for the filter dropdown)

### 7. Logs & Monitoring (`/logs`)
**Purpose:** System events, sync status, and errors.
- `GET /api/admin/logs` (Currently Mocked)

## 4. State Management
State is managed locally within each page using standard React `useState` and `useEffect` hooks. Because the data is read-heavy (dashboards), pages fetch their data on mount. 

For the Bot Management page, local state tracks whether the user is viewing the table (`isCreating: false, isEditing: null`) or viewing the form (`isCreating: true` or `isEditing: Bot`). Form submissions trigger an API call via `src/lib/api.ts`, await the response, and then re-fetch the bot list to update the table.
