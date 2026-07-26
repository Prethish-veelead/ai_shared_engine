"use client";

import { useEffect, useState } from "react";
import { api, ChatHistoryRow, Bot } from "@/lib/api";
import { useAuthReady } from "@/lib/useAuthReady";
import { Search } from "lucide-react";
import { format } from "date-fns";
import { cn } from "@/lib/utils";

const AVATAR_COLORS = [
  "bg-blue-100 text-blue-700",
  "bg-emerald-100 text-emerald-700",
  "bg-amber-100 text-amber-700",
  "bg-rose-100 text-rose-700",
  "bg-violet-100 text-violet-700",
  "bg-cyan-100 text-cyan-700",
];

const BOT_COLORS = [
  "bg-blue-50 text-blue-700 ring-blue-700/10",
  "bg-emerald-50 text-emerald-700 ring-emerald-700/10",
  "bg-amber-50 text-amber-700 ring-amber-700/10",
  "bg-violet-50 text-violet-700 ring-violet-700/10",
];

// Simple string hash so the same user/bot always gets the same color, without
// needing a lookup table that would drift out of sync with bots.yaml.
function colorFor(key: string, palette: string[]) {
  let hash = 0;
  for (let i = 0; i < key.length; i++) hash = (hash * 31 + key.charCodeAt(i)) | 0;
  return palette[Math.abs(hash) % palette.length];
}

function initialsFor(label: string) {
  const local = label.split("@")[0];
  const parts = local.split(/[.\s_-]+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return local.slice(0, 2).toUpperCase();
}

export default function HistoryPage() {
  const [history, setHistory] = useState<ChatHistoryRow[]>([]);
  const [bots, setBots] = useState<Bot[]>([]);
  const [loading, setLoading] = useState(true);
  const authReady = useAuthReady();

  useEffect(() => {
    if (!authReady) return;
    async function loadData() {
      try {
        const [hist, bts] = await Promise.all([
          api.getChatHistory(),
          api.getBots()
        ]);
        setHistory(hist);
        setBots(bts);
      } catch (error) {
        console.error(error);
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, [authReady]);

  if (loading) return <div className="flex h-full items-center justify-center">Loading chat history...</div>;

  const botName = (botId: string) => bots.find(b => b.id === botId)?.name ?? botId;

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-gray-900">Chat History</h1>
          <p className="text-sm text-gray-500">Search and audit conversations across bots.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-gray-400" />
            <input
              type="text"
              placeholder="Search keyword..."
              className="pl-9 rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <select className="rounded-md border border-gray-300 px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="">All Bots</option>
            {bots.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </div>
      </div>

      <div className="rounded-lg border bg-white shadow-sm overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Timestamp</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">User</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase w-1/2">Conversation</th>
              <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">Metrics</th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {history.map((row) => {
              const label = row.user_email || row.user_id;
              return (
                <tr key={row.id} className="hover:bg-gray-50 align-top">
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    {format(new Date(row.created_at), "MMM d, HH:mm")}
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <div className={cn("flex-shrink-0 h-8 w-8 flex items-center justify-center rounded-full text-xs font-semibold", colorFor(label, AVATAR_COLORS))}>
                        {initialsFor(label)}
                      </div>
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-gray-900 truncate" title={label}>{label}</div>
                        <span className={cn("mt-1 inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset", colorFor(row.bot_id, BOT_COLORS))}>
                          {botName(row.bot_id)}
                        </span>
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <div className="text-sm font-medium text-gray-900 mb-1">Q: {row.question}</div>
                    <div className="text-sm text-gray-600 line-clamp-2">A: {row.answer}</div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-right text-sm text-gray-500">
                    <div>{row.total_tokens} tokens</div>
                    <div>${row.cost_usd.toFixed(4)}</div>
                    <div>{row.response_time_ms}ms</div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
