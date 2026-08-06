"use client";

import { useMsal, useIsAuthenticated } from "@azure/msal-react";
import { InteractionStatus } from "@azure/msal-browser";
import { LogIn } from "lucide-react";
import { DotLottiePlayer } from "@dotlottie/react-player";
import "@dotlottie/react-player/dist/index.css";
import { getApiScope } from "@/lib/msal";
import { BASE_PATH } from "@/lib/basePath";

// Gates PAGE CONTENT (not the Sidebar/Header shell, which already shows its
// own "Sign In" button) behind a real signed-in check. Providers.tsx's
// AuthGate only waits for MSAL's redirect handshake to settle - it renders
// children regardless of whether anyone is actually signed in, which is what
// let every page (e.g. /assistant) fully render for an anonymous visitor.
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { instance, inProgress } = useMsal();
  const isAuthenticated = useIsAuthenticated();

  // Mid-redirect: Providers.tsx's outer AuthGate already shows a loading
  // screen for this state, so render nothing here rather than flashing the
  // sign-in prompt for a moment.
  if (inProgress !== InteractionStatus.None) {
    return null;
  }

  if (!isAuthenticated) {
    return (
      <div className="flex h-full min-h-[60vh] flex-col items-center justify-center gap-4 text-center">
        <div className="h-48 w-48">
          <DotLottiePlayer src={`${BASE_PATH}/login.json`} autoplay loop className="w-full h-full object-contain" />
        </div>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Sign in to view this page.
        </p>
        <button
          onClick={() => instance.loginRedirect({ scopes: [getApiScope()] }).catch(console.error)}
          className="flex items-center gap-2 rounded-full border border-orange bg-orange px-5 py-2 text-sm font-semibold text-white shadow-md hover:bg-orange-hover transition-all"
        >
          <LogIn className="h-4 w-4" />
          Sign In
        </button>
      </div>
    );
  }

  return <>{children}</>;
}
