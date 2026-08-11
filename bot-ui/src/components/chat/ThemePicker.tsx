import { Palette } from "lucide-react";
import { CHAT_THEMES, type ChatTheme } from "@/components/chat/themes/types";

export function ThemePicker({ value, onChange }: { value: ChatTheme; onChange: (theme: ChatTheme) => void }) {
  return (
    <label className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-gray-400 dark:text-gray-500 hover:text-navy dark:hover:text-white hover:bg-gray-100 dark:hover:bg-navy-deep/50 transition-colors cursor-pointer">
      <Palette className="h-3.5 w-3.5" />
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as ChatTheme)}
        className="cursor-pointer appearance-none bg-transparent text-xs font-medium text-inherit focus:outline-none"
        aria-label="Chat theme"
      >
        {CHAT_THEMES.map((t) => (
          <option key={t.value} value={t.value} className="text-navy dark:text-white bg-white dark:bg-navy-deep">
            {t.label}
          </option>
        ))}
      </select>
    </label>
  );
}