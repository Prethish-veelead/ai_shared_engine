"use client";

import { useEffect, useState } from "react";
import { api, UsageSummary, UsageTrend, Bot } from "@/lib/api";
import { useAuthReady } from "@/lib/useAuthReady";
import {
  LineChart, 
  Line, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ResponsiveContainer 
} from "recharts";
import { Activity, Database, FileText, Users } from "lucide-react";

export default function UsagePage() {
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [trend, setTrend] = useState<UsageTrend[]>([]);
  const [bots, setBots] = useState<Bot[]>([]);
  const [indexTotals, setIndexTotals] = useState({ documents: 0, chunks: 0 });
  const [loading, setLoading] = useState(true);
  const [botId, setBotId] = useState("");
  const [period, setPeriod] = useState("");
  const authReady = useAuthReady();

  useEffect(() => {
    if (!authReady) return;
    async function loadData() {
      try {
        const filterParams = { bot_id: botId || undefined, period: period || undefined };
        const [sum, trnd, bts, indexStatus] = await Promise.all([
          api.getUsageSummary(filterParams),
          api.getUsageTrend({ ...filterParams, granularity: "day" }),
          api.getBots(),
          api.getIndexStatus(botId || undefined),
        ]);
        setSummary(sum);
        setTrend(trnd);
        setBots(bts);
        setIndexTotals({
          documents: indexStatus.reduce((sum, s) => sum + s.documents_indexed, 0),
          chunks: indexStatus.reduce((sum, s) => sum + s.chunks_indexed, 0),
        });
      } catch (error) {
        console.error(error);
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, [authReady, botId, period]);

  if (loading || !summary) return <div className="flex h-full items-center justify-center">Loading usage...</div>;

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-navy">Usage Dashboard</h1>
          <p className="text-sm text-gray-500">Monitor token consumption and request volume.</p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={botId}
            onChange={(e) => setBotId(e.target.value)}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-orange"
          >
            <option value="">All Bots</option>
            {bots.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
          <select
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-orange"
          >
            <option value="today">Today</option>
            <option value="last_7_days">Last 7 Days</option>
            <option value="last_30_days">Last 30 Days</option>
            <option value="">All Time</option>
          </select>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-lg border bg-white p-6 shadow-sm">
          <p className="text-sm font-medium text-gray-500">Total Tokens</p>
          <h3 className="text-2xl font-semibold text-navy mt-2">{summary.total_tokens.toLocaleString()}</h3>
          <p className="text-xs text-gray-400 mt-1">Prompt: {summary.prompt_tokens.toLocaleString()} | Completion: {summary.completion_tokens.toLocaleString()}</p>
        </div>
        <div className="rounded-lg border bg-white p-6 shadow-sm">
          <p className="text-sm font-medium text-gray-500">Avg Response Time</p>
          <h3 className="text-2xl font-semibold text-navy mt-2">{summary.avg_response_time_ms} ms</h3>
        </div>
        <div className="rounded-lg border bg-white p-6 shadow-sm">
          <p className="text-sm font-medium text-gray-500">Active Users</p>
          <h3 className="text-2xl font-semibold text-navy mt-2">{summary.active_users.toLocaleString()}</h3>
        </div>
        <div className="rounded-lg border bg-white p-6 shadow-sm">
          <p className="text-sm font-medium text-gray-500">Chunks Indexed</p>
          <h3 className="text-2xl font-semibold text-navy mt-2">{indexTotals.chunks.toLocaleString()}</h3>
          <p className="text-xs text-gray-400 mt-1">{indexTotals.documents.toLocaleString()} docs across all bots</p>
        </div>
      </div>

      <div className="rounded-lg border bg-white p-6 shadow-sm">
        <h3 className="text-base font-semibold text-navy mb-4">Token Usage Trend</h3>
        <div className="h-80">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={trend}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="period" tickLine={false} axisLine={false} tickFormatter={val => val.slice(5)} />
              <YAxis tickLine={false} axisLine={false} tickFormatter={val => `${val / 1000}k`} />
              <Tooltip formatter={(val: any) => [Number(val).toLocaleString(), "Tokens"]} />
              <Line type="monotone" dataKey="tokens" stroke="#8b5cf6" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
