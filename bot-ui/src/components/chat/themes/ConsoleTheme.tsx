import ReactMarkdown from "react-markdown";
import { AnswerChart } from "@/components/chat/AnswerChart";
import { citationPageLabel, groupCitations } from "@/lib/citations";
import { cn } from "@/lib/utils";
import { AlertCircle, Check, Copy, ExternalLink, Pencil, ThumbsDown, ThumbsUp } from "lucide-react";
import type { MessageItemProps } from "./types";

// Dense, monospace, bordered - reads like a dev console rather than a
// consumer chat app. Matches the reviewed "02 · Structured Console"
// concept - a deliberate single fixed dark palette, not reactive to the
// app's separate light/dark toggle (same reasoning as EditorialTheme).
const PALETTE = {
  bg: "#0a0d12",
  panel: "#12161c",
  border: "#1c2229",
  text: "#d7dde5",
  dim: "#6f7a89",
  accent: "#4fa3d1",
};

const MARKDOWN_COMPONENTS = {
  p: ({ children }: { children?: React.ReactNode }) => <p className="mb-2 last:mb-0">{children}</p>,
  ul: ({ children }: { children?: React.ReactNode }) => <ul className="mb-2 ml-4 list-disc space-y-1 last:mb-0">{children}</ul>,
  ol: ({ children }: { children?: React.ReactNode }) => <ol className="mb-2 ml-4 list-decimal space-y-1 last:mb-0">{children}</ol>,
  code: ({ children }: { children?: React.ReactNode }) => (
    <code className="rounded-sm px-1 py-0.5" style={{ background: PALETTE.panel, border: `1px solid ${PALETTE.border}` }}>{children}</code>
  ),
  a: ({ href, children }: { href?: string; children?: React.ReactNode }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" style={{ color: PALETTE.accent }} className="underline">
      {children}
    </a>
  ),
};

export function ConsoleMessage(props: MessageItemProps) {
  const {
    msg, isLast, isTyping, editingMessageId, editingText, setEditingText,
    onStartEdit, onSaveEdit, onCancelEdit, onCopy, copiedMessageId,
    onFeedback, commentDraftFor, commentText, setCommentText,
    onSubmitComment, onSkipComment, onFollowUpClick,
  } = props;

  const groups = msg.citations ? groupCitations(msg.citations) : [];
  const tag = msg.role === "user" ? "USER" : "BOT";

  return (
    <div
      className="group w-full font-mono text-[12.5px]"
      style={{ background: msg.role === "user" ? PALETTE.panel : "transparent", borderBottom: `1px solid ${PALETTE.border}`, color: PALETTE.text }}
    >
      <div className="flex gap-3 px-4 py-3">
        <span className="w-12 shrink-0 font-bold tracking-wide" style={{ color: msg.role === "user" ? PALETTE.accent : PALETTE.dim }}>
          {tag}
        </span>
        <div className="min-w-0 flex-1">
          {msg.role === "user" && editingMessageId === msg.id ? (
            <div className="flex flex-col gap-2">
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
                className="w-full resize-none bg-transparent p-2 font-mono text-[12.5px] focus:outline-none"
                style={{ border: `1px solid ${PALETTE.accent}`, color: PALETTE.text }}
              />
              <div className="flex justify-end gap-3 text-[11px] font-bold uppercase">
                <button onClick={onCancelEdit} style={{ color: PALETTE.dim }}>cancel</button>
                <button onClick={() => onSaveEdit(msg)} disabled={!editingText.trim()} style={{ color: PALETTE.accent }} className="disabled:opacity-40">
                  submit
                </button>
              </div>
            </div>
          ) : msg.error ? (
            <div className="flex items-center gap-2 text-rose-400">
              <AlertCircle className="h-4 w-4" />
              <span>{msg.error}</span>
            </div>
          ) : msg.role === "bot" ? (
            <div className="leading-relaxed [&>*:last-child]:mb-0">
              <ReactMarkdown components={MARKDOWN_COMPONENTS}>{msg.content}</ReactMarkdown>
            </div>
          ) : (
            <div className="leading-relaxed">{msg.content}</div>
          )}

          {msg.role === "user" && !msg.error && editingMessageId !== msg.id && (
            <div className="mt-1.5 flex items-center gap-3 opacity-0 group-hover:opacity-100 transition-opacity text-[10.5px] uppercase">
              <button onClick={() => onStartEdit(msg)} className="inline-flex items-center gap-1" style={{ color: PALETTE.dim }}>
                <Pencil className="h-2.5 w-2.5" /> edit
              </button>
              <button onClick={() => onCopy(msg.content, msg.id)} className="inline-flex items-center gap-1" style={{ color: PALETTE.dim }}>
                {copiedMessageId === msg.id ? <Check className="h-2.5 w-2.5 text-emerald-400" /> : <Copy className="h-2.5 w-2.5" />} copy
              </button>
            </div>
          )}
        </div>
      </div>

      {msg.chart && (
        <div className="px-4 pb-3">
          <AnswerChart chart={msg.chart} />
        </div>
      )}

      {groups.length > 0 && (
        <div className="mx-4 mb-3 overflow-hidden rounded-sm" style={{ border: `1px solid ${PALETTE.border}` }}>
          <div className="px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider" style={{ background: PALETTE.panel, color: PALETTE.dim, borderBottom: `1px solid ${PALETTE.border}` }}>
            SOURCES · {groups.length}
          </div>
          {groups.map((cit, idx) => {
            const label = cit.source.split("/").pop();
            return (
              <div key={idx} className="flex items-center justify-between px-3 py-2 text-[11.5px]" style={{ borderBottom: idx < groups.length - 1 ? `1px solid ${PALETTE.border}` : "none" }}>
                {cit.url ? (
                  <a href={cit.url} target="_blank" rel="noopener noreferrer" style={{ color: PALETTE.accent }} className="inline-flex items-center gap-1 truncate hover:underline">
                    {label} <ExternalLink className="h-2.5 w-2.5 shrink-0" />
                  </a>
                ) : (
                  <span className="truncate">{label}</span>
                )}
                {cit.pages.length > 0 && <span className="shrink-0 pl-2 tabular-nums" style={{ color: PALETTE.dim }}>{citationPageLabel(cit.pages).trim()}</span>}
              </div>
            );
          })}
        </div>
      )}

      {msg.followUpQuestions && msg.followUpQuestions.length > 0 && isLast && (
        <div className="mx-4 mb-3 flex flex-wrap gap-2">
          {msg.followUpQuestions.map((q, idx) => (
            <button
              key={idx}
              onClick={() => onFollowUpClick(q)}
              disabled={isTyping}
              className="rounded-sm px-2.5 py-1 text-[11px] disabled:opacity-40"
              style={{ border: `1px solid ${PALETTE.border}`, color: PALETTE.accent }}
            >
              &gt; {q}
            </button>
          ))}
        </div>
      )}

      {!msg.error && msg.role === "bot" && (
        <div className="flex items-center gap-4 px-4 pb-3 text-[10.5px]" style={{ color: PALETTE.dim }}>
          {msg.metadata && <span>{msg.metadata.model} · {(msg.metadata.timeMs / 1000).toFixed(1)}s</span>}
          <button onClick={() => onCopy(msg.content, msg.id)} className="inline-flex items-center gap-1">
            {copiedMessageId === msg.id ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />} copy
          </button>
          {msg.chatLogId != null && (
            <span className="flex items-center gap-2">
              <button onClick={() => onFeedback(msg, "like")} className={cn(msg.feedback === "like" ? "text-emerald-400" : "hover:text-emerald-400")}>
                <ThumbsUp className="h-3.5 w-3.5" />
              </button>
              <button onClick={() => onFeedback(msg, "dislike")} className={cn(msg.feedback === "dislike" ? "text-rose-400" : "hover:text-rose-400")}>
                <ThumbsDown className="h-3.5 w-3.5" />
              </button>
            </span>
          )}
        </div>
      )}

      {commentDraftFor === msg.id && (
        <div className="mx-4 mb-3 p-3" style={{ border: `1px solid ${PALETTE.border}` }}>
          <p className="mb-2 text-[11px]" style={{ color: PALETTE.dim }}>what went wrong? (optional)</p>
          <textarea
            value={commentText}
            onChange={(e) => setCommentText(e.target.value)}
            placeholder="e.g. missed a detail, wrong source..."
            rows={2}
            className="w-full resize-none bg-transparent px-2 py-1.5 font-mono text-[12px] placeholder:text-gray-600 focus:outline-none"
            style={{ border: `1px solid ${PALETTE.border}`, color: PALETTE.text }}
          />
          <div className="mt-2 flex justify-end gap-3 text-[11px] font-bold uppercase">
            <button onClick={onSkipComment} style={{ color: PALETTE.dim }}>skip</button>
            <button onClick={() => onSubmitComment(msg)} disabled={!commentText.trim()} style={{ color: PALETTE.accent }} className="disabled:opacity-40">
              submit
            </button>
          </div>
        </div>
      )}
      {msg.commentSubmitted && commentDraftFor !== msg.id && (
        <p className="px-4 pb-3 text-[10.5px]" style={{ color: PALETTE.dim }}>thanks for the feedback.</p>
      )}
    </div>
  );
}