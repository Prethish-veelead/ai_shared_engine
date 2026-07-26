"use client";

import { useEffect, useState } from "react";
import { api, LogEntry } from "@/lib/api";
import { useAuthReady } from "@/lib/useAuthReady";
import { format } from "date-fns";
import { cn } from "@/lib/utils";
import { AlertCircle, FileWarning, RefreshCw, Zap, ShieldAlert } from "lucide-react";

const typeIcons = {
  error: AlertCircle,
  sync: RefreshCw,
  auth: ShieldAlert,
  ai: Zap,
  indexing: FileWarning,
};

const typeColors = {
  error: "text-red-600 bg-red-50",
  sync: "text-blue-600 bg-blue-50",
  auth: "text-orange-600 bg-orange-50",
  ai: "text-purple-600 bg-purple-50",
  indexing: "text-yellow-600 bg-yellow-50",
};

export default function LogsPage() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const authReady = useAuthReady();

  useEffect(() => {
    if (!authReady) return;
    async function loadData() {
      try {
        const data = await api.getLogs();
        setLogs(data);
      } catch (error) {
        console.error(error);
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, [authReady]);

  if (loading) return <div className="flex h-full items-center justify-center">Loading logs...</div>;

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-gray-900">Logs & Monitoring</h1>
          <p className="text-sm text-gray-500">System events, sync status, and errors.</p>
        </div>
        <select className="rounded-md border border-gray-300 px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500">
          <option value="">All Types</option>
          <option value="error">Errors</option>
          <option value="sync">SharePoint Sync</option>
          <option value="auth">Auth</option>
          <option value="ai">AI / Rate Limits</option>
          <option value="indexing">Indexing</option>
        </select>
      </div>

      <div className="rounded-lg border bg-white shadow-sm overflow-hidden">
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
                    <p className="text-sm font-medium text-gray-900 capitalize">{log.type} Event</p>
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
