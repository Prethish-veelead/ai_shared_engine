import { AppShell } from "@/components/layout/AppShell";

export default function Home() {
  return (
    <AppShell>
      <div className="flex h-full items-center justify-center p-6 text-center text-gray-500">
        <div>
          <h2 className="mb-2 text-lg font-semibold text-gray-900">No Bot Selected</h2>
          <p>Please navigate to a specific bot route to start chatting.</p>
          <p className="mt-4 text-sm font-mono bg-gray-100 px-3 py-1 rounded inline-block">
            e.g. /bot/hr
          </p>
        </div>
      </div>
    </AppShell>
  );
}
