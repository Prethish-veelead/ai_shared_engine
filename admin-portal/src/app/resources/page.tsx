"use client";

import { useEffect, useState } from "react";
import { api, StorageByBot, SystemResources, ActivityByBot } from "@/lib/api";
import { useAuthReady } from "@/lib/useAuthReady";
import { formatBytes } from "@/lib/utils";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { HardDrive, Cpu, MemoryStick, Info } from "lucide-react";

function UsageBar({ pct, colorClass }: { pct: number; colorClass: string }) {
  const clamped = Math.max(0, Math.min(100, pct));
  return (
    <div className="mt-2 h-2 w-full rounded-full bg-gray-100 dark:bg-navy-deep overflow-hidden">
      <div className={`h-full rounded-full ${colorClass}`} style={{ width: `${clamped}%` }} />
    </div>
  );
}

export default function ResourcesPage() {
  const [storage, setStorage] = useState<StorageByBot[]>([]);
  const [resources, setResources] = useState<SystemResources | null>(null);
  const [activity, setActivity] = useState<ActivityByBot[]>([]);
  const [period, setPeriod] = useState("");
  const [loading, setLoading] = useState(true);
  const authReady = useAuthReady();

  // Storage + system resources are exact/current-state, not tied to a time
  // period - fetched once on mount, not re-fetched when the activity period
  // filter changes (matches the spec: heavy queries run on mount only).
  useEffect(() => {
    if (!authReady) return;
    async function loadStatic() {
      try {
        const [s, r] = await Promise.all([api.getStorageByBot(), api.getResources()]);
        setStorage(s);
        setResources(r);
      } catch (error) {
        console.error(error);
      } finally {
        setLoading(false);
      }
    }
    loadStatic();
  }, [authReady]);

  useEffect(() => {
    if (!authReady) return;
    async function loadActivity() {
      try {
        setActivity(await api.getActivityByBot({ period: period || undefined }));
      } catch (error) {
        console.error(error);
      }
    }
    loadActivity();
  }, [authReady, period]);

  if (loading || !resources) {
    return <div className="flex h-full items-center justify-center">Loading system resources...</div>;
  }

  const storageChartData = storage.map((s) => ({
    name: s.name,
    "Vector (Qdrant)": s.vectorSizeBytes,
    "Structured (Postgres)": s.structuredTotalBytes,
  }));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-navy dark:text-white">System</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400">Storage per bot, host resource usage, and per-bot activity share.</p>
      </div>

      {/* ---- Section 1: Storage by bot (exact) ---- */}
      <div className="rounded-lg border border-gray-200 dark:border-navy-deep bg-white dark:bg-card p-6 shadow-sm">
        <div className="flex items-center gap-2 mb-1">
          <HardDrive className="h-4 w-4 text-orange" />
          <h3 className="text-base font-semibold text-navy dark:text-white">Storage by Bot</h3>
        </div>
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-4">
          Each bot owns its Qdrant collection and, for list bots, its own Postgres tables - these numbers are exact.
          Vector byte size is an <span title="Estimated from point count x embedding dimension x 4 bytes + per-point overhead - Qdrant doesn't expose real on-disk size for these collections." className="underline decoration-dotted cursor-help">estimate (est.)</span>, structured table size is real (pg_total_relation_size).
        </p>
        <div className="h-72 mb-6">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={storageChartData} layout="vertical" margin={{ left: 60 }}>
              <CartesianGrid strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" tickFormatter={(v) => formatBytes(v)} tickLine={false} axisLine={false} />
              <YAxis type="category" dataKey="name" width={140} tickLine={false} axisLine={false} />
              <Tooltip formatter={(val: any) => formatBytes(Number(val))} />
              <Legend />
              <Bar dataKey="Vector (Qdrant)" stackId="storage" fill="#8b5cf6" />
              <Bar dataKey="Structured (Postgres)" stackId="storage" fill="#f5821f" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 dark:border-navy-deep text-left text-gray-500 dark:text-gray-400">
                <th className="py-2 pr-4 font-medium">Bot</th>
                <th className="py-2 pr-4 font-medium">Vector points</th>
                <th className="py-2 pr-4 font-medium">Vector size</th>
                <th className="py-2 pr-4 font-medium">Structured tables</th>
                <th className="py-2 pr-4 font-medium">Structured size</th>
                <th className="py-2 pr-4 font-medium">Chat / Usage rows</th>
                <th className="py-2 pr-4 font-medium">Total</th>
              </tr>
            </thead>
            <tbody>
              {storage.map((s) => (
                <tr key={s.botId} className="border-b border-gray-100 dark:border-navy-deep/50">
                  <td className="py-2 pr-4 font-medium text-navy dark:text-white">{s.name}</td>
                  <td className="py-2 pr-4">{s.vectorPoints.toLocaleString()}</td>
                  <td className="py-2 pr-4">
                    {formatBytes(s.vectorSizeBytes)}
                    {s.vectorSizeIsEstimate && (
                      <span className="ml-1 rounded bg-gray-100 dark:bg-navy-deep px-1.5 py-0.5 text-[10px] text-gray-500 dark:text-gray-400" title="Estimated, not exact">est.</span>
                    )}
                  </td>
                  <td className="py-2 pr-4">
                    {s.structuredTables.length === 0 ? (
                      <span className="text-gray-400 dark:text-gray-500">-</span>
                    ) : (
                      <div className="space-y-0.5">
                        {s.structuredTables.map((t) => (
                          <div key={t.tableName} className="text-xs text-gray-500 dark:text-gray-400">
                            {t.listName}: {t.rows.toLocaleString()} rows
                          </div>
                        ))}
                      </div>
                    )}
                  </td>
                  <td className="py-2 pr-4">{s.structuredTables.length === 0 ? <span className="text-gray-400 dark:text-gray-500">-</span> : formatBytes(s.structuredTotalBytes)}</td>
                  <td className="py-2 pr-4 text-xs text-gray-500 dark:text-gray-400">{s.chatRows.toLocaleString()} / {s.usageRows.toLocaleString()}</td>
                  <td className="py-2 pr-4 font-semibold text-navy dark:text-white">{formatBytes(s.totalStorageBytes)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* ---- Section 2: System resources (container/system level) ---- */}
      <div className="rounded-lg border border-gray-200 dark:border-navy-deep bg-white dark:bg-card p-6 shadow-sm">
        <div className="flex items-center gap-2 mb-1">
          <Cpu className="h-4 w-4 text-orange" />
          <h3 className="text-base font-semibold text-navy dark:text-white">System Resources</h3>
        </div>
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-4">
          Real memory/CPU/disk for this deployment, read from {resources.source === "cgroup" ? "the container's cgroup limits" : "the host (psutil)"}. Not broken down per bot - see Activity below for that.
        </p>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-lg border border-gray-100 dark:border-navy-deep/50 p-4">
            <div className="flex items-center gap-1.5 text-sm font-medium text-gray-500 dark:text-gray-400">
              <MemoryStick className="h-3.5 w-3.5" /> Memory
            </div>
            <h4 className="text-xl font-semibold text-navy dark:text-white mt-1">{resources.memory.pct}%</h4>
            <p className="text-xs text-gray-400 dark:text-gray-500">{formatBytes(resources.memory.usedBytes)} / {formatBytes(resources.memory.limitBytes)}</p>
            <UsageBar pct={resources.memory.pct} colorClass="bg-orange" />
          </div>
          <div className="rounded-lg border border-gray-100 dark:border-navy-deep/50 p-4">
            <div className="flex items-center gap-1.5 text-sm font-medium text-gray-500 dark:text-gray-400">
              <Cpu className="h-3.5 w-3.5" /> CPU
            </div>
            <h4 className="text-xl font-semibold text-navy dark:text-white mt-1">{resources.cpu.pct}%</h4>
            <p className="text-xs text-gray-400 dark:text-gray-500">host-level sample</p>
            <UsageBar pct={resources.cpu.pct} colorClass="bg-purple-500" />
          </div>
          <div className="rounded-lg border border-gray-100 dark:border-navy-deep/50 p-4">
            <div className="flex items-center gap-1.5 text-sm font-medium text-gray-500 dark:text-gray-400">
              <HardDrive className="h-3.5 w-3.5" /> Disk
            </div>
            <h4 className="text-xl font-semibold text-navy dark:text-white mt-1">{resources.disk.pct}%</h4>
            <p className="text-xs text-gray-400 dark:text-gray-500">{formatBytes(resources.disk.usedBytes)} / {formatBytes(resources.disk.totalBytes)}</p>
            <UsageBar pct={resources.disk.pct} colorClass="bg-blue-500" />
          </div>
          <div className="rounded-lg border border-gray-100 dark:border-navy-deep/50 p-4">
            <div className="flex items-center gap-1.5 text-sm font-medium text-gray-500 dark:text-gray-400">
              <Cpu className="h-3.5 w-3.5" /> API process
            </div>
            <h4 className="text-xl font-semibold text-navy dark:text-white mt-1">{formatBytes(resources.process.rssBytes)}</h4>
            <p className="text-xs text-gray-400 dark:text-gray-500">{resources.process.cpuPct}% CPU</p>
          </div>
        </div>

        <div className="mt-4 flex items-start gap-2 rounded-md bg-gray-50 dark:bg-navy-deep/40 p-3 text-xs text-gray-500 dark:text-gray-400">
          <Info className="h-3.5 w-3.5 mt-0.5 shrink-0" />
          {resources.containersAvailable ? (
            <span>Per-container breakdown available.</span>
          ) : (
            <span>{resources.note}</span>
          )}
        </div>
      </div>

      {/* ---- Section 3: Activity by bot (load proxy, NOT per-bot RAM/CPU) ---- */}
      <div className="rounded-lg border border-gray-200 dark:border-navy-deep bg-white dark:bg-card p-6 shadow-sm">
        <div className="flex items-center justify-between mb-1">
          <h3 className="text-base font-semibold text-navy dark:text-white">Activity by Bot</h3>
          <select
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            className="rounded-md border border-gray-300 dark:border-navy-deep px-3 py-1.5 text-sm bg-white dark:bg-card dark:text-white focus:outline-none focus:ring-2 focus:ring-orange"
          >
            <option value="today">Today</option>
            <option value="last_7_days">Last 7 Days</option>
            <option value="last_30_days">Last 30 Days</option>
            <option value="">All Time</option>
          </select>
        </div>
        <p className="text-xs text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/30 rounded-md px-3 py-2 mb-4">
          Activity share is a proxy for load. All bots share one engine, so per-bot RAM isn&apos;t directly measurable - this shows each bot&apos;s share of the work.
        </p>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 dark:border-navy-deep text-left text-gray-500 dark:text-gray-400">
                <th className="py-2 pr-4 font-medium">Bot</th>
                <th className="py-2 pr-4 font-medium">Requests</th>
                <th className="py-2 pr-4 font-medium">Tokens</th>
                <th className="py-2 pr-4 font-medium">Cost</th>
                <th className="py-2 pr-4 font-medium">Avg response</th>
                <th className="py-2 pr-4 font-medium">Requests share</th>
                <th className="py-2 pr-4 font-medium">Tokens share</th>
                <th className="py-2 pr-4 font-medium">Cost share</th>
                <th className="py-2 pr-4 font-medium">Last sync</th>
              </tr>
            </thead>
            <tbody>
              {activity.map((a) => (
                <tr key={a.botId} className="border-b border-gray-100 dark:border-navy-deep/50">
                  <td className="py-2 pr-4 font-medium text-navy dark:text-white">{a.name}</td>
                  <td className="py-2 pr-4">{a.requests.toLocaleString()}</td>
                  <td className="py-2 pr-4">{a.tokens.toLocaleString()}</td>
                  <td className="py-2 pr-4">${a.cost.toFixed(2)}</td>
                  <td className="py-2 pr-4">{a.avgResponseTimeMs} ms</td>
                  <td className="py-2 pr-4">{a.requestsSharePct}%</td>
                  <td className="py-2 pr-4">{a.tokensSharePct}%</td>
                  <td className="py-2 pr-4">{a.costSharePct}%</td>
                  <td className="py-2 pr-4 text-xs text-gray-500 dark:text-gray-400">
                    {a.lastSyncAt ? new Date(a.lastSyncAt).toLocaleString() : "-"}
                    {a.lastSyncStatus && <span className="ml-1">({a.lastSyncStatus})</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
