"use client";

import { useEffect, useState } from "react";
import { api, Bot, AvailableModels, IndexStatus } from "@/lib/api";
import { useAuthReady } from "@/lib/useAuthReady";
import { Bot as BotIcon, Plus, Settings2, Trash2, Edit2, Play, Square, ExternalLink } from "lucide-react";
import { cn } from "@/lib/utils";

export default function BotsPage() {
  const [bots, setBots] = useState<Bot[]>([]);
  const [loading, setLoading] = useState(true);
  const [isEditing, setIsEditing] = useState<Bot | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [allowedGroupsInput, setAllowedGroupsInput] = useState("");
  const [availableModels, setAvailableModels] = useState<AvailableModels>({ llm: [], embedding: [] });
  const [indexStatus, setIndexStatus] = useState<Record<string, IndexStatus>>({});
  const authReady = useAuthReady();

  const openEdit = (bot: Bot) => {
    setIsEditing(bot);
    setIsCreating(false);
    setAllowedGroupsInput(bot.access?.allowed_groups.join(", ") || "");
  };

  const openCreate = () => {
    setIsCreating(true);
    setIsEditing(null);
    setAllowedGroupsInput("");
  };

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
      sharepointLibrary: formData.get("sharepointLibrary") as string,
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

    setIsEditing(null);
    setIsCreating(false);
    setAllowedGroupsInput("");
    loadBots();
  }

  if (loading && bots.length === 0) return <div className="flex h-full items-center justify-center">Loading bots...</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-gray-900">Bot Management</h1>
          <p className="text-sm text-gray-500">Configure and monitor your RAG bots.</p>
        </div>
        <button
          onClick={openCreate}
          className="flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          <Plus className="h-4 w-4" />
          Create Bot
        </button>
      </div>

      {(isCreating || isEditing) ? (
        <div className="rounded-lg border bg-white shadow-sm overflow-hidden">
          <div className="border-b px-6 py-4 flex items-center justify-between bg-gray-50">
            <h3 className="font-semibold text-gray-900">{isCreating ? "Create New Bot" : `Edit Bot: ${isEditing?.name}`}</h3>
            <button 
              onClick={() => { setIsCreating(false); setIsEditing(null); setAllowedGroupsInput(""); }}
              className="text-gray-500 hover:text-gray-700 text-sm font-medium"
            >
              Cancel
            </button>
          </div>
          <form onSubmit={handleSave} className="p-6 space-y-6">
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
              <div>
                <label className="block text-sm font-medium text-gray-700">Bot Name</label>
                <input required name="name" defaultValue={isEditing?.name} className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none" placeholder="e.g. HR Assistant" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">Route</label>
                <input required name="route" defaultValue={isEditing?.route} className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none" placeholder="e.g. /ask/hr" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">SharePoint Site URL</label>
                <input required name="sharepointSite" defaultValue={isEditing?.sharepointSite} className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none" placeholder="https://contoso.sharepoint.com/sites/hr" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">Document Library</label>
                <input required name="sharepointLibrary" defaultValue={isEditing?.sharepointLibrary} className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none" placeholder="e.g. HR Knowledge Base" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">Qdrant Collection Name</label>
                <input required name="qdrantCollection" defaultValue={isEditing?.qdrantCollection || isEditing?.id} className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">LLM Model</label>
                <select name="llmModel" defaultValue={isEditing?.llmModel || availableModels.llm[0] || ""} className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none">
                  {modelOptions(availableModels.llm, isEditing?.llmModel).map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">Embedding Model</label>
                <select name="embeddingModel" defaultValue={isEditing?.embeddingModel || availableModels.embedding[0] || ""} className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none">
                  {modelOptions(availableModels.embedding, isEditing?.embeddingModel).map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">Indexing Schedule (Cron)</label>
                <input name="indexingSchedule" defaultValue={isEditing?.indexingSchedule || "0 0 * * *"} className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none" />
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Allowed Groups (Entra ID Object IDs)</label>
              <p className="text-xs text-gray-500 mb-1">Leave empty to allow all signed-in users. Separate IDs by comma or space.</p>
              <input 
                name="allowedGroups" 
                value={allowedGroupsInput}
                onChange={(e) => setAllowedGroupsInput(e.target.value)}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none" 
                placeholder="e.g. 1234-5678, 9876-5432" 
              />
              <div className="mt-2 flex flex-wrap gap-2">
                {allowedGroupsInput.split(/[\s,]+/).map(g => g.trim()).filter(Boolean).map(g => (
                  <span key={g} className="inline-flex items-center rounded-full bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700 ring-1 ring-inset ring-blue-700/10">
                    {g}
                  </span>
                ))}
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">System Prompt</label>
              <textarea required name="systemPrompt" defaultValue={isEditing?.systemPrompt || "You are a helpful assistant."} rows={4} className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none" />
            </div>
            <div className="flex justify-end">
              <button type="submit" className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700">
                {isCreating ? "Create Bot" : "Save Changes"}
              </button>
            </div>
          </form>
        </div>
      ) : (
        <div className="rounded-lg border bg-white shadow-sm overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Bot</th>
                <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Route</th>
                <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">SharePoint Site</th>
                <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Model</th>
                <th scope="col" className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Documents</th>
                <th scope="col" className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Chunks</th>
                <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                <th scope="col" className="relative px-6 py-3"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {bots.map((bot) => (
                <tr key={bot.id} className="hover:bg-gray-50">
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="flex items-center">
                      <div className="flex-shrink-0 h-10 w-10 flex items-center justify-center rounded-full bg-blue-50">
                        <BotIcon className="h-5 w-5 text-blue-600" />
                      </div>
                      <div className="ml-4">
                        <div className="text-sm font-medium text-gray-900">{bot.name}</div>
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
                        {bot.sharepointLibrary || "Site"}
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
                    <span className={cn("px-2 inline-flex text-xs leading-5 font-semibold rounded-full", bot.enabled ? "bg-green-100 text-green-800" : "bg-gray-100 text-gray-800")}>
                      {bot.enabled ? "Active" : "Disabled"}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                    <div className="flex items-center justify-end gap-3">
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
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
