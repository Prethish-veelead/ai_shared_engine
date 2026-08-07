"use client";

import { useState, useRef, useEffect } from "react";
import Lottie from "lottie-react";
import ReactMarkdown from "react-markdown";
import { AppShell } from "@/components/layout/AppShell";
import { api, Bot as BotType, Citation, HistoryTurn } from "@/lib/api";
import { Send, Bot, User, AlertCircle, ThumbsUp, ThumbsDown, Trash2, Copy, Check, Pencil, ExternalLink } from "lucide-react";
import { cn } from "@/lib/utils";

// Cycled while waiting for an answer (see the isTyping block below) - purely
// cosmetic, doesn't reflect real pipeline stages, just keeps a long wait
// from feeling stuck on one static line.
const GENERATING_PHRASES = ["Thinking...", "Searching documents...", "Reviewing sources...", "Generating response..."];
const GENERATING_PHRASE_INTERVAL_MS = 1800;

// One raw Citation per retrieved chunk means the same document can show up
// several times (once per matched page) - collapse to one chip per unique
// source, combining every page it matched into that one chip's label.
// List-bot citations (no page field, already one-per-list from the backend)
// pass through as a single-item group unchanged.
interface CitationGroup {
  source: string;
  url: string | null;
  pages: number[];
}

// Bot answers come back with real markdown (**bold**, numbered lists, ...)
// but were rendered as plain text - defined once, outside the component, so
// it isn't recreated on every render.
const MARKDOWN_COMPONENTS = {
  p: ({ children }: { children?: React.ReactNode }) => <p className="mb-2 last:mb-0">{children}</p>,
  ul: ({ children }: { children?: React.ReactNode }) => <ul className="mb-2 ml-4 list-disc space-y-1 last:mb-0">{children}</ul>,
  ol: ({ children }: { children?: React.ReactNode }) => <ol className="mb-2 ml-4 list-decimal space-y-1 last:mb-0">{children}</ol>,
  code: ({ children }: { children?: React.ReactNode }) => (
    <code className="rounded bg-black/5 dark:bg-white/10 px-1 py-0.5 text-[13px]">{children}</code>
  ),
  a: ({ href, children }: { href?: string; children?: React.ReactNode }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" className="underline">
      {children}
    </a>
  ),
};

function groupCitations(citations: Citation[]): CitationGroup[] {
  const groups = new Map<string, CitationGroup>();
  for (const c of citations) {
    let group = groups.get(c.source);
    if (!group) {
      group = { source: c.source, url: c.url, pages: [] };
      groups.set(c.source, group);
    }
    if (c.page !== null && c.page !== undefined && !group.pages.includes(c.page)) {
      group.pages.push(c.page);
    }
  }
  return Array.from(groups.values()).map((g) => ({ ...g, pages: g.pages.sort((a, b) => a - b) }));
}

interface Message {
  id: string;
  role: "user" | "bot";
  content: string;
  citations?: Citation[];
  metadata?: {
    model: string;
    timeMs: number;
  };
  error?: string;
  botId?: string;
  chatLogId?: number;
  feedback?: "like" | "dislike" | null;
  commentSubmitted?: boolean;
}

// Client-side safety cap on how much history a single request body carries -
// the backend's chat_history_max_messages setting is the authoritative
// trim, this just keeps a very long session's payload from growing unbounded.
const HISTORY_CLIENT_SEND_CAP = 16;

// All the actual chat UI/behavior - split out from page.tsx (a Server
// Component) because generateStaticParams there requires a non-"use client"
// file, and this component is fully "use client".
//
// botId is read directly from window.location.pathname, NOT from a prop
// passed down from page.tsx and NOT from next/navigation's useParams().
// Both of those derive from Next's own client-side router state, which for
// a page built from generateStaticParams's single synthetic "_shell" entry
// stays "_shell" FOREVER, regardless of the real browser URL - verified
// empirically (a debug log showed useParams() reporting "_shell" while
// window.location.pathname correctly showed "/bot/it"). This is a purely
// static export served by FastAPI's own fallback route (app/main.py) for
// ANY bot id, known or not - there is no live Next.js server to resolve
// params/router state against the real URL, only the raw browser URL itself
// is trustworthy.
export function ChatClient() {
  const [botId, setBotId] = useState("");
  useEffect(() => {
    const segments = window.location.pathname.split("/").filter(Boolean);
    setBotId(segments[1] || "");
  }, []);

  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [currentBot, setCurrentBot] = useState<BotType | null>(null);
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  // Which user message is currently being edited in place (Claude/ChatGPT-
  // style edit), and its draft text - at most one at a time.
  const [editingMessageId, setEditingMessageId] = useState<string | null>(null);
  const [editingText, setEditingText] = useState("");
  // Which bot message currently has its "what went wrong?" comment box open
  // (dislike-only "Learning loop") - at most one at a time.
  const [commentDraftFor, setCommentDraftFor] = useState<string | null>(null);
  const [commentText, setCommentText] = useState("");
  const [loadingAnimation, setLoadingAnimation] = useState<object | null>(null);
  const [generatingPhraseIndex, setGeneratingPhraseIndex] = useState(0);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  // Next.js doesn't remount page.tsx on a dynamic-param change (only
  // template.tsx gets that), so without this the chat history and any
  // in-flight request from the previous bot would carry over when the
  // user switches bots via the AppShell dropdown.
  const activeBotIdRef = useRef(botId);

  useEffect(() => {
    activeBotIdRef.current = botId;
    setMessages([]);
    setInput("");
    setIsTyping(false);
    setCurrentBot(null);
  }, [botId]);

  useEffect(() => {
    let cancelled = false;
    api.getBots()
      .then((bots) => {
        if (!cancelled) setCurrentBot(bots.find((b) => b.id === botId) || null);
      })
      .catch(console.error);
    return () => {
      cancelled = true;
    };
  }, [botId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isTyping]);

  useEffect(() => {
    fetch("/loading.json")
      .then((res) => res.json())
      .then(setLoadingAnimation)
      .catch(() => setLoadingAnimation(null));
  }, []);

  // Cycles the "Thinking... / Searching documents... / ..." text while
  // waiting for an answer - resets to the first phrase each time a new
  // request starts, rather than continuing from wherever the last one left off.
  useEffect(() => {
    if (!isTyping) {
      setGeneratingPhraseIndex(0);
      return;
    }
    const interval = setInterval(() => {
      setGeneratingPhraseIndex((i) => (i + 1) % GENERATING_PHRASES.length);
    }, GENERATING_PHRASE_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [isTyping]);

  // Accepts an explicit question (used by the sample-question chips below,
  // which send immediately on click) or falls back to whatever's typed in
  // the input box. `historyBase`, when passed (only by handleSaveEdit
  // below), replaces `messages` as the base to build on - this is what lets
  // an edited resend truncate everything after the edited message instead
  // of just appending a new turn at the end.
  const handleSend = async (question?: string, historyBase?: Message[]) => {
    const text = (question ?? input).trim();
    if (!text || isTyping) return;

    const requestBotId = botId;
    const userMessage: Message = {
      id: Date.now().toString(),
      role: "user",
      content: text,
    };

    const priorMessages = historyBase ?? messages;

    // Temporary, non-persisted history (docs/CHAT_SESSIONS.md): built from
    // this in-memory `messages` state, sent with the request, and never
    // written anywhere else - a refresh/tab close just loses it, by design.
    // The backend trims to its own window authoritatively; this client-side
    // cap just keeps the request body from growing unbounded in a very long
    // session.
    const history: HistoryTurn[] = priorMessages
      .filter((m) => !m.error)
      .slice(-HISTORY_CLIENT_SEND_CAP)
      .map((m) => ({ role: m.role === "user" ? "user" : "assistant", content: m.content }));

    if (historyBase) {
      // Editing an earlier message: replace state with the truncated
      // history + the resubmitted message, discarding that message's old
      // text and everything that came after it (its old answer included).
      setMessages([...historyBase, userMessage]);
    } else {
      setMessages((prev) => [...prev, userMessage]);
    }
    setInput("");
    setIsTyping(true);

    try {
      const response = await api.askBot(requestBotId, userMessage.content, history);
      if (activeBotIdRef.current !== requestBotId) return;
      const botMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: "bot",
        content: response.answer,
        citations: response.citations,
        metadata: {
          model: response.model,
          timeMs: response.response_time_ms,
        },
        botId: requestBotId,
        chatLogId: response.chat_log_id,
        feedback: null,
      };
      setMessages((prev) => [...prev, botMessage]);
    } catch (error: any) {
      if (activeBotIdRef.current !== requestBotId) return;
      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: "bot",
        content: "",
        error: error.message || "An unexpected error occurred.",
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      if (activeBotIdRef.current === requestBotId) setIsTyping(false);
    }
  };

  const handleFeedback = async (msg: Message, feedback: "like" | "dislike") => {
    if (!msg.botId || msg.chatLogId == null || msg.feedback === feedback) return;
    const previous = msg.feedback ?? null;
    setMessages((prev) => prev.map((m) => (m.id === msg.id ? { ...m, feedback } : m)));
    try {
      await api.sendFeedback(msg.botId, msg.chatLogId, feedback);
      // Dislike-only "Learning loop": offer an optional free-text reason
      // right after the dislike registers, rather than blocking on it.
      if (feedback === "dislike") {
        setCommentText("");
        setCommentDraftFor(msg.id);
      }
    } catch (error) {
      console.error(error);
      setMessages((prev) => prev.map((m) => (m.id === msg.id ? { ...m, feedback: previous } : m)));
    }
  };

  async function handleSubmitComment(msg: Message) {
    const text = commentText.trim();
    if (!msg.botId || msg.chatLogId == null || !text) return;
    try {
      await api.sendFeedback(msg.botId, msg.chatLogId, "dislike", text);
      setMessages((prev) => prev.map((m) => (m.id === msg.id ? { ...m, commentSubmitted: true } : m)));
    } catch (error) {
      console.error(error);
    } finally {
      setCommentDraftFor(null);
      setCommentText("");
    }
  }

  function handleSkipComment() {
    setCommentDraftFor(null);
    setCommentText("");
  }

  function handleClearChat() {
    setMessages([]);
    setInput("");
  }

  async function handleCopy(text: string, messageId: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedMessageId(messageId);
      setTimeout(() => setCopiedMessageId((current) => (current === messageId ? null : current)), 1500);
    } catch (error) {
      console.error("Copy failed", error);
    }
  }

  // In-place edit (Claude/ChatGPT-style): turns the message bubble itself
  // into an editable box, rather than copying its text into the bottom
  // input - see handleSaveEdit for what happens on submit.
  function handleStartEdit(msg: Message) {
    setEditingMessageId(msg.id);
    setEditingText(msg.content);
  }

  function handleCancelEdit() {
    setEditingMessageId(null);
    setEditingText("");
  }

  // Drops the edited message and everything after it (its old answer
  // included), then resends the new text as if the conversation had ended
  // right before it - so the thread shows only the edited version, not both.
  function handleSaveEdit(msg: Message) {
    const text = editingText.trim();
    if (!text || isTyping) return;
    const index = messages.findIndex((m) => m.id === msg.id);
    const historyBase = index === -1 ? messages : messages.slice(0, index);
    setEditingMessageId(null);
    setEditingText("");
    handleSend(text, historyBase);
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // Extracted to a local const rather than accessed inline as currentBot.sample_questions -
  // a stale/mid-rollout backend can omit this field entirely, and TS's undefined-narrowing
  // on an optional property doesn't reliably persist into the .map() callback below.
  const sampleQuestions = currentBot?.sample_questions ?? [];

  return (
    <AppShell currentBotId={botId || undefined}>
      <div className="flex h-full flex-col bg-gray-50/30 dark:bg-navy-deep/20">
        {/* Chat Area */}
        <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-6 relative">
          {messages.length > 0 && (
            <div className="flex justify-end">
              <button
                onClick={handleClearChat}
                title="Clear chat"
                className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-gray-400 dark:text-gray-500 hover:text-rose-600 dark:hover:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-500/10 transition-colors"
              >
                <Trash2 className="h-3.5 w-3.5" />
                Clear chat
              </button>
            </div>
          )}

          {messages.length === 0 && (
            <div className="flex h-full items-center justify-center text-center">
              <div className="bg-white/50 dark:bg-navy/30 backdrop-blur-sm p-8 rounded-3xl border border-white/20 dark:border-white/5 shadow-xl max-w-md">
                <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl bg-orange/10 dark:bg-orange/20 mb-4">
                  <Bot className="h-8 w-8 text-orange" />
                </div>
                <h3 className="text-lg font-bold text-navy dark:text-white mb-2">How can I help you today?</h3>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Send a message to start chatting with {currentBot?.name || "the assistant"}.
                </p>

                {sampleQuestions.length > 0 && (
                  <div className="mt-6 flex flex-col gap-2 text-left">
                    <p className="text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wider">
                      Try asking
                    </p>
                    {sampleQuestions.map((q) => (
                      <button
                        key={q}
                        onClick={() => handleSend(q)}
                        disabled={isTyping}
                        className="rounded-xl border border-gray-200 dark:border-navy-deep bg-white/70 dark:bg-navy-deep/50 px-4 py-2.5 text-sm text-navy dark:text-gray-200 text-left hover:border-orange hover:bg-orange/5 dark:hover:bg-orange/10 transition-colors disabled:opacity-50"
                      >
                        {q}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {messages.map((msg) => (
            <div
              key={msg.id}
              className={cn(
                "group flex max-w-[85%] sm:max-w-[75%] flex-col gap-2 relative",
                msg.role === "user" ? "ml-auto items-end" : "mr-auto items-start"
              )}
            >
              <div
                className={cn(
                  "px-5 py-4 text-[15px] shadow-sm leading-relaxed backdrop-blur-md",
                  msg.role === "user"
                    ? "bg-navy dark:bg-accent text-white rounded-2xl rounded-br-sm shadow-md"
                    : "bg-white/90 dark:bg-card/90 text-navy dark:text-gray-100 border border-gray-100/50 dark:border-navy-deep/50 rounded-2xl rounded-bl-sm"
                )}
              >
                {msg.role === "user" && editingMessageId === msg.id ? (
                  <div className="flex w-72 flex-col gap-2 sm:w-96">
                    <textarea
                      value={editingText}
                      onChange={(e) => setEditingText(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !e.shiftKey) {
                          e.preventDefault();
                          handleSaveEdit(msg);
                        } else if (e.key === "Escape") {
                          handleCancelEdit();
                        }
                      }}
                      rows={2}
                      autoFocus
                      className="w-full resize-none rounded-lg border border-white/30 bg-white/10 px-3 py-2 text-sm text-white placeholder:text-white/50 focus:outline-none focus:border-white/60"
                    />
                    <div className="flex justify-end gap-2">
                      <button
                        onClick={handleCancelEdit}
                        className="rounded-lg px-3 py-1 text-xs font-medium text-white/70 hover:bg-white/10 transition-colors"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={() => handleSaveEdit(msg)}
                        disabled={!editingText.trim()}
                        className="rounded-lg bg-white/20 px-3 py-1 text-xs font-semibold text-white hover:bg-white/30 disabled:opacity-50 transition-colors"
                      >
                        Save &amp; Submit
                      </button>
                    </div>
                  </div>
                ) : msg.error ? (
                  <div className="flex items-center gap-2 text-rose-500">
                    <AlertCircle className="h-5 w-5" />
                    <span className="font-medium">{msg.error}</span>
                  </div>
                ) : msg.role === "bot" ? (
                  <div className="[&>*:last-child]:mb-0">
                    <ReactMarkdown components={MARKDOWN_COMPONENTS}>{msg.content}</ReactMarkdown>
                  </div>
                ) : (
                  <div className="whitespace-pre-wrap">{msg.content}</div>
                )}

                {/* Citations */}
                {msg.citations && msg.citations.length > 0 && (
                  <div className="mt-4 flex flex-wrap gap-2 pt-3 border-t border-black/5 dark:border-white/10">
                    {groupCitations(msg.citations).map((cit, idx) => {
                      const pageLabel =
                        cit.pages.length === 0 ? "" :
                        cit.pages.length === 1 ? ` (p.${cit.pages[0]})` :
                        ` (pp. ${cit.pages.join(", ")})`;
                      const label = cit.source.split("/").pop() + pageLabel;
                      const className =
                        "inline-flex items-center gap-1 rounded-lg bg-orange/10 dark:bg-orange/20 px-2.5 py-1 text-[11px] font-semibold text-orange-hover dark:text-orange border border-orange/20";
                      return cit.url ? (
                        <a
                          key={idx}
                          href={cit.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className={`${className} hover:bg-orange/20 dark:hover:bg-orange/30 transition-colors`}
                          title="View Source Document"
                        >
                          {label}
                          <ExternalLink className="h-3 w-3" />
                        </a>
                      ) : (
                        <span key={idx} className={className} title={cit.source}>
                          {label}
                        </span>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* Edit/copy - user messages only, revealed on hover */}
              {msg.role === "user" && !msg.error && editingMessageId !== msg.id && (
                <div className="flex items-center gap-1 px-2 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button
                    onClick={() => handleStartEdit(msg)}
                    title="Edit message"
                    className="rounded-md p-1 text-gray-400 dark:text-gray-500 hover:text-orange transition-colors"
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </button>
                  <button
                    onClick={() => handleCopy(msg.content, msg.id)}
                    title="Copy question"
                    className="rounded-md p-1 text-gray-400 dark:text-gray-500 hover:text-navy dark:hover:text-white transition-colors"
                  >
                    {copiedMessageId === msg.id ? (
                      <Check className="h-3.5 w-3.5 text-emerald-500" />
                    ) : (
                      <Copy className="h-3.5 w-3.5" />
                    )}
                  </button>
                </div>
              )}

              {/* Metadata */}
              {msg.metadata && (
                <div className="px-2 flex items-center gap-3 text-[11px] text-gray-400 dark:text-gray-500 font-medium">
                  <span>{msg.metadata.model} • {(msg.metadata.timeMs / 1000).toFixed(1)}s</span>
                  <button
                    onClick={() => handleCopy(msg.content, msg.id)}
                    title="Copy answer"
                    className="rounded-md p-1 text-gray-300 dark:text-gray-600 hover:text-navy dark:hover:text-white transition-colors"
                  >
                    {copiedMessageId === msg.id ? (
                      <Check className="h-3.5 w-3.5 text-emerald-500" />
                    ) : (
                      <Copy className="h-3.5 w-3.5" />
                    )}
                  </button>
                  {msg.chatLogId != null && (
                    <span className="flex items-center gap-1.5">
                      <button
                        onClick={() => handleFeedback(msg, "like")}
                        title="Good answer"
                        className={cn(
                          "rounded-md p-1 transition-colors",
                          msg.feedback === "like"
                            ? "text-emerald-600 dark:text-emerald-400"
                            : "text-gray-300 dark:text-gray-600 hover:text-emerald-600 dark:hover:text-emerald-400"
                        )}
                      >
                        <ThumbsUp className="h-3.5 w-3.5" />
                      </button>
                      <button
                        onClick={() => handleFeedback(msg, "dislike")}
                        title="Bad answer"
                        className={cn(
                          "rounded-md p-1 transition-colors",
                          msg.feedback === "dislike"
                            ? "text-rose-600 dark:text-rose-400"
                            : "text-gray-300 dark:text-gray-600 hover:text-rose-600 dark:hover:text-rose-400"
                        )}
                      >
                        <ThumbsDown className="h-3.5 w-3.5" />
                      </button>
                    </span>
                  )}
                </div>
              )}

              {/* Dislike comment box ("Learning loop") - optional, dislike-only */}
              {commentDraftFor === msg.id && (
                <div className="w-full max-w-sm rounded-xl border border-gray-200 dark:border-navy-deep bg-white dark:bg-card p-3 shadow-sm">
                  <p className="mb-2 text-xs font-medium text-gray-500 dark:text-gray-400">
                    What went wrong? (optional)
                  </p>
                  <textarea
                    value={commentText}
                    onChange={(e) => setCommentText(e.target.value)}
                    placeholder="e.g. missed a detail, wrong source..."
                    rows={2}
                    className="w-full resize-none rounded-lg border border-gray-200 dark:border-navy-deep bg-gray-50 dark:bg-navy-deep/50 px-3 py-2 text-sm text-navy dark:text-white placeholder:text-gray-400 focus:outline-none focus:border-orange"
                  />
                  <div className="mt-2 flex justify-end gap-2">
                    <button
                      onClick={handleSkipComment}
                      className="rounded-lg px-3 py-1.5 text-xs font-medium text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-navy-deep transition-colors"
                    >
                      Skip
                    </button>
                    <button
                      onClick={() => handleSubmitComment(msg)}
                      disabled={!commentText.trim()}
                      className="rounded-lg bg-orange px-3 py-1.5 text-xs font-semibold text-white hover:bg-orange-hover disabled:opacity-50 transition-colors"
                    >
                      Submit
                    </button>
                  </div>
                </div>
              )}
              {msg.commentSubmitted && commentDraftFor !== msg.id && (
                <p className="px-2 text-[11px] text-gray-400 dark:text-gray-500">Thanks for the feedback.</p>
              )}
            </div>
          ))}

          {isTyping && (
            <div className="mr-auto flex max-w-[75%] items-center gap-3 rounded-2xl rounded-bl-sm bg-white/80 dark:bg-card/80 backdrop-blur-md border border-gray-100/50 dark:border-navy-deep/50 px-5 py-4 text-sm text-gray-500 shadow-sm">
              <div className="h-10 w-10 shrink-0">
                {loadingAnimation && <Lottie animationData={loadingAnimation} loop autoplay />}
              </div>
              <span className="font-medium">{GENERATING_PHRASES[generatingPhraseIndex]}</span>
            </div>
          )}
          <div ref={messagesEndRef} className="h-4" />
        </div>

        {/* Input Area - Glassmorphism */}
        <div className="shrink-0 bg-white/70 dark:bg-navy/70 backdrop-blur-lg p-4 sm:p-6 border-t border-gray-200/50 dark:border-navy-deep/50 z-10">
          <div className="mx-auto max-w-4xl relative flex items-end overflow-hidden rounded-2xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-navy-deep shadow-inner focus-within:border-orange focus-within:ring-1 focus-within:ring-orange transition-all">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask a question..."
              className="max-h-32 min-h-[60px] w-full resize-none bg-transparent py-4 pl-5 pr-14 text-sm focus:outline-none text-navy dark:text-white placeholder:text-gray-400"
              rows={1}
              disabled={isTyping || editingMessageId !== null}
            />
            <button
              onClick={() => handleSend()}
              disabled={!input.trim() || isTyping || editingMessageId !== null}
              className="absolute bottom-2 right-2 flex h-11 w-11 items-center justify-center rounded-xl bg-orange text-white transition-all hover:bg-orange-hover hover:scale-105 disabled:bg-gray-100 dark:disabled:bg-gray-800 disabled:text-gray-400 disabled:hover:scale-100 shadow-sm"
            >
              <Send className="h-5 w-5" />
            </button>
          </div>
          <p className="mt-3 text-center text-[11px] font-medium text-gray-400 dark:text-gray-500">
            AI-generated responses can be inaccurate. Please check the provided citations.
          </p>
        </div>
      </div>
    </AppShell>
  );
}
