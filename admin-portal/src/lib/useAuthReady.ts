"use client";

import { useMsal, useIsAuthenticated } from "@azure/msal-react";
import { InteractionStatus } from "@azure/msal-browser";

// True once MSAL has finished processing any redirect/interaction AND there
// is a signed-in account. Data-fetching effects should gate on this instead
// of firing on mount - calling the API before this is true is what produced
// 401s during the redirect handshake and triggered the login loop.
export function useAuthReady(): boolean {
  const { inProgress, accounts } = useMsal();
  const isAuthenticated = useIsAuthenticated();
  return inProgress === InteractionStatus.None && isAuthenticated && accounts.length > 0;
}
