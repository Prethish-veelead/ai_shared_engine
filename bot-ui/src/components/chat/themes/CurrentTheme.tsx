import ReactMarkdown from "react-markdown";
import { AnswerChart } from "@/components/chat/AnswerChart";
import { citationPageLabel, groupCitations } from "@/lib/citations";
import { cn } from "@/lib/utils";
import { AlertCircle, Check, Copy, ExternalLink, Pencil, ThumbsDown, ThumbsUp } from "lucide-react";
import type { MessageItemProps } from "./types";

// Today's baseline look (soft glassmorphic bubbles, navy + orange) -
// extracted verbatim from what ChatClient.tsx rendered inline before the
// theme picker existed, so picking "Current" is pixel-identical to before.
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

export function CurrentMessage(props: MessageItemProps) {
  const {
    msg, isLast, isTyping, editingMessageId, editingText, setEditingText,
    onStartEdit, onSaveEdit, onCancelEdit, onCopy, copiedMessageId,
    onFeedback, commentDraftFor, commentText, setCommentText,
    onSubmitComment, onSkipComment, onFollowUpClick,
  } = props;

  return (
    <div
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
                  onSaveEdit(msg);
                } else if (e.key === "Escape") {
                  onCancelEdit();
                }
              }}
              rows={2}
              autoFocus
              className="w-full resize-none rounded-lg border border-white/30 bg-white/10 px-3 py-2 text-sm text-white placeholder:text-white/50 focus:outline-none focus:border-white/60"
            />
            <div className="flex justify-end gap-2">
              <button
                onClick={onCancelEdit}
                className="rounded-lg px-3 py-1 text-xs font-medium text-white/70 hover:bg-white/10 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => onSaveEdit(msg)}
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

        {msg.citations && msg.citations.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-2 pt-3 border-t border-black/5 dark:border-white/10">
            {groupCitations(msg.citations).map((cit, idx) => {
              const label = cit.source.split("/").pop() + citationPageLabel(cit.pages);
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

        {msg.chart && <AnswerChart chart={msg.chart} />}
      </div>

      {msg.role === "bot" && msg.followUpQuestions && msg.followUpQuestions.length > 0 && isLast && (
        <div className="flex flex-wrap gap-2 px-2">
          {msg.followUpQuestions.map((q, idx) => (
            <button
              key={idx}
              onClick={() => onFollowUpClick(q)}
              disabled={isTyping}
              className="rounded-full border border-gray-200 dark:border-navy-deep bg-white/70 dark:bg-navy-deep/50 px-3 py-1.5 text-xs text-navy dark:text-gray-200 hover:border-orange hover:bg-orange/5 dark:hover:bg-orange/10 transition-colors disabled:opacity-50"
            >
              {q}
            </button>
          ))}
        </div>
      )}

      {msg.role === "user" && !msg.error && editingMessageId !== msg.id && (
        <div className="flex items-center gap-1 px-2 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            onClick={() => onStartEdit(msg)}
            title="Edit message"
            className="rounded-md p-1 text-gray-400 dark:text-gray-500 hover:text-orange transition-colors"
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={() => onCopy(msg.content, msg.id)}
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

      {msg.metadata && (
        <div className="px-2 flex items-center gap-3 text-[11px] text-gray-400 dark:text-gray-500 font-medium">
          <span>{msg.metadata.model} • {(msg.metadata.timeMs / 1000).toFixed(1)}s</span>
          <button
            onClick={() => onCopy(msg.content, msg.id)}
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
                onClick={() => onFeedback(msg, "like")}
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
                onClick={() => onFeedback(msg, "dislike")}
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
              onClick={onSkipComment}
              className="rounded-lg px-3 py-1.5 text-xs font-medium text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-navy-deep transition-colors"
            >
              Skip
            </button>
            <button
              onClick={() => onSubmitComment(msg)}
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
  );
}