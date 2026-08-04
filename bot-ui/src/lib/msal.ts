import {
  Configuration,
  EventType,
  InteractionRequiredAuthError,
  InteractionType,
  PublicClientApplication,
} from "@azure/msal-browser";

export const msalConfig: Configuration = {
  auth: {
    clientId: process.env.NEXT_PUBLIC_ENTRA_CLIENT_ID || "",
    authority: `https://login.microsoftonline.com/${process.env.NEXT_PUBLIC_ENTRA_TENANT_ID || "common"}`,
    redirectUri: typeof window !== "undefined" ? window.location.origin : "/",
  },
  cache: {
    cacheLocation: "sessionStorage",
  },
};

export const msalInstance = new PublicClientApplication(msalConfig);

export const getApiScope = () => process.env.NEXT_PUBLIC_API_SCOPE || "";

// MsalProvider (see Providers.tsx) already calls instance.initialize() and
// awaits handleRedirectPromise() before it reports inProgress === "none", so
// nothing here needs to duplicate that. What MSAL does NOT do for us:
// 1) set an active account once a login/redirect completes, and
// 2) give plain (non-React) code like the api.ts fetcher a way to know
//    whether an interactive request is already underway, so it doesn't fire
//    a second one and trigger BrowserAuthError: interaction_in_progress.
if (typeof window !== "undefined") {
  msalInstance.addEventCallback((event) => {
    if (
      (event.eventType === EventType.LOGIN_SUCCESS ||
        event.eventType === EventType.ACQUIRE_TOKEN_SUCCESS) &&
      event.payload &&
      "account" in event.payload &&
      event.payload.account
    ) {
      msalInstance.setActiveAccount(event.payload.account);
    }
  });
}

const INTERACTION_START_EVENTS: string[] = [
  EventType.ACQUIRE_TOKEN_START,
  EventType.HANDLE_REDIRECT_START,
];
const INTERACTION_END_EVENTS: string[] = [
  EventType.ACQUIRE_TOKEN_SUCCESS,
  EventType.ACQUIRE_TOKEN_FAILURE,
  EventType.HANDLE_REDIRECT_END,
];

let interactionInProgress = false;
if (typeof window !== "undefined") {
  msalInstance.addEventCallback((event) => {
    // ACQUIRE_TOKEN_START/SUCCESS/FAILURE fire for acquireTokenSilent() too,
    // not just interactive redirects - event.eventType alone can't tell them
    // apart. Without this interactionType check, a background silent token
    // refresh from one caller could flip this flag off (or on) while a
    // genuinely separate interactive redirect from another caller is still
    // pending, letting two acquireTokenRedirect() calls race and throw
    // interaction_in_progress - exactly what this flag exists to prevent.
    // HANDLE_REDIRECT_START/END don't carry a meaningful interactionType
    // (they fire once at startup for the redirect-return handshake), so
    // those are always tracked regardless.
    const isRedirectInteraction =
      event.interactionType === InteractionType.Redirect ||
      event.eventType === EventType.HANDLE_REDIRECT_START ||
      event.eventType === EventType.HANDLE_REDIRECT_END;
    if (!isRedirectInteraction) return;

    if (INTERACTION_START_EVENTS.includes(event.eventType)) {
      interactionInProgress = true;
    } else if (INTERACTION_END_EVENTS.includes(event.eventType)) {
      interactionInProgress = false;
    }
  });
}

// Silent-first token acquisition for API calls. Only falls back to an
// interactive redirect when silent acquisition genuinely requires it
// (InteractionRequiredAuthError), and only if no other interactive request
// (login or token redirect) is already in flight - firing a second one while
// one is pending is exactly what throws interaction_in_progress.
export async function acquireApiToken(): Promise<string | null> {
  const account = msalInstance.getActiveAccount() || msalInstance.getAllAccounts()[0];
  if (!account) {
    console.warn("acquireApiToken: no signed-in account yet; request will be sent without a token");
    return null;
  }

  const scopes = [getApiScope()];
  try {
    const result = await msalInstance.acquireTokenSilent({ scopes, account });
    return result.accessToken;
  } catch (error) {
    if (error instanceof InteractionRequiredAuthError) {
      if (interactionInProgress) {
        console.warn("acquireApiToken: interaction already in progress, not starting another redirect");
        return null;
      }
      // Single guarded interactive fallback - this navigates away, so there
      // is no token to return from this call.
      await msalInstance.acquireTokenRedirect({ scopes, account });
      return null;
    }
    console.warn("acquireApiToken: silent token acquisition failed", error);
    return null;
  }
}
