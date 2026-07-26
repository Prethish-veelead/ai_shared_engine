"use client";

import { UserCircle, LogOut, LogIn } from "lucide-react";
import { useMsal, useIsAuthenticated } from "@azure/msal-react";
import { getApiScope } from "@/lib/msal";

export function Header() {
  const { instance, accounts } = useMsal();
  const isAuthenticated = useIsAuthenticated();

  const handleLogin = () => {
    instance.loginRedirect({ scopes: [getApiScope()] }).catch(console.error);
  };

  const handleLogout = () => {
    instance.logoutRedirect().catch(console.error);
  };

  return (
    <header className="flex h-16 shrink-0 items-center justify-between border-b bg-white px-6">
      <div className="flex-1">
        {/* Placeholder for global search or breadcrumbs if needed */}
      </div>
      <div className="flex items-center space-x-4">
        {isAuthenticated && accounts.length > 0 ? (
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2 text-sm font-medium text-gray-700">
              <UserCircle className="h-5 w-5 text-blue-600" />
              <span>{accounts[0].name || accounts[0].username}</span>
            </div>
            <button
              onClick={handleLogout}
              className="flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium text-gray-500 hover:bg-gray-50 hover:text-gray-900 transition-colors"
            >
              <LogOut className="h-4 w-4" />
              Sign Out
            </button>
          </div>
        ) : (
          <button
            onClick={handleLogin}
            className="flex items-center gap-2 rounded-full border border-blue-600 bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
          >
            <LogIn className="h-4 w-4" />
            <span>Sign In (Entra ID)</span>
          </button>
        )}
      </div>
    </header>
  );
}
