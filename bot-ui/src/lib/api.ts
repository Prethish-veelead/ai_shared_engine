import { acquireApiToken } from "./msal";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "/api";

export interface Citation {
  index: number;
  source: string;
  page: number | null;
}

export interface AskResponse {
  answer: string;
  citations: Citation[];
  model: string;
  total_tokens: number;
  cost_usd: number;
  response_time_ms: number;
}

export const api = {
  askBot: async (botId: string, question: string): Promise<AskResponse> => {
    const url = `${API_BASE}/ask/${botId}`;
    const token = typeof window !== "undefined" ? await acquireApiToken() : null;

    const headers: HeadersInit = {
      "Content-Type": "application/json",
    };

    if (token) {
      (headers as Record<string, string>)["Authorization"] = `Bearer ${token}`;
    } else {
      console.warn("askBot: sending request without a Bearer token");
    }

    const response = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify({ question }),
    });

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
};
