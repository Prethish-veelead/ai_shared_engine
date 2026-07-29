"use client";

import { useEffect, useState } from "react";
import { api, Bot, AvailableModels, IndexStatus } from "@/lib/api";
import { useAuthReady } from "@/lib/useAuthReady";
import { Bot as BotIcon, Plus, Settings2, Trash2, Edit2, Play, Square, ExternalLink, RefreshCw, RotateCcw } from "lucide-react";
import { cn } from "@/lib/utils";

export default function BotsPage() {
  const [bots, setBots] = useState<Bot[]>([]);
  const [loading, setLoading] = useState(true);
  const [isEditing, setIsEditing] = useState<Bot | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [allowedGroupsInput, setAllowedGroupsInput] = useState("");
  const [availableModels, setAvailableModels] = useState<AvailableModels>({ llm: [], embedding: [] });
  const [indexStatus, setIndexStatus] = useState<Record<string, IndexStatus>>({});
  const [syncStatus, setSyncStatus] = useState<Record<string, { syncing: boolean; message?: string }>>({});
  const [siteUrlInput, setSiteUrlInput] = useState("");
  const [libraryOptions, setLibraryOptions] = useState<string[]>([]);
  const [selectedLibraries, setSelectedLibraries] = useState<string[]>([]);
  const [loadingLibraries, setLoadingLibraries] = useState(false);
  const [libraryError, setLibraryError] = useState("");
  const authReady = useAuthReady();

  const openEdit = (bot: Bot) => {
    setIsEditing(bot);
    setIsCreating(false);
    setAllowedGroupsInput(bot.access?.allowed_groups.join(", ") || "");
    setSiteUrlInput(bot.sharepointSite || "");
    // Seed the picker with the bot's already-configured libraries so they show
    // pre-checked without requiring a live SharePoint call just to open Edit;
    // "Load Libraries" below still works to discover/add others.
    setLibraryOptions(bot.sharepointLibraries || []);
    setSelectedLibraries(bot.sharepointLibraries || []);
    setLibraryError("");
  };

  const openCreate = () => {
    setIsCreating(true);
    setIsEditing(null);
    setAllowedGroupsInput("");
    setSiteUrlInput("");
    setLibraryOptions([]);
    setSelectedLibraries([]);
    setLibraryError("");
  };

  async function handleLoadLibraries() {
    if (!siteUrlInput.trim()) {
      setLibraryError("Enter a SharePoint site URL first.");
      return;
    }
    setLoadingLibraries(true);
    setLibraryError("");
    try {
      const libs = await api.getSharePointLibraries(siteUrlInput.trim());
      // Union with whatever's already selected, so re-loading never silently
      // drops a library that's configured but happens to be missing from
      // this particular response (e.g. a transient Graph hiccup).
      setLibraryOptions((prev) => Array.from(new Set([...prev, ...libs])));
    } catch (error: any) {
      setLibraryError(error?.message || "Failed to load libraries for that site.");
    } finally {
      setLoadingLibraries(false);
    }
  }

  function toggleLibrary(lib: string) {
    setSelectedLibraries((prev) =>
      prev.includes(lib) ? prev.filter((l) => l !== lib) : [...prev, lib]
    );
  }

  useEffect(() => {
    if (!authReady) return;
    loadBots();
    api.getAvailableModels()
      .then(setAvailableModels)
      .catch((error) => console.error("Failed to load available models", error));
    api.getIndexStatus()
      .then((rows) => setIndexStatus(Object.fromEntries(rows.map((r) => [r.bot_id, r]))))
      .catch((error) => console.error("Failed to load index status", error));
  }, [authReady]);

  async function loadBots() {
    setLoading(true);
    try {
      const data = await api.getBots();
      setBots(data);
    } catch (error) {
      console.error(error);
    } finally {
      setLoading(false);
    }
  }

  // Always include the bot's current value even if it's no longer a live
  // deployment (e.g. edited via config directly, or the deployment was since
  // removed), so saving the form can't silently change it out from under you.
  function modelOptions(list: string[], current?: string): string[] {
    return current && !list.includes(current) ? [current, ...list] : list;
  }

  async function handleToggleStatus(bot: Bot) {
    await api.toggleBotStatus(bot.id, !bot.enabled);
    loadBots();
  }

  async function handleDelete(botId: string) {
    if (confirm("Are you sure you want to delete this bot?")) {
      await api.deleteBot(botId);
      loadBots();
    }
  }

  async function handleSave(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const formData = new FormData(e.currentTarget);
    
    const rawGroups = formData.get("allowedGroups") as string;
    const allowed_groups = rawGroups
      .split(/[\s,]+/)
      .map((g) => g.trim())
      .filter((g) => g.length > 0);

    const data: Bot = {
      ...(isEditing || { id: "", enabled: true }),
      name: formData.get("name") as string,
      route: formData.get("route") as string,
      sharepointSite: formData.get("sharepointSite") as string,
      sharepointLibraries: selectedLibraries,
      qdrantCollection: formData.get("qdrantCollection") as string,
      llmModel: formData.get("llmModel") as string,
      embeddingModel: formData.get("embeddingModel") as string,
      indexingSchedule: formData.get("indexingSchedule") as string,
      systemPrompt: formData.get("systemPrompt") as string,
      access: {
        allowed_groups,
      },
    };

    if (isEditing) {
      await api.updateBot(isEditing.id, data);
    } else {
      await api.createBot(data);
    }

    closeForm();
    loadBots();
  }

  function closeForm() {
    setIsEditing(null);
    setIsCreating(false);
    setAllowedGroupsInput("");
    setSiteUrlInput("");
    setLibraryOptions([]);
    setSelectedLibraries([]);
    setLibraryError("");
  }

  if (loading && bots.length === 0) return <div className="flex h-full items-center justify-center">Loading bots...</div>;

  const handleSyncNow = async (bot: Bot) => {
    setSyncStatus((prev) => ({ ...prev, [bot.id]: { syncing: true, message: "Sync started..." } }));
    try {
      await api.syncBotNow(bot.id);
      setTimeout(() => {
        setSyncStatus((prev) => {
          const next = { ...prev };
          delete next[bot.id];
          return next;
        });
        api.getIndexStatus().then(rows => setIndexStatus(Object.fromEntries(rows.map(r => [r.bot_id, r]))));
      }, 5000);
    } catch (err: any) {
      setSyncStatus((prev) => ({ ...prev, [bot.id]: { syncing: false, message: err.message || "Sync failed" } }));
    }
  };

  const handleReindex = async (bot: Bot) => {
    if (!confirm(`Are you sure you want to completely reindex "${bot.name}"?`)) return;
    setSyncStatus((prev) => ({ ...prev, [bot.id]: { syncing: true, message: "Reindex started..." } }));
    try {
      await api.reindexBot(bot.id);
      setTimeout(() => {
        setSyncStatus((prev) => {
          const next = { ...prev };
          delete next[bot.id];
          return next;
        });
        api.getIndexStatus().then(rows => setIndexStatus(Object.fromEntries(rows.map(r => [r.bot_id, r]))));
      }, 5000);
    } catch (err: any) {
      setSyncStatus((prev) => ({ ...prev, [bot.id]: { syncing: false, message: err.message || "Reindex failed" } }));
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-navy">Bot Management</h1>
          <p className="text-sm text-gray-500">Configure and monitor your RAG bots.</p>
        </div>
        <button
          onClick={openCreate}
          className="flex items-center gap-2 rounded-md bg-orange px-4 py-2 text-sm font-medium text-white hover:bg-orange-hover"
        >
          <Plus className="h-4 w-4" />
          Create Bot
        </button>
      </div>

      {(isCreating || isEditing) ? (
        <div className="rounded-lg border bg-white shadow-sm overflow-hidden">
          <div className="border-b px-6 py-4 flex items-center justify-between bg-gray-50">
            <h3 className="font-semibold text-navy">{isCreating ? "Create New Bot" : `Edit Bot: ${isEditing?.name}`}</h3>
            <button
              onClick={closeForm}
              className="text-gray-500 hover:text-gray-700 text-sm font-medium"
            >
              Cancel
            </button>
          </div>
          <form onSubmit={handleSave} className="p-6 space-y-6">
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
              <div>
                <label className="block text-sm font-medium text-gray-700">Bot Name</label>
                <input required name="name" defaultValue={isEditing?.name} className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-orange focus:outline-none" placeholder="e.g. HR Assistant" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">Route</label>
                <input required name="route" defaultValue={isEditing?.route} className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-orange focus:outline-none" placeholder="e.g. /ask/hr" />
              </div>
              <div className="sm:col-span-2">
                <label className="block text-sm font-medium text-gray-700">SharePoint Site URL</label>
                <div className="mt-1 flex gap-2">
                  <input
                    required
                    name="sharepointSite"
                    value={siteUrlInput}
                    onChange={(e) => setSiteUrlInput(e.target.value)}
                    className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-orange focus:outline-none"
                    placeholder="https://contoso.sharepoint.com/sites/hr"
                  />
                  <button
                    type="button"
                    onClick={handleLoadLibraries}
                    disabled={loadingLibraries || !siteUrlInput.trim()}
                    className="shrink-0 rounded-md border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {loadingLibraries ? "Loading..." : "Load Libraries"}
                  </button>
                </div>
                {libraryError && <p className="mt-1 text-xs text-red-600">{libraryError}</p>}
              </div>
              <div className="sm:col-span-2">
                <label className="block text-sm font-medium text-gray-700">Document Libraries</label>
                {libraryOptions.length === 0 ? (
                  <p className="mt-1 text-xs text-gray-500">
                    Click &quot;Load Libraries&quot; above to choose from this site&apos;s real document libraries.
                  </p>
                ) : (
                  <div className="mt-1 max-h-40 space-y-1 overflow-y-auto rounded-md border border-gray-300 p-2">
                    {libraryOptions.map((lib) => (
                      <label key={lib} className="flex items-center gap-2 text-sm text-gray-700">
                        <input
                          type="checkbox"
                          checked={selectedLibraries.includes(lib)}
                          onChange={() => toggleLibrary(lib)}
                          className="rounded border-gray-300"
                        />
                        {lib}
                      </label>
                    ))}
                  </div>
                )}
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">Qdrant Collection Name</label>
                <input required name="qdrantCollection" defaultValue={isEditing?.qdrantCollection || isEditing?.id} className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-orange focus:outline-none" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">LLM Model</label>
                <select name="llmModel" defaultValue={isEditing?.llmModel || availableModels.llm[0] || ""} className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-orange focus:outline-none">
                  {modelOptions(availableModels.llm, isEditing?.llmModel).map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">Embedding Model</label>
                <select name="embeddingModel" defaultValue={isEditing?.embeddingModel || availableModels.embedding[0] || ""} className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-orange focus:outline-none">
                  {modelOptions(availableModels.embedding, isEditing?.embeddingModel).map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">Indexing Schedule (Cron)</label>
                <input name="indexingSchedule" defaultValue={isEditing?.indexingSchedule || "0 0 * * *"} className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-orange focus:outline-none" />
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Allowed Groups (Entra ID Object IDs)</label>
              <p className="text-xs text-gray-500 mb-1">Leave empty to allow all signed-in users. Separate IDs by comma or space.</p>
              <input 
                name="allowedGroups" 
                value={allowedGroupsInput}
                onChange={(e) => setAllowedGroupsInput(e.target.value)}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-orange focus:outline-none" 
                placeholder="e.g. 1234-5678, 9876-5432" 
              />
              <div className="mt-2 flex flex-wrap gap-2">
                {allowedGroupsInput.split(/[\s,]+/).map(g => g.trim()).filter(Boolean).map(g => (
                  <span key={g} className="inline-flex items-center rounded-full bg-info px-2 py-1 text-xs font-medium text-blue-700 ring-1 ring-inset ring-orange/10">
                    {g}
                  </span>
                ))}
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">System Prompt</label>
              <textarea required name="systemPrompt" defaultValue={isEditing?.systemPrompt || "You are a helpful assistant."} rows={4} className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-orange focus:outline-none" />
            </div>
            <div className="flex justify-end">
              <button type="submit" className="rounded-md bg-orange px-4 py-2 text-sm font-medium text-white hover:bg-orange-hover">
                {isCreating ? "Create Bot" : "Save Changes"}
              </button>
            </div>
          </form>
        </div>
      ) : (
        <div className="rounded-lg border bg-white shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-muted uppercase tracking-wider">Bot</th>
                  <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-muted uppercase tracking-wider">Route</th>
                  <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-muted uppercase tracking-wider">SharePoint Site</th>
                  <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-muted uppercase tracking-wider">Model</th>
                  <th scope="col" className="px-6 py-3 text-right text-xs font-medium text-muted uppercase tracking-wider">Documents</th>
                  <th scope="col" className="px-6 py-3 text-right text-xs font-medium text-muted uppercase tracking-wider">Chunks</th>
                  <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-muted uppercase tracking-wider">Status</th>
                  <th scope="col" className="px-6 py-3 text-right text-xs font-medium text-muted uppercase tracking-wider">Actions</th>
                </tr>
              </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {bots.map((bot) => (
                <tr key={bot.id} className="hover:bg-gray-50">
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="flex items-center">
                      <div className="flex-shrink-0 h-10 w-10 flex items-center justify-center rounded-full bg-info">
                        <BotIcon className="h-5 w-5 text-blue-600" />
                      </div>
                      <div className="ml-4">
                        <div className="text-sm font-medium text-navy">{bot.name}</div>
                        <div className="text-sm text-gray-500">ID: {bot.id}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{bot.route}</td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    {bot.sharepointSite ? (
                      <a
                        href={bot.sharepointSite}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-blue-600 hover:text-blue-800 hover:underline"
                        title={bot.sharepointSite}
                      >
                        {bot.sharepointLibraries?.length ? bot.sharepointLibraries.join(", ") : "Site"}
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    ) : "—"}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{bot.llmModel || "Default"}</td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 text-right">
                    {indexStatus[bot.id]?.documents_indexed ?? "—"}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 text-right">
                    {indexStatus[bot.id]?.chunks_indexed ?? "—"}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span className={cn("px-2 inline-flex text-xs leading-5 font-semibold rounded-full", bot.enabled ? "bg-success text-green-800" : "bg-gray-100 text-navy-deep")}>
                      {bot.enabled ? "Active" : "Disabled"}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                    <div className="flex items-center justify-end gap-3">
                      <button
                        onClick={() => handleSyncNow(bot)}
                        disabled={syncStatus[bot.id]?.syncing}
                        title="Sync Now"
                        className="text-gray-400 hover:text-gray-600 disabled:opacity-40 disabled:cursor-not-allowed"
                      >
                        <RefreshCw className={cn("h-4 w-4", syncStatus[bot.id]?.syncing && "animate-spin")} />
                      </button>
                      <button
                        onClick={() => handleReindex(bot)}
                        disabled={syncStatus[bot.id]?.syncing}
                        title="Full Reindex"
                        className="text-gray-400 hover:text-gray-600 disabled:opacity-40 disabled:cursor-not-allowed"
                      >
                        <RotateCcw className="h-4 w-4" />
                      </button>
                      <button onClick={() => handleToggleStatus(bot)} title={bot.enabled ? "Disable" : "Enable"} className="text-gray-400 hover:text-gray-600">
                        {bot.enabled ? <Square className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                      </button>
                      <button onClick={() => openEdit(bot)} title="Edit" className="text-blue-600 hover:text-blue-900">
                        <Edit2 className="h-4 w-4" />
                      </button>
                      <button onClick={() => handleDelete(bot.id)} title="Delete" className="text-red-600 hover:text-red-900">
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                    {syncStatus[bot.id]?.message && (
                      <div className="mt-1 text-xs text-gray-500">{syncStatus[bot.id]?.message}</div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
