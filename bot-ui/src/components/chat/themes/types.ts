import type { ChartSpec, Citation } from "@/lib/api";

// A visual theme changes layout/typography/shape, not just color - see
// docs discussion. "current" is today's baseline (soft glassmorphic navy +
// orange), the other three are the reviewed concepts.
export type ChatTheme = "current" | "editorial" | "console" | "companion";

export const CHAT_THEMES: { value: ChatTheme; label: string }[] = [
  { value: "current", label: "Current" },
  { value: "editorial", label: "Editorial Reader" },
  { value: "console", label: "Structured Console" },
  { value: "companion", label: "Warm Companion" },
];

export interface Message {
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
  chart?: ChartSpec;
  followUpQuestions?: string[];
}

// Every theme's per-message component implements this same interface - all
// interactive state/logic stays in ChatClient.tsx, themes only differ in
// how they RENDER a message, never in what a message can do.
export interface MessageItemProps {
  msg: Message;
  isLast: boolean;
  isTyping: boolean;
  editingMessageId: string | null;
  editingText: string;
  setEditingText: (text: string) => void;
  onStartEdit: (msg: Message) => void;
  onSaveEdit: (msg: Message) => void;
  onCancelEdit: () => void;
  onCopy: (text: string, messageId: string) => void;
  copiedMessageId: string | null;
  onFeedback: (msg: Message, feedback: "like" | "dislike") => void;
  commentDraftFor: string | null;
  commentText: string;
  setCommentText: (text: string) => void;
  onSubmitComment: (msg: Message) => void;
  onSkipComment: () => void;
  onFollowUpClick: (question: string) => void;
}