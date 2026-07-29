"use client";

import { useEffect, useState } from "react";
import { api, Bot, LogEntry } from "@/lib/api";
import { useAuthReady } from "@/lib/useAuthReady";
import { format } from "date-fns";
import { cn } from "@/lib/utils";
import { AlertCircle, FileWarning, RefreshCw, Zap, ShieldAlert, RotateCw } from "lucide-react";

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
  const authReady = useAuthReady();

  async function loadLogs(isRefresh = false) {
    if (isRefresh) setRefreshing(true);
    try {
      const data = await api.getLogs({ type: filterType || undefined, bot_id: filterBotId || undefined });
      setLogs(data);
    } catch (error) {
      console.error(error);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => {
    if (!authReady) return;
    loadLogs();
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
          <h1 className="text-2xl font-bold tracking-tight text-navy">Logs & Monitoring</h1>
          <p className="text-sm text-gray-500">System events, sync status, and errors.</p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={filterBotId}
            onChange={(e) => setFilterBotId(e.target.value)}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-orange"
          >
            <option value="">All Bots</option>
            {bots.map((b) => (
              <option key={b.id} value={b.id}>{b.name}</option>
            ))}
          </select>
          <select
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-orange"
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
            className="flex items-center gap-2 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            <RotateCw className={cn("h-4 w-4", refreshing && "animate-spin")} />
            Refresh
          </button>
        </div>
      </div>

      <div className="rounded-lg border bg-white shadow-sm overflow-hidden">
        {logs.length === 0 && (
          <p className="p-6 text-center text-sm text-gray-500">No logs match the current filters.</p>
        )}
        <ul className="divide-y divide-gray-200">
          {logs.map((log, idx) => {
            const Icon = typeIcons[log.type] || AlertCircle;
            return (
              <li key={idx} className="p-4 hover:bg-gray-50 flex items-start gap-4">
                <div className={cn("p-2 rounded-full", typeColors[log.type])}>
                  <Icon className="h-5 w-5" />
                </div>
                <div className="flex-1">
                  <div className="flex items-center justify-between">
                    <p className="text-sm font-medium text-navy capitalize">{log.type} Event</p>
                    <p className="text-xs text-gray-500">{format(new Date(log.timestamp), "MMM d, yyyy HH:mm:ss")}</p>
                  </div>
                  <p className="text-sm text-gray-700 mt-1">{log.message}</p>
                  {log.bot_id && (
                    <p className="text-xs text-gray-500 mt-1">Target Bot: {log.bot_id}</p>
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
