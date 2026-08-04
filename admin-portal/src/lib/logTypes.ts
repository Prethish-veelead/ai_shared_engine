import { AlertCircle, AlertTriangle, FileWarning, RefreshCw, Zap, ShieldAlert, LucideIcon } from "lucide-react";
import type { LogEntry } from "./api";

// Shared between the Logs & Monitoring page and the header's notification
// bell - both render the same EventLog rows, so the icon/color per type
// lives in one place rather than two copies that can drift apart.
export const LOG_TYPE_ICONS: Record<LogEntry["type"], LucideIcon> = {
  error: AlertCircle,
  sync: RefreshCw,
  auth: ShieldAlert,
  ai: Zap,
  indexing: FileWarning,
  resource: AlertTriangle,
};

export const LOG_TYPE_COLORS: Record<LogEntry["type"], string> = {
  error: "text-red-600 bg-red-50",
  sync: "text-blue-600 bg-info",
  auth: "text-orange-600 bg-warning",
  ai: "text-purple-600 bg-warning",
  indexing: "text-yellow-600 bg-warning",
  resource: "text-rose-600 bg-rose-50",
};
