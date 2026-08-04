"use client";

import { useEffect, useState } from "react";
import { api, Bot, LogEntry } from "@/lib/api";
import { useAuthReady } from "@/lib/useAuthReady";
import { format } from "date-fns";
import { cn } from "@/lib/utils";
import { AlertCircle, FileWarning, RefreshCw, Zap, ShieldAlert, RotateCw } from "lucide-react";

const POLL_INTERVAL_MS = 60000;

const typeIcons = {
  error: AlertCircle,
  sync: RefreshCw,
  auth: ShieldAlert,
  ai: Zap,
  indexing: FileWarning,
};

const typeColors = {
  error: "text-red-600 bg-red-50",
  sync: "text-blue-600 bg-info",
  auth: "text-orange-600 bg-warning",
  ai: "text-purple-600 bg-warning",
  indexing: "text-yellow-600 bg-warning",
};

export default function LogsPage() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [bots, setBots] = useState<Bot[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filterType, setFilterType] = useState("");
  const [filterBotId, setFilterBotId] = useState("");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const authReady = useAuthReady();

  async function loadLogs(isRefresh = false) {
    if (isRefresh) setRefreshing(true);
    try {
      const data = await api.getLogs({ type: filterType || undefined, bot_id: filterBotId || undefined });
      setLogs(data);
      setLastUpdated(new Date());
    } catch (error) {
      console.error(error);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  // Auto-poll so new events/errors show up without a manual refresh. Fetches
  // immediately (mount or filter change), then every POLL_INTERVAL_MS after -
  // background ticks call loadLogs() with isRefresh=false so they update
  // silently instead of spinning the manual Refresh button on every tick.
  // The interval is torn down and recreated whenever filters change, so it
  // never polls with stale filter values.
  useEffect(() => {
    if (!authReady) return;
    loadLogs();
    const interval = setInterval(() => loadLogs(), POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [authReady, filterType, filterBotId]);

  useEffect(() => {
    if (!authReady) return;
    api.getBots().then(setBots).catch((error) => console.error("Failed to load bots", error));
  }, [authReady]);

  if (loading) return <div className="flex h-full items-center justify-center">Loading logs...</div>;

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-navy dark:text-white">Logs & Monitoring</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">System events, sync status, and errors.</p>
          <div className="mt-1 flex items-center gap-1.5 text-xs text-gray-400 dark:text-gray-500">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
            </span>
            <span>
              Live - updates every {POLL_INTERVAL_MS / 1000}s
              {lastUpdated && ` - last updated ${format(lastUpdated, "HH:mm:ss")}`}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={filterBotId}
            onChange={(e) => setFilterBotId(e.target.value)}
            className="rounded-md border border-gray-300 dark:border-navy-deep px-3 py-1.5 text-sm bg-white dark:bg-card dark:text-white focus:outline-none focus:ring-2 focus:ring-orange"
          >
            <option value="">All Bots</option>
            {bots.map((b) => (
              <option key={b.id} value={b.id}>{b.name}</option>
            ))}
          </select>
          <select
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
            className="rounded-md border border-gray-300 dark:border-navy-deep px-3 py-1.5 text-sm bg-white dark:bg-card dark:text-white focus:outline-none focus:ring-2 focus:ring-orange"
          >
            <option value="">All Types</option>
            <option value="error">Errors</option>
            <option value="sync">SharePoint Sync</option>
            <option value="auth">Auth</option>
            <option value="ai">AI / Rate Limits</option>
            <option value="indexing">Indexing</option>
          </select>
          <button
            onClick={() => loadLogs(true)}
            disabled={refreshing}
            title="Refresh Logs"
            className="flex items-center gap-2 rounded-md border border-gray-300 dark:border-navy-deep bg-white dark:bg-card px-3 py-1.5 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-navy-deep/30 disabled:opacity-50"
          >
            <RotateCw className={cn("h-4 w-4", refreshing && "animate-spin")} />
            Refresh
          </button>
        </div>
      </div>

      <div className="rounded-lg border border-gray-200 dark:border-navy-deep bg-white dark:bg-card shadow-sm overflow-hidden">
        {logs.length === 0 && (
          <p className="p-6 text-center text-sm text-gray-500 dark:text-gray-400">No logs match the current filters.</p>
        )}
        <ul className="divide-y divide-gray-200 dark:divide-navy-deep">
          {logs.map((log, idx) => {
            const Icon = typeIcons[log.type] || AlertCircle;
            return (
              <li key={idx} className="p-4 hover:bg-gray-50 dark:hover:bg-navy-deep/30 flex items-start gap-4">
                <div className={cn("p-2 rounded-full", typeColors[log.type])}>
                  <Icon className="h-5 w-5" />
                </div>
                <div className="flex-1">
                  <div className="flex items-center justify-between">
                    <p className="text-sm font-medium text-navy dark:text-white capitalize">{log.type} Event</p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">{format(new Date(log.timestamp), "MMM d, yyyy HH:mm:ss")}</p>
                  </div>
                  <p className="text-sm text-gray-700 dark:text-gray-300 mt-1">{log.message}</p>
                  {log.bot_id && (
                    <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Target Bot: {log.bot_id}</p>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
