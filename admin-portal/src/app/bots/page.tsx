"use client";

import { useEffect, useRef, useState } from "react";
import { api, Bot, AvailableModels, IndexStatus, deriveBotId } from "@/lib/api";
import { useAuthReady } from "@/lib/useAuthReady";
import { LottieLoader } from "@/components/ui/LottieLoader";
import { Bot as BotIcon, Plus, Settings2, Trash2, Edit2, Play, Square, ExternalLink, RefreshCw, RotateCcw, ThumbsUp, ThumbsDown, Sparkles, Loader2, Braces } from "lucide-react";
import { cn } from "@/lib/utils";

// A bot can pull from more than one SharePoint site, each with its own set
// of libraries (library names are only unique WITHIN a site, so they can't
// be flattened into one shared list without risking a collision). Each
// block below is one site's picker, working exactly like the single picker
// used to, just repeated per site.
interface SiteBlock {
  key: string;
  siteUrlInput: string;
  // The site URL that libraryOptions/selectedLibraries (or listOptions/
  // selectedLists) currently correspond to. Lets handleLoadLibrariesForBlock/
  // handleLoadListsForBlock tell "reload the same site" (safe to union, so a
  // transient Graph hiccup can't silently drop an already-selected entry)
  // apart from "switched to a different site" (must reset - keeping the old
  // site's entries around let a bot get saved pointing at content from a
  // completely different SharePoint site).
  loadedSiteUrl: string | null;
  libraryOptions: string[];
  selectedLibraries: string[];
  loadingLibraries: boolean;
  libraryError: string;
  // Same shape as the library fields above, for a "list" content-type bot -
  // a bot is one or the other (see BotConfig.content_type), never both, so
  // only one set of these is ever populated at a time.
  listOptions: string[];
  selectedLists: string[];
  loadingLists: boolean;
  listError: string;
}

function newSiteBlock(): SiteBlock {
  return {
    key: crypto.randomUUID(),
    siteUrlInput: "",
    loadedSiteUrl: null,
    libraryOptions: [],
    selectedLibraries: [],
    loadingLibraries: false,
    libraryError: "",
    listOptions: [],
    selectedLists: [],
    loadingLists: false,
    listError: "",
  };
}

// Extra fields a bot adds to its /ask response, on top of the fixed base
// fields - purely additive and optional, so unlike SiteBlock these are never
// required. A block with an empty name is just dropped on save rather than
// blocking submission (see handleSave).
interface ResponseFieldBlock {
  key: string;
  name: string;
  prompt: string;
}

function newResponseFieldBlock(): ResponseFieldBlock {
  return { key: crypto.randomUUID(), name: "", prompt: "" };
}

// Clickable starter prompts shown in bot-ui's empty chat state. Same
// repeatable-block pattern as ResponseFieldBlock above - a block with an
// empty text is just dropped on save, not blocking submission.
interface SampleQuestionBlock {
  key: string;
  text: string;
}

function newSampleQuestionBlock(): SampleQuestionBlock {
  return { key: crypto.randomUUID(), text: "" };
}

export default function BotsPage() {
  const [bots, setBots] = useState<Bot[]>([]);
  const [loading, setLoading] = useState(true);
  const [isEditing, setIsEditing] = useState<Bot | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [allowedGroupsInput, setAllowedGroupsInput] = useState("");
  const [availableModels, setAvailableModels] = useState<AvailableModels>({ llm: [], embedding: [] });
  const [indexStatus, setIndexStatus] = useState<Record<string, IndexStatus>>({});
  const [syncStatus, setSyncStatus] = useState<Record<string, { syncing: boolean; message?: string }>>({});
  const [siteBlocks, setSiteBlocks] = useState<SiteBlock[]>([]);
  const [formError, setFormError] = useState("");
  const [responseFieldBlocks, setResponseFieldBlocks] = useState<ResponseFieldBlock[]>([]);
  const [includeCategory, setIncludeCategory] = useState(false);
  const [sampleQuestionBlocks, setSampleQuestionBlocks] = useState<SampleQuestionBlock[]>([]);
  const [showJsonPreview, setShowJsonPreview] = useState(false);
  const [contentType, setContentType] = useState<"library" | "list">("library");
  const authReady = useAuthReady();

  // Name/Route stay uncontrolled (defaultValue, like every other plain field
  // on this form) - these two mirror their live values purely so the Qdrant
  // Collection preview below can recompute as the admin types, without
  // converting the whole form to controlled state.
  const [nameInput, setNameInput] = useState("");
  const [routeInput, setRouteInput] = useState("");
  // Qdrant collection is never hand-typed (Point 1): on create it's derived
  // live from Name/Route with the exact same logic the backend payload uses
  // (deriveBotId), so what you see here is exactly what gets created. On
  // edit it's pinned to the bot's EXISTING collection and never recomputed -
  // vectorstore.collection can't change after creation (the backend rejects
  // that), so re-deriving it from a possibly-edited Route here would just
  // produce a value the save call then fails on.
  const collectionPreview = isEditing
    ? (isEditing.qdrantCollection || isEditing.id)
    : deriveBotId({ name: nameInput, route: routeInput });

  // System Prompt field is uncontrolled (defaultValue, read via FormData on
  // submit, like every other plain text field on this form) - "Improve
  // Prompt" reads/writes it directly through this ref instead of lifting the
  // whole form to controlled state just for one button.
  const systemPromptRef = useRef<HTMLTextAreaElement>(null);
  const [improvingPrompt, setImprovingPrompt] = useState(false);
  const [improveError, setImproveError] = useState("");
  // The exact text the field held right before the last successful "Improve"
  // - only ever set right after a successful improve, cleared on Undo or
  // whenever the form is reset. Nothing is written back to the server until
  // Save/Create is clicked, so Undo is just restoring the textarea's value.
  const [promptBeforeImprove, setPromptBeforeImprove] = useState<string | null>(null);

  const openEdit = (bot: Bot) => {
    setIsEditing(bot);
    setIsCreating(false);
    setAllowedGroupsInput(bot.access?.allowed_groups.join(", ") || "");
    setContentType(bot.contentType || "library");
    // Seed each site's picker with the bot's already-configured libraries/
    // lists so they show pre-checked without requiring a live SharePoint
    // call just to open Edit; "Load Libraries"/"Load Lists" below still
    // works to discover/add others.
    const blocks: SiteBlock[] = bot.sharepointSites && bot.sharepointSites.length > 0
      ? bot.sharepointSites.map((s) => ({
          key: crypto.randomUUID(),
          siteUrlInput: s.siteUrl,
          loadedSiteUrl: s.siteUrl,
          libraryOptions: s.libraries,
          selectedLibraries: s.libraries,
          loadingLibraries: false,
          libraryError: "",
          listOptions: s.lists || [],
          selectedLists: s.lists || [],
          loadingLists: false,
          listError: "",
        }))
      : [newSiteBlock()];
    setSiteBlocks(blocks);
    setFormError("");
    setResponseFieldBlocks(
      (bot.responseFields || []).map((f) => ({ key: crypto.randomUUID(), name: f.name, prompt: f.prompt }))
    );
    setIncludeCategory(bot.includeCategory ?? false);
    setSampleQuestionBlocks(
      (bot.sampleQuestions || []).map((q) => ({ key: crypto.randomUUID(), text: q }))
    );
    setShowJsonPreview(false);
    setPromptBeforeImprove(null);
    setImproveError("");
    setNameInput(bot.name || "");
    setRouteInput(bot.route || "");
  };

  const openCreate = () => {
    setIsCreating(true);
    setIsEditing(null);
    setAllowedGroupsInput("");
    setContentType("library");
    setSiteBlocks([newSiteBlock()]);
    setFormError("");
    setResponseFieldBlocks([]);
    setIncludeCategory(false);
    setSampleQuestionBlocks([]);
    setShowJsonPreview(false);
    setPromptBeforeImprove(null);
    setImproveError("");
    setNameInput("");
    setRouteInput("");
  };

  async function handleImprovePrompt() {
    const textarea = systemPromptRef.current;
    if (!textarea || improvingPrompt) return;

    const current = textarea.value;
    if (!current.trim()) {
      setImproveError("Write a system prompt first, then improve it.");
      return;
    }

    setImprovingPrompt(true);
    setImproveError("");
    try {
      const improved = await api.improveSystemPrompt(current);
      // Nothing is sent to the server here - this only rewrites the field
      // in this open form. Save/Create Bot still has to be clicked for it
      // to actually take effect, same as typing over it by hand.
      setPromptBeforeImprove(current);
      textarea.value = improved;
    } catch (error: any) {
      setImproveError(error.message || "Could not improve the prompt - try again.");
    } finally {
      setImprovingPrompt(false);
    }
  }

  function handleUndoImprove() {
    if (promptBeforeImprove === null || !systemPromptRef.current) return;
    systemPromptRef.current.value = promptBeforeImprove;
    setPromptBeforeImprove(null);
    setImproveError("");
  }

  function addResponseField() {
    setResponseFieldBlocks((prev) => [...prev, newResponseFieldBlock()]);
  }

  function removeResponseField(key: string) {
    setResponseFieldBlocks((prev) => prev.filter((b) => b.key !== key));
  }

  function updateResponseField(key: string, patch: Partial<ResponseFieldBlock>) {
    setResponseFieldBlocks((prev) => prev.map((b) => (b.key === key ? { ...b, ...patch } : b)));
  }

  function addSampleQuestion() {
    setSampleQuestionBlocks((prev) => [...prev, newSampleQuestionBlock()]);
  }

  function removeSampleQuestion(key: string) {
    setSampleQuestionBlocks((prev) => prev.filter((b) => b.key !== key));
  }

  function updateSampleQuestion(key: string, text: string) {
    setSampleQuestionBlocks((prev) => prev.map((b) => (b.key === key ? { ...b, text } : b)));
  }

  // Mirrors AskResponse (ai-search-engine/app/api/routes/ask.py) - the fixed
  // base fields every bot returns, plus whatever this bot's currently
  // configured response_fields/include_category add on top. Recomputed from
  // live form state so the preview always matches what Save would send.
  function buildResponseJsonPreview(): Record<string, unknown> {
    const shape: Record<string, unknown> = {
      answer: "string",
      citations: [{ index: 0, source: "string", page: 0 }],
      model: "string",
      total_tokens: 0,
      cost_usd: 0,
      response_time_ms: 0,
      chat_log_id: 0,
    };
    for (const b of responseFieldBlocks) {
      if (b.name.trim()) shape[b.name.trim()] = "string";
    }
    if (includeCategory) shape.category = "string";
    return shape;
  }

  function updateSiteBlock(key: string, patch: Partial<SiteBlock>) {
    setSiteBlocks((prev) => prev.map((b) => (b.key === key ? { ...b, ...patch } : b)));
  }

  function addSiteBlock() {
    setSiteBlocks((prev) => [...prev, newSiteBlock()]);
  }

  function removeSiteBlock(key: string) {
    setSiteBlocks((prev) => prev.filter((b) => b.key !== key));
  }

  async function handleLoadLibrariesForBlock(key: string) {
    const block = siteBlocks.find((b) => b.key === key);
    if (!block) return;
    const trimmed = block.siteUrlInput.trim();
    if (!trimmed) {
      updateSiteBlock(key, { libraryError: "Enter a SharePoint site URL first." });
      return;
    }
    updateSiteBlock(key, { loadingLibraries: true, libraryError: "" });
    try {
      const libs = await api.getSharePointLibraries(trimmed);
      const isNewSite = trimmed !== block.loadedSiteUrl;
      // Union with whatever's already selected only when re-loading the SAME
      // site, so re-loading never silently drops a library that's configured
      // but happens to be missing from this particular response (e.g. a
      // transient Graph hiccup). A genuinely different site starts fresh.
      setSiteBlocks((prev) => prev.map((b) => b.key === key ? {
        ...b,
        libraryOptions: Array.from(new Set([...(isNewSite ? [] : b.libraryOptions), ...libs])),
        selectedLibraries: isNewSite ? [] : b.selectedLibraries,
        loadedSiteUrl: trimmed,
        loadingLibraries: false,
      } : b));
    } catch (error: any) {
      updateSiteBlock(key, { libraryError: error?.message || "Failed to load libraries for that site.", loadingLibraries: false });
    }
  }

  function toggleLibraryForBlock(key: string, lib: string) {
    setSiteBlocks((prev) => prev.map((b) => {
      if (b.key !== key) return b;
      const selectedLibraries = b.selectedLibraries.includes(lib)
        ? b.selectedLibraries.filter((l) => l !== lib)
        : [...b.selectedLibraries, lib];
      return { ...b, selectedLibraries };
    }));
  }

  async function handleLoadListsForBlock(key: string) {
    const block = siteBlocks.find((b) => b.key === key);
    if (!block) return;
    const trimmed = block.siteUrlInput.trim();
    if (!trimmed) {
      updateSiteBlock(key, { listError: "Enter a SharePoint site URL first." });
      return;
    }
    updateSiteBlock(key, { loadingLists: true, listError: "" });
    try {
      const lists = await api.getSharePointLists(trimmed);
      const isNewSite = trimmed !== block.loadedSiteUrl;
      setSiteBlocks((prev) => prev.map((b) => b.key === key ? {
        ...b,
        listOptions: Array.from(new Set([...(isNewSite ? [] : b.listOptions), ...lists])),
        selectedLists: isNewSite ? [] : b.selectedLists,
        loadedSiteUrl: trimmed,
        loadingLists: false,
      } : b));
    } catch (error: any) {
      updateSiteBlock(key, { listError: error?.message || "Failed to load lists for that site.", loadingLists: false });
    }
  }

  function toggleListForBlock(key: string, list: string) {
    setSiteBlocks((prev) => prev.map((b) => {
      if (b.key !== key) return b;
      const selectedLists = b.selectedLists.includes(list)
        ? b.selectedLists.filter((l) => l !== list)
        : [...b.selectedLists, list];
      return { ...b, selectedLists };
    }));
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

  async function handleDelete(bot: Bot) {
    // Deleting a bot is a full purge, not a soft delete (product decision) -
    // its Chat History, feedback, and Cost/Usage numbers are gone with it,
    // not just the bot config. No "keep the history" option, so the warning
    // has to be explicit since this can't be undone afterward.
    if (confirm(
      `Delete "${bot.name}"?\n\nThis permanently deletes its chat history, feedback, and cost/usage data on top of the bot itself. This cannot be undone.`
    )) {
      await api.deleteBot(bot.id);
      loadBots();
    }
  }

  async function handleSave(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();

    // Without this, a bot can be saved with zero libraries/lists selected (or
    // a dangling site with none checked) - it creates and syncs successfully
    // (nothing to sync from isn't an error), then silently answers "I don't
    // know" to everything forever with no indication anything's wrong.
    const sourceLabel = contentType === "list" ? "list" : "library";
    const hasEmptyBlock = contentType === "list"
      ? siteBlocks.some((b) => b.selectedLists.length === 0)
      : siteBlocks.some((b) => b.selectedLibraries.length === 0);
    if (siteBlocks.length === 0 || hasEmptyBlock) {
      setFormError(`Add at least one SharePoint site with at least one ${sourceLabel} selected before creating this bot.`);
      return;
    }

    const formData = new FormData(e.currentTarget);

    // Point 2: block creating a bot whose derived ID would collide with an
    // existing one. IDs (and, since Point 1, the Qdrant collection too) are
    // derived from Name/Route - without this check two bots could end up
    // silently fighting over the same collection.
    if (!isEditing) {
      const derivedId = deriveBotId({
        name: formData.get("name") as string,
        route: formData.get("route") as string,
      });
      if (bots.some((b) => b.id === derivedId)) {
        setFormError(`A bot already exists with ID "${derivedId}" (derived from this Name/Route) - choose a different Bot Name or Route.`);
        return;
      }
    }

    // Point 3: `required` on the field only enforces "not empty" - a lone
    // "0" or any other non-cron text would otherwise sail through and the
    // bot would just never sync, with no indication why. Require the
    // standard 5 whitespace-separated fields (minute hour day month weekday).
    const cronValue = ((formData.get("indexingSchedule") as string) || "").trim();
    if (cronValue.split(/\s+/).filter(Boolean).length !== 5) {
      setFormError(`Indexing Schedule must be a 5-field cron expression (minute hour day month weekday), e.g. "0 2 * * *" - got "${cronValue}".`);
      return;
    }

    const rawGroups = formData.get("allowedGroups") as string;
    const allowed_groups = rawGroups
      .split(/[\s,]+/)
      .map((g) => g.trim())
      .filter((g) => g.length > 0);

    const data: Bot = {
      ...(isEditing || { id: "", enabled: true }),
      name: formData.get("name") as string,
      route: formData.get("route") as string,
      contentType,
      sharepointSites: siteBlocks.map((b) => ({
        siteUrl: b.loadedSiteUrl || b.siteUrlInput.trim(),
        libraries: contentType === "library" ? b.selectedLibraries : [],
        lists: contentType === "list" ? b.selectedLists : [],
      })),
      qdrantCollection: formData.get("qdrantCollection") as string,
      llmModel: formData.get("llmModel") as string,
      embeddingModel: formData.get("embeddingModel") as string,
      indexingSchedule: formData.get("indexingSchedule") as string,
      systemPrompt: formData.get("systemPrompt") as string,
      access: {
        allowed_groups,
      },
      // Purely additive and optional - an incomplete row (no name typed yet)
      // is just dropped rather than blocking submission like an empty
      // SharePoint library selection does.
      responseFields: responseFieldBlocks
        .filter((b) => b.name.trim().length > 0)
        .map((b) => ({ name: b.name.trim(), prompt: b.prompt.trim() })),
      includeCategory,
      sampleQuestions: sampleQuestionBlocks
        .map((b) => b.text.trim())
        .filter((text) => text.length > 0),
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
    setContentType("library");
    setSiteBlocks([]);
    setFormError("");
    setResponseFieldBlocks([]);
    setPromptBeforeImprove(null);
    setImproveError("");
    setIncludeCategory(false);
    setNameInput("");
    setRouteInput("");
  }

  if (loading && bots.length === 0) return <LottieLoader message="Loading bots..." />;

  // Sync/reindex run in the background on the API side (see api.ts comment
  // on syncBotNow) - there's no "still running" flag, only last_sync_at per
  // bot, so "done" is detected here as last_sync_at advancing past whatever
  // it was right before the job was triggered. A real reindex of a real
  // SharePoint library can easily take longer than a few seconds; a single
  // fixed-delay check used to stop the spinner and leave stale counts on
  // screen with no error, looking like the job silently did nothing.
  async function pollUntilSynced(botId: string, baselineLastSync: string | null | undefined, actionLabel: string) {
    const intervalMs = 3000;
    const maxAttempts = 40; // ~2 minutes ceiling
    // A brand-new bot has no indexStatus entry yet, so baselineLastSync is
    // undefined - but the API always returns last_sync_at as JSON null, never
    // omitted. undefined !== null in JS, so without this normalization the
    // very first poll of a bot's first-ever sync reads as "already changed"
    // (null, the real un-synced value, doesn't strictly-equal undefined,
    // the placeholder for "no data fetched yet") and the spinner stops
    // immediately - even though the real sync is still running in the
    // background for another 30-60+ seconds.
    const baselineNormalized = baselineLastSync ?? null;

    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
      try {
        const rows = await api.getIndexStatus(botId);
        const row = rows.find((r) => r.bot_id === botId);
        if (row) setIndexStatus((prev) => ({ ...prev, [botId]: row }));
        if (row && (row.last_sync_at ?? null) !== baselineNormalized) {
          setSyncStatus((prev) => {
            const next = { ...prev };
            delete next[botId];
            return next;
          });
          return;
        }
      } catch {
        // Transient poll failure - keep trying rather than aborting on one hiccup.
      }
    }

    // Gave up waiting for confirmation, but the job may still be running
    // server-side - say so instead of silently clearing the spinner.
    setSyncStatus((prev) => ({
      ...prev,
      [botId]: { syncing: false, message: `${actionLabel} is taking longer than expected - check back later.` },
    }));
  }

  const handleSyncNow = async (bot: Bot) => {
    const baseline = indexStatus[bot.id]?.last_sync_at;
    setSyncStatus((prev) => ({ ...prev, [bot.id]: { syncing: true, message: "Sync started..." } }));
    try {
      await api.syncBotNow(bot.id);
      pollUntilSynced(bot.id, baseline, "Sync");
    } catch (err: any) {
      setSyncStatus((prev) => ({ ...prev, [bot.id]: { syncing: false, message: err.message || "Sync failed" } }));
    }
  };

  const handleReindex = async (bot: Bot) => {
    if (!confirm(`Are you sure you want to completely reindex "${bot.name}"?`)) return;
    const baseline = indexStatus[bot.id]?.last_sync_at;
    setSyncStatus((prev) => ({ ...prev, [bot.id]: { syncing: true, message: "Reindex started..." } }));
    try {
      await api.reindexBot(bot.id);
      pollUntilSynced(bot.id, baseline, "Reindex");
    } catch (err: any) {
      setSyncStatus((prev) => ({ ...prev, [bot.id]: { syncing: false, message: err.message || "Reindex failed" } }));
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-navy dark:text-white">Bot Management</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">Configure and monitor your RAG bots.</p>
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
        <div className="rounded-lg border border-gray-200 dark:border-navy-deep bg-white dark:bg-card shadow-sm overflow-hidden">
          <div className="border-b border-gray-200 dark:border-navy-deep px-6 py-4 flex items-center justify-between bg-gray-50 dark:bg-navy-deep/40">
            <h3 className="font-semibold text-navy dark:text-white">{isCreating ? "Create New Bot" : `Edit Bot: ${isEditing?.name}`}</h3>
            <button
              onClick={closeForm}
              className="text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 text-sm font-medium"
            >
              Cancel
            </button>
          </div>
          <form key={isCreating ? "create" : isEditing?.id} onSubmit={handleSave} className="p-6 space-y-6">
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">Bot Name</label>
                <input required name="name" defaultValue={isEditing?.name} onChange={(e) => setNameInput(e.target.value)} className="mt-1 block w-full rounded-md border border-gray-300 dark:border-navy-deep bg-white dark:bg-card dark:text-white px-3 py-2 text-sm focus:border-orange focus:outline-none" placeholder="e.g. HR Assistant" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">Route</label>
                <input required name="route" defaultValue={isEditing?.route} onChange={(e) => setRouteInput(e.target.value)} className="mt-1 block w-full rounded-md border border-gray-300 dark:border-navy-deep bg-white dark:bg-card dark:text-white px-3 py-2 text-sm focus:border-orange focus:outline-none" placeholder="e.g. /ask/hr" />
              </div>
              <div className="sm:col-span-2">
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">Content Type</label>
                <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">
                  A bot pulls from either document libraries (files) or SharePoint Lists (rows), not both - and can&apos;t be changed after creation.
                </p>
                <div className="flex gap-4">
                  <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                    <input
                      type="radio"
                      name="contentTypeRadio"
                      checked={contentType === "library"}
                      disabled={!!isEditing}
                      onChange={() => setContentType("library")}
                      className="border-gray-300 dark:border-navy-deep"
                    />
                    Library (files)
                  </label>
                  <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                    <input
                      type="radio"
                      name="contentTypeRadio"
                      checked={contentType === "list"}
                      disabled={!!isEditing}
                      onChange={() => setContentType("list")}
                      className="border-gray-300 dark:border-navy-deep"
                    />
                    List (rows)
                  </label>
                </div>
              </div>
              <div className="sm:col-span-2 space-y-3">
                <div className="flex items-center justify-between">
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">SharePoint Sources</label>
                  <button
                    type="button"
                    onClick={addSiteBlock}
                    className="text-sm font-medium text-orange hover:text-orange-hover"
                  >
                    + Add another SharePoint site
                  </button>
                </div>
                {siteBlocks.map((block, idx) => (
                  <div key={block.key} className="rounded-md border border-gray-300 dark:border-navy-deep p-3 space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Site {idx + 1}</span>
                      {siteBlocks.length > 1 && (
                        <button
                          type="button"
                          onClick={() => removeSiteBlock(block.key)}
                          className="text-xs font-medium text-red-600 dark:text-red-400 hover:underline"
                        >
                          Remove
                        </button>
                      )}
                    </div>
                    <div className="flex gap-2">
                      <input
                        value={block.siteUrlInput}
                        onChange={(e) => updateSiteBlock(block.key, { siteUrlInput: e.target.value })}
                        className="block w-full rounded-md border border-gray-300 dark:border-navy-deep bg-white dark:bg-card dark:text-white px-3 py-2 text-sm focus:border-orange focus:outline-none"
                        placeholder="https://contoso.sharepoint.com/sites/hr"
                      />
                      {contentType === "library" ? (
                        <button
                          type="button"
                          onClick={() => handleLoadLibrariesForBlock(block.key)}
                          disabled={block.loadingLibraries || !block.siteUrlInput.trim()}
                          className="shrink-0 rounded-md border border-gray-300 dark:border-navy-deep bg-white dark:bg-card px-3 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-navy-deep/30 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          {block.loadingLibraries ? "Loading..." : "Load Libraries"}
                        </button>
                      ) : (
                        <button
                          type="button"
                          onClick={() => handleLoadListsForBlock(block.key)}
                          disabled={block.loadingLists || !block.siteUrlInput.trim()}
                          className="shrink-0 rounded-md border border-gray-300 dark:border-navy-deep bg-white dark:bg-card px-3 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-navy-deep/30 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          {block.loadingLists ? "Loading..." : "Load Lists"}
                        </button>
                      )}
                    </div>
                    {contentType === "library" ? (
                      <>
                        {block.libraryError && <p className="text-xs text-red-600 dark:text-red-400">{block.libraryError}</p>}
                        {block.libraryOptions.length === 0 ? (
                          <p className="text-xs text-gray-500 dark:text-gray-400">
                            Click &quot;Load Libraries&quot; above to choose from this site&apos;s real document libraries.
                          </p>
                        ) : (
                          <div className="max-h-40 space-y-1 overflow-y-auto rounded-md border border-gray-300 dark:border-navy-deep p-2">
                            {block.libraryOptions.map((lib) => (
                              <label key={lib} className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                                <input
                                  type="checkbox"
                                  checked={block.selectedLibraries.includes(lib)}
                                  onChange={() => toggleLibraryForBlock(block.key, lib)}
                                  className="rounded border-gray-300 dark:border-navy-deep"
                                />
                                {lib}
                              </label>
                            ))}
                          </div>
                        )}
                      </>
                    ) : (
                      <>
                        {block.listError && <p className="text-xs text-red-600 dark:text-red-400">{block.listError}</p>}
                        {block.listOptions.length === 0 ? (
                          <p className="text-xs text-gray-500 dark:text-gray-400">
                            Click &quot;Load Lists&quot; above to choose from this site&apos;s real SharePoint Lists.
                          </p>
                        ) : (
                          <div className="max-h-40 space-y-1 overflow-y-auto rounded-md border border-gray-300 dark:border-navy-deep p-2">
                            {block.listOptions.map((lst) => (
                              <label key={lst} className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                                <input
                                  type="checkbox"
                                  checked={block.selectedLists.includes(lst)}
                                  onChange={() => toggleListForBlock(block.key, lst)}
                                  className="rounded border-gray-300 dark:border-navy-deep"
                                />
                                {lst}
                              </label>
                            ))}
                          </div>
                        )}
                      </>
                    )}
                  </div>
                ))}
                {formError && <p className="text-xs text-red-600 dark:text-red-400">{formError}</p>}
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">Qdrant Collection Name</label>
                <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">
                  Auto-generated from the Route (or Bot Name as a fallback) - matches the bot&apos;s ID and can never be changed after creation.
                </p>
                <input
                  readOnly
                  disabled
                  value={collectionPreview || "(fill in Route or Bot Name above)"}
                  className="mt-1 block w-full rounded-md border border-gray-300 dark:border-navy-deep bg-gray-50 dark:bg-navy-deep/40 text-gray-500 dark:text-gray-400 px-3 py-2 text-sm cursor-not-allowed"
                />
                <input type="hidden" name="qdrantCollection" value={collectionPreview} />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">LLM Model</label>
                <select name="llmModel" defaultValue={isEditing?.llmModel || availableModels.llm[0] || ""} className="mt-1 block w-full rounded-md border border-gray-300 dark:border-navy-deep bg-white dark:bg-card dark:text-white px-3 py-2 text-sm focus:border-orange focus:outline-none">
                  {modelOptions(availableModels.llm, isEditing?.llmModel).map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">Embedding Model</label>
                <select name="embeddingModel" defaultValue={isEditing?.embeddingModel || availableModels.embedding[0] || ""} className="mt-1 block w-full rounded-md border border-gray-300 dark:border-navy-deep bg-white dark:bg-card dark:text-white px-3 py-2 text-sm focus:border-orange focus:outline-none">
                  {modelOptions(availableModels.embedding, isEditing?.embeddingModel).map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">Indexing Schedule (Cron)</label>
                <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">
                  Standard 5-field cron (minute hour day month weekday), e.g. <code>0 2 * * *</code> for 2 AM daily. Required.
                </p>
                <input required name="indexingSchedule" defaultValue={isEditing?.indexingSchedule || "0 2 * * *"} placeholder="0 2 * * *" className="mt-1 block w-full rounded-md border border-gray-300 dark:border-navy-deep bg-white dark:bg-card dark:text-white px-3 py-2 text-sm focus:border-orange focus:outline-none" />
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">Allowed Groups (Entra ID Object IDs)</label>
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Leave empty to allow all signed-in users. Separate IDs by comma or space.</p>
              <input 
                name="allowedGroups" 
                value={allowedGroupsInput}
                onChange={(e) => setAllowedGroupsInput(e.target.value)}
                className="mt-1 block w-full rounded-md border border-gray-300 dark:border-navy-deep bg-white dark:bg-card dark:text-white px-3 py-2 text-sm focus:border-orange focus:outline-none" 
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
              <div className="flex items-center justify-between">
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">System Prompt</label>
                <button
                  type="button"
                  onClick={handleImprovePrompt}
                  disabled={improvingPrompt}
                  title="Rewrite this prompt with clearer structure and RAG best practices"
                  className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-orange hover:bg-orange/10 disabled:opacity-50 disabled:hover:bg-transparent transition-colors"
                >
                  {improvingPrompt ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Sparkles className="h-3.5 w-3.5" />
                  )}
                  {improvingPrompt ? "Improving..." : "Improve Prompt"}
                </button>
              </div>
              <div className="relative mt-1">
                <textarea
                  ref={systemPromptRef}
                  required
                  name="systemPrompt"
                  defaultValue={isEditing?.systemPrompt || "You are a helpful assistant."}
                  rows={4}
                  disabled={improvingPrompt}
                  className="block w-full rounded-md border border-gray-300 dark:border-navy-deep bg-white dark:bg-card dark:text-white px-3 py-2 text-sm focus:border-orange focus:outline-none disabled:opacity-50"
                />
                {improvingPrompt && (
                  <div className="absolute inset-0 flex items-center justify-center gap-2 rounded-md bg-white/70 dark:bg-card/80 backdrop-blur-[1px] text-sm font-medium text-orange">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Improving prompt...
                  </div>
                )}
              </div>
              {improveError && <p className="mt-1 text-xs text-red-500">{improveError}</p>}
              {promptBeforeImprove !== null && !improveError && (
                <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                  ✓ Improved.{" "}
                  <button type="button" onClick={handleUndoImprove} className="font-medium text-orange hover:underline">
                    Undo
                  </button>
                </p>
              )}
            </div>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">Sample Questions (optional)</label>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    Shown as clickable starter prompts when a user opens this bot for the first time.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={addSampleQuestion}
                  className="shrink-0 text-sm font-medium text-orange hover:text-orange-hover"
                >
                  + Add a question
                </button>
              </div>
              {sampleQuestionBlocks.map((block) => (
                <div key={block.key} className="flex items-center gap-2">
                  <input
                    value={block.text}
                    onChange={(e) => updateSampleQuestion(block.key, e.target.value)}
                    className="block w-full rounded-md border border-gray-300 dark:border-navy-deep bg-white dark:bg-card dark:text-white px-3 py-2 text-sm focus:border-orange focus:outline-none"
                    placeholder="e.g. How do I fix Teams audio not working?"
                  />
                  <button
                    type="button"
                    onClick={() => removeSampleQuestion(block.key)}
                    className="shrink-0 text-xs font-medium text-red-600 dark:text-red-400 hover:underline"
                  >
                    Remove
                  </button>
                </div>
              ))}
            </div>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">Response Fields (optional)</label>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    Extra fields added to this bot&apos;s answer, on top of the standard ones. Generated in the same request - no extra cost or delay.
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-3">
                  <button
                    type="button"
                    onClick={() => setShowJsonPreview((v) => !v)}
                    title="Preview the /ask response JSON structure this bot would return"
                    className="inline-flex items-center gap-1.5 text-sm font-medium text-gray-500 dark:text-gray-400 hover:text-orange"
                  >
                    <Braces className="h-3.5 w-3.5" />
                    {showJsonPreview ? "Hide JSON" : "Preview JSON"}
                  </button>
                  <button
                    type="button"
                    onClick={addResponseField}
                    className="text-sm font-medium text-orange hover:text-orange-hover"
                  >
                    + Add another field
                  </button>
                </div>
              </div>
              {showJsonPreview && (
                <pre className="overflow-x-auto rounded-md border border-gray-300 dark:border-navy-deep bg-gray-50 dark:bg-navy-deep/50 p-3 text-xs text-navy dark:text-gray-200">
                  {JSON.stringify(buildResponseJsonPreview(), null, 2)}
                </pre>
              )}
              {responseFieldBlocks.map((block) => (
                <div key={block.key} className="rounded-md border border-gray-300 dark:border-navy-deep p-3 space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <input
                      value={block.name}
                      onChange={(e) => updateResponseField(block.key, { name: e.target.value })}
                      className="block w-full rounded-md border border-gray-300 dark:border-navy-deep bg-white dark:bg-card dark:text-white px-3 py-2 text-sm focus:border-orange focus:outline-none"
                      placeholder="Field name, e.g. subject"
                    />
                    <button
                      type="button"
                      onClick={() => removeResponseField(block.key)}
                      className="shrink-0 text-xs font-medium text-red-600 dark:text-red-400 hover:underline"
                    >
                      Remove
                    </button>
                  </div>
                  <input
                    value={block.prompt}
                    onChange={(e) => updateResponseField(block.key, { prompt: e.target.value })}
                    className="block w-full rounded-md border border-gray-300 dark:border-navy-deep bg-white dark:bg-card dark:text-white px-3 py-2 text-sm focus:border-orange focus:outline-none"
                    placeholder="What it should contain, e.g. A short title for this question"
                  />
                </div>
              ))}
              <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                <input
                  type="checkbox"
                  checked={includeCategory}
                  onChange={(e) => setIncludeCategory(e.target.checked)}
                  className="rounded border-gray-300 dark:border-navy-deep"
                />
                Include category (from SharePoint metadata, no extra cost)
              </label>
            </div>
            <div className="flex justify-end">
              <button type="submit" className="rounded-md bg-orange px-4 py-2 text-sm font-medium text-white hover:bg-orange-hover">
                {isCreating ? "Create Bot" : "Save Changes"}
              </button>
            </div>
          </form>
        </div>
      ) : (
        <div className="rounded-lg border border-gray-200 dark:border-navy-deep bg-white dark:bg-card shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 dark:divide-navy-deep">
              <thead className="bg-gray-50 dark:bg-navy-deep/40">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium text-muted uppercase tracking-wider">Bot</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium text-muted uppercase tracking-wider">Route</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium text-muted uppercase tracking-wider">SharePoint Site</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium text-muted uppercase tracking-wider">Model</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium text-muted uppercase tracking-wider">Documents</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium text-muted uppercase tracking-wider">Chunks</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium text-muted uppercase tracking-wider">Feedback</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium text-muted uppercase tracking-wider">Status</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium text-muted uppercase tracking-wider">Actions</th>
                </tr>
              </thead>
            <tbody className="bg-white dark:bg-card divide-y divide-gray-200 dark:divide-navy-deep">
              {bots.map((bot) => (
                <tr key={bot.id} className="hover:bg-gray-50 dark:hover:bg-navy-deep/30">
                  <td className="px-4 py-4 whitespace-nowrap">
                    <div className="flex items-center">
                      <div className="flex-shrink-0 h-10 w-10 flex items-center justify-center rounded-full bg-info">
                        <BotIcon className="h-5 w-5 text-blue-600" />
                      </div>
                      <div className="ml-4">
                        <div className="text-sm font-medium text-navy dark:text-white">{bot.name}</div>
                        <div className="text-sm text-gray-500 dark:text-gray-400">ID: {bot.id}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">{bot.route}</td>
                  <td className="px-4 py-4 text-sm text-gray-500 dark:text-gray-400 max-w-[200px] break-words">
                    {bot.sharepointSites && bot.sharepointSites.length > 0 ? (
                      <div className="space-y-1">
                        {bot.sharepointSites.map((site, i) => (
                          <a
                            key={i}
                            href={site.siteUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="flex items-center gap-1 text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 hover:underline"
                            title={site.siteUrl}
                          >
                            {site.libraries.length ? site.libraries.join(", ") : site.lists.length ? site.lists.join(", ") : "Site"}
                            <ExternalLink className="h-3 w-3 shrink-0" />
                          </a>
                        ))}
                      </div>
                    ) : "—"}
                  </td>
                  <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">{bot.llmModel || "Default"}</td>
                  <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400 text-right">
                    {indexStatus[bot.id]?.documents_indexed ?? "—"}
                  </td>
                  <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400 text-right">
                    {indexStatus[bot.id]?.chunks_indexed ?? "—"}
                  </td>
                  <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400 text-right">
                    <span className="inline-flex items-center gap-3">
                      <span className="inline-flex items-center gap-1"><ThumbsUp className="h-3.5 w-3.5" />{indexStatus[bot.id]?.likes ?? 0}</span>
                      <span className="inline-flex items-center gap-1"><ThumbsDown className="h-3.5 w-3.5" />{indexStatus[bot.id]?.dislikes ?? 0}</span>
                    </span>
                  </td>
                  <td className="px-4 py-4 whitespace-nowrap">
                    <span className={cn("px-2 inline-flex text-xs leading-5 font-semibold rounded-full", bot.enabled ? "bg-success text-green-800 dark:text-green-300" : "bg-gray-100 dark:bg-navy-deep text-navy-deep dark:text-gray-300")}>
                      {bot.enabled ? "Active" : "Disabled"}
                    </span>
                  </td>
                  <td className="px-4 py-4 whitespace-nowrap text-right text-sm font-medium">
                    <div className="flex items-center justify-end gap-3">
                      <button
                        onClick={() => handleSyncNow(bot)}
                        disabled={syncStatus[bot.id]?.syncing}
                        title="Sync Now"
                        className="text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 disabled:opacity-40 disabled:cursor-not-allowed"
                      >
                        <RefreshCw className={cn("h-4 w-4", syncStatus[bot.id]?.syncing && "animate-spin")} />
                      </button>
                      <button
                        onClick={() => handleReindex(bot)}
                        disabled={syncStatus[bot.id]?.syncing}
                        title="Full Reindex"
                        className="text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 disabled:opacity-40 disabled:cursor-not-allowed"
                      >
                        <RotateCcw className="h-4 w-4" />
                      </button>
                      <button onClick={() => handleToggleStatus(bot)} title={bot.enabled ? "Disable" : "Enable"} className="text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300">
                        {bot.enabled ? <Square className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                      </button>
                      <button onClick={() => openEdit(bot)} title="Edit" className="text-blue-600 hover:text-blue-900">
                        <Edit2 className="h-4 w-4" />
                      </button>
                      <button onClick={() => handleDelete(bot)} title="Delete" className="text-red-600 hover:text-red-900">
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                    {syncStatus[bot.id]?.message && (
                      <div className="mt-1 text-xs text-gray-500 dark:text-gray-400">{syncStatus[bot.id]?.message}</div>
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
