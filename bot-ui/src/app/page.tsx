import { AppShell } from "@/components/layout/AppShell";
import { Bot } from "lucide-react";

export default function Home() {
  return (
    <AppShell>
      <div className="flex h-full items-center justify-center p-6 bg-gray-50/30 dark:bg-navy-deep/20">
        <div className="bg-white/50 dark:bg-navy/30 backdrop-blur-md p-10 rounded-3xl border border-white/20 dark:border-white/5 shadow-xl max-w-md text-center">
          <div className="mx-auto flex h-20 w-20 items-center justify-center rounded-3xl bg-orange/10 dark:bg-orange/20 mb-6 shadow-inner">
            <Bot className="h-10 w-10 text-orange" />
          </div>
          <h2 className="mb-3 text-2xl font-bold text-navy dark:text-white tracking-tight">No Assistant Selected</h2>
          <p className="text-gray-500 dark:text-gray-400 mb-6 text-sm leading-relaxed">
            Please select an assistant from the dropdown menu in the header above to start a conversation.
          </p>
          <div className="inline-flex items-center gap-2 text-xs font-mono bg-white/80 dark:bg-navy-deep px-4 py-2 rounded-xl shadow-sm border border-gray-100 dark:border-navy-deep">
            <span className="text-gray-400 dark:text-gray-500">System Ready</span>
            <div className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse"></div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
