"use client";

import { useEffect, useState } from "react";
import { api, ChatHistoryRow, Bot } from "@/lib/api";
import { useAuthReady } from "@/lib/useAuthReady";
import { LottieLoader } from "@/components/ui/LottieLoader";
import { Search, ChevronDown, ChevronUp, ThumbsUp, ThumbsDown } from "lucide-react";
import { format } from "date-fns";
import { cn, getInitials } from "@/lib/utils";

const AVATAR_COLORS = [
  "bg-blue-100 text-blue-700",
  "bg-emerald-100 text-emerald-700",
  "bg-amber-100 text-amber-700",
  "bg-rose-100 text-rose-700",
  "bg-violet-100 text-violet-700",
  "bg-cyan-100 text-cyan-700",
];

const BOT_COLORS = [
  "bg-info text-blue-700 ring-orange/10",
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

export default function HistoryPage() {
  const [history, setHistory] = useState<ChatHistoryRow[]>([]);
  const [bots, setBots] = useState<Bot[]>([]);
  const [loading, setLoading] = useState(true);
  const [botId, setBotId] = useState("");
  const [keywordInput, setKeywordInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const authReady = useAuthReady();

  const toggleRow = (id: string) => {
    setExpandedRow(expandedRow === id ? null : id);
  };

  // Debounce the search box so it doesn't re-fetch on every keystroke.
  useEffect(() => {
    const t = setTimeout(() => setKeyword(keywordInput), 400);
    return () => clearTimeout(t);
  }, [keywordInput]);

  useEffect(() => {
    if (!authReady) return;
    async function loadData() {
      try {
        const [hist, bts] = await Promise.all([
          api.getChatHistory({ bot_id: botId || undefined, keyword: keyword || undefined }),
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
  }, [authReady, botId, keyword]);

  if (loading) return <LottieLoader message="Loading chat history..." />;

  const botName = (botId: string) => bots.find(b => b.id === botId)?.name ?? botId;

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-navy dark:text-white">Chat History</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">Search and audit conversations across bots.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-gray-400 dark:text-gray-500" />
            <input
              type="text"
              value={keywordInput}
              onChange={(e) => setKeywordInput(e.target.value)}
              placeholder="Search question, answer, or user..."
              className="pl-9 rounded-md border border-gray-300 dark:border-navy-deep bg-white dark:bg-card dark:text-white px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-orange"
            />
          </div>
          <select
            value={botId}
            onChange={(e) => setBotId(e.target.value)}
            className="rounded-md border border-gray-300 dark:border-navy-deep px-3 py-1.5 text-sm bg-white dark:bg-card dark:text-white focus:outline-none focus:ring-2 focus:ring-orange"
          >
            <option value="">All Bots</option>
            {bots.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </div>
      </div>

      <div className="space-y-3">
        {history.length === 0 ? (
          <div className="rounded-lg border border-gray-200 dark:border-navy-deep bg-white dark:bg-card p-8 text-center text-gray-500 dark:text-gray-400 shadow-sm">
            No chat history found matching your filters.
          </div>
        ) : (
          history.map((row) => {
            const label = row.user_email || row.user_id;
            const isExpanded = expandedRow === row.id;

            return (
              <div key={row.id} className="rounded-lg border border-gray-200 dark:border-navy-deep bg-white dark:bg-card shadow-sm overflow-hidden transition-all duration-200">
                <div
                  onClick={() => toggleRow(row.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      toggleRow(row.id);
                    }
                  }}
                  role="button"
                  tabIndex={0}
                  aria-expanded={isExpanded}
                  className="flex items-center gap-4 p-4 cursor-pointer hover:bg-gray-50 dark:hover:bg-navy-deep/30 focus:outline-none focus-visible:ring-2 focus-visible:ring-orange focus-visible:ring-inset"
                >
                  <div className={cn("flex-shrink-0 h-10 w-10 flex items-center justify-center rounded-full text-sm font-semibold", colorFor(label, AVATAR_COLORS))}>
                    {getInitials(label)}
                  </div>
                  <div className="flex-1 min-w-0 flex flex-col sm:flex-row sm:items-center gap-2">
                    <div className="flex items-center gap-2 flex-shrink-0">
                      <span className="text-sm font-medium text-navy dark:text-white truncate max-w-[150px]" title={label}>{label}</span>
                      <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset", colorFor(row.bot_id, BOT_COLORS))}>
                        {botName(row.bot_id)}
                      </span>
                    </div>
                    <div className="text-sm text-gray-600 dark:text-gray-400 truncate flex-1" title={row.question}>
                      {row.question}
                    </div>
                  </div>
                  <div className="flex items-center gap-4 flex-shrink-0">
                    {row.feedback === "like" && (
                      <span title="Liked"><ThumbsUp className="h-4 w-4 text-emerald-600 dark:text-emerald-400" /></span>
                    )}
                    {row.feedback === "dislike" && (
                      <span title="Disliked"><ThumbsDown className="h-4 w-4 text-rose-600 dark:text-rose-400" /></span>
                    )}
                    <span className="text-xs text-gray-400 dark:text-gray-500 hidden sm:inline-block">
                      {format(new Date(row.created_at), "MMM d, HH:mm")}
                    </span>
                    {isExpanded ? (
                      <ChevronUp className="h-5 w-5 text-gray-400 dark:text-gray-500" />
                    ) : (
                      <ChevronDown className="h-5 w-5 text-gray-400 dark:text-gray-500" />
                    )}
                  </div>
                </div>

                {isExpanded && (
                  <div className="border-t border-gray-200 dark:border-navy-deep bg-gray-50/50 dark:bg-navy-deep/20 p-6 space-y-4">
                    <div>
                      <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">Question</h4>
                      <p className="text-sm text-navy dark:text-white">{row.question}</p>
                    </div>
                    <div>
                      <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">Answer</h4>
                      <div className="text-sm text-gray-700 dark:text-gray-300 bg-white dark:bg-card border border-gray-200 dark:border-navy-deep rounded-lg p-4 shadow-sm whitespace-pre-wrap">
                        {row.answer}
                      </div>
                    </div>

                    <div className="flex items-center gap-6 pt-2 text-xs font-medium text-gray-500 dark:text-gray-400 flex-wrap">
                      <div className="flex items-center gap-1">
                        <span className="text-gray-400 dark:text-gray-500">Input Tokens:</span>
                        <span className="text-navy dark:text-white">{row.prompt_tokens.toLocaleString()}</span>
                      </div>
                      <div className="flex items-center gap-1">
                        <span className="text-gray-400 dark:text-gray-500">Output Tokens:</span>
                        <span className="text-navy dark:text-white">{row.completion_tokens.toLocaleString()}</span>
                      </div>
                      <div className="flex items-center gap-1">
                        <span className="text-gray-400 dark:text-gray-500">Total Tokens:</span>
                        <span className="text-navy dark:text-white">{row.total_tokens.toLocaleString()}</span>
                      </div>
                      <div className="flex items-center gap-1">
                        <span className="text-gray-400 dark:text-gray-500">Cost:</span>
                        <span className="text-navy dark:text-white">${row.cost_usd.toFixed(4)}</span>
                      </div>
                      <div className="flex items-center gap-1">
                        <span className="text-gray-400 dark:text-gray-500">Latency:</span>
                        <span className="text-navy dark:text-white">{row.response_time_ms}ms</span>
                      </div>
                      <div className="flex items-center gap-1 sm:hidden ml-auto">
                        <span className="text-gray-400 dark:text-gray-500">{format(new Date(row.created_at), "HH:mm")}</span>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
