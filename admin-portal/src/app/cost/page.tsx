"use client";

import { useEffect, useState } from "react";
import { api, CostSummary, CostByBot, CostByModel, CostByUser } from "@/lib/api";
import { useAuthReady } from "@/lib/useAuthReady";
import { LottieLoader } from "@/components/ui/LottieLoader";
import {
  BarChart, 
  Bar, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell
} from "recharts";

const COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6"];

export default function CostPage() {
  const [summary, setSummary] = useState<CostSummary | null>(null);
  const [byBot, setByBot] = useState<CostByBot[]>([]);
  const [byModel, setByModel] = useState<CostByModel[]>([]);
  const [chatModels, setChatModels] = useState<CostByModel[]>([]);
  const [byUser, setByUser] = useState<CostByUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [period, setPeriod] = useState("last_30_days");
  const authReady = useAuthReady();

  useEffect(() => {
    if (!authReady) return;
    async function loadData() {
      try {
        const params = { period: period || undefined };
        const [sum, bot, model, user] = await Promise.all([
          api.getCostSummary(params),
          api.getCostByBot(params),
          api.getCostByModel(params),
          api.getCostByUser(params)
        ]);
        setSummary(sum);
        setByBot(bot);
        // "Cost by Model" is meant to show LLM generation cost only - the
        // separate Embedding Cost card above already covers embedding spend.
        // Filter by the real kind column, not by guessing from model names
        // (a renamed/new embedding model would silently slip back in).
        setByModel(model.filter(m => m.kind !== "embedding"));
        setChatModels(model.filter(m => m.kind === "chat"));
        setByUser(user);
      } catch (error) {
        console.error(error);
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, [authReady, period]);

  if (loading || !summary) return <LottieLoader message="Loading cost data..." />;

  const pieData = [
    { name: "LLM (Generation)", value: summary.llm_cost },
    { name: "Embeddings (Indexing/Search)", value: summary.embedding_cost },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-navy dark:text-white">Cost Dashboard</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">Analyze spending by bot, model, and user.</p>
        </div>
        <select
          value={period}
          onChange={(e) => setPeriod(e.target.value)}
          className="rounded-md border border-gray-300 dark:border-navy-deep px-3 py-1.5 text-sm bg-white dark:bg-card dark:text-white focus:outline-none focus:ring-2 focus:ring-orange"
        >
          <option value="last_30_days">Last 30 Days</option>
          <option value="this_month">This Month</option>
          <option value="">All Time</option>
        </select>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-lg border border-gray-200 dark:border-navy-deep bg-white dark:bg-card p-6 shadow-sm">
          <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Total Cost</p>
          <h3 className="text-3xl font-bold text-navy dark:text-white mt-2">${summary.total_cost.toFixed(2)}</h3>
        </div>
        <div className="rounded-lg border border-gray-200 dark:border-navy-deep bg-white dark:bg-card p-6 shadow-sm">
          <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Input Tokens</p>
          <h3 className="text-2xl font-bold text-navy dark:text-white mt-2">${summary.llm_input_cost.toFixed(4)}</h3>
          <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">{summary.input_tokens.toLocaleString()} tokens</p>
        </div>
        <div className="rounded-lg border border-gray-200 dark:border-navy-deep bg-white dark:bg-card p-6 shadow-sm">
          <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Output Tokens</p>
          <h3 className="text-2xl font-bold text-navy dark:text-white mt-2">${summary.llm_output_cost.toFixed(4)}</h3>
          <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">{summary.output_tokens.toLocaleString()} tokens</p>
        </div>
        <div className="rounded-lg border border-gray-200 dark:border-navy-deep bg-white dark:bg-card p-6 shadow-sm">
          <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Embedding Cost</p>
          <h3 className="text-3xl font-bold text-navy dark:text-white mt-2">${summary.embedding_cost.toFixed(2)}</h3>
          <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">$0 = local model, no API cost</p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-lg border border-gray-200 dark:border-navy-deep bg-white dark:bg-card p-6 shadow-sm">
          <h3 className="text-base font-semibold text-navy dark:text-white mb-4">Cost vs Type</h3>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={pieData} cx="50%" cy="50%" innerRadius={60} outerRadius={80} paddingAngle={5} dataKey="value">
                  {pieData.map((entry, index) => <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />)}
                </Pie>
                <Tooltip formatter={(value: any) => `$${Number(value).toFixed(2)}`} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="rounded-lg border border-gray-200 dark:border-navy-deep bg-white dark:bg-card p-6 shadow-sm">
          <h3 className="text-base font-semibold text-navy dark:text-white mb-4">Cost by Model</h3>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={byModel} layout="vertical" margin={{ left: 50 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                <XAxis type="number" tickLine={false} axisLine={false} tickFormatter={val => `$${val}`} />
                <YAxis dataKey="model" type="category" tickLine={false} axisLine={false} fontSize={12} />
                <Tooltip formatter={(value: any) => [`$${Number(value).toFixed(2)}`, "Cost"]} />
                <Bar dataKey="cost" fill="#10b981" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Left Column: Token Usage by Model (if applicable) */}
        {chatModels.length > 1 ? (
          <div>
            <h3 className="text-base font-semibold text-navy dark:text-white mb-3">Token Usage by Model</h3>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              {chatModels.map(m => (
                <div key={m.model} className="rounded-lg border border-gray-200 dark:border-navy-deep bg-white dark:bg-card p-6 shadow-sm hover:scale-[1.02] transition-transform">
                  <p className="text-sm font-medium text-gray-500 dark:text-gray-400">{m.model}</p>
                  <h3 className="text-2xl font-bold text-navy dark:text-white mt-2">${m.cost.toFixed(2)}</h3>
                  <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
                    In: {m.prompt_tokens.toLocaleString()} &middot; Out: {m.completion_tokens.toLocaleString()}
                  </p>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="hidden lg:block">
            {/* Empty placeholder if only 1 model, so Top Users doesn't stretch weirdly, 
                or we could just let Top Users span full width if we wanted, but side-by-side is requested */}
          </div>
        )}

        {/* Right Column: Top Users by Cost */}
        <div>
          <h3 className="text-base font-semibold text-navy dark:text-white mb-3">Top Users by Cost</h3>
          <div className="rounded-lg border border-gray-200 dark:border-navy-deep bg-white dark:bg-card shadow-sm overflow-hidden">
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 dark:divide-navy-deep">
                <thead className="bg-gray-50 dark:bg-navy-deep/40">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">User</th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Requests</th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Cost</th>
                  </tr>
                </thead>
                <tbody className="bg-white dark:bg-card divide-y divide-gray-200 dark:divide-navy-deep">
                  {byUser.map(user => (
                    <tr key={user.user_id}>
                      <td 
                        className="px-6 py-4 whitespace-nowrap text-sm font-medium text-navy dark:text-white max-w-[150px] sm:max-w-[200px] truncate"
                        title={user.email || user.user_id}
                      >
                        {user.email || user.user_id}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400 text-right">{user.requests}</td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-navy dark:text-white text-right">${user.cost.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
