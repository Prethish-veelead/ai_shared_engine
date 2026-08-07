"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ChartSpec } from "@/lib/api";

// Brand orange first, then a small rotation for multi-series/multi-slice
// charts - same family as the color palettes already used elsewhere
// (admin-portal's history page avatar/bot badges).
const PALETTE = ["#F2811D", "#1E2A47", "#10B981", "#F59E0B", "#8B5CF6", "#06B6D4"];
const AXIS_COLOR = "#9CA3AF";
const GRID_COLOR = "rgba(148, 163, 184, 0.25)";

export function AnswerChart({ chart }: { chart: ChartSpec }) {
  if (chart.type === "none" || !chart.labels?.length || !chart.values?.length) return null;

  const data = chart.labels.map((label, i) => ({ name: label, value: chart.values?.[i] ?? 0 }));

  return (
    <div className="mt-4 pt-3 border-t border-black/5 dark:border-white/10">
      <div className="h-56 w-full">
        <ResponsiveContainer width="100%" height="100%">
          {chart.type === "pie" ? (
            <PieChart>
              <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
              <Pie data={data} dataKey="value" nameKey="name" outerRadius={80} label={{ fontSize: 11 }}>
                {data.map((_, i) => (
                  <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
                ))}
              </Pie>
            </PieChart>
          ) : chart.type === "line" ? (
            <LineChart data={data}>
              <CartesianGrid stroke={GRID_COLOR} vertical={false} />
              <XAxis dataKey="name" tick={{ fontSize: 11, fill: AXIS_COLOR }} />
              <YAxis tick={{ fontSize: 11, fill: AXIS_COLOR }} allowDecimals={false} />
              <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
              <Line type="monotone" dataKey="value" stroke={PALETTE[0]} strokeWidth={2} dot={{ r: 3 }} />
            </LineChart>
          ) : (
            <BarChart data={data}>
              <CartesianGrid stroke={GRID_COLOR} vertical={false} />
              <XAxis dataKey="name" tick={{ fontSize: 11, fill: AXIS_COLOR }} />
              <YAxis tick={{ fontSize: 11, fill: AXIS_COLOR }} allowDecimals={false} />
              <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
              <Bar dataKey="value" fill={PALETTE[0]} radius={[4, 4, 0, 0]} />
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  );
}
