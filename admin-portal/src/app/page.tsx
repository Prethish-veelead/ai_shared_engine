"use client";

import { useEffect, useState } from "react";
import { api, UsageSummary, UsageTrend, CostByBot } from "@/lib/api";
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
  LineChart,
  Line,
  Legend
} from "recharts";
import { Users, FileText, Database, Activity } from "lucide-react";

export default function DashboardPage() {
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [trend, setTrend] = useState<UsageTrend[]>([]);
  const [costByBot, setCostByBot] = useState<CostByBot[]>([]);
  const [documentsIndexed, setDocumentsIndexed] = useState(0);
  const [loading, setLoading] = useState(true);
  const authReady = useAuthReady();

  useEffect(() => {
    if (!authReady) return;
    async function loadData() {
      try {
        const [sum, trnd, cost, indexStatus] = await Promise.all([
          api.getUsageSummary(),
          api.getUsageTrend({ granularity: "day" }),
          api.getCostByBot(),
          api.getIndexStatus(),
        ]);
        setSummary(sum);
        setTrend(trnd);
        setCostByBot(cost);
        setDocumentsIndexed(indexStatus.reduce((sum, s) => sum + s.documents_indexed, 0));
      } catch (error) {
        console.error("Failed to load dashboard data", error);
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, [authReady]);

  if (loading || !summary) {
    return <LottieLoader message="Loading dashboard..." />;
  }

  const statCards = [
    { name: "Total Requests", value: summary.total_requests.toLocaleString(), icon: Activity },
    { name: "Total Cost", value: `$${summary.estimated_cost.toFixed(2)}`, icon: Database },
    { name: "Active Users", value: summary.active_users.toLocaleString(), icon: Users },
    { name: "Docs Indexed", value: documentsIndexed.toLocaleString(), icon: FileText },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-navy dark:text-white">Dashboard</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400">Overview of your Multi-Bot RAG system.</p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {statCards.map((stat) => (
          <div key={stat.name} className="flex items-center rounded-lg border border-gray-200 dark:border-navy-deep bg-white dark:bg-card p-6 shadow-sm">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-info">
              <stat.icon className="h-6 w-6 text-blue-600" />
            </div>
            <div className="ml-4">
              <p className="text-sm font-medium text-gray-500 dark:text-gray-400">{stat.name}</p>
              <h3 className="text-2xl font-semibold text-navy dark:text-white">{stat.value}</h3>
            </div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-lg border border-gray-200 dark:border-navy-deep bg-white dark:bg-card p-6 shadow-sm">
          <h3 className="text-base font-semibold text-navy dark:text-white mb-4">Usage Trend (Requests)</h3>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={trend}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="period" tickLine={false} axisLine={false} tickFormatter={(val) => val.slice(5)} />
                <YAxis tickLine={false} axisLine={false} />
                <Tooltip />
                <Line type="monotone" dataKey="requests" stroke="#2563eb" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="rounded-lg border border-gray-200 dark:border-navy-deep bg-white dark:bg-card p-6 shadow-sm">
          <h3 className="text-base font-semibold text-navy dark:text-white mb-4">Cost by Bot (USD)</h3>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={costByBot}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="bot_id" tickLine={false} axisLine={false} />
                <YAxis tickLine={false} axisLine={false} tickFormatter={(val) => `$${val}`} />
                <Tooltip formatter={(value: any) => [`$${Number(value).toFixed(2)}`, "Cost"]} />
                <Bar dataKey="cost" fill="#3b82f6" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  );
}
