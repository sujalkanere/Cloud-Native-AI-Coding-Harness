import React, { useState, useEffect, useRef } from "react";
import {
  GitBranch,
  UploadCloud,
  FileArchive,
  Play,
  Shield,
  Layers,
  Clock,
  ExternalLink,
  RefreshCw,
  AlertCircle,
  Terminal,
  Zap,
  Lock,
} from "lucide-react";
import type { Run, VerificationMode } from "../../types/run";
import { api } from "../../services/api";
import { Input } from "../ui/input";
import { Textarea } from "../ui/textarea";
import { Badge } from "../ui/badge";

export interface SessionManagerProps {
  onSelectRun: (runId: string) => void;
}

export function SessionManager({ onSelectRun }: SessionManagerProps) {
  // Form State
  const [sourceType, setSourceType] = useState<"git" | "archive">("git");
  const [repoUrl, setRepoUrl] = useState("");
  const [archiveFile, setArchiveFile] = useState<File | null>(null);
  const [task, setTask] = useState("");
  const [verification, setVerification] = useState<VerificationMode>("required");
  const [formError, setFormError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Runs Table State
  const [runs, setRuns] = useState<Run[]>([]);
  const [isLoadingRuns, setIsLoadingRuns] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const configuratorRef = useRef<HTMLDivElement>(null);

  const fetchRuns = async () => {
    try {
      setIsLoadingRuns(true);
      const data = await api.listRuns();
      setRuns(data || []);
    } catch (err) {
      console.error("Failed to fetch runs:", err);
    } finally {
      setIsLoadingRuns(false);
    }
  };

  useEffect(() => {
    fetchRuns();
  }, []);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFormError(null);
    const files = e.target.files;
    if (!files || files.length === 0) {
      setArchiveFile(null);
      return;
    }

    const file = files[0];
    const maxBytes = 50 * 1024 * 1024; // 50MB limit from Spec §3.6

    if (file.size > maxBytes) {
      setFormError("Archive size exceeds 50MB limit.");
      setArchiveFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      return;
    }

    setArchiveFile(file);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);

    if (!task.trim()) {
      setFormError("Field 'task' is required.");
      return;
    }

    try {
      setIsSubmitting(true);

      let createdRun: Run;
      if (sourceType === "archive" && archiveFile) {
        const formData = new FormData();
        formData.append("task", task.trim());
        if (repoUrl.trim()) formData.append("repo_url", repoUrl.trim());
        formData.append(
          "options",
          JSON.stringify({ verification })
        );
        formData.append("archive", archiveFile);
        createdRun = await api.createRun(formData);
      } else {
        createdRun = await api.createRun({
          task: task.trim(),
          repo_url: repoUrl.trim() || undefined,
          options: { verification },
        });
      }

      // Reset form and transition to RunView
      setTask("");
      setRepoUrl("");
      setArchiveFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      onSelectRun(createdRun.id);
    } catch (err: any) {
      setFormError(err?.message || "Failed to start agent run.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const getStatusBadge = (status: string, isPausing: boolean) => {
    switch (status) {
      case "QUEUED":
        return <Badge variant="secondary" className="rounded-full px-2.5 py-0.5">QUEUED</Badge>;
      case "PREPARING":
        return (
          <Badge variant="info" className="animate-pulse rounded-full px-2.5 py-0.5">
            PREPARING
          </Badge>
        );
      case "RUNNING":
        return (
          <Badge variant="success" className="animate-pulse rounded-full px-2.5 py-0.5">
            {isPausing ? "PAUSING..." : "RUNNING"}
          </Badge>
        );
      case "PAUSED":
        return <Badge variant="warning" className="rounded-full px-2.5 py-0.5">PAUSED</Badge>;
      case "SUCCEEDED":
        return <Badge variant="success" className="rounded-full px-2.5 py-0.5">SUCCEEDED</Badge>;
      case "FAILED":
        return <Badge variant="destructive" className="rounded-full px-2.5 py-0.5">FAILED</Badge>;
      case "TERMINATED":
        return <Badge variant="secondary" className="rounded-full px-2.5 py-0.5">TERMINATED</Badge>;
      default:
        return <Badge variant="outline" className="rounded-full px-2.5 py-0.5">{status}</Badge>;
    }
  };

  const scrollToConfigurator = () => {
    configuratorRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  return (
    <div className="min-h-screen bg-[#0a1317] text-white selection:bg-[#0064e0] selection:text-white font-sans antialiased">
      {/* Meta Top Navigation Bar */}
      <nav className="sticky top-0 z-50 border-b border-slate-800/80 bg-[#0a1317]/95 backdrop-blur-md px-6 py-3.5">
        <div className="mx-auto flex max-w-7xl items-center justify-between">
          <div className="flex items-center space-x-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-[#0064e0] text-white shadow-md">
              <Layers className="h-5 w-5" />
            </div>
            <div>
              <span className="font-bold tracking-tight text-white text-base">
                Cloud-Native AI Coding Harness
              </span>
              <span className="ml-2 hidden rounded-full bg-slate-800 border border-slate-700 px-2 py-0.5 text-[10px] font-mono text-slate-300 sm:inline-block">
                v2.0
              </span>
            </div>
          </div>

          <div className="flex items-center space-x-3">
            <span className="hidden sm:inline-flex items-center rounded-full bg-emerald-950/80 border border-emerald-800/80 px-3 py-1 text-xs text-emerald-300 font-medium">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 mr-2 animate-pulse" />
              Engine Online
            </span>
            <span className="hidden md:inline-flex items-center rounded-full bg-slate-900 border border-slate-700/80 px-3 py-1 text-xs text-slate-300 font-mono">
              ⚡ GROQ (openai/gpt-oss-120b)
            </span>
            <button
              onClick={scrollToConfigurator}
              className="rounded-full bg-white text-black hover:bg-slate-200 px-5 py-2 text-xs font-bold transition-all shadow-sm"
            >
              Start New Run
            </button>
          </div>
        </div>
      </nav>

      {/* Meta Hero Section (Optimistic VF styling & Dual-CTA) */}
      <section className="relative overflow-hidden border-b border-slate-800/80 bg-gradient-to-b from-[#0a1317] via-[#0d1820] to-[#0a1317] px-6 py-16 sm:py-24">
        <div className="mx-auto max-w-4xl text-center space-y-6">
          <div className="inline-flex items-center rounded-full bg-blue-950/60 border border-blue-700/50 px-4 py-1.5 text-xs text-blue-300 font-semibold tracking-wide">
            Autonomous Ephemeral Micro-Sandboxes
          </div>

          <h1 className="text-4xl sm:text-6xl font-medium tracking-tight text-white leading-[1.15]">
            Code with an autonomous AI agent in <span className="text-[#0091ff]">total isolation</span>.
          </h1>

          <p className="mx-auto max-w-2xl text-base sm:text-lg text-slate-300 font-normal leading-relaxed">
            Submit any task or repository. The agent works inside an isolated, hardened Linux sandbox while you steer, monitor execution logs, and inspect changes in a VS Code-style IDE.
          </p>

          <div className="flex flex-wrap items-center justify-center gap-4 pt-4">
            <button
              onClick={scrollToConfigurator}
              className="rounded-full bg-[#0064e0] hover:bg-[#0457cb] text-white px-8 py-3.5 text-sm font-bold transition-all shadow-lg hover:shadow-blue-500/25 flex items-center space-x-2"
            >
              <Play className="h-4 w-4 fill-white" />
              <span>Configure Run Below</span>
            </button>

            <button
              onClick={fetchRuns}
              className="rounded-full border-2 border-slate-700 hover:border-slate-500 text-slate-200 hover:text-white px-7 py-3 text-sm font-bold transition-all flex items-center space-x-2"
            >
              <RefreshCw className={`h-4 w-4 ${isLoadingRuns ? "animate-spin" : ""}`} />
              <span>Refresh Runs ({runs.length})</span>
            </button>
          </div>
        </div>
      </section>

      {/* Main Content Area */}
      <div className="mx-auto max-w-6xl px-6 py-12 space-y-12">
        {/* Meta Configurator Card (card-product-feature, 32px radius) */}
        <div
          ref={configuratorRef}
          className="rounded-[32px] border border-slate-800 bg-[#0f172a]/90 backdrop-blur-xl p-8 sm:p-10 shadow-2xl space-y-8"
        >
          <div>
            <div className="flex items-center space-x-2 text-xs font-bold uppercase tracking-wider text-blue-400">
              <Zap className="h-4 w-4" />
              <span>Agent Configurator</span>
            </div>
            <h2 className="mt-2 text-2xl sm:text-3xl font-medium tracking-tight text-white">
              Start New Coding Run
            </h2>
            <p className="mt-1 text-sm text-slate-400">
              Configure your objective, repository source, and test verification mode.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-8">
            {/* Error Banner */}
            {formError && (
              <div className="flex items-center space-x-3 rounded-2xl border border-rose-800 bg-rose-950/60 p-4 text-xs text-rose-300">
                <AlertCircle className="h-5 w-5 text-rose-400 shrink-0" />
                <span>{formError}</span>
              </div>
            )}

            {/* Source Type Selector (button-pill-tab) */}
            <div className="space-y-3">
              <label className="text-xs font-bold uppercase tracking-wider text-slate-300">
                Workspace Source
              </label>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setSourceType("git")}
                  className={`rounded-full px-5 py-2 text-xs font-bold transition-all flex items-center space-x-2 border ${
                    sourceType === "git"
                      ? "bg-white text-black border-white shadow"
                      : "bg-slate-900/60 text-slate-400 border-slate-800 hover:text-white hover:border-slate-700"
                  }`}
                >
                  <GitBranch className="h-3.5 w-3.5" />
                  <span>Git Repository URL</span>
                </button>

                <button
                  type="button"
                  onClick={() => setSourceType("archive")}
                  className={`rounded-full px-5 py-2 text-xs font-bold transition-all flex items-center space-x-2 border ${
                    sourceType === "archive"
                      ? "bg-white text-black border-white shadow"
                      : "bg-slate-900/60 text-slate-400 border-slate-800 hover:text-white hover:border-slate-700"
                  }`}
                >
                  <UploadCloud className="h-3.5 w-3.5" />
                  <span>Upload Archive</span>
                </button>
              </div>
            </div>

            {/* Source Inputs */}
            {sourceType === "git" ? (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <label className="text-xs text-slate-400">
                    Repository Endpoint (HTTPS)
                  </label>
                  <span className="text-[11px] text-slate-500">
                    Leave blank to initialize clean scratch workspace
                  </span>
                </div>
                <Input
                  type="url"
                  value={repoUrl}
                  onChange={(e) => setRepoUrl(e.target.value)}
                  placeholder="https://github.com/owner/repository.git (or leave blank for scratch workspace)"
                  className="h-12 rounded-xl bg-slate-950 border-slate-800 px-4 text-sm text-slate-200 placeholder:text-slate-600 focus:border-[#0064e0]"
                />
              </div>
            ) : (
              <div className="space-y-2">
                <label className="text-xs text-slate-400">
                  Archive File (up to 50MB, .zip, .tar.gz)
                </label>
                <div className="flex items-center space-x-3">
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".zip,.tar.gz,.tgz,.tar"
                    onChange={handleFileChange}
                    className="hidden"
                    id="archive-upload"
                  />
                  <label
                    htmlFor="archive-upload"
                    className="flex cursor-pointer items-center justify-center rounded-xl border border-dashed border-slate-700 bg-slate-950 px-5 py-3 text-xs text-slate-300 hover:border-[#0064e0] hover:bg-slate-900 transition-colors"
                  >
                    <FileArchive className="mr-2 h-4 w-4 text-blue-400" />
                    {archiveFile ? archiveFile.name : "Choose archive file"}
                  </label>
                  {archiveFile && (
                    <Badge variant="outline" className="rounded-full text-xs font-mono">
                      {(archiveFile.size / (1024 * 1024)).toFixed(2)} MB
                    </Badge>
                  )}
                </div>
              </div>
            )}

            {/* Task Description & Quick Start Pills */}
            <div className="space-y-3">
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
                <label className="text-xs font-bold uppercase tracking-wider text-slate-300">
                  Task Objective <span className="text-rose-400">*</span>
                </label>
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-[11px] text-slate-500">Quick start:</span>
                  <button
                    type="button"
                    onClick={() => {
                      setTask("Build a complete, playable Hangman game in python with clean code structure and write unit tests in test_hangman.py that pass.");
                      setVerification("required");
                      setRepoUrl("");
                    }}
                    className="rounded-full bg-slate-900 hover:bg-slate-800 border border-slate-800 px-3 py-1 text-[11px] font-medium text-blue-300 transition-colors"
                  >
                    🎮 Hangman (with tests)
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setTask("Make me a hangman game in python");
                      setVerification("none");
                      setRepoUrl("");
                    }}
                    className="rounded-full bg-slate-900 hover:bg-slate-800 border border-slate-800 px-3 py-1 text-[11px] font-medium text-emerald-300 transition-colors"
                  >
                    ⚡ Hangman (no tests)
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setTask("Make me a hangman game in rust with cargo project structure and unit tests");
                      setVerification("none");
                      setRepoUrl("");
                    }}
                    className="rounded-full bg-slate-900 hover:bg-slate-800 border border-slate-800 px-3 py-1 text-[11px] font-medium text-orange-400 transition-colors"
                  >
                    🦀 Hangman (Rust)
                  </button>
                </div>
              </div>
              <Textarea
                value={task}
                onChange={(e) => setTask(e.target.value)}
                placeholder="Describe what the agent should implement or fix (e.g. 'Make me a hangman game in python' or 'Fix divide-by-zero bug')..."
                rows={3}
                className="rounded-xl bg-slate-950 border-slate-800 p-3.5 text-sm text-slate-200 placeholder:text-slate-600 focus:border-[#0064e0]"
              />
            </div>

            {/* Verification Mode Selector */}
            <div className="space-y-3">
              <label className="text-xs font-bold uppercase tracking-wider text-slate-300 flex items-center">
                <Shield className="mr-1.5 h-3.5 w-3.5 text-blue-400" />
                Verification Mode
              </label>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div
                  onClick={() => setVerification("required")}
                  className={`cursor-pointer rounded-2xl border p-4 transition-all ${
                    verification === "required"
                      ? "border-[#0064e0] bg-[#0064e0]/10 shadow-sm"
                      : "border-slate-800 bg-slate-950 hover:border-slate-700"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-white">
                      Required (Default)
                    </span>
                    {verification === "required" && (
                      <div className="h-2.5 w-2.5 rounded-full bg-[#0064e0]" />
                    )}
                  </div>
                  <p className="mt-1 text-[11px] text-slate-400 leading-relaxed">
                    Finish requires verified passing tests before completion. Prevents unverified changes.
                  </p>
                </div>

                <div
                  onClick={() => setVerification("none")}
                  className={`cursor-pointer rounded-2xl border p-4 transition-all ${
                    verification === "none"
                      ? "border-[#0064e0] bg-[#0064e0]/10 shadow-sm"
                      : "border-slate-800 bg-slate-950 hover:border-slate-700"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-white">None</span>
                    {verification === "none" && (
                      <div className="h-2.5 w-2.5 rounded-full bg-[#0064e0]" />
                    )}
                  </div>
                  <p className="mt-1 text-[11px] text-slate-400 leading-relaxed">
                    Finish accepted directly (great for scratch prototyping and exploratory coding).
                  </p>
                </div>
              </div>
            </div>

            {/* Submit Button (Meta button-buy-cta) */}
            <div className="pt-2">
              <button
                type="submit"
                disabled={isSubmitting}
                className="w-full sm:w-auto rounded-full bg-[#0064e0] hover:bg-[#0457cb] disabled:opacity-50 text-white px-10 py-4 text-sm font-bold transition-all shadow-lg hover:shadow-blue-500/25 flex items-center justify-center space-x-2"
              >
                {isSubmitting ? (
                  <>
                    <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
                    <span>Initializing Agent Sandbox...</span>
                  </>
                ) : (
                  <>
                    <Play className="mr-2 h-4 w-4 fill-white" />
                    <span>Launch Autonomous Run</span>
                  </>
                )}
              </button>
            </div>
          </form>
        </div>

        {/* Feature Tiles Grid (Meta why-buy-tile, 3 columns) */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="rounded-[24px] border border-slate-800/80 bg-[#0f172a]/60 p-6 space-y-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-blue-950 text-blue-400 border border-blue-800/50">
              <Lock className="h-5 w-5" />
            </div>
            <h3 className="text-base font-bold text-white">Ephemeral Micro-Sandboxes</h3>
            <p className="text-xs text-slate-400 leading-relaxed">
              Every coding run executes in a disposable container sandbox with network isolation and no host access.
            </p>
          </div>

          <div className="rounded-[24px] border border-slate-800/80 bg-[#0f172a]/60 p-6 space-y-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-purple-950 text-purple-400 border border-purple-800/50">
              <Terminal className="h-5 w-5" />
            </div>
            <h3 className="text-base font-bold text-white">Live Monotonic Telemetry</h3>
            <p className="text-xs text-slate-400 leading-relaxed">
              Gap-free serialized event streaming over WebSocket. Watch stdout, stderr, and thoughts in real time.
            </p>
          </div>

          <div className="rounded-[24px] border border-slate-800/80 bg-[#0f172a]/60 p-6 space-y-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-emerald-950 text-emerald-400 border border-emerald-800/50">
              <GitBranch className="h-5 w-5" />
            </div>
            <h3 className="text-base font-bold text-white">Deterministic Git Patches</h3>
            <p className="text-xs text-slate-400 leading-relaxed">
              Binary git diffs against the baseline commit SHA. Export clean, verified patches ready to apply to your repo.
            </p>
          </div>
        </div>

        {/* Recent Runs Table Card */}
        <div className="rounded-[24px] border border-slate-800 bg-[#0f172a]/80 backdrop-blur-xl p-6 sm:p-8 space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-xl font-bold tracking-tight text-white">Recent Coding Sessions</h2>
              <p className="text-xs text-slate-400">Click any session to open it in the VS Code IDE</p>
            </div>
            <span className="rounded-full bg-slate-800 px-3 py-1 text-xs font-mono text-slate-300">
              {runs.length} runs recorded
            </span>
          </div>

          <div className="overflow-hidden rounded-2xl border border-slate-800/80 bg-slate-950/60">
            {runs.length === 0 ? (
              <div className="p-8 text-center text-slate-500 text-sm">
                No coding runs found. Start one above!
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs text-slate-300">
                  <thead className="border-b border-slate-800 bg-slate-900/80 text-[11px] uppercase tracking-wider text-slate-400">
                    <tr>
                      <th className="px-5 py-3.5">Status</th>
                      <th className="px-5 py-3.5">Run ID</th>
                      <th className="px-5 py-3.5">Task Objective</th>
                      <th className="px-5 py-3.5">Verification</th>
                      <th className="px-5 py-3.5">Created</th>
                      <th className="px-5 py-3.5 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60">
                    {runs.map((r) => (
                      <tr
                        key={r.id}
                        className="hover:bg-slate-800/40 transition cursor-pointer"
                        onClick={() => onSelectRun(r.id)}
                      >
                        <td className="px-5 py-4 whitespace-nowrap">
                          {getStatusBadge(r.status, r.is_pausing)}
                        </td>
                        <td className="px-5 py-4 font-mono font-semibold text-white whitespace-nowrap">
                          {r.id}
                        </td>
                        <td className="px-5 py-4 max-w-xs truncate text-slate-200">
                          {r.task}
                        </td>
                        <td className="px-5 py-4 whitespace-nowrap">
                          <span className="rounded-full bg-slate-900 border border-slate-700 px-2.5 py-0.5 text-[10px] font-mono text-slate-300">
                            {r.options?.verification || "required"}
                          </span>
                        </td>
                        <td className="px-5 py-4 whitespace-nowrap text-slate-400">
                          <div className="flex items-center space-x-1.5 font-mono text-[11px]">
                            <Clock className="h-3 w-3 text-slate-500" />
                            <span>{new Date(r.created_at).toLocaleString()}</span>
                          </div>
                        </td>
                        <td className="px-5 py-4 text-right whitespace-nowrap">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              onSelectRun(r.id);
                            }}
                            className="rounded-full bg-slate-800 hover:bg-[#0064e0] hover:text-white px-4 py-1.5 text-xs font-semibold text-slate-300 transition-colors inline-flex items-center space-x-1"
                          >
                            <span>View</span>
                            <ExternalLink className="h-3 w-3" />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
