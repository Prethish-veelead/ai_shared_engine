"use client";

import { useMsal, useIsAuthenticated } from "@azure/msal-react";
import { InteractionStatus } from "@azure/msal-browser";
import { getApiScope } from "@/lib/msal";
import { Bot, LogOut, UserCircle } from "lucide-react";
import { useEffect, useState } from "react";

export function AppShell({ children }: { children: React.ReactNode }) {
  const { instance, accounts, inProgress } = useMsal();
  const isAuthenticated = useIsAuthenticated();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  // Prevent hydration mismatch by not rendering MSAL dependent UI until mounted
  if (!mounted) return null;

  if (!isAuthenticated || accounts.length === 0) {
    return (
      <div className="flex h-screen flex-col items-center justify-center bg-gray-50">
        <div className="flex flex-col items-center max-w-sm text-center px-4">
          <div className="mb-8 flex h-16 w-16 items-center justify-center rounded-2xl bg-blue-600 text-white shadow-lg">
            <Bot className="h-8 w-8" />
          </div>
          <h1 className="mb-2 text-2xl font-bold text-gray-900">Welcome to HelloBot</h1>
          <p className="mb-8 text-sm text-gray-500">Sign in with your corporate Microsoft account to access the AI assistants.</p>
          <button
            onClick={() => instance.loginRedirect({ scopes: [getApiScope()] }).catch(console.error)}
            disabled={inProgress !== InteractionStatus.None}
            className="w-full rounded-md bg-gray-900 px-4 py-3 text-sm font-semibold text-white shadow-sm hover:bg-gray-800 focus:outline-none disabled:opacity-50"
          >
            {inProgress !== InteractionStatus.None ? "Signing in..." : "Sign in with Microsoft"}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen flex-col bg-white">
      <header className="flex h-14 shrink-0 items-center justify-between border-b px-4 sm:px-6">
        <div className="flex items-center gap-2 font-semibold text-gray-900">
          <Bot className="h-5 w-5 text-blue-600" />
          HelloBot
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 text-sm font-medium text-gray-700">
            <UserCircle className="h-4 w-4 text-gray-400" />
            <span className="hidden sm:inline">{accounts[0].name || accounts[0].username}</span>
          </div>
          <button
            onClick={() => instance.logoutRedirect().catch(console.error)}
            className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-gray-500 hover:bg-gray-100 hover:text-gray-900"
          >
            <LogOut className="h-3.5 w-3.5" />
            Sign Out
          </button>
        </div>
      </header>
      <main className="flex-1 overflow-hidden relative">
        {children}
      </main>
    </div>
  );
}
