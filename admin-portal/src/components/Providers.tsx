"use client";

import { MsalProvider, useMsal } from "@azure/msal-react";
import { InteractionStatus } from "@azure/msal-browser";
import { msalInstance } from "@/lib/msal";
import { createContext, useState, useContext, ReactNode, useEffect } from "react";
import { DotLottiePlayer } from "@dotlottie/react-player";
import "@dotlottie/react-player/dist/index.css";
import { BASE_PATH } from "@/lib/basePath";

import { ThemeProvider } from "next-themes";

// Context to track 403 Forbidden states globally
interface AuthErrorContextType {
  isForbidden: boolean;
  setForbidden: (val: boolean) => void;
}

const AuthErrorContext = createContext<AuthErrorContextType>({
  isForbidden: false,
  setForbidden: () => {},
});

export const useAuthError = () => useContext(AuthErrorContext);

// MsalProvider itself awaits instance.initialize() + handleRedirectPromise()
// before inProgress settles to "none" (see msal-react's MsalProvider source),
// but it renders children immediately regardless of that state. Without this
// gate, pages mount and fire API calls while the redirect handshake is still
// being processed - before there's an account or a usable token - which is
// what was causing the 401 -> loginRedirect -> interaction_in_progress loop.
function AuthGate({ children }: { children: ReactNode }) {
  const { inProgress } = useMsal();

  if (inProgress !== InteractionStatus.None) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-background text-sm text-gray-500 dark:text-gray-400">
        Loading…
      </div>
    );
  }

  return <>{children}</>;
}

export function Providers({ children }: { children: ReactNode }) {
  const [isForbidden, setForbidden] = useState(false);

  useEffect(() => {
    const handleForbidden = () => setForbidden(true);
    window.addEventListener("admin-forbidden", handleForbidden);
    return () => window.removeEventListener("admin-forbidden", handleForbidden);
  }, []);

  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
      <MsalProvider instance={msalInstance}>
        <AuthErrorContext.Provider value={{ isForbidden, setForbidden }}>
          <AuthGate>{children}</AuthGate>
          {isForbidden && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
              <div className="mx-4 max-w-md rounded-lg bg-white dark:bg-card p-6 shadow-xl text-center">
                <div className="mx-auto mb-2 h-40 w-40">
                  <DotLottiePlayer src={`${BASE_PATH}/Error.json`} autoplay loop className="w-full h-full object-contain" />
                </div>
                <p className="mb-6 text-sm font-medium text-gray-500 dark:text-gray-400">
                  You don&apos;t have access. Please contact admin.
                </p>
                <button
                  onClick={() => setForbidden(false)}
                  className="w-full rounded-md bg-gray-900 dark:bg-gray-100 px-4 py-2 text-sm font-medium text-white dark:text-gray-900 hover:bg-gray-800 dark:hover:bg-white"
                >
                  Dismiss
                </button>
              </div>
            </div>
          )}
        </AuthErrorContext.Provider>
      </MsalProvider>
    </ThemeProvider>
  );
}
