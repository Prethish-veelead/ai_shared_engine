"use client";

import { useState, useRef, useEffect } from "react";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { LogOut, LogIn, ChevronDown, Sun, Moon, Monitor } from "lucide-react";
import { useMsal, useIsAuthenticated } from "@azure/msal-react";
import { getApiScope } from "@/lib/msal";
import { cn, getInitials } from "@/lib/utils";
import { NotificationBell } from "./NotificationBell";

const ROUTE_TITLES: Record<string, string> = {
  "/": "Dashboard Overview",
  "/assistant": "Admin Assistant",
  "/bots": "Bot Management",
  "/usage": "Usage Analytics",
  "/cost": "Cost Analysis",
  "/users": "User Analytics",
  "/history": "Chat History",
  "/logs": "Logs & Monitoring"
};

export function Header() {
  const { instance, accounts } = useMsal();
  const isAuthenticated = useIsAuthenticated();
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const pathname = usePathname();
  const { theme, setTheme } = useTheme();

  const account = accounts[0];
  const pageTitle = ROUTE_TITLES[pathname] || "Admin Portal";

  const handleLogin = () => {
    instance.loginRedirect({ scopes: [getApiScope()] }).catch(console.error);
  };

  const handleLogout = () => {
    instance.logoutRedirect().catch(console.error);
  };

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <header className="flex h-20 shrink-0 items-center justify-between border-b border-gray-200 dark:border-navy-deep bg-white dark:bg-navy px-8 shadow-sm z-10">
      <div className="flex-1">
        {/* Dynamic Page Title */}
        <h2 className="text-xl font-bold tracking-tight text-navy dark:text-white">{pageTitle}</h2>
      </div>
      <div className="flex items-center space-x-4">
        {isAuthenticated && account && <NotificationBell />}
        {isAuthenticated && account ? (
          <div className="relative" ref={dropdownRef}>
            <button
              onClick={() => setDropdownOpen(!dropdownOpen)}
              className={cn(
                "flex items-center gap-3 rounded-full py-1.5 pl-2 pr-4 transition-all duration-200 ease-in-out border",
                dropdownOpen 
                  ? "bg-gray-50 dark:bg-navy-deep border-gray-200 dark:border-navy shadow-inner" 
                  : "bg-white dark:bg-navy border-gray-100 dark:border-navy-deep hover:bg-gray-50 dark:hover:bg-navy-deep hover:border-gray-200 shadow-sm"
              )}
            >
              <div className="flex h-9 w-9 items-center justify-center rounded-full bg-navy dark:bg-accent text-sm font-semibold text-white shadow-sm ring-2 ring-white dark:ring-navy-deep">
                {getInitials(account.name || account.username)}
              </div>
              <div className="flex flex-col items-start hidden sm:flex">
                <span className="text-sm font-bold text-navy dark:text-white leading-tight">
                  {account.name || account.username.split("@")[0]}
                </span>
                <span className="text-xs font-medium text-gray-500 dark:text-gray-400 leading-tight">Administrator</span>
              </div>
              <ChevronDown className={cn("h-4 w-4 text-gray-400 dark:text-gray-500 transition-transform ml-1", dropdownOpen && "rotate-180")} />
            </button>

            {dropdownOpen && (
              <div className="absolute right-0 mt-3 w-72 rounded-2xl bg-white dark:bg-card p-2 shadow-2xl ring-1 ring-black/5 dark:ring-white/10 z-50 transform opacity-100 scale-100 transition-all duration-200">
                <div className="flex flex-col items-center gap-3 p-6 border-b border-gray-100 dark:border-gray-800">
                  <div className="flex h-16 w-16 items-center justify-center rounded-full bg-navy dark:bg-navy-deep text-2xl font-bold text-white shadow-inner">
                     {getInitials(account.name || account.username)}
                  </div>
                  <div className="flex flex-col items-center text-center min-w-0">
                    <span className="text-base font-bold text-navy dark:text-white w-full truncate">
                      {account.name || "Admin User"}
                    </span>
                    <span className="text-sm text-gray-500 dark:text-gray-400 w-full truncate">
                      {account.username}
                    </span>
                  </div>
                </div>
                <div className="p-2 border-b border-gray-100 dark:border-gray-800">
                  <div className="flex items-center justify-between px-2 py-1 mb-1">
                    <span className="text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wider">Theme</span>
                  </div>
                  <div className="flex items-center gap-1 bg-gray-50 dark:bg-navy-deep p-1 rounded-xl">
                    <button 
                      onClick={() => setTheme("light")}
                      className={cn("flex-1 flex justify-center py-1.5 rounded-lg transition-colors", theme === "light" ? "bg-white dark:bg-card shadow-sm text-navy dark:text-white" : "text-gray-400 hover:text-gray-600 dark:hover:text-white")}
                      title="Light Mode"
                    >
                      <Sun className="h-4 w-4" />
                    </button>
                    <button 
                      onClick={() => setTheme("system")}
                      className={cn("flex-1 flex justify-center py-1.5 rounded-lg transition-colors", theme === "system" ? "bg-white dark:bg-card shadow-sm text-navy dark:text-white" : "text-gray-400 hover:text-gray-600 dark:hover:text-white")}
                      title="System Settings"
                    >
                      <Monitor className="h-4 w-4" />
                    </button>
                    <button 
                      onClick={() => setTheme("dark")}
                      className={cn("flex-1 flex justify-center py-1.5 rounded-lg transition-colors", theme === "dark" ? "bg-white dark:bg-card shadow-sm text-navy dark:text-white" : "text-gray-400 hover:text-gray-600 dark:hover:text-white")}
                      title="Dark Mode"
                    >
                      <Moon className="h-4 w-4" />
                    </button>
                  </div>
                </div>
                <div className="p-2 mt-1">
                  <button
                    onClick={handleLogout}
                    className="flex w-full items-center justify-center gap-2 rounded-xl bg-gray-50 dark:bg-navy-deep/50 px-4 py-2.5 text-sm font-semibold text-gray-700 dark:text-gray-300 hover:bg-rose-50 dark:hover:bg-rose-500/10 hover:text-rose-600 dark:hover:text-rose-400 transition-colors"
                  >
                    <LogOut className="h-4 w-4" />
                    Sign Out
                  </button>
                </div>
              </div>
            )}
          </div>
        ) : (
          <button
            onClick={handleLogin}
            className="flex items-center gap-2 rounded-full border border-orange bg-orange px-5 py-2 text-sm font-semibold text-white shadow-md hover:bg-orange-hover transition-all"
          >
            <LogIn className="h-4 w-4" />
            <span>Sign In</span>
          </button>
        )}
      </div>
    </header>
  );
}
