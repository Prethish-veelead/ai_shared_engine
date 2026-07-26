"use client";

import { use, useState, useRef, useEffect } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { api, Citation } from "@/lib/api";
import { Send, Bot, User, Loader2, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";

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
}

export default function BotChatPage({ params }: { params: Promise<{ botId: string }> }) {
  const resolvedParams = use(params);
  const botId = resolvedParams.botId;

  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isTyping]);

  const handleSend = async () => {
    if (!input.trim() || isTyping) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: "user",
      content: input.trim(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsTyping(true);

    try {
      const response = await api.askBot(botId, userMessage.content);
      const botMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: "bot",
        content: response.answer,
        citations: response.citations,
        metadata: {
          model: response.model,
          timeMs: response.response_time_ms,
        },
      };
      setMessages((prev) => [...prev, botMessage]);
    } catch (error: any) {
      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: "bot",
        content: "",
        error: error.message || "An unexpected error occurred.",
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setIsTyping(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <AppShell>
      <div className="flex h-full flex-col">
        {/* Header */}
        <div className="shrink-0 border-b bg-white/50 px-6 py-3 backdrop-blur-sm flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-blue-100">
              <Bot className="h-4 w-4 text-blue-700" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-gray-900 capitalize">{botId} Bot</h2>
              <p className="text-xs text-gray-500">Ready to answer your questions</p>
            </div>
          </div>
        </div>

        {/* Chat Area */}
        <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-6 bg-gray-50/50">
          {messages.length === 0 && (
            <div className="flex h-full items-center justify-center text-center text-gray-500">
              <div>
                <Bot className="mx-auto h-12 w-12 text-gray-300 mb-3" />
                <p>Send a message to start chatting with the {botId} bot.</p>
              </div>
            </div>
          )}

          {messages.map((msg) => (
            <div
              key={msg.id}
              className={cn(
                "flex max-w-[85%] sm:max-w-[75%] flex-col gap-2",
                msg.role === "user" ? "ml-auto items-end" : "mr-auto items-start"
              )}
            >
              <div
                className={cn(
                  "rounded-2xl px-4 py-3 text-sm shadow-sm",
                  msg.role === "user"
                    ? "bg-blue-600 text-white rounded-br-sm"
                    : "bg-white text-gray-800 border border-gray-100 rounded-bl-sm"
                )}
              >
                {msg.error ? (
                  <div className="flex items-center gap-2 text-red-600">
                    <AlertCircle className="h-4 w-4" />
                    <span>{msg.error}</span>
                  </div>
                ) : (
                  <div className="whitespace-pre-wrap">{msg.content}</div>
                )}

                {/* Citations */}
                {msg.citations && msg.citations.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5 pt-3 border-t border-gray-100">
                    {msg.citations.map((cit, idx) => (
                      <span
                        key={idx}
                        className="inline-flex items-center rounded-full bg-blue-50 px-2 py-0.5 text-[10px] font-medium text-blue-700 border border-blue-100"
                        title={cit.source}
                      >
                        {cit.source.split("/").pop()} 
                        {cit.page !== null && cit.page !== undefined ? ` (p.${cit.page})` : ""}
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {/* Metadata */}
              {msg.metadata && (
                <div className="px-1 text-[10px] text-gray-400 font-medium">
                  {msg.metadata.model} • {(msg.metadata.timeMs / 1000).toFixed(1)}s
                </div>
              )}
            </div>
          ))}

          {isTyping && (
            <div className="mr-auto flex max-w-[75%] items-center gap-2 rounded-2xl rounded-bl-sm bg-white border border-gray-100 px-4 py-3 text-sm text-gray-500 shadow-sm">
              <Loader2 className="h-4 w-4 animate-spin text-blue-600" />
              <span>Generating response...</span>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input Area */}
        <div className="shrink-0 bg-white p-4 sm:p-6 border-t">
          <div className="mx-auto max-w-4xl relative flex items-end overflow-hidden rounded-2xl border border-gray-300 bg-white shadow-sm focus-within:border-blue-600 focus-within:ring-1 focus-within:ring-blue-600">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask a question..."
              className="max-h-32 min-h-[56px] w-full resize-none bg-transparent py-4 pl-4 pr-12 text-sm focus:outline-none"
              rows={1}
              disabled={isTyping}
            />
            <button
              onClick={handleSend}
              disabled={!input.trim() || isTyping}
              className="absolute bottom-2 right-2 flex h-10 w-10 items-center justify-center rounded-xl bg-blue-600 text-white transition-colors hover:bg-blue-700 disabled:bg-gray-100 disabled:text-gray-400"
            >
              <Send className="h-4 w-4" />
            </button>
          </div>
          <p className="mt-2 text-center text-[10px] text-gray-400">
            AI-generated responses can be inaccurate. Please check the provided citations.
          </p>
        </div>
      </div>
    </AppShell>
  );
}
