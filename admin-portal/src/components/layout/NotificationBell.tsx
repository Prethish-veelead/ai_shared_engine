"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { AlertCircle, Bell, Check } from "lucide-react";
import { api, LogEntry } from "@/lib/api";
import { LOG_TYPE_ICONS, LOG_TYPE_COLORS } from "@/lib/logTypes";
import { cn } from "@/lib/utils";

// Azure-Portal-style bell: polls the SAME event feed the Logs & Monitoring
// page already reads (GET /admin/logs via api.getLogs) - sync start/success/
// failure and resource-threshold alerts all land in EventLog server-side
// (app/workers/sync_scheduler.py, app/monitoring/alerts.py), so this needed
// no new backend read path, just a poller + a small unread-tracking UI.
//
// "Unread" is a purely client-side concept - the highest notification id
// the admin has seen, kept in localStorage (no server-side read/unread
// column, so nothing to migrate and every browser/tab tracks its own).
const POLL_INTERVAL_MS = 15000;
const FETCH_LIMIT = 30;
const LAST_SEEN_KEY = "notif_last_seen_id";

function timeAgo(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function NotificationBell() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [lastSeenId, setLastSeenId] = useState(0);
  const [open, setOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const stored = Number(localStorage.getItem(LAST_SEEN_KEY) || "0");
    setLastSeenId(Number.isFinite(stored) ? stored : 0);
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const data = await api.getLogs({ limit: FETCH_LIMIT });
        if (!cancelled) setLogs(data);
      } catch (error) {
        console.error(error);
      }
    }
    poll();
    const interval = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Once seen (Mark all read), a notification must not show up again - the
  // panel only ever lists what's still unread. Full history (read or not)
  // stays available via the "View all in Logs & Monitoring" link below,
  // that's what the Logs page is for; the bell's job is only "what's new."
  const unreadLogs = logs.filter((l) => l.id > lastSeenId);
  const unreadCount = unreadLogs.length;
  const hasAnyHistory = logs.length > 0;

  function markAllRead() {
    const maxId = logs.reduce((max, l) => Math.max(max, l.id), lastSeenId);
    localStorage.setItem(LAST_SEEN_KEY, String(maxId));
    setLastSeenId(maxId);
  }

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setOpen(!open)}
        className={cn(
          "relative flex h-10 w-10 items-center justify-center rounded-full transition-colors",
          open ? "bg-gray-50 dark:bg-navy-deep" : "hover:bg-gray-50 dark:hover:bg-navy-deep"
        )}
        title="Notifications"
      >
        <Bell className="h-5 w-5 text-gray-500 dark:text-gray-400" />
        {unreadCount > 0 && (
          <span className="absolute top-1.5 right-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-orange px-1 text-[10px] font-bold text-white">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 mt-3 w-96 max-w-[90vw] rounded-2xl bg-white dark:bg-card shadow-2xl ring-1 ring-black/5 dark:ring-white/10 z-50">
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 dark:border-gray-800">
            <span className="text-sm font-bold text-navy dark:text-white">Notifications</span>
            {unreadCount > 0 && (
              <button
                onClick={markAllRead}
                className="flex items-center gap-1 text-xs font-medium text-orange hover:underline"
              >
                <Check className="h-3.5 w-3.5" />
                Mark all read
              </button>
            )}
          </div>

          <div className="max-h-96 overflow-y-auto divide-y divide-gray-100 dark:divide-gray-800">
            {unreadLogs.length === 0 && (
              <p className="px-4 py-6 text-center text-sm text-gray-400 dark:text-gray-500">
                {hasAnyHistory ? "You're all caught up!" : "No notifications yet."}
              </p>
            )}
            {unreadLogs.map((log) => {
              const Icon = LOG_TYPE_ICONS[log.type] || AlertCircle;
              return (
                <div key={log.id} className="flex gap-3 px-4 py-3 bg-orange/5 dark:bg-orange/10">
                  <div className={cn("shrink-0 flex h-8 w-8 items-center justify-center rounded-full", LOG_TYPE_COLORS[log.type] || "text-gray-600 bg-gray-100")}>
                    <Icon className="h-4 w-4" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-navy dark:text-white break-words">{log.message}</p>
                    <div className="mt-0.5 flex items-center gap-2 text-xs text-gray-400 dark:text-gray-500">
                      <span>{timeAgo(log.timestamp)}</span>
                      {log.bot_id && (
                        <span className="rounded bg-gray-100 dark:bg-navy-deep px-1.5 py-0.5 font-medium">{log.bot_id}</span>
                      )}
                    </div>
                  </div>
                  <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-orange" />
                </div>
              );
            })}
          </div>

          <Link
            href="/logs"
            onClick={() => setOpen(false)}
            className="block px-4 py-3 text-center text-xs font-semibold text-orange hover:bg-gray-50 dark:hover:bg-navy-deep border-t border-gray-100 dark:border-gray-800 rounded-b-2xl"
          >
            View all in Logs &amp; Monitoring
          </Link>
        </div>
      )}
    </div>
  );
}
