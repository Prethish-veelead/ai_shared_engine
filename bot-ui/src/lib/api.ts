import { acquireApiToken } from "./msal";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "/api";

export interface Citation {
  index: number;
  source: string;
  page: number | null;
  url: string | null;
}

export interface ChartSpec {
  type: "bar" | "pie" | "line" | "none";
  labels?: string[];
  values?: number[];
}

export interface AskResponse {
  answer: string;
  citations: Citation[];
  model: string;
  total_tokens: number;
  cost_usd: number;
  response_time_ms: number;
  chat_log_id: number;
  // Both optional and bot-specific: only present when a bot's config
  // (app/bots/schema.py's response_fields) defines a field with exactly
  // this name - see docs on how to configure either one.
  follow_up_questions?: string[];
  chart?: ChartSpec;
}

export interface Bot {
  id: string;
  name: string;
  route: string;
  enabled: boolean;
  // Optional: a backend that predates this field (or is mid-rollout) simply
  // omits it - never assume it's present.
  sample_questions?: string[];
}

// Temporary, non-persisted conversation continuity (docs/CHAT_SESSIONS.md):
// held in browser memory only (see the chat page's `messages` state) and
// resent with each call - never written to localStorage/sessionStorage, and
// never anything but plain text (no tool-call internals ever cross the wire).
export interface HistoryTurn {
  role: "user" | "assistant";
  content: string;
}

async function authFetch(url: string, options: RequestInit = {}): Promise<Response> {
  const token = typeof window !== "undefined" ? await acquireApiToken() : null;
  const headers = new Headers(options.headers);
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  } else {
    console.warn(`authFetch: sending ${url} without a Bearer token`);
  }
  return fetch(url, { ...options, headers });
}

// Shared response handling so every call gets the same 401/403 treatment -
// getBots() used to skip this and just throw a generic "Failed to fetch
// bots" on any non-2xx, silently swallowing an expired-token case that
// askBot() already handled correctly (retry-silent, then a single guarded
// interactive redirect; dispatch bot-forbidden on 403).
async function handleResponse<T>(response: Response): Promise<T> {
  if (response.status === 401) {
    // Do NOT blindly call loginRedirect() here - acquireApiToken() already
    // tries silently first and only starts a single guarded interactive
    // redirect if silent acquisition genuinely requires it. Calling
    // loginRedirect() unconditionally on every 401 is what caused the
    // interaction_in_progress loop.
    if (typeof window !== "undefined") {
      acquireApiToken().catch(console.error);
    }
    throw new Error("Unauthorized");
  }

  if (response.status === 403) {
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("bot-forbidden"));
    }
    throw new Error("Forbidden - No access to this bot");
  }

  if (!response.ok) {
    // Backend errors come back as {"error": {"code", "message"}} - see
    // ai-search-engine/app/api/error_handlers.py.
    let message = response.statusText;
    try {
      const body = await response.json();
      message = body?.error?.message || message;
    } catch {
      // response had no JSON body
    }
    throw new Error(`API call failed: ${message}`);
  }

  return response.json();
}

export const api = {
  getBots: async (): Promise<Bot[]> => {
    const response = await authFetch(`${API_BASE}/bots`);
    return handleResponse<Bot[]>(response);
  },

  askBot: async (botId: string, question: string, history: HistoryTurn[] = []): Promise<AskResponse> => {
    const response = await authFetch(`${API_BASE}/ask/${botId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, history }),
    });
    return handleResponse<AskResponse>(response);
  },

  // Optional: nothing else about /ask changes if this is never called.
  // comment is dislike-only ("Learning loop") - ignored by the backend for "like".
  sendFeedback: async (botId: string, chatLogId: number, feedback: "like" | "dislike", comment?: string): Promise<void> => {
    const response = await authFetch(`${API_BASE}/ask/${botId}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_log_id: chatLogId, feedback, comment }),
    });
    await handleResponse<{ chat_log_id: number; feedback: string }>(response);
  }
};
