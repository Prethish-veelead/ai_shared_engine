import ReactMarkdown from "react-markdown";
import { AnswerChart } from "@/components/chat/AnswerChart";
import { citationPageLabel, groupCitations } from "@/lib/citations";
import { cn } from "@/lib/utils";
import { AlertCircle, Check, Copy, ExternalLink, Pencil, ThumbsDown, ThumbsUp } from "lucide-react";
import type { MessageItemProps } from "./types";

// Friendly, rounded, avatar-forward - speech-tail bubbles and a warm
// blush/coral palette instead of navy/orange. Matches the reviewed
// "03 · Warm Companion" concept - a deliberate single fixed palette, same
// reasoning as EditorialTheme/ConsoleTheme.
const PALETTE = {
  bg: "#f7eef1",
  ink: "#3a2a2f",
  userBubble: "#3a2a2f",
  userText: "#fdf6f7",
  botBubble: "#ffffff",
  accent: "#e8637a",
  chipBg: "#fbe4e9",
  chipText: "#b23e58",
};

const MARKDOWN_COMPONENTS = {
  p: ({ children }: { children?: React.ReactNode }) => <p className="mb-2 last:mb-0">{children}</p>,
  ul: ({ children }: { children?: React.ReactNode }) => <ul className="mb-2 ml-4 list-disc space-y-1 last:mb-0">{children}</ul>,
  ol: ({ children }: { children?: React.ReactNode }) => <ol className="mb-2 ml-4 list-decimal space-y-1 last:mb-0">{children}</ol>,
  code: ({ children }: { children?: React.ReactNode }) => (
    <code className="rounded bg-black/5 px-1 py-0.5 text-[13px]">{children}</code>
  ),
  a: ({ href, children }: { href?: string; children?: React.ReactNode }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" style={{ color: PALETTE.accent }} className="underline">
      {children}
    </a>
  ),
};

function initials(text: string) {
  return text.trim().slice(0, 2).toUpperCase() || "?";
}

export function CompanionMessage(props: MessageItemProps) {
  const {
    msg, isLast, isTyping, editingMessageId, editingText, setEditingText,
    onStartEdit, onSaveEdit, onCancelEdit, onCopy, copiedMessageId,
    onFeedback, commentDraftFor, commentText, setCommentText,
    onSubmitComment, onSkipComment, onFollowUpClick,
  } = props;

  const isUser = msg.role === "user";
  const groups = msg.citations ? groupCitations(msg.citations) : [];

  return (
    <div className={cn("group flex max-w-[85%] sm:max-w-[75%] flex-col gap-1.5", isUser ? "ml-auto items-end" : "mr-auto items-start")}>
      <div className={cn("flex items-end gap-2", isUser && "flex-row-reverse")}>
        <div
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] font-bold"
          style={{ background: isUser ? PALETTE.userBubble : PALETTE.accent, color: "#fff" }}
        >
          {isUser ? "You" : initials(msg.botId || "AI")}
        </div>

        <div
          className="px-4 py-3 text-[14.5px] leading-relaxed"
          style={{
            maxWidth: "100%",
            background: isUser ? PALETTE.userBubble : PALETTE.botBubble,
            color: isUser ? PALETTE.userText : PALETTE.ink,
            borderRadius: isUser ? "18px 18px 5px 18px" : "18px 18px 18px 5px",
            boxShadow: isUser ? "none" : "0 4px 14px rgba(58,42,47,0.08)",
          }}
        >
          {isUser && editingMessageId === msg.id ? (
            <div className="flex w-64 flex-col gap-2 sm:w-80">
              <textarea
                value={editingText}
                onChange={(e) => setEditingText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    onSaveEdit(msg);
                  } else if (e.key === "Escape") {
                    onCancelEdit();
                  }
                }}
                rows={2}
                autoFocus
                className="w-full resize-none rounded-xl border border-white/30 bg-white/10 px-3 py-2 text-sm text-white placeholder:text-white/50 focus:outline-none"
              />
              <div className="flex justify-end gap-2">
                <button onClick={onCancelEdit} className="rounded-full px-3 py-1 text-xs font-medium text-white/70 hover:bg-white/10">Cancel</button>
                <button
                  onClick={() => onSaveEdit(msg)}
                  disabled={!editingText.trim()}
                  className="rounded-full bg-white/20 px-3 py-1 text-xs font-semibold text-white hover:bg-white/30 disabled:opacity-50"
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
          ) : !isUser ? (
            <div className="[&>*:last-child]:mb-0">
              <ReactMarkdown components={MARKDOWN_COMPONENTS}>{msg.content}</ReactMarkdown>
            </div>
          ) : (
            <div className="whitespace-pre-wrap">{msg.content}</div>
          )}

          {groups.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5 pt-2.5" style={{ borderTop: "1px solid rgba(58,42,47,0.08)" }}>
              {groups.map((cit, idx) => {
                const label = cit.source.split("/").pop() + citationPageLabel(cit.pages);
                return cit.url ? (
                  <a
                    key={idx}
                    href={cit.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 rounded-full px-3 py-1 text-[11px] font-semibold hover:opacity-80 transition-opacity"
                    style={{ background: PALETTE.chipBg, color: PALETTE.chipText }}
                    title="View Source Document"
                  >
                    {label} <ExternalLink className="h-2.5 w-2.5" />
                  </a>
                ) : (
                  <span key={idx} className="rounded-full px-3 py-1 text-[11px] font-semibold" style={{ background: PALETTE.chipBg, color: PALETTE.chipText }}>
                    {label}
                  </span>
                );
              })}
            </div>
          )}

          {msg.chart && <AnswerChart chart={msg.chart} />}
        </div>
      </div>

      {!isUser && msg.followUpQuestions && msg.followUpQuestions.length > 0 && isLast && (
        <div className="ml-9 flex flex-wrap gap-1.5">
          {msg.followUpQuestions.map((q, idx) => (
            <button
              key={idx}
              onClick={() => onFollowUpClick(q)}
              disabled={isTyping}
              className="rounded-full px-3 py-1.5 text-xs font-medium disabled:opacity-40 hover:opacity-80 transition-opacity"
              style={{ background: "#ffffff", color: PALETTE.ink, border: `1px solid ${PALETTE.chipBg}` }}
            >
              {q} 💬
            </button>
          ))}
        </div>
      )}

      {isUser && !msg.error && editingMessageId !== msg.id && (
        <div className="mr-9 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <button onClick={() => onStartEdit(msg)} title="Edit message" className="rounded-full p-1" style={{ color: "#9a8489" }}>
            <Pencil className="h-3.5 w-3.5" />
          </button>
          <button onClick={() => onCopy(msg.content, msg.id)} title="Copy question" className="rounded-full p-1" style={{ color: "#9a8489" }}>
            {copiedMessageId === msg.id ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
          </button>
        </div>
      )}

      {!isUser && msg.metadata && (
        <div className="ml-9 flex items-center gap-3 text-[11px] font-medium" style={{ color: "#9a8489" }}>
          <span>{msg.metadata.model} · {(msg.metadata.timeMs / 1000).toFixed(1)}s</span>
          <button onClick={() => onCopy(msg.content, msg.id)} title="Copy answer" className="rounded-full p-1 hover:opacity-70">
            {copiedMessageId === msg.id ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
          </button>
          {msg.chatLogId != null && (
            <span className="flex items-center gap-1.5">
              <button onClick={() => onFeedback(msg, "like")} className={cn("rounded-full p-1", msg.feedback === "like" ? "text-emerald-600" : "hover:text-emerald-600")}>
                <ThumbsUp className="h-3.5 w-3.5" />
              </button>
              <button onClick={() => onFeedback(msg, "dislike")} className={cn("rounded-full p-1", msg.feedback === "dislike" ? "text-rose-600" : "hover:text-rose-600")}>
                <ThumbsDown className="h-3.5 w-3.5" />
              </button>
            </span>
          )}
        </div>
      )}

      {commentDraftFor === msg.id && (
        <div className="ml-9 w-full max-w-sm rounded-2xl bg-white p-3 shadow-sm">
          <p className="mb-2 text-xs font-medium" style={{ color: "#9a8489" }}>What went wrong? (optional)</p>
          <textarea
            value={commentText}
            onChange={(e) => setCommentText(e.target.value)}
            placeholder="e.g. missed a detail, wrong source..."
            rows={2}
            className="w-full resize-none rounded-xl px-3 py-2 text-sm placeholder:text-gray-400 focus:outline-none"
            style={{ background: PALETTE.bg, color: PALETTE.ink }}
          />
          <div className="mt-2 flex justify-end gap-2">
            <button onClick={onSkipComment} className="rounded-full px-3 py-1.5 text-xs font-medium" style={{ color: "#9a8489" }}>Skip</button>
            <button
              onClick={() => onSubmitComment(msg)}
              disabled={!commentText.trim()}
              className="rounded-full px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
              style={{ background: PALETTE.accent }}
            >
              Submit
            </button>
          </div>
        </div>
      )}
      {msg.commentSubmitted && commentDraftFor !== msg.id && (
        <p className="ml-9 text-[11px]" style={{ color: "#9a8489" }}>Thanks for the feedback. 💛</p>
      )}
    </div>
  );
}