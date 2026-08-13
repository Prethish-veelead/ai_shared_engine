"use client";

import { useState, useRef, useEffect } from "react";
import Lottie from "lottie-react";
import { AppShell } from "@/components/layout/AppShell";
import { ThemePicker } from "@/components/chat/ThemePicker";
import { CurrentMessage } from "@/components/chat/themes/CurrentTheme";
import { EditorialMessage } from "@/components/chat/themes/EditorialTheme";
import { ConsoleMessage } from "@/components/chat/themes/ConsoleTheme";
import { CompanionMessage } from "@/components/chat/themes/CompanionTheme";
import type { ChatTheme, Message } from "@/components/chat/themes/types";
import { api, Bot as BotType, HistoryTurn } from "@/lib/api";
import { Send, Bot, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";

// Cycled while waiting for an answer (see the isTyping block below) - purely
// cosmetic, doesn't reflect real pipeline stages, just keeps a long wait
// from feeling stuck on one static line.
const GENERATING_PHRASES = ["Thinking...", "Searching documents...", "Reviewing sources...", "Generating response..."];
const GENERATING_PHRASE_INTERVAL_MS = 1800;

// Persisted per-browser (not per-bot) - a visual preference, not chat data,
// so it's fine to survive across the temporary/in-memory chat sessions.
const CHAT_THEME_STORAGE_KEY = "bot-ui-chat-theme";

const THEME_MESSAGE_COMPONENTS = {
  current: CurrentMessage,
  editorial: EditorialMessage,
  console: ConsoleMessage,
  companion: CompanionMessage,
};

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
  // Visual theme for the message list (layout/typography/shape, not just
  // color - see docs/BOT_UI_THEME_CONCEPTS) - independent of the app-wide
  // light/dark toggle in AppShell, which stays exactly as-is.
  const [chatTheme, setChatTheme] = useState<ChatTheme>("current");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  // Next.js doesn't remount page.tsx on a dynamic-param change (only
  // template.tsx gets that), so without this the chat history and any
  // in-flight request from the previous bot would carry over when the
  // user switches bots via the AppShell dropdown.
  const activeBotIdRef = useRef(botId);

  useEffect(() => {
    const stored = localStorage.getItem(CHAT_THEME_STORAGE_KEY) as ChatTheme | null;
    if (stored && stored in THEME_MESSAGE_COMPONENTS) setChatTheme(stored);
  }, []);

  function handleThemeChange(theme: ChatTheme) {
    setChatTheme(theme);
    localStorage.setItem(CHAT_THEME_STORAGE_KEY, theme);
  }

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
        chart: response.chart,
        followUpQuestions: response.follow_up_questions,
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

  const MessageItem = THEME_MESSAGE_COMPONENTS[chatTheme];
  const messageItemProps = {
    isTyping,
    editingMessageId,
    editingText,
    setEditingText,
    onStartEdit: handleStartEdit,
    onSaveEdit: handleSaveEdit,
    onCancelEdit: handleCancelEdit,
    onCopy: handleCopy,
    copiedMessageId,
    onFeedback: handleFeedback,
    commentDraftFor,
    commentText,
    setCommentText,
    onSubmitComment: handleSubmitComment,
    onSkipComment: handleSkipComment,
    onFollowUpClick: (q: string) => handleSend(q),
  };

  return (
    <AppShell currentBotId={botId || undefined}>
      <div
        className={cn(
          "flex h-full flex-col",
          chatTheme === "console" ? "bg-[#0a0d12]" : chatTheme === "editorial" ? "bg-[#eef1f4]" : chatTheme === "companion" ? "bg-[#f7eef1]" : "bg-gray-50/30 dark:bg-navy-deep/20"
        )}
      >
        {/* Chat Area */}
        <div className={cn("flex-1 overflow-y-auto relative", chatTheme === "console" ? "p-0" : "p-4 sm:p-6 space-y-6")}>
          <div className={cn("flex items-center justify-end gap-1", chatTheme === "console" && "px-4 pt-3")}>
            <ThemePicker value={chatTheme} onChange={handleThemeChange} />
            {messages.length > 0 && (
              <button
                onClick={handleClearChat}
                title="Clear chat"
                className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-gray-400 dark:text-gray-500 hover:text-rose-600 dark:hover:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-500/10 transition-colors"
              >
                <Trash2 className="h-3.5 w-3.5" />
                Clear chat
              </button>
            )}
          </div>

          {messages.length === 0 && (
            <div className="flex h-full items-center justify-center p-4 animate-fade-in-up">
              {chatTheme === "console" ? (
                <div className="w-full max-w-2xl font-mono text-[13px]" style={{ color: "#d7dde5" }}>
                  <div className="mb-6 pb-2" style={{ borderBottom: "1px solid #1c2229", color: "#4fa3d1" }}>
                    SYSTEM READY // {currentBot?.name?.toUpperCase() || "ASSISTANT"}
                  </div>
                  <div className="mb-4 text-[#6f7a89]">
                    &gt; connection established<br/>
                    &gt; waiting for input...
                  </div>
                  {sampleQuestions.length > 0 && (
                    <div className="flex flex-col gap-2">
                      <div className="text-[#6f7a89] uppercase text-[10px] tracking-widest mt-4 mb-1">Suggested Queries</div>
                      {sampleQuestions.map((q) => (
                        <button
                          key={q}
                          onClick={() => handleSend(q)}
                          disabled={isTyping}
                          className="text-left px-3 py-2 rounded-sm transition-colors hover:bg-[#12161c]"
                          style={{ border: "1px solid #1c2229", color: "#4fa3d1" }}
                        >
                          $ {q}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              ) : chatTheme === "editorial" ? (
                <div className="w-full max-w-2xl text-center">
                  <h1 className="font-serif text-3xl mb-4" style={{ color: "#161b22" }}>{currentBot?.name || "The Assistant"}</h1>
                  <div className="w-16 h-px mx-auto mb-6" style={{ background: "#3b6e71" }}></div>
                  <p className="font-sans text-sm mb-8 max-w-md mx-auto" style={{ color: "#5c6672" }}>
                    A refined conversational experience. Ask a question to begin reading.
                  </p>
                  {sampleQuestions.length > 0 && (
                    <div className="flex flex-col gap-3 max-w-md mx-auto">
                      <p className="font-sans text-[11px] font-bold uppercase tracking-[0.14em]" style={{ color: "#3b6e71" }}>
                        Inquiries
                      </p>
                      {sampleQuestions.map((q) => (
                        <button
                          key={q}
                          onClick={() => handleSend(q)}
                          disabled={isTyping}
                          className="text-left font-serif text-lg leading-snug hover:opacity-70 transition-opacity pb-2"
                          style={{ borderBottom: "1px solid #d4d9de", color: "#161b22" }}
                        >
                          {q}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              ) : chatTheme === "companion" ? (
                <div className="w-full max-w-md text-center bg-white rounded-[32px] p-8 shadow-sm">
                  <div className="mx-auto flex h-20 w-20 items-center justify-center rounded-full text-white text-2xl font-bold mb-6" style={{ background: "#e8637a" }}>
                    {(currentBot?.name || "AI").slice(0, 2).toUpperCase()}
                  </div>
                  <h3 className="text-2xl font-bold mb-2" style={{ color: "#3a2a2f" }}>Hi there! 👋</h3>
                  <p className="text-[15px] mb-8" style={{ color: "#9a8489" }}>
                    I'm {currentBot?.name || "your AI companion"}. How can I help you today?
                  </p>
                  {sampleQuestions.length > 0 && (
                    <div className="flex flex-col gap-2.5">
                      {sampleQuestions.map((q) => (
                        <button
                          key={q}
                          onClick={() => handleSend(q)}
                          disabled={isTyping}
                          className="text-left px-5 py-3.5 rounded-2xl transition-transform hover:scale-[1.02] active:scale-95 font-medium"
                          style={{ background: "#fdf6f7", color: "#3a2a2f" }}
                        >
                          {q}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              ) : (
                <div className="bg-white/50 dark:bg-navy/30 backdrop-blur-sm p-8 rounded-3xl border border-white/20 dark:border-white/5 shadow-xl max-w-md text-center">
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
              )}
            </div>
          )}

          <div className={cn(chatTheme === "console" ? "" : "space-y-6")}>
            {messages.map((msg, i) => (
              <MessageItem key={msg.id} msg={msg} isLast={i === messages.length - 1} {...messageItemProps} />
            ))}
          </div>

          {isTyping && (
            <div className={cn(chatTheme === "console" && "px-4 pb-4")}>
              {chatTheme === "console" ? (
                <div className="font-mono text-[12.5px]" style={{ color: "#6f7a89" }}>
                  &gt; {GENERATING_PHRASES[generatingPhraseIndex]}
                </div>
              ) : chatTheme === "editorial" ? (
                <div className="font-sans text-sm" style={{ color: "#5c6672" }}>
                  {GENERATING_PHRASES[generatingPhraseIndex]}
                </div>
              ) : chatTheme === "companion" ? (
                <div className="flex items-center gap-2">
                  <div
                    className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] font-bold text-white"
                    style={{ background: "#e8637a" }}
                  >
                    AI
                  </div>
                  <div className="flex items-center gap-2 rounded-2xl rounded-tl-sm bg-white px-4 py-3 text-sm shadow-sm" style={{ color: "#3a2a2f" }}>
                    <div className="h-7 w-7 shrink-0">{loadingAnimation && <Lottie animationData={loadingAnimation} loop autoplay />}</div>
                    {GENERATING_PHRASES[generatingPhraseIndex]}
                  </div>
                </div>
              ) : (
                <div className="mr-auto flex max-w-[75%] items-center gap-3 rounded-2xl rounded-bl-sm bg-white/80 dark:bg-card/80 backdrop-blur-md border border-gray-100/50 dark:border-navy-deep/50 px-5 py-4 text-sm text-gray-500 shadow-sm">
                  <div className="h-10 w-10 shrink-0">
                    {loadingAnimation && <Lottie animationData={loadingAnimation} loop autoplay />}
                  </div>
                  <span className="font-medium">{GENERATING_PHRASES[generatingPhraseIndex]}</span>
                </div>
              )}
            </div>
          )}
          <div ref={messagesEndRef} className="h-4" />
        </div>

        {/* Input Area */}
        {chatTheme === "console" ? (
          <div className="shrink-0 p-4 font-mono text-[12.5px]" style={{ background: "#0a0d12", borderTop: "1px solid #1c2229" }}>
            <div className="mx-auto flex max-w-4xl items-end gap-2 rounded-sm px-3 py-2 transition-all focus-within:ring-1 focus-within:ring-[#4fa3d1]" style={{ border: "1px solid #1c2229" }}>
              <span style={{ color: "#4fa3d1" }}>&gt;</span>
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="ask a question..."
                className="min-h-[24px] w-full resize-none bg-transparent focus:outline-none placeholder:text-[#4a5361]"
                style={{ color: "#d7dde5" }}
                rows={1}
                disabled={isTyping || editingMessageId !== null}
              />
              <button
                onClick={() => handleSend()}
                disabled={!input.trim() || isTyping || editingMessageId !== null}
                className="shrink-0 font-bold uppercase disabled:opacity-30"
                style={{ color: "#4fa3d1" }}
              >
                send
              </button>
            </div>
          </div>
        ) : chatTheme === "editorial" ? (
          <div className="shrink-0 p-5" style={{ background: "#eef1f4", borderTop: "1px solid #d4d9de" }}>
            <div className="mx-auto flex max-w-3xl items-end gap-3 pb-1.5 transition-all focus-within:border-[#3b6e71]" style={{ borderBottom: "1px solid #b7bfc7" }}>
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask a question..."
                className="min-h-[28px] w-full resize-none bg-transparent font-serif text-lg focus:outline-none placeholder:text-gray-400"
                style={{ color: "#161b22" }}
                rows={1}
                disabled={isTyping || editingMessageId !== null}
              />
              <button
                onClick={() => handleSend()}
                disabled={!input.trim() || isTyping || editingMessageId !== null}
                className="shrink-0 font-sans text-xs font-bold uppercase tracking-wide disabled:opacity-30"
                style={{ color: "#3b6e71" }}
              >
                Send
              </button>
            </div>
          </div>
        ) : chatTheme === "companion" ? (
          <div className="shrink-0 p-4 sm:p-6" style={{ background: "#f7eef1", borderTop: "1px solid #f0dde2" }}>
            <div className="mx-auto flex max-w-4xl items-end overflow-hidden rounded-3xl bg-white px-4 shadow-sm transition-all focus-within:ring-2 focus-within:ring-[#f0dde2]">
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask me anything..."
                className="max-h-32 min-h-[52px] w-full resize-none bg-transparent py-3.5 pr-2 text-sm focus:outline-none placeholder:text-gray-400"
                style={{ color: "#3a2a2f" }}
                rows={1}
                disabled={isTyping || editingMessageId !== null}
              />
              <button
                onClick={() => handleSend()}
                disabled={!input.trim() || isTyping || editingMessageId !== null}
                className="my-2 flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-white transition-transform hover:scale-105 disabled:opacity-40"
                style={{ background: "#e8637a" }}
              >
                <Send className="h-4 w-4" />
              </button>
            </div>
          </div>
        ) : (
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
          </div>
        )}
        <p
          className={cn(
            "text-center text-[11px] font-medium pb-2",
            chatTheme === "console" ? "font-mono" : "",
            chatTheme === "console" ? "" : "mt-3"
          )}
          style={
            chatTheme === "console" ? { color: "#4a5361", background: "#0a0d12" } :
            chatTheme === "editorial" ? { color: "#8a93a0", background: "#eef1f4" } :
            chatTheme === "companion" ? { color: "#b09aa0", background: "#f7eef1" } :
            undefined
          }
        >
          <span className={chatTheme === "current" ? "text-gray-400 dark:text-gray-500" : undefined}>
            AI-generated responses can be inaccurate. Please check the provided citations.
          </span>
        </p>
      </div>
    </AppShell>
  );
}