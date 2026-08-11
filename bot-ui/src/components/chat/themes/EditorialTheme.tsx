import ReactMarkdown from "react-markdown";
import { AnswerChart } from "@/components/chat/AnswerChart";
import { citationPageLabel, groupCitations } from "@/lib/citations";
import { cn } from "@/lib/utils";
import { AlertCircle, Check, Copy, ExternalLink, Pencil, ThumbsDown, ThumbsUp } from "lucide-react";
import type { MessageItemProps } from "./types";

// No chat bubbles at all - a question reads as a headline, an answer reads
// as flowing serif prose under it, citations drop to numbered footnotes.
// Matches the reviewed "01 · Editorial Reader" concept exactly - a
// deliberate single fixed palette (cool paper, ink navy, slate-teal), not
// reactive to the app's separate light/dark toggle, same as the mockup
// that was actually reviewed and picked.
const PALETTE = {
  paper: "#eef1f4",
  ink: "#161b22",
  accent: "#3b6e71",
  rule: "#d4d9de",
  muted: "#5c6672",
};

const MARKDOWN_COMPONENTS = {
  p: ({ children }: { children?: React.ReactNode }) => <p className="mb-3 last:mb-0">{children}</p>,
  ul: ({ children }: { children?: React.ReactNode }) => <ul className="mb-3 ml-5 list-disc space-y-1.5 last:mb-0">{children}</ul>,
  ol: ({ children }: { children?: React.ReactNode }) => <ol className="mb-3 ml-5 list-decimal space-y-1.5 last:mb-0">{children}</ol>,
  code: ({ children }: { children?: React.ReactNode }) => (
    <code className="rounded bg-black/5 px-1 py-0.5 font-sans text-[13px]">{children}</code>
  ),
  a: ({ href, children }: { href?: string; children?: React.ReactNode }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" style={{ color: PALETTE.accent }} className="underline">
      {children}
    </a>
  ),
};

export function EditorialMessage(props: MessageItemProps) {
  const {
    msg, isLast, isTyping, editingMessageId, editingText, setEditingText,
    onStartEdit, onSaveEdit, onCancelEdit, onCopy, copiedMessageId,
    onFeedback, commentDraftFor, commentText, setCommentText,
    onSubmitComment, onSkipComment, onFollowUpClick,
  } = props;

  if (msg.role === "user") {
    return (
      <div className="group relative w-full max-w-3xl" style={{ color: PALETTE.ink }}>
        {editingMessageId === msg.id ? (
          <div className="flex flex-col gap-2 pb-5" style={{ borderBottom: `1px solid ${PALETTE.accent}55` }}>
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
              className="w-full resize-none bg-transparent pb-2 font-serif text-xl focus:outline-none"
              style={{ borderBottom: `1px solid ${PALETTE.ink}33`, color: PALETTE.ink }}
            />
            <div className="flex justify-end gap-3 text-xs font-sans font-semibold uppercase tracking-wide">
              <button onClick={onCancelEdit} style={{ color: PALETTE.muted }}>Cancel</button>
              <button onClick={() => onSaveEdit(msg)} disabled={!editingText.trim()} style={{ color: PALETTE.accent }} className="hover:underline disabled:opacity-40">
                Save &amp; Submit
              </button>
            </div>
          </div>
        ) : (
          <>
            <p className="mb-1 font-sans text-[11px] font-bold uppercase tracking-[0.14em]" style={{ color: PALETTE.accent }}>
              Asked
            </p>
            <p className="pb-5 font-serif text-xl leading-snug text-wrap-balance" style={{ borderBottom: `1px solid ${PALETTE.ink}26` }}>
              {msg.content}
            </p>
            <div className="mt-1.5 flex items-center gap-3 opacity-0 group-hover:opacity-100 transition-opacity">
              <button
                onClick={() => onStartEdit(msg)}
                className="inline-flex items-center gap-1 font-sans text-[11px] font-semibold uppercase tracking-wide transition-colors"
                style={{ color: PALETTE.muted }}
              >
                <Pencil className="h-3 w-3" /> Edit
              </button>
              <button
                onClick={() => onCopy(msg.content, msg.id)}
                className="inline-flex items-center gap-1 font-sans text-[11px] font-semibold uppercase tracking-wide transition-colors"
                style={{ color: PALETTE.muted }}
              >
                {copiedMessageId === msg.id ? <Check className="h-3 w-3 text-emerald-600" /> : <Copy className="h-3 w-3" />}
                Copy
              </button>
            </div>
          </>
        )}
      </div>
    );
  }

  const groups = msg.citations ? groupCitations(msg.citations) : [];
  return (
    <div className="w-full max-w-3xl" style={{ color: PALETTE.ink }}>
      {msg.error ? (
        <div className="flex items-center gap-2 text-rose-600">
          <AlertCircle className="h-5 w-5" />
          <span className="font-medium">{msg.error}</span>
        </div>
      ) : (
        <div className="max-w-[62ch] font-serif text-[17px] leading-[1.75] [&>*:last-child]:mb-0">
          <ReactMarkdown components={MARKDOWN_COMPONENTS}>{msg.content}</ReactMarkdown>
        </div>
      )}

      {msg.chart && (
        <div className="max-w-[62ch]">
          <AnswerChart chart={msg.chart} />
        </div>
      )}

      {groups.length > 0 && (
        <div className="mt-5 max-w-[62ch] pt-3 font-sans" style={{ borderTop: `1px solid ${PALETTE.rule}` }}>
          <p className="mb-2 text-[10.5px] font-bold uppercase tracking-[0.14em]" style={{ color: PALETTE.accent }}>
            Referenced
          </p>
          <ol className="space-y-1 text-[12.5px]" style={{ color: PALETTE.muted }}>
            {groups.map((cit, idx) => {
              const label = cit.source.split("/").pop() + citationPageLabel(cit.pages);
              return (
                <li key={idx} className="flex items-center gap-1">
                  <span className="tabular-nums">{idx + 1}.</span>
                  {cit.url ? (
                    <a href={cit.url} target="_blank" rel="noopener noreferrer" style={{ color: PALETTE.accent }} className="inline-flex items-center gap-1 hover:underline">
                      {label} <ExternalLink className="h-2.5 w-2.5" />
                    </a>
                  ) : (
                    <span>{label}</span>
                  )}
                </li>
              );
            })}
          </ol>
        </div>
      )}

      {msg.followUpQuestions && msg.followUpQuestions.length > 0 && isLast && (
        <div className="mt-4 max-w-[62ch] font-sans">
          <p className="mb-2 text-[10.5px] font-bold uppercase tracking-[0.14em]" style={{ color: PALETTE.muted }}>
            Ask next
          </p>
          <div className="flex flex-col gap-1.5">
            {msg.followUpQuestions.map((q, idx) => (
              <button
                key={idx}
                onClick={() => onFollowUpClick(q)}
                disabled={isTyping}
                style={{ color: PALETTE.accent }}
                className="text-left text-[13.5px] hover:underline disabled:opacity-40"
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      )}

      {!msg.error && (
        <div className="mt-3 flex items-center gap-4 font-sans text-[11px]" style={{ color: PALETTE.muted }}>
          {msg.metadata && <span>{msg.metadata.model} · {(msg.metadata.timeMs / 1000).toFixed(1)}s</span>}
          <button onClick={() => onCopy(msg.content, msg.id)} className="inline-flex items-center gap-1 hover:opacity-70 transition-opacity">
            {copiedMessageId === msg.id ? <Check className="h-3 w-3 text-emerald-600" /> : <Copy className="h-3 w-3" />} Copy
          </button>
          {msg.chatLogId != null && (
            <span className="flex items-center gap-2">
              <button
                onClick={() => onFeedback(msg, "like")}
                className={cn("transition-colors", msg.feedback === "like" ? "text-emerald-600" : "hover:text-emerald-600")}
              >
                <ThumbsUp className="h-3.5 w-3.5" />
              </button>
              <button
                onClick={() => onFeedback(msg, "dislike")}
                className={cn("transition-colors", msg.feedback === "dislike" ? "text-rose-600" : "hover:text-rose-600")}
              >
                <ThumbsDown className="h-3.5 w-3.5" />
              </button>
            </span>
          )}
        </div>
      )}

      {commentDraftFor === msg.id && (
        <div className="mt-3 max-w-sm p-3" style={{ border: `1px solid ${PALETTE.rule}` }}>
          <p className="mb-2 font-sans text-xs" style={{ color: PALETTE.muted }}>What went wrong? (optional)</p>
          <textarea
            value={commentText}
            onChange={(e) => setCommentText(e.target.value)}
            placeholder="e.g. missed a detail, wrong source..."
            rows={2}
            className="w-full resize-none bg-transparent px-2 py-1.5 font-sans text-sm placeholder:text-gray-400 focus:outline-none"
            style={{ border: `1px solid ${PALETTE.rule}`, color: PALETTE.ink }}
          />
          <div className="mt-2 flex justify-end gap-3 font-sans text-xs font-semibold uppercase tracking-wide">
            <button onClick={onSkipComment} style={{ color: PALETTE.muted }}>Skip</button>
            <button onClick={() => onSubmitComment(msg)} disabled={!commentText.trim()} style={{ color: PALETTE.accent }} className="hover:underline disabled:opacity-40">
              Submit
            </button>
          </div>
        </div>
      )}
      {msg.commentSubmitted && commentDraftFor !== msg.id && (
        <p className="mt-2 font-sans text-[11px]" style={{ color: PALETTE.muted }}>Thanks for the feedback.</p>
      )}
    </div>
  );
}