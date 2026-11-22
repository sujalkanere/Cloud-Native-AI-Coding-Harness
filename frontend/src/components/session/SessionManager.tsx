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
} from "lucide-react";
import type { Run, VerificationMode } from "../../types/run";
import { api } from "../../services/api";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Textarea } from "../ui/textarea";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../ui/card";
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

    if (sourceType === "git" && !repoUrl.trim() && !archiveFile) {
      // Allowed if scratch environment, but if git is selected and empty, warn
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
        return <Badge variant="secondary">QUEUED</Badge>;
      case "PREPARING":
        return (
          <Badge variant="info" className="animate-pulse">
            PREPARING
          </Badge>
        );
      case "RUNNING":
        return (
          <Badge variant="success" className="animate-pulse">
            {isPausing ? "PAUSING..." : "RUNNING"}
          </Badge>
        );
      case "PAUSED":
        return <Badge variant="warning">PAUSED</Badge>;
      case "SUCCEEDED":
        return <Badge variant="success">SUCCEEDED</Badge>;
      case "FAILED":
        return <Badge variant="destructive">FAILED</Badge>;
      case "TERMINATED":
        return <Badge variant="secondary">TERMINATED</Badge>;
      default:
        return <Badge variant="outline">{status}</Badge>;
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-6 md:p-8">
      <div className="mx-auto max-w-6xl space-y-8">
        {/* Header Banner */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-slate-800 pb-6">
          <div>
            <div className="flex items-center space-x-2">
              <Layers className="h-6 w-6 text-blue-500" />
              <h1 className="text-xl font-bold tracking-tight text-white">
                Cloud-Native AI Coding Harness
              </h1>
            </div>
            <p className="mt-1 text-sm text-slate-400">
              Autonomous, isolated sandboxed coding agent orchestrator — watch & steer runs live
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
              <span className="inline-flex items-center rounded-full bg-emerald-950/80 border border-emerald-800 px-2.5 py-0.5 text-emerald-300 font-medium">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 mr-1.5 animate-pulse" />
                Harness Engine Ready
              </span>
              <span className="inline-flex items-center rounded-full bg-blue-950/80 border border-blue-800 px-2.5 py-0.5 text-blue-300">
                ⚡ LLM: GROQ (openai/gpt-oss-120b)
              </span>
              <span className="inline-flex items-center rounded-full bg-purple-950/80 border border-purple-800 px-2.5 py-0.5 text-purple-300">
                📦 Ephemeral Sandbox
              </span>
            </div>
          </div>

          <Button
            variant="outline"
            size="sm"
            onClick={fetchRuns}
            disabled={isLoadingRuns}
            className="self-start sm:self-auto border-slate-700 text-slate-300 hover:bg-slate-800"
          >
            <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${isLoadingRuns ? "animate-spin" : ""}`} />
            Refresh Runs
          </Button>
        </div>

        {/* Create Run Card */}
        <Card className="border-slate-800 bg-slate-900/60 shadow-xl">
          <CardHeader>
            <CardTitle className="flex items-center text-base">
              <Play className="mr-2 h-4 w-4 text-emerald-400" />
              Start New Coding Run
            </CardTitle>
            <CardDescription>
              Provide an objective and select repository source or archive package.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-6">
              {/* Error Banner */}
              {formError && (
                <div className="flex items-center space-x-2 rounded-lg border border-rose-800 bg-rose-950/60 p-3 text-xs text-rose-300">
                  <AlertCircle className="h-4 w-4 text-rose-400 shrink-0" />
                  <span>{formError}</span>
                </div>
              )}

              {/* Source Type Selector (Git URL vs Archive) */}
              <div className="space-y-2">
                <label className="text-xs font-semibold text-slate-300">
                  Repository Source
                </label>
                <div className="flex space-x-2">
                  <Button
                    type="button"
                    variant={sourceType === "git" ? "default" : "outline"}
                    size="sm"
                    onClick={() => setSourceType("git")}
                    className={sourceType === "git" ? "" : "border-slate-700 text-slate-400"}
                  >
                    <GitBranch className="mr-1.5 h-3.5 w-3.5" />
                    Git Repository URL
                  </Button>
                  <Button
                    type="button"
                    variant={sourceType === "archive" ? "default" : "outline"}
                    size="sm"
                    onClick={() => setSourceType("archive")}
                    className={sourceType === "archive" ? "" : "border-slate-700 text-slate-400"}
                  >
                    <UploadCloud className="mr-1.5 h-3.5 w-3.5" />
                    Upload Archive (.zip / .tar.gz)
                  </Button>
                </div>
              </div>

              {/* Source Inputs */}
              {sourceType === "git" ? (
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <label className="text-xs text-slate-400">
                      Repository URL (HTTPS git endpoint)
                    </label>
                    <span className="text-[11px] text-slate-500">
                      Optional — leave blank for scratch workspace
                    </span>
                  </div>
                  <Input
                    type="url"
                    value={repoUrl}
                    onChange={(e) => setRepoUrl(e.target.value)}
                    placeholder="https://github.com/owner/repository.git (or leave blank)"
                    className="bg-slate-950 border-slate-700"
                  />
                </div>
              ) : (
                <div className="space-y-2">
                  <label className="text-xs text-slate-400">
                    Archive File (up to 50MB, .zip, .tar.gz, .tgz)
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
                      className="flex cursor-pointer items-center justify-center rounded-lg border border-dashed border-slate-700 bg-slate-950/60 px-4 py-3 text-xs text-slate-300 hover:border-blue-500 hover:bg-slate-900 transition"
                    >
                      <FileArchive className="mr-2 h-4 w-4 text-blue-400" />
                      {archiveFile ? archiveFile.name : "Choose archive file"}
                    </label>
                    {archiveFile && (
                      <Badge variant="outline" className="text-xs font-mono">
                        {(archiveFile.size / (1024 * 1024)).toFixed(2)} MB
                      </Badge>
                    )}
                  </div>
                </div>
              )}

              {/* Task Description */}
              <div className="space-y-1.5">
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1.5">
                  <label className="text-xs font-semibold text-slate-300">
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
                      className="rounded bg-slate-800 hover:bg-slate-700 px-2 py-0.5 text-[11px] text-blue-300 transition"
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
                      className="rounded bg-slate-800 hover:bg-slate-700 px-2 py-0.5 text-[11px] text-emerald-300 transition"
                    >
                      ⚡ Hangman (no tests)
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setTask("Implement a scientific calculator module in calculator.py and comprehensive unit tests in test_calculator.py that verify all functions pass.");
                        setVerification("required");
                        setRepoUrl("");
                      }}
                      className="rounded bg-slate-800 hover:bg-slate-700 px-2 py-0.5 text-[11px] text-purple-300 transition"
                    >
                      🧮 Calculator + Tests
                    </button>
                  </div>
                </div>
                <Textarea
                  value={task}
                  onChange={(e) => setTask(e.target.value)}
                  placeholder="Describe what the agent should implement or fix (e.g. 'Make me a hangman game in python' or 'Fix divide-by-zero bug')..."
                  rows={3}
                  className="bg-slate-950 border-slate-700 text-sm"
                />
              </div>

              {/* Verification Mode Selector */}
              <div className="space-y-2">
                <label className="text-xs font-semibold text-slate-300 flex items-center">
                  <Shield className="mr-1.5 h-3.5 w-3.5 text-blue-400" />
                  Verification Mode
                </label>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div
                    onClick={() => setVerification("required")}
                    className={`cursor-pointer rounded-lg border p-3 transition ${
                      verification === "required"
                        ? "border-blue-500 bg-blue-950/20"
                        : "border-slate-800 bg-slate-950/40 hover:border-slate-700"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold text-white">
                        Required (Default)
                      </span>
                      {verification === "required" && (
                        <div className="h-2 w-2 rounded-full bg-blue-500" />
                      )}
                    </div>
                    <p className="mt-1 text-[11px] text-slate-400">
                      Finish requires passing tests without subsequent edits. Prevents hallucinated solutions.
                    </p>
                  </div>

                  <div
                    onClick={() => setVerification("none")}
                    className={`cursor-pointer rounded-lg border p-3 transition ${
                      verification === "none"
                        ? "border-blue-500 bg-blue-950/20"
                        : "border-slate-800 bg-slate-950/40 hover:border-slate-700"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold text-white">None</span>
                      {verification === "none" && (
                        <div className="h-2 w-2 rounded-full bg-blue-500" />
                      )}
                    </div>
                    <p className="mt-1 text-[11px] text-slate-400">
                      Finish accepted without fresh test execution (useful for repos without tests).
                    </p>
                  </div>
                </div>
              </div>

              {/* Submit Button */}
              <Button
                type="submit"
                disabled={isSubmitting}
                className="w-full sm:w-auto px-6 font-semibold"
              >
                {isSubmitting ? (
                  <>
                    <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
                    Initializing Agent Sandbox...
                  </>
                ) : (
                  <>
                    <Play className="mr-2 h-4 w-4" />
                    Launch Autonomous Run
                  </>
                )}
              </Button>
            </form>
          </CardContent>
        </Card>

        {/* Recent Runs Table */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-white">Recent Runs</h2>
            <span className="text-xs text-slate-400">{runs.length} runs recorded</span>
          </div>

          <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/60 shadow">
            {runs.length === 0 ? (
              <div className="p-8 text-center text-slate-500 text-sm">
                No coding runs found. Start one above!
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs text-slate-300">
                  <thead className="border-b border-slate-800 bg-slate-950/80 text-[11px] uppercase tracking-wider text-slate-400">
                    <tr>
                      <th className="px-4 py-3">Status</th>
                      <th className="px-4 py-3">Run ID</th>
                      <th className="px-4 py-3">Task Objective</th>
                      <th className="px-4 py-3">Verification</th>
                      <th className="px-4 py-3">Created</th>
                      <th className="px-4 py-3 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60">
                    {runs.map((r) => {
                      return (
                        <tr
                          key={r.id}
                          className="hover:bg-slate-800/40 transition cursor-pointer"
                          onClick={() => onSelectRun(r.id)}
                        >
                          <td className="px-4 py-3 whitespace-nowrap">
                            {getStatusBadge(r.status, r.is_pausing)}
                          </td>
                          <td className="px-4 py-3 font-mono font-semibold text-white whitespace-nowrap">
                            {r.id}
                          </td>
                          <td className="px-4 py-3 max-w-xs truncate text-slate-200">
                            {r.task}
                          </td>
                          <td className="px-4 py-3 whitespace-nowrap">
                            <Badge variant="outline" className="text-[10px]">
                              {r.options?.verification || "required"}
                            </Badge>
                          </td>
                          <td className="px-4 py-3 whitespace-nowrap text-slate-400">
                            <div className="flex items-center space-x-1">
                              <Clock className="h-3 w-3" />
                              <span>{new Date(r.created_at).toLocaleString()}</span>
                            </div>
                          </td>
                          <td className="px-4 py-3 text-right whitespace-nowrap space-x-1">
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={(e) => {
                                e.stopPropagation();
                                onSelectRun(r.id);
                              }}
                              className="h-7 text-xs text-blue-400 hover:text-white"
                            >
                              <ExternalLink className="mr-1 h-3 w-3" />
                              View
                            </Button>
                          </td>
                        </tr>
                      );
                    })}
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
