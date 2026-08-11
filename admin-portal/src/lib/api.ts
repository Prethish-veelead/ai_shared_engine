const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "/api";
const USE_MOCKS = process.env.NEXT_PUBLIC_USE_MOCKS === "true";

// ---------------------------------------------------------------------
// TEMPORARY - dev/production tenant toggle, for testing only. Remove this
// whole block (and the Dev/Production switch in bots/page.tsx that calls
// setSharePointTenant) once testing against the dev tenant is no longer
// needed - see the conversation this was added in.
//
// The bot create/edit form does not collect a SharePoint tenant slug per
// bot (it only exists as a backend-required field: app/bots/schema.py's
// SharePointConfig.tenant / WebSourceConfig.tenant) - every bot created or
// edited through the form, and every "Load Libraries"/"Load Lists" call,
// uses whichever of these two is currently selected.
export const TENANT_DEV = "veelead-development";
export const TENANT_PRODUCTION = "veelead-solutions";
const TENANT_STORAGE_KEY = "admin-portal-sharepoint-tenant";

// Module-level, not React state - api.ts has no component of its own, and
// every caller (getSharePointLibraries/getSharePointLists/toBotConfigPayload)
// is a plain function, not a hook. bots/page.tsx's toggle just calls
// setSharePointTenant() and forces its own re-render.
let currentTenant: string =
  (typeof window !== "undefined" && localStorage.getItem(TENANT_STORAGE_KEY)) ||
  process.env.NEXT_PUBLIC_SHAREPOINT_TENANT ||
  TENANT_DEV;

export function getSharePointTenant(): string {
  return currentTenant;
}

export function setSharePointTenant(tenant: string): void {
  currentTenant = tenant;
  if (typeof window !== "undefined") localStorage.setItem(TENANT_STORAGE_KEY, tenant);
}
// ---------------------------------------------------------------------

// --- Types ---

export interface SharePointSiteEntry {
  siteUrl: string;
  libraries: string[];
  lists: string[];
}

export interface ResponseFieldEntry {
  name: string;
  prompt: string;
}

// content_type: web bots (ai-search-engine/app/bots/schema.py WebSourceConfig)
// scrape an admin-maintained SharePoint List of URLs into the bot's own
// Qdrant collection - see docs/WEB_SOURCE_BOT.md. Unlike library/list bots'
// sharepointSites (repeatable, multi-select), a web bot has exactly ONE
// site + ONE source list, so this is its own flat shape, not another
// SharePointSiteEntry-style array.
export interface WebSourceEntry {
  siteUrl: string;
  sourceList: string;
  idColumn: string;
  urlColumn: string;
  enableColumn: string;
  enabledValue: string;
  categoryColumn: string;
}

export interface Bot {
  id: string;
  name: string;
  route: string;
  enabled: boolean;
  // A bot is a "Library bot" (files), a "List bot" (SharePoint List rows),
  // or a "Web bot" (scraped URLs) - never more than one at once (hybrid is
  // a possible future addition, not supported yet). Immutable after
  // creation - see config_writer.py.
  contentType?: "library" | "list" | "web";
  // Additional fields for the form that might not exist in the basic list yet.
  // A bot can pull from more than one SharePoint site, each with its own
  // libraries/lists - names are only unique WITHIN a site. Library/list
  // bots only - web bots use webSource below instead.
  sharepointSites?: SharePointSiteEntry[];
  webSource?: WebSourceEntry;
  qdrantCollection?: string;
  llmModel?: string;
  embeddingModel?: string;
  indexingSchedule?: string;
  systemPrompt?: string;
  access?: {
    allowed_groups: string[];
  };
  // Extra fields this bot adds to its /ask response, on top of the fixed
  // base fields (answer, citations, model, tokens, cost, latency) - those
  // never change. Generated in the SAME LLM call as the answer, not a
  // second one (see ai-search-engine/app/rag/prompt_builder.py).
  responseFields?: ResponseFieldEntry[];
  // Free: read straight off the top-cited chunk's SharePoint Category
  // column metadata, no extra LLM call.
  includeCategory?: boolean;
  // Shown as clickable starter prompts in bot-ui's empty chat state.
  sampleQuestions?: string[];
}

export interface ChatHistoryRow {
  id: string;
  bot_id: string;
  user_id: string;
  user_email: string | null;
  question: string;
  answer: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_usd: number;
  response_time_ms: number;
  created_at: string;
  feedback: "like" | "dislike" | null;
  // Optional dislike-only reason ("Learning loop") - null if none was given
  // or a stale backend predates this field.
  feedback_comment?: string | null;
}

export interface CostByBot {
  bot_id: string;
  tokens: number;
  cost: number;
  requests: number;
}

export interface CostByModel {
  model: string;
  kind: "chat" | "embedding";
  cost: number;
  tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
}

export interface UsageSummary {
  total_requests: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_cost: number;
  avg_response_time_ms: number;
  active_users: number;
  // Not tracked in Postgres today (backend returns null - see
  // app/db/repositories/usage_repository.py usage_summary()). The UI must
  // render "—" rather than doing arithmetic on these.
  documents_indexed: number | null;
  index_size: number | null;
}

export interface UsageTrend {
  period: string;
  requests: number;
  tokens: number;
  cost: number;
}

export interface CostSummary {
  total_cost: number;
  embedding_cost: number;
  llm_cost: number;
  llm_input_cost: number;
  llm_output_cost: number;
  input_tokens: number;
  output_tokens: number;
}

export interface CostByUser {
  user_id: string;
  email: string | null;
  cost: number;
  tokens: number;
  requests: number;
}

export interface AvailableModels {
  llm: string[];
  embedding: string[];
}

export interface IndexStatus {
  bot_id: string;
  documents_indexed: number;
  chunks_indexed: number;
  last_sync_at: string | null;
  likes: number;
  dislikes: number;
}

// --- Resources page (storage / system / activity) ---
// Storage is exact. System resources are real but container/system-level,
// never per-bot. Activity is an explicit LOAD PROXY, never "RAM/CPU per bot" -
// see docs/ADMIN_RESOURCES_PAGE.md in ai-search-engine.

export interface StructuredTableStat {
  listName: string;
  tableName: string;
  rows: number;
  sizeBytes: number;
}

export interface StorageByBot {
  botId: string;
  name: string;
  contentType: "library" | "list";
  vectorPoints: number;
  vectorSizeBytes: number;
  vectorSizeIsEstimate: boolean;
  structuredTables: StructuredTableStat[];
  structuredTotalBytes: number;
  chatRows: number;
  usageRows: number;
  totalStorageBytes: number;
}

export interface ContainerResourceStat {
  memPct: number;
  cpuPct: number;
}

export interface SystemResources {
  memory: { usedBytes: number; limitBytes: number; pct: number };
  cpu: { pct: number };
  disk: { totalBytes: number; usedBytes: number; freeBytes: number; pct: number };
  process: { rssBytes: number; cpuPct: number };
  containers: Record<string, ContainerResourceStat> | null;
  containersAvailable: boolean;
  source: "cgroup" | "psutil";
  note: string;
}

export interface ActivityByBot {
  botId: string;
  name: string;
  requests: number;
  tokens: number;
  cost: number;
  avgResponseTimeMs: number;
  requestsSharePct: number;
  tokensSharePct: number;
  costSharePct: number;
  lastSyncAt: string | null;
  lastSyncStatus: string | null;
}

export interface UserAnalytics {
  user_id: string;
  email: string;
  last_login: string | null;
  questions_asked: number;
  tokens_used: number;
}

export interface LogEntry {
  id: number;
  timestamp: string;
  type: "error" | "sync" | "auth" | "ai" | "indexing" | "resource";
  bot_id: string | null;
  message: string;
}

// Shared time-filter params every dashboard endpoint accepts
// (see app/api/time_filters.py: period OR start/end, both ISO datetimes).
interface TimeFilterParams {
  bot_id?: string;
  period?: "today" | "yesterday" | "last_7_days" | "last_30_days" | "this_month" | "custom" | string;
  start?: string;
  end?: string;
}

// --- Helper ---

import { acquireApiToken } from "./msal";

function buildQuery(params?: object): string {
  if (!params) return "";
  const searchParams = new URLSearchParams();
  for (const [key, value] of Object.entries(params as Record<string, unknown>)) {
    if (value !== undefined && value !== null && value !== "") {
      searchParams.append(key, String(value));
    }
  }
  const qs = searchParams.toString();
  return qs ? `?${qs}` : "";
}

async function fetcher<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE}${endpoint}`;
  const token = typeof window !== "undefined" ? await acquireApiToken() : null;

  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...options?.headers,
  };

  if (token) {
    (headers as Record<string, string>)["Authorization"] = `Bearer ${token}`;
  } else {
    console.warn(`fetcher: sending ${endpoint} without a Bearer token`);
  }

  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (response.status === 401) {
    // Do NOT blindly call loginRedirect() here - acquireApiToken() already
    // tries silently first and only starts a single guarded interactive
    // redirect if silent acquisition genuinely requires it. Calling
    // loginRedirect() unconditionally on every 401 is what caused the
    // interaction_in_progress loop (a second interactive request firing
    // while the first redirect's handleRedirectPromise() was still pending).
    if (typeof window !== "undefined") {
      acquireApiToken().catch(console.error);
    }
    throw new Error("Unauthorized - redirecting to login");
  }

  if (response.status === 403) {
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("admin-forbidden"));
    }
    throw new Error("Forbidden - Admin access required");
  }

  if (!response.ok) {
    // Backend errors come back as {"error": {"code", "message"}} - see
    // app/api/error_handlers.py. Fall back to statusText if the body isn't JSON.
    let message = response.statusText;
    try {
      const body = await response.json();
      message = body?.error?.message || message;
    } catch {
      // response had no JSON body
    }
    throw new Error(`API call failed: ${message}`);
  }

  if (response.status === 204) return undefined as T;
  return response.json();
}

// The create-bot form only collects `name` and `route` (e.g. "/ask/hr"), not
// a separate id/slug, even though the backend uses `id` as the bot's YAML
// filename and registry key (app/bots/schema.py). Every existing bot's route
// is exactly `/ask/{id}`, so derive the id from the route the same way;
// fall back to slugifying the name if the route doesn't follow that shape.
export function deriveBotId(data: Partial<Bot>): string {
  const routeMatch = data.route?.match(/^\/ask\/([a-zA-Z0-9_-]+)\/?$/);
  if (routeMatch) return routeMatch[1];
  return (data.name || "")
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
}

// Maps the flat form fields the Bot Management page collects into the nested
// BotConfig shape the backend requires (app/bots/schema.py). Fields the form
// does not collect (sharepoint.tenant/web.tenant, prompt.temperature,
// indexing chunk sizes, and every WebSourceConfig fetch-etiquette setting -
// user_agent/timeouts/rate-limit/robots/feeds) fall back to the same
// defaults BotConfig itself uses, except `tenant`, which has no safe
// default - see getSharePointTenant() (TEMPORARY dev/production toggle
// above). An admin who needs to tune those specific fetch settings per bot
// still can by hand-editing the YAML - see docs/WEB_SOURCE_BOT.md.
function toBotConfigPayload(botId: string, data: Partial<Bot>) {
  const isWeb = data.contentType === "web";
  return {
    id: botId,
    name: data.name,
    route: data.route,
    enabled: data.enabled ?? true,
    content_type: data.contentType || "library",
    // Mutually exclusive - a web bot sets `web`, never `sharepoint`
    // (app/bots/schema.py's _valid_content_source enforces this server-side
    // too; omitting the unused key here rather than sending an empty one
    // avoids relying on that validator alone to catch a form bug).
    ...(isWeb
      ? {
          web: {
            tenant: getSharePointTenant(),
            site_url: data.webSource?.siteUrl || "",
            source_list: data.webSource?.sourceList || "",
            id_column: data.webSource?.idColumn || "ID",
            url_column: data.webSource?.urlColumn || "URL",
            enable_column: data.webSource?.enableColumn || "Enable",
            enabled_value: data.webSource?.enabledValue || "yes",
            category_column: data.webSource?.categoryColumn || "Category",
          },
        }
      : {
          sharepoint: {
            tenant: getSharePointTenant(),
            sites: (data.sharepointSites || []).map((s) => ({ site_url: s.siteUrl, libraries: s.libraries, lists: s.lists })),
          },
        }),
    vectorstore: {
      collection: data.qdrantCollection || botId,
    },
    models: {
      llm: data.llmModel || "gpt-4o-mini",
      embedding: data.embeddingModel || "bge-base-en-v1.5",
    },
    prompt: {
      system: data.systemPrompt || "You are a helpful assistant.",
      temperature: 0.2,
    },
    indexing: {
      schedule: data.indexingSchedule || "0 2 * * *",
      chunk_size: 800,
      chunk_overlap: 100,
    },
    access: {
      allowed_groups: data.access?.allowed_groups || [],
    },
    response_fields: (data.responseFields || []).map((f) => ({ name: f.name, prompt: f.prompt })),
    include_category: data.includeCategory ?? false,
    sample_questions: (data.sampleQuestions || []).map((q) => q.trim()).filter((q) => q.length > 0),
  };
}

// --- API Methods ---

export const api = {
  async getBots(): Promise<Bot[]> {
    if (USE_MOCKS) {
      return [
        { id: "hr", name: "HR Assistant", route: "/ask/hr", enabled: true, contentType: "library", sharepointSites: [{ siteUrl: "https://contoso.sharepoint.com/sites/hr", libraries: ["HR Docs"], lists: [] }], llmModel: "gpt-4-turbo" },
        { id: "it", name: "IT Helpdesk", route: "/ask/it", enabled: true, contentType: "library", sharepointSites: [{ siteUrl: "https://contoso.sharepoint.com/sites/it", libraries: ["IT Docs"], lists: [] }], llmModel: "gpt-35-turbo" },
        { id: "finance", name: "Finance Policy", route: "/ask/finance", enabled: false, contentType: "library", sharepointSites: [{ siteUrl: "https://contoso.sharepoint.com/sites/finance", libraries: ["Finance Docs"], lists: [] }], llmModel: "gpt-4" },
      ];
    }
    return fetcher<Bot[]>("/admin/bots");
  },

  async reloadBots(): Promise<{ reloaded: number }> {
    if (USE_MOCKS) return { reloaded: 3 };
    return fetcher<{ reloaded: number }>("/admin/bots/reload", { method: "POST" });
  },

  async getAvailableModels(): Promise<AvailableModels> {
    if (USE_MOCKS) {
      return { llm: ["gpt-4o-mini", "gpt-4o"], embedding: ["bge-base-en-v1.5"] };
    }
    // Real deployments on the connected Azure OpenAI resource (app/api/routes/
    // admin.py list_available_models) - replaces the old hardcoded dropdown
    // options, which could reference deployments that don't actually exist.
    return fetcher<AvailableModels>("/admin/models");
  },

  async getIndexStatus(botId?: string): Promise<IndexStatus[]> {
    if (USE_MOCKS) {
      return [
        { bot_id: "hr", documents_indexed: 12, chunks_indexed: 84, last_sync_at: new Date().toISOString(), likes: 8, dislikes: 1 },
        { bot_id: "it", documents_indexed: 5, chunks_indexed: 31, last_sync_at: new Date().toISOString(), likes: 3, dislikes: 0 },
      ];
    }
    // Read live from the vector store (app/api/routes/admin.py index_status) -
    // not persisted in Postgres, so this is always current as of the last sync.
    return fetcher<IndexStatus[]>(`/admin/index-status${buildQuery({ bot_id: botId })}`);
  },

  async getSharePointLibraries(siteUrl: string): Promise<string[]> {
    if (USE_MOCKS) return ["HR Knowledge Base", "Policies", "Onboarding"];
    // Live query against the real SharePoint site (app/api/routes/admin.py
    // sharepoint_libraries) - lets the form offer a real dropdown instead of
    // a free-text field that can silently typo-mismatch the real library name
    // (exactly what broke the hr bot's sync earlier this session).
    return fetcher<string[]>(`/admin/sharepoint/libraries${buildQuery({ site_url: siteUrl, tenant: getSharePointTenant() })}`);
  },

  async getSharePointLists(siteUrl: string): Promise<string[]> {
    if (USE_MOCKS) return ["IT FAQ", "Ticket Categories"];
    // Same idea as getSharePointLibraries, but for genuine SharePoint Lists
    // (app/api/routes/admin.py sharepoint_lists) - powers a List bot's picker.
    return fetcher<string[]>(`/admin/sharepoint/lists${buildQuery({ site_url: siteUrl, tenant: getSharePointTenant() })}`);
  },

  async getChatHistory(params?: { bot_id?: string; user_id?: string; keyword?: string; limit?: number }): Promise<ChatHistoryRow[]> {
    if (USE_MOCKS) {
      return [
        { id: "1", bot_id: "hr", user_id: "alice@contoso.com", user_email: "alice@contoso.com", question: "How many vacation days do I get?", answer: "You have 20 PTO days...", prompt_tokens: 380, completion_tokens: 70, total_tokens: 450, cost_usd: 0.003, response_time_ms: 1200, created_at: new Date().toISOString(), feedback: "like" },
        { id: "2", bot_id: "it", user_id: "bob@contoso.com", user_email: "bob@contoso.com", question: "How to reset VPN?", answer: "Go to the portal and click...", prompt_tokens: 250, completion_tokens: 50, total_tokens: 300, cost_usd: 0.002, response_time_ms: 950, created_at: new Date(Date.now() - 3600000).toISOString(), feedback: null },
        { id: "3", bot_id: "hr", user_id: "charlie@contoso.com", user_email: "charlie@contoso.com", question: "What is the holiday schedule?", answer: "We observe 10 federal holidays...", prompt_tokens: 420, completion_tokens: 80, total_tokens: 500, cost_usd: 0.004, response_time_ms: 1500, created_at: new Date(Date.now() - 86400000).toISOString(), feedback: "dislike" },
      ];
    }
    return fetcher<ChatHistoryRow[]>(`/admin/chat-history${buildQuery(params)}`);
  },

  async getCostByBot(params?: TimeFilterParams): Promise<CostByBot[]> {
    if (USE_MOCKS) {
      return [
        { bot_id: "hr", tokens: 1200000, cost: 45.20, requests: 3400 },
        { bot_id: "it", tokens: 800000, cost: 20.50, requests: 4100 },
        { bot_id: "finance", tokens: 150000, cost: 8.90, requests: 400 },
      ];
    }
    // Note: GET /admin/cost/by-bot does not accept bot_id server-side
    // (app/api/routes/admin.py cost_by_bot only takes period/start/end).
    return fetcher<CostByBot[]>(`/admin/cost/by-bot${buildQuery({ period: params?.period, start: params?.start, end: params?.end })}`);
  },

  async getCostByModel(params?: TimeFilterParams): Promise<CostByModel[]> {
    if (USE_MOCKS) {
      return [
        { model: "gpt-4-turbo", kind: "chat", cost: 60.10, tokens: 1500000, prompt_tokens: 1100000, completion_tokens: 400000 },
        { model: "gpt-35-turbo", kind: "chat", cost: 12.40, tokens: 600000, prompt_tokens: 450000, completion_tokens: 150000 },
        { model: "text-embedding-3-large", kind: "embedding", cost: 2.10, tokens: 50000, prompt_tokens: 50000, completion_tokens: 0 },
      ];
    }
    // Same as by-bot: no bot_id filter on this endpoint server-side.
    return fetcher<CostByModel[]>(`/admin/cost/by-model${buildQuery({ period: params?.period, start: params?.start, end: params?.end })}`);
  },

  async createBot(botData: Partial<Bot>): Promise<Bot> {
    if (USE_MOCKS) return { ...botData, id: botData.id || "new-bot", enabled: true } as Bot;
    const id = botData.id || deriveBotId(botData);
    const payload = toBotConfigPayload(id, botData);
    await fetcher<{ created: string }>("/admin/bots", { method: "POST", body: JSON.stringify(payload) });
    return { ...botData, id, enabled: true } as Bot;
  },

  async updateBot(botId: string, botData: Partial<Bot>): Promise<Bot> {
    if (USE_MOCKS) return { ...botData, id: botId, enabled: true } as Bot;
    const payload = toBotConfigPayload(botId, botData);
    await fetcher<{ updated: string }>(`/admin/bots/${botId}`, { method: "PUT", body: JSON.stringify(payload) });
    return { ...botData, id: botId, enabled: true } as Bot;
  },

  async toggleBotStatus(botId: string, enabled: boolean): Promise<{ success: boolean }> {
    if (USE_MOCKS) return { success: true };
    // PATCH /admin/bots/{id} takes `enabled` as a query param, not a JSON body
    // (app/api/routes/admin.py: def toggle_bot(bot_id: str, enabled: bool)).
    await fetcher<{ bot_id: string; enabled: boolean }>(`/admin/bots/${botId}${buildQuery({ enabled: String(enabled) })}`, { method: "PATCH" });
    return { success: true };
  },

  async deleteBot(botId: string): Promise<{ success: boolean }> {
    if (USE_MOCKS) return { success: true };
    await fetcher<{ deleted: string }>(`/admin/bots/${botId}`, { method: "DELETE" });
    return { success: true };
  },

  // Both run in the background on the API side; the caller polls
  // getIndexStatus() to see doc/chunk counts and last_sync_at update.
  async syncBotNow(botId: string): Promise<{ status: string; bot_id: string }> {
    if (USE_MOCKS) return { status: "sync_started", bot_id: botId };
    return fetcher<{ status: string; bot_id: string }>(`/admin/bots/${botId}/sync`, { method: "POST" });
  },

  async reindexBot(botId: string): Promise<{ status: string; bot_id: string }> {
    if (USE_MOCKS) return { status: "reindex_started", bot_id: botId };
    return fetcher<{ status: string; bot_id: string }>(`/admin/bots/${botId}/reindex`, { method: "POST" });
  },

  async getUsageSummary(params?: TimeFilterParams): Promise<UsageSummary> {
    if (USE_MOCKS) {
      return {
        total_requests: 12450,
        prompt_tokens: 3500000,
        completion_tokens: 850000,
        total_tokens: 4350000,
        estimated_cost: 134.50,
        avg_response_time_ms: 1120,
        active_users: 430,
        documents_indexed: 12400,
        index_size: 45000000 // approx 45MB
      };
    }
    return fetcher<UsageSummary>(`/admin/usage/summary${buildQuery(params)}`);
  },

  async getUsageTrend(params?: { bot_id?: string; granularity?: "day" | "week" | "month"; period?: string; start?: string; end?: string }): Promise<UsageTrend[]> {
    if (USE_MOCKS) {
      const isWeek = params?.granularity === "week";
      const isMonth = params?.granularity === "month";
      const points = isMonth ? 12 : isWeek ? 8 : 14;
      const today = new Date();
      return Array.from({ length: points }).map((_, i) => {
        const d = new Date(today);
        if (isMonth) d.setMonth(today.getMonth() - (points - 1 - i));
        else if (isWeek) d.setDate(today.getDate() - (points - 1 - i) * 7);
        else d.setDate(today.getDate() - (points - 1 - i));

        return {
          period: d.toISOString().split("T")[0],
          requests: Math.floor(Math.random() * 500) + 100,
          tokens: Math.floor(Math.random() * 200000) + 50000,
          cost: Math.random() * 10 + 2
        };
      });
    }
    return fetcher<UsageTrend[]>(`/admin/usage/trend${buildQuery(params)}`);
  },

  async getCostSummary(params?: TimeFilterParams): Promise<CostSummary> {
    if (USE_MOCKS) {
      return {
        total_cost: 210.45, embedding_cost: 30.15, llm_cost: 180.30,
        llm_input_cost: 120.10, llm_output_cost: 60.20,
        input_tokens: 800000, output_tokens: 200000,
      };
    }
    return fetcher<CostSummary>(`/admin/cost/summary${buildQuery(params)}`);
  },

  async getCostByUser(params?: TimeFilterParams): Promise<CostByUser[]> {
    if (USE_MOCKS) {
      return [
        { user_id: "alice@contoso.com", email: "alice@contoso.com", cost: 12.50, tokens: 450000, requests: 120 },
        { user_id: "bob@contoso.com", email: "bob@contoso.com", cost: 8.20, tokens: 300000, requests: 85 },
        { user_id: "charlie@contoso.com", email: "charlie@contoso.com", cost: 4.10, tokens: 150000, requests: 40 },
      ];
    }
    return fetcher<CostByUser[]>(`/admin/cost/by-user${buildQuery(params)}`);
  },

  async getUserAnalytics(params?: TimeFilterParams): Promise<UserAnalytics[]> {
    if (USE_MOCKS) {
      return [
        { user_id: "alice@contoso.com", email: "alice@contoso.com", last_login: new Date().toISOString(), questions_asked: 120, tokens_used: 450000 },
        { user_id: "bob@contoso.com", email: "bob@contoso.com", last_login: new Date(Date.now() - 86400000).toISOString(), questions_asked: 85, tokens_used: 300000 },
      ];
    }
    // GET /admin/users returns { total_users, users: [{ user_id, email,
    // questions_asked, tokens_used, last_activity }] } - not a bare array,
    // and the per-user timestamp field is `last_activity`, not `last_login`.
    const response = await fetcher<{ total_users: number; users: Array<{ user_id: string; email: string | null; questions_asked: number; tokens_used: number; last_activity: string | null }> }>(
      `/admin/users${buildQuery(params)}`
    );
    return response.users.map((u) => ({
      user_id: u.user_id,
      email: u.email || u.user_id,
      last_login: u.last_activity,
      questions_asked: u.questions_asked,
      tokens_used: u.tokens_used,
    }));
  },

  async getLogs(params?: { type?: string; bot_id?: string; period?: string; start?: string; end?: string; limit?: number }): Promise<LogEntry[]> {
    if (USE_MOCKS) {
      return [
        { id: 4, timestamp: new Date().toISOString(), type: "error", bot_id: "hr", message: "Failed to connect to SharePoint site." },
        { id: 3, timestamp: new Date(Date.now() - 3600000).toISOString(), type: "indexing", bot_id: "it", message: "Successfully indexed 45 documents." },
        { id: 2, timestamp: new Date(Date.now() - 7200000).toISOString(), type: "ai", bot_id: "finance", message: "Rate limit exceeded for gpt-4-turbo." },
        { id: 1, timestamp: new Date(Date.now() - 86400000).toISOString(), type: "auth", bot_id: null, message: "Invalid Entra ID token received." },
      ];
    }
    return fetcher<LogEntry[]>(`/admin/logs${buildQuery(params)}`);
  },

  async askAssistant(question: string): Promise<string> {
    if (USE_MOCKS) return `(mock) You asked: "${question}"`;
    const response = await fetcher<{ answer: string }>("/admin/assistant/ask", {
      method: "POST",
      body: JSON.stringify({ question }),
    });
    return response.answer;
  },

  async improveSystemPrompt(prompt: string): Promise<string> {
    if (USE_MOCKS) return `(mock improved)\n\n${prompt}`;
    const response = await fetcher<{ improved_prompt: string }>("/admin/bots/improve-prompt", {
      method: "POST",
      body: JSON.stringify({ prompt }),
    });
    return response.improved_prompt;
  },

  // Exact, no time filter - fetch once on page mount, not on every poll
  // (pg_total_relation_size + Qdrant collection stats are a bit heavy).
  async getStorageByBot(): Promise<StorageByBot[]> {
    if (USE_MOCKS) {
      return [
        {
          botId: "hr", name: "HR Assistant", contentType: "library",
          vectorPoints: 3400, vectorSizeBytes: 3400 * (768 * 4 + 256), vectorSizeIsEstimate: true,
          structuredTables: [], structuredTotalBytes: 0,
          chatRows: 1200, usageRows: 2100,
          totalStorageBytes: 3400 * (768 * 4 + 256),
        },
        {
          botId: "list_test", name: "List Bot Structured-Storage Test", contentType: "list",
          vectorPoints: 200, vectorSizeBytes: 200 * (768 * 4 + 256), vectorSizeIsEstimate: true,
          structuredTables: [
            { listName: "Employee Details", tableName: "lb_list_test__employee_details_5da7467f", rows: 100, sizeBytes: 98304 },
            { listName: "Employee Asset Subtable", tableName: "lb_list_test__employee_asset_subtable_2f5193ef", rows: 100, sizeBytes: 65536 },
          ],
          structuredTotalBytes: 98304 + 65536,
          chatRows: 60, usageRows: 60,
          totalStorageBytes: 200 * (768 * 4 + 256) + 98304 + 65536,
        },
      ];
    }
    return fetcher<StorageByBot[]>("/admin/storage/by-bot");
  },

  // Container/system-level only - never per-bot (see SystemResources doc comment).
  async getResources(): Promise<SystemResources> {
    if (USE_MOCKS) {
      return {
        memory: { usedBytes: 1_400_000_000, limitBytes: 4_000_000_000, pct: 35.0 },
        cpu: { pct: 12.5 },
        disk: { totalBytes: 60_000_000_000, usedBytes: 22_000_000_000, freeBytes: 38_000_000_000, pct: 36.7 },
        process: { rssBytes: 210_000_000, cpuPct: 3.2 },
        containers: null,
        containersAvailable: false,
        source: "cgroup",
        note: "Per-container breakdown needs Docker socket access on the VM - not mounted in this deployment.",
      };
    }
    return fetcher<SystemResources>("/admin/resources");
  },

  async getActivityByBot(params?: TimeFilterParams): Promise<ActivityByBot[]> {
    if (USE_MOCKS) {
      return [
        { botId: "hr", name: "HR Assistant", requests: 3400, tokens: 1200000, cost: 45.20, avgResponseTimeMs: 820, requestsSharePct: 45.3, tokensSharePct: 60.0, costSharePct: 62.3, lastSyncAt: new Date(Date.now() - 3600000).toISOString(), lastSyncStatus: "success" },
        { botId: "it", name: "IT Support Assistant", requests: 4100, tokens: 800000, cost: 20.50, avgResponseTimeMs: 650, requestsSharePct: 54.7, tokensSharePct: 40.0, costSharePct: 37.7, lastSyncAt: new Date(Date.now() - 7200000).toISOString(), lastSyncStatus: "success" },
      ];
    }
    return fetcher<ActivityByBot[]>(`/admin/activity/by-bot${buildQuery({ period: params?.period, start: params?.start, end: params?.end })}`);
  }
};
