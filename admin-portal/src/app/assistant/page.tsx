"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useAuthReady } from "@/lib/useAuthReady";
import { Send, Sparkles, Loader2, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  error?: string;
}

const SUGGESTED_QUESTIONS = [
  "How many requests did hr and it bot get?",
  "In the last 7 days which person used more tokens?",
  "Which model cost highest?",
  "Show me all bot info",
];

export default function AssistantPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isThinking, setIsThinking] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const authReady = useAuthReady();

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isThinking]);

  async function send(question: string) {
    if (!question.trim() || isThinking || !authReady) return;

    const userMessage: Message = { id: Date.now().toString(), role: "user", content: question.trim() };
    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsThinking(true);

    try {
      const answer = await api.askAssistant(question.trim());
      setMessages((prev) => [...prev, { id: (Date.now() + 1).toString(), role: "assistant", content: answer }]);
    } catch (error: any) {
      setMessages((prev) => [...prev, {
        id: (Date.now() + 1).toString(), role: "assistant", content: "",
        error: error.message || "An unexpected error occurred.",
      }]);
    } finally {
      setIsThinking(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(input);
    }
  }

  return (
    <div className="flex h-full flex-col space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-navy dark:text-white">Admin Assistant</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Ask about bot usage, cost, and configuration in plain language.
        </p>
      </div>

      <div className="flex flex-1 flex-col rounded-lg border border-gray-200 dark:border-navy-deep bg-white dark:bg-card shadow-sm overflow-hidden">
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {messages.length === 0 && (
            <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-info">
                <Sparkles className="h-6 w-6 text-blue-600" />
              </div>
              <p className="text-sm text-gray-500 dark:text-gray-400 max-w-sm">
                Try one of these, or type your own question below.
              </p>
              <div className="flex flex-wrap justify-center gap-2 max-w-lg">
                {SUGGESTED_QUESTIONS.map((q) => (
                  <button
                    key={q}
                    onClick={() => send(q)}
                    className="rounded-full border border-gray-300 dark:border-navy-deep bg-white dark:bg-card px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-navy-deep/30"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg) => (
            <div
              key={msg.id}
              className={cn("flex max-w-[85%] flex-col gap-1", msg.role === "user" ? "ml-auto items-end" : "mr-auto items-start")}
            >
              <div
                className={cn(
                  "rounded-2xl px-4 py-3 text-sm shadow-sm",
                  msg.role === "user"
                    ? "bg-navy dark:bg-accent text-white rounded-br-sm"
                    : "bg-gray-50 dark:bg-navy-deep/40 text-navy dark:text-gray-100 border border-gray-100 dark:border-navy-deep/50 rounded-bl-sm"
                )}
              >
                {msg.error ? (
                  <div className="flex items-center gap-2 text-rose-500">
                    <AlertCircle className="h-4 w-4" />
                    <span>{msg.error}</span>
                  </div>
                ) : (
                  <div className="whitespace-pre-wrap">{msg.content}</div>
                )}
              </div>
            </div>
          ))}

          {isThinking && (
            <div className="mr-auto flex items-center gap-2 rounded-2xl rounded-bl-sm bg-gray-50 dark:bg-navy-deep/40 border border-gray-100 dark:border-navy-deep/50 px-4 py-3 text-sm text-gray-500 dark:text-gray-400">
              <Loader2 className="h-4 w-4 animate-spin text-orange" />
              <span>Checking the data...</span>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        <div className="shrink-0 border-t border-gray-200 dark:border-navy-deep p-4">
          <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-xl border border-gray-300 dark:border-navy-deep bg-white dark:bg-card px-3 py-2 focus-within:border-orange focus-within:ring-1 focus-within:ring-orange">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask about usage, cost, or bot config..."
              className="max-h-32 min-h-[24px] w-full resize-none bg-transparent text-sm focus:outline-none text-navy dark:text-white placeholder:text-gray-400"
              rows={1}
              disabled={isThinking}
            />
            <button
              onClick={() => send(input)}
              disabled={!input.trim() || isThinking}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-orange text-white hover:bg-orange-hover disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Send className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
