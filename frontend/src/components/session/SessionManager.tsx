import React, { useState, useEffect, useRef } from "react";
import {
  GitBranch,
  UploadCloud,
  FileArchive,
  Play,
  Shield,
  Clock,
  ExternalLink,
  RefreshCw,
  AlertCircle,
  Terminal,
  Lock,
  Copy,
  Check,
  Trash2,
} from "lucide-react";
import type { Run, VerificationMode } from "../../types/run";
import { api } from "../../services/api";
import { Input } from "../ui/input";
import { Textarea } from "../ui/textarea";
import { SandboxHero3D } from "./SandboxHero3D";

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
  const [multiAgent, setMultiAgent] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [copiedCli, setCopiedCli] = useState(false);

  // Runs Table State
  const [runs, setRuns] = useState<Run[]>([]);
  const [isLoadingRuns, setIsLoadingRuns] = useState(false);
  const [deletingRunId, setDeletingRunId] = useState<string | null>(null);
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
        formData.append("options", JSON.stringify(multiAgent ? { verification, multi_agent: true } : { verification }));
        formData.append("archive", archiveFile);
        createdRun = await api.createRun(formData);
      } else {
        createdRun = await api.createRun({
          task: task.trim(),
          repo_url: repoUrl.trim() || undefined,
          options: multiAgent ? { verification, multi_agent: true } : { verification },
        });
      }

      setTask("");
      setRepoUrl("");
      setArchiveFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      onSelectRun(createdRun.id);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to start agent run.";
      setFormError(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCopyCli = async () => {
    try {
      await navigator.clipboard.writeText("docker run --read-only --network=none --user 1000:1000 harness-sandbox");
      setCopiedCli(true);
      setTimeout(() => setCopiedCli(false), 1800);
    } catch {
      // ignore
    }
  };

  const getStatusIndicator = (status: string, isPausing: boolean) => {
    const label = isPausing ? "PAUSING" : status;
    let dotColor = "bg-[#85858b]";
    let textColor = "text-[#a1a1a6]";

    switch (status) {
      case "RUNNING":
        dotColor = "bg-[#4cc38a]";
        textColor = "text-[#ededed]";
        break;
      case "PREPARING":
        dotColor = "bg-[#2f81f7]";
        textColor = "text-[#ededed]";
        break;
      case "PAUSED":
        dotColor = "bg-[#d29922]";
        textColor = "text-[#d29922]";
        break;
      case "SUCCEEDED":
        dotColor = "bg-[#4cc38a]";
        textColor = "text-[#4cc38a]";
        break;
      case "FAILED":
        dotColor = "bg-[#e5484d]";
        textColor = "text-[#e5484d]";
        break;
      default:
        break;
    }

    return (
      <span className={`inline-flex items-center gap-2 font-mono text-xs ${textColor}`}>
        <span className={`h-1.5 w-1.5 rounded-full ${dotColor}`} />
        <span>{label}</span>
      </span>
    );
  };

  const handleDeleteRun = async (runId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      setDeletingRunId(runId);
      await api.deleteRun(runId);
      setRuns((prev) => prev.filter((r) => r.id !== runId));
    } catch (err) {
      console.error("Failed to delete run:", err);
    } finally {
      setDeletingRunId(null);
    }
  };

  return (
    <div className="min-h-screen bg-[#111113] text-[#ededed] selection:bg-[#2f81f7]/30 selection:text-[#ededed] font-sans antialiased">
      {/* Quiet Top Navigation */}
      <header className="sticky top-0 z-50 h-14 border-b border-white/[0.08] bg-[#111113]/90 backdrop-blur-md">
        <div className="mx-auto flex h-full max-w-7xl items-center justify-between px-6">
          <div className="flex items-center gap-3">
            {/* Simple geometric flat sandbox mark */}
            <div className="flex h-7 w-7 items-center justify-center rounded-md border border-white/[0.12] bg-[#161619]">
              <div className="h-3 w-3 rounded-[2px] border border-[#ededed]" />
            </div>
            <span className="text-[15px] font-medium tracking-tight text-[#ededed]">
              Cloud-Native AI Coding Harness
            </span>
          </div>
        </div>
      </header>

      {/* Asymmetric Split Hero */}
      <section className="border-b border-white/[0.08]">
        <div className="mx-auto max-w-7xl px-6 pt-16 pb-20 lg:pt-24 lg:pb-24">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-12 lg:gap-10 items-center animate-enter">
            {/* Left: Editorial Framing & Actions */}
            <div className="lg:col-span-6 space-y-6">
              <div className="inline-flex items-center gap-2 text-xs font-mono text-[#a1a1a6]">
                <span className="h-1.5 w-1.5 rounded-full bg-[#2f81f7]" />
                <span>Ephemeral Linux micro-sandboxes</span>
              </div>

              <h1 className="text-4xl sm:text-5xl lg:text-[58px] font-normal tracking-[-0.03em] leading-[1.04] text-[#ededed]">
                Isolated sandboxes for{" "}
                <span className="font-display text-[1.12em] text-white">
                  coding agents
                </span>
              </h1>

              <p className="max-w-[34rem] text-[17px] leading-[1.6] text-[#a1a1a6]">
                Submit a repository or scratch prompt. Every run boots a read-only container with zero network egress while you steer, diff, and run code live.
              </p>

              {/* Signature CLI Spec Strip */}
              <div className="pt-2">
                <button
                  type="button"
                  onClick={handleCopyCli}
                  className="group inline-flex max-w-full items-center gap-3 rounded-lg border border-white/[0.08] bg-[#0b0b0d] px-3.5 py-2 text-left font-mono text-xs text-[#a1a1a6] hover:border-white/[0.14] transition-colors"
                >
                  <span className="text-[#85858b]">$</span>
                  <span className="truncate">
                    docker run --read-only --network=none --user 1000:1000
                  </span>
                  {copiedCli ? (
                    <Check className="h-3.5 w-3.5 shrink-0 text-[#4cc38a]" strokeWidth={1.5} />
                  ) : (
                    <Copy className="h-3.5 w-3.5 shrink-0 text-[#85858b] group-hover:text-[#ededed]" strokeWidth={1.5} />
                  )}
                </button>
              </div>
            </div>

            {/* Right: Interactive 3D Container Visual */}
            <div className="lg:col-span-6">
              <SandboxHero3D />
            </div>
          </div>
        </div>
      </section>

      {/* Main Workbench */}
      <main className="mx-auto max-w-7xl px-6 py-16 space-y-16">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
          {/* Configurator Card (7 cols) */}
          <div
            ref={configuratorRef}
            className="lg:col-span-7 rounded-2xl border border-white/[0.08] bg-[#161619] p-6 sm:p-8 space-y-6"
          >
            <div className="space-y-1">
              <h2 className="text-2xl font-medium tracking-[-0.02em] text-[#ededed]">
                Start New Coding Run
              </h2>
              <p className="text-sm text-[#a1a1a6]">
                Configure your repository source, objective, and test verification mode
              </p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-6">
              {formError && (
                <div className="flex items-center gap-3 rounded-lg border border-[#e5484d]/40 bg-[#e5484d]/10 px-4 py-3 text-xs text-[#e5484d]">
                  <AlertCircle className="h-4 w-4 shrink-0" strokeWidth={1.5} />
                  <span>{formError}</span>
                </div>
              )}

              {/* Workspace Source */}
              <div className="space-y-2.5">
                <label className="block text-sm font-medium text-[#ededed]">
                  Workspace source
                </label>
                <div className="inline-flex rounded-lg border border-white/[0.08] bg-[#0b0b0d] p-1">
                  <button
                    type="button"
                    onClick={() => setSourceType("git")}
                    className={`inline-flex items-center gap-2 rounded-md px-3.5 py-1.5 text-xs font-medium transition-colors ${
                      sourceType === "git"
                        ? "bg-[#1e1e22] text-[#ededed] border border-white/[0.08]"
                        : "text-[#85858b] hover:text-[#ededed] border border-transparent"
                    }`}
                  >
                    <GitBranch className="h-3.5 w-3.5" strokeWidth={1.5} />
                    <span>Git Repository URL</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => setSourceType("archive")}
                    className={`inline-flex items-center gap-2 rounded-md px-3.5 py-1.5 text-xs font-medium transition-colors ${
                      sourceType === "archive"
                        ? "bg-[#1e1e22] text-[#ededed] border border-white/[0.08]"
                        : "text-[#85858b] hover:text-[#ededed] border border-transparent"
                    }`}
                  >
                    <UploadCloud className="h-3.5 w-3.5" strokeWidth={1.5} />
                    <span>Upload Archive</span>
                  </button>
                </div>
              </div>

              {/* Source Input */}
              {sourceType === "git" ? (
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <label htmlFor="repo-url-input" className="text-xs text-[#a1a1a6]">
                      Repository endpoint (HTTPS)
                    </label>
                    <span className="text-xs text-[#85858b]">
                      Optional for scratch workspace
                    </span>
                  </div>
                  <Input
                    id="repo-url-input"
                    name="repo_url"
                    type="url"
                    value={repoUrl}
                    onChange={(e) => setRepoUrl(e.target.value)}
                    placeholder="https://github.com/owner/repository.git (or leave blank for scratch workspace)"
                    className="h-10 rounded-lg bg-[#0b0b0d] border-white/[0.08] px-3.5 text-sm text-[#ededed] placeholder:text-[#85858b] focus-visible:ring-1 focus-visible:ring-[#2f81f7] focus-visible:border-[#2f81f7]"
                  />
                </div>
              ) : (
                <div className="space-y-2">
                  <label className="block text-xs text-[#a1a1a6]">
                    Archive file (up to 50MB, .zip, .tar.gz)
                  </label>
                  <div className="flex items-center gap-3">
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
                      className="inline-flex h-10 cursor-pointer items-center gap-2 rounded-lg border border-dashed border-white/[0.14] bg-[#0b0b0d] px-4 text-xs text-[#ededed] hover:border-white/[0.24] transition-colors"
                    >
                      <FileArchive className="h-4 w-4 text-[#a1a1a6]" strokeWidth={1.5} />
                      <span>{archiveFile ? archiveFile.name : "Choose archive file"}</span>
                    </label>
                    {archiveFile && (
                      <span className="font-mono text-xs text-[#a1a1a6] tabular-nums">
                        {(archiveFile.size / (1024 * 1024)).toFixed(2)} MB
                      </span>
                    )}
                  </div>
                </div>
              )}

              {/* Task Description */}
              <div className="space-y-2.5">
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
                  <label htmlFor="task-objective-input" className="text-sm font-medium text-[#ededed]">
                    Task objective
                  </label>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-xs text-[#85858b]">Presets:</span>
                    <button
                      type="button"
                      onClick={() => {
                        setTask("Make me a coffee website, make the website attractive and beautiful.");
                        setVerification("none");
                        setMultiAgent(true);
                        setRepoUrl("");
                      }}
                      className="rounded-md border border-[#2f81f7]/30 bg-[#2f81f7]/10 hover:bg-[#2f81f7]/20 px-2.5 py-1 text-xs text-[#ededed] transition-colors"
                    >
                      Coffee website (5-agent)
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setTask("Build a complete, playable Hangman game in python with clean code structure and write unit tests in test_hangman.py that pass.");
                        setVerification("required");
                        setRepoUrl("");
                      }}
                      className="rounded-md border border-white/[0.08] bg-[#1e1e22] hover:bg-[#27272c] px-2.5 py-1 text-xs text-[#a1a1a6] hover:text-[#ededed] transition-colors"
                    >
                      Hangman (with tests)
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setTask("Make me a hangman game in python");
                        setVerification("none");
                        setRepoUrl("");
                      }}
                      className="rounded-md border border-white/[0.08] bg-[#1e1e22] hover:bg-[#27272c] px-2.5 py-1 text-xs text-[#a1a1a6] hover:text-[#ededed] transition-colors"
                    >
                      Hangman (no tests)
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setTask("Make me a hangman game in rust with cargo project structure and unit tests");
                        setVerification("none");
                        setRepoUrl("");
                      }}
                      className="rounded-md border border-white/[0.08] bg-[#1e1e22] hover:bg-[#27272c] px-2.5 py-1 text-xs text-[#a1a1a6] hover:text-[#ededed] transition-colors"
                    >
                      Hangman (Rust)
                    </button>
                  </div>
                </div>
                <Textarea
                  id="task-objective-input"
                  name="task"
                  value={task}
                  onChange={(e) => setTask(e.target.value)}
                  placeholder="Describe what the agent should implement or fix (e.g. 'Make me a hangman game in python' or 'Fix divide-by-zero bug')..."
                  rows={4}
                  className="rounded-lg bg-[#0b0b0d] border-white/[0.08] p-3.5 text-sm text-[#ededed] placeholder:text-[#85858b] focus-visible:ring-1 focus-visible:ring-[#2f81f7] focus-visible:border-[#2f81f7]"
                />
              </div>

              {/* Verification Mode */}
              <div className="space-y-2.5">
                <label className="flex items-center gap-2 text-sm font-medium text-[#ededed]">
                  <Shield className="h-4 w-4 text-[#a1a1a6]" strokeWidth={1.5} />
                  <span>Verification mode</span>
                </label>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div
                    onClick={() => setVerification("required")}
                    className={`cursor-pointer rounded-xl border p-4 transition-colors ${
                      verification === "required"
                        ? "border-[#2f81f7] bg-[#2f81f7]/[0.06]"
                        : "border-white/[0.08] bg-[#0b0b0d] hover:border-white/[0.14]"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium text-[#ededed]">
                        Required (Default)
                      </span>
                      <span
                        className={`h-2 w-2 rounded-full ${
                          verification === "required" ? "bg-[#2f81f7]" : "bg-white/[0.12]"
                        }`}
                      />
                    </div>
                    <p className="mt-1.5 text-xs text-[#a1a1a6] leading-relaxed">
                      Requires verified passing tests before the run can finish
                    </p>
                  </div>

                  <div
                    onClick={() => setVerification("none")}
                    className={`cursor-pointer rounded-xl border p-4 transition-colors ${
                      verification === "none"
                        ? "border-[#2f81f7] bg-[#2f81f7]/[0.06]"
                        : "border-white/[0.08] bg-[#0b0b0d] hover:border-white/[0.14]"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium text-[#ededed]">None</span>
                      <span
                        className={`h-2 w-2 rounded-full ${
                          verification === "none" ? "bg-[#2f81f7]" : "bg-white/[0.12]"
                        }`}
                      />
                    </div>
                    <p className="mt-1.5 text-xs text-[#a1a1a6] leading-relaxed">
                      Finishes directly without test gate for scratch prototyping
                    </p>
                  </div>
                </div>
              </div>

              {/* Agent Orchestration Mode */}
              <div className="space-y-2.5">
                <label className="block text-sm font-medium text-[#ededed]">
                  Agent orchestration
                </label>
                <div className="inline-flex rounded-lg border border-white/[0.08] bg-[#0b0b0d] p-1">
                  <button
                    type="button"
                    onClick={() => setMultiAgent(false)}
                    className={`rounded-md px-3.5 py-1.5 text-xs font-medium transition-colors ${
                      !multiAgent
                        ? "bg-[#1e1e22] text-[#ededed] border border-white/[0.08]"
                        : "text-[#85858b] hover:text-[#ededed] border border-transparent"
                    }`}
                  >
                    Single agent
                  </button>
                  <button
                    type="button"
                    onClick={() => setMultiAgent(true)}
                    className={`rounded-md px-3.5 py-1.5 text-xs font-medium transition-colors ${
                      multiAgent
                        ? "bg-[#1e1e22] text-[#ededed] border border-white/[0.08]"
                        : "text-[#85858b] hover:text-[#ededed] border border-transparent"
                    }`}
                  >
                    Multi-agent swarm (5 parallel)
                  </button>
                </div>
              </div>

              {/* Submit */}
              <div className="pt-2">
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="inline-flex h-11 w-full sm:w-auto items-center justify-center gap-2 rounded-lg bg-[#ededed] hover:bg-white disabled:opacity-50 px-6 text-sm font-medium text-[#0b0b0d] transition-colors"
                >
                  {isSubmitting ? (
                    <>
                      <RefreshCw className="h-4 w-4 animate-spin" strokeWidth={1.5} />
                      <span>Initializing sandbox...</span>
                    </>
                  ) : (
                    <>
                      <Play className="h-4 w-4 fill-current" strokeWidth={1.5} />
                      <span>Launch Autonomous Run</span>
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>

          {/* Architecture Guarantees (5 cols) */}
          <div className="lg:col-span-5 space-y-4">
            <div className="rounded-2xl border border-white/[0.08] bg-[#161619] divide-y divide-white/[0.08]">
              <div className="p-6 space-y-1.5">
                <div className="flex items-center gap-2.5 text-sm font-medium text-[#ededed]">
                  <Lock className="h-4 w-4 text-[#a1a1a6]" strokeWidth={1.5} />
                  <span>Kernel-level containment</span>
                </div>
                <p className="text-xs text-[#a1a1a6] leading-relaxed pl-6">
                  Non-root UID 1000, read-only root filesystem, dropped Linux capabilities, and no network egress.
                </p>
              </div>

              <div className="p-6 space-y-1.5">
                <div className="flex items-center gap-2.5 text-sm font-medium text-[#ededed]">
                  <Terminal className="h-4 w-4 text-[#a1a1a6]" strokeWidth={1.5} />
                  <span>Interactive PTY shell</span>
                </div>
                <p className="text-xs text-[#a1a1a6] leading-relaxed pl-6">
                  Bidirectional WebSocket bash session with full stdin/stdout support for CLI programs and tests.
                </p>
              </div>

              <div className="p-6 space-y-1.5">
                <div className="flex items-center gap-2.5 text-sm font-medium text-[#ededed]">
                  <GitBranch className="h-4 w-4 text-[#a1a1a6]" strokeWidth={1.5} />
                  <span>Deterministic git patches</span>
                </div>
                <p className="text-xs text-[#a1a1a6] leading-relaxed pl-6">
                  Every change is diffed against the baseline commit SHA and exportable as a clean patch.
                </p>
              </div>
            </div>

            {/* App Workflow Diagram */}
            <div className="rounded-2xl border border-white/[0.08] bg-[#161619] p-6 space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-[#ededed]">Execution workflow</span>
                <span className="font-mono text-[11px] text-[#85858b]">4 stages</span>
              </div>

              <div className="space-y-0">
                {[
                  {
                    step: "01",
                    title: "Prompt or repository",
                    meta: "Clone Git URL, upload archive, or start scratch",
                  },
                  {
                    step: "02",
                    title: "Ephemeral micro-sandbox",
                    meta: "Read-only rootfs, UID 1000, zero network egress",
                  },
                  {
                    step: "03",
                    title: "Live IDE & PTY shell",
                    meta: "Edit code, preview HTML, steer agent, run tests",
                  },
                  {
                    step: "04",
                    title: "Deterministic git patch",
                    meta: "Diffed against baseline SHA, ready to export",
                  },
                ].map((item, idx, arr) => (
                  <div key={item.step} className="flex gap-3.5">
                    <div className="flex flex-col items-center">
                      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-white/[0.1] bg-[#0b0b0d] font-mono text-[11px] text-[#ededed] tabular-nums">
                        {item.step}
                      </span>
                      {idx < arr.length - 1 && (
                        <div className="w-px flex-1 bg-white/[0.08] my-1" />
                      )}
                    </div>
                    <div className={idx < arr.length - 1 ? "pb-4" : ""}>
                      <div className="text-xs font-medium text-[#ededed]">{item.title}</div>
                      <div className="text-[11px] text-[#85858b] mt-0.5">{item.meta}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Recent Coding Sessions Table */}
        <section
          className="rounded-2xl border border-white/[0.08] bg-[#161619] overflow-hidden"
        >
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-white/[0.08] px-6 py-5">
            <div>
              <h2 className="text-lg font-medium tracking-[-0.01em] text-[#ededed]">
                Recent coding sessions
              </h2>
              <p className="text-xs text-[#a1a1a6]">
                Select any session to inspect files, diffs, and interactive terminal
              </p>
            </div>
            <div className="flex items-center gap-3">
              <span className="font-mono text-xs text-[#85858b] tabular-nums">
                {runs.length} recorded
              </span>
              <button
                type="button"
                onClick={fetchRuns}
                className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-white/[0.08] bg-[#1e1e22] hover:bg-[#27272c] px-3 text-xs text-[#ededed] transition-colors"
              >
                <RefreshCw
                  className={`h-3.5 w-3.5 text-[#a1a1a6] ${isLoadingRuns ? "animate-spin" : ""}`}
                  strokeWidth={1.5}
                />
                <span>Refresh</span>
              </button>
            </div>
          </div>

          {runs.length === 0 ? (
            <div className="px-6 py-12 text-center text-sm text-[#85858b]">
              No coding runs recorded yet
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="border-b border-white/[0.08] bg-[#111113] text-[#85858b]">
                  <tr>
                    <th className="px-6 py-3 font-medium">Status</th>
                    <th className="px-6 py-3 font-medium">Run ID</th>
                    <th className="px-6 py-3 font-medium">Task objective</th>
                    <th className="px-6 py-3 font-medium">Verification</th>
                    <th className="px-6 py-3 font-medium">Created</th>
                    <th className="px-6 py-3 font-medium text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.06]">
                  {runs.map((r) => (
                    <tr
                      key={r.id}
                      onClick={() => onSelectRun(r.id)}
                      className="cursor-pointer hover:bg-[#1e1e22]/60 transition-colors"
                    >
                      <td className="px-6 py-3.5 whitespace-nowrap">
                        {getStatusIndicator(r.status, r.is_pausing)}
                      </td>
                      <td className="px-6 py-3.5 font-mono font-medium text-[#ededed] whitespace-nowrap">
                        {r.id}
                      </td>
                      <td className="px-6 py-3.5 max-w-md truncate text-[#a1a1a6]">
                        {r.task}
                      </td>
                      <td className="px-6 py-3.5 whitespace-nowrap">
                        <span className="rounded border border-white/[0.08] bg-[#0b0b0d] px-2 py-0.5 font-mono text-[11px] text-[#a1a1a6]">
                          {r.options?.verification || "required"}
                        </span>
                      </td>
                      <td className="px-6 py-3.5 whitespace-nowrap font-mono text-[11px] text-[#85858b] tabular-nums">
                        <div className="inline-flex items-center gap-1.5">
                          <Clock className="h-3.5 w-3.5" strokeWidth={1.5} />
                          <span>{new Date(r.created_at).toLocaleString()}</span>
                        </div>
                      </td>
                      <td className="px-6 py-3.5 text-right whitespace-nowrap">
                        <div className="inline-flex items-center gap-2">
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              onSelectRun(r.id);
                            }}
                            className="inline-flex items-center gap-1.5 rounded-lg border border-white/[0.08] bg-[#1e1e22] hover:bg-[#ededed] hover:text-[#0b0b0d] px-3 py-1.5 text-xs font-medium text-[#ededed] transition-colors"
                          >
                            <span>View</span>
                            <ExternalLink className="h-3 w-3" strokeWidth={1.5} />
                          </button>

                          <button
                            type="button"
                            disabled={deletingRunId === r.id}
                            onClick={(e) => handleDeleteRun(r.id, e)}
                            className="inline-flex items-center justify-center rounded-lg border border-white/[0.08] bg-[#1e1e22] hover:border-[#e5484d]/40 hover:bg-[#e5484d]/15 hover:text-[#e5484d] disabled:opacity-50 p-1.5 text-[#85858b] transition-colors"
                            title={`Delete ${r.id}`}
                            aria-label={`Delete ${r.id}`}
                          >
                            <Trash2 className="h-3.5 w-3.5" strokeWidth={1.5} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
