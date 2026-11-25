import { useEffect, useState, useMemo, useCallback, useRef } from "react";
import {
  ArrowLeft,
  Activity,
  CheckCircle,
  XCircle,
  Clock,
  Layers,
  FileCode,
  GitBranch,
  Terminal as TerminalIcon,
  Sparkles,
  ChevronUp,
  ChevronDown,
  X,
  Play,
  Pause,
  Square,
  Download,
  RotateCcw,
} from "lucide-react";
import type { RunStatus, FileDiff } from "../../types/run";
import { useRunEvents } from "../../hooks/useRunEvents";
import { useRunDetails } from "../../hooks/useRunDetails";
import { api } from "../../services/api";
import { ActivityBar, SidebarTab } from "./ActivityBar";
import { ExplorerSidebar, WorkspaceFile } from "./ExplorerSidebar";
import { CodeEditorView } from "./CodeEditorView";
import { DiffViewer } from "./DiffViewer";
import { TerminalView } from "./TerminalView";
import { ReasoningStream } from "./ReasoningStream";
import { AgentChatPanel } from "./AgentChatPanel";
import { AgentWindowsGrid } from "./AgentWindowsGrid";
import { Badge } from "../ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../ui/dialog";
import { detectExternalPythonPackages } from "../../lib/pythonImports";

export interface RunViewProps {
  runId: string;
  onBack?: () => void;
}

function parseUtcMs(iso: string): number {
  const hasTz = /(?:Z|[+-]\d{2}:\d{2})$/i.test(iso);
  return new Date(hasTz ? iso : `${iso}Z`).getTime();
}

export function RunView({ runId, onBack }: RunViewProps) {
  const { run, refetch: refetchRun } = useRunDetails({ runId, pollInterval: 4000 });
  const { state, connectionStatus, dispatch } = useRunEvents({ runId, enabled: true });

  const currentStatus: RunStatus = state.status !== "QUEUED" ? state.status : (run?.status ?? "QUEUED");
  const isPausing: boolean = state.isPausing || (run?.is_pausing ?? false);

  // VS Code Layout States
  const [activeSidebarTab, setActiveSidebarTab] = useState<SidebarTab>("files");
  const [openTabs, setOpenTabs] = useState<string[]>(["diff"]);
  const [activeTab, setActiveTab] = useState<string>("diff");
  const [bottomTab, setBottomTab] = useState<"terminal" | "thoughts" | "actions">("terminal");
  const [bottomPanelExpanded, setBottomPanelExpanded] = useState<boolean>(true);
  const [chatOpen, setChatOpen] = useState<boolean>(true);
  const [isLaunchingSwarm, setIsLaunchingSwarm] = useState(false);
  const [installedPackages, setInstalledPackages] = useState<string[]>([]);
  const [pendingPkgPrompt, setPendingPkgPrompt] = useState<{
    filename: string;
    packages: string[];
  } | null>(null);
  const [isInstallingPackages, setIsInstallingPackages] = useState(false);

  // File system and diffs
  const [files, setFiles] = useState<WorkspaceFile[]>([]);
  const [fileContents, setFileContents] = useState<Record<string, string>>({});
  const [diffs, setDiffs] = useState<FileDiff[]>([]);
  const [guidanceText, setGuidanceText] = useState("");
  const [isSendingGuidance, setIsSendingGuidance] = useState(false);
  const [guidanceFeedback, setGuidanceFeedback] = useState<{ type: "success" | "error"; message: string } | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [isRunningFile, setIsRunningFile] = useState(false);
  const [isRerunning, setIsRerunning] = useState(false);

  // Duration
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const isTerminal = ["SUCCEEDED", "FAILED", "TERMINATED"].includes(currentStatus);

  useEffect(() => {
    if (!run?.created_at) return;
    const start = parseUtcMs(run.created_at);

    const updateTimer = () => {
      const end = isTerminal && run.updated_at ? parseUtcMs(run.updated_at) : Date.now();
      setElapsedSeconds(Math.max(0, Math.floor((end - start) / 1000)));
    };

    updateTimer();
    if (!isTerminal) {
      const timer = setInterval(updateTimer, 1000);
      return () => clearInterval(timer);
    }
  }, [run?.created_at, run?.updated_at, isTerminal]);

  const hasSwarmEvents = useMemo(
    () =>
      Boolean(run?.options?.multi_agent) ||
      state.events.some((e) => e.type === "agent_status" || e.type === "agent_message"),
    [run?.options?.multi_agent, state.events]
  );

  useEffect(() => {
    if (hasSwarmEvents && !openTabs.includes("agents")) {
      setOpenTabs((prev) => ["agents", ...prev]);
      setActiveTab((prev) => (prev === "diff" ? "agents" : prev));
      setBottomPanelExpanded(false);
    }
  }, [hasSwarmEvents, openTabs]);

  const handleLaunchSwarm = async () => {
    setActionError(null);
    try {
      setIsLaunchingSwarm(true);
      if (!openTabs.includes("agents")) {
        setOpenTabs((prev) => ["agents", ...prev]);
      }
      setActiveTab("agents");
      await api.orchestrateRun(runId);
      refetchRun();
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : "Failed to launch multi-agent swarm");
    } finally {
      setIsLaunchingSwarm(false);
    }
  };

  const formattedDuration = useMemo(() => {
    const mins = Math.floor(elapsedSeconds / 60);
    const secs = elapsedSeconds % 60;
    return `${mins}m ${secs < 10 ? "0" : ""}${secs}s`;
  }, [elapsedSeconds]);

  const openTabsRef = useRef(openTabs);
  openTabsRef.current = openTabs;
  const diffsRef = useRef(diffs);
  diffsRef.current = diffs;
  const toolCallsRef = useRef(state.toolCalls);
  toolCallsRef.current = state.toolCalls;

  // Sync diffs from API
  const refreshDiffs = useCallback(async () => {
    try {
      const data = await api.getDiff(runId);
      if (data) setDiffs(data);
    } catch {
      // ignore
    }
  }, [runId]);

  // Sync files from API & tool calls
  const refreshFiles = useCallback(async () => {
    try {
      const backendFiles = await api.listFiles(runId);
      const fileMap = new Map<string, WorkspaceFile>();

      for (const bf of backendFiles) {
        fileMap.set(bf.path, { path: bf.path, name: bf.name, status: "modified" });
      }

      for (const tc of toolCallsRef.current.values()) {
        if (tc.name === "write_file" && tc.arguments?.path) {
          const p = tc.arguments.path;
          const name = p.split("/").pop() || p;
          fileMap.set(p, {
            path: p,
            name,
            content: tc.arguments.content,
            status: "added",
          });
          if (tc.arguments.content) {
            setFileContents((prev) => (prev[p] === tc.arguments.content ? prev : { ...prev, [p]: tc.arguments.content }));
          }
        }
      }

      for (const d of diffsRef.current) {
        if (d.status !== "deleted") {
          const existing = fileMap.get(d.path);
          fileMap.set(d.path, {
            path: d.path,
            name: d.path.split("/").pop() || d.path,
            status: d.status === "added" ? "added" : "modified",
            additions: d.additions,
            deletions: d.deletions,
            ...existing,
          });
        }
      }

      const fileList = Array.from(fileMap.values());
      setFiles(fileList);

      const currentTabs = openTabsRef.current;
      const hasOpenFile = currentTabs.some((t) => t !== "diff" && t !== "agents");
      if (fileList.length > 0 && !hasOpenFile) {
        const firstFile = fileList[0].path;
        setOpenTabs((prev) => (prev.includes(firstFile) ? prev : [...prev, firstFile]));
        if (!currentTabs.includes("agents")) {
          setActiveTab(firstFile);
        }
        api.getFileContent(runId, firstFile).then((res) => {
          if (res?.content !== undefined) {
            setFileContents((prev) => ({ ...prev, [firstFile]: res.content }));
          }
        }).catch(() => {});
      }
    } catch {
      // ignore
    }
  }, [runId]);

  useEffect(() => {
    refreshDiffs();
  }, [refreshDiffs, currentStatus]);

  useEffect(() => {
    refreshFiles();
    if (isTerminal) return;
    const interval = setInterval(refreshFiles, 3000);
    return () => clearInterval(interval);
  }, [refreshFiles, isTerminal]);

  // Auto-fetch file content whenever activeTab changes
  useEffect(() => {
    if (activeTab && activeTab !== "diff" && fileContents[activeTab] === undefined) {
      api.getFileContent(runId, activeTab).then((res) => {
        if (res?.content !== undefined) {
          setFileContents((prev) => ({ ...prev, [activeTab]: res.content }));
        }
      }).catch(() => {});
    }
  }, [activeTab, runId, fileContents]);

  // Fetch content when opening a tab
  const handleSelectFile = async (filePath: string) => {
    if (filePath.startsWith("diff:")) {
      if (!openTabs.includes("diff")) {
        setOpenTabs((prev) => [...prev, "diff"]);
      }
      setActiveTab("diff");
      return;
    }

    if (!openTabs.includes(filePath)) {
      setOpenTabs((prev) => [...prev, filePath]);
    }
    setActiveTab(filePath);

    if (!fileContents[filePath]) {
      try {
        const res = await api.getFileContent(runId, filePath);
        if (res?.content !== undefined) {
          setFileContents((prev) => ({ ...prev, [filePath]: res.content }));
        }
      } catch {
        // ignore
      }
    }
  };

  const handleCloseTab = (tabToClose: string, e: React.MouseEvent) => {
    e.stopPropagation();
    const nextTabs = openTabs.filter((t) => t !== tabToClose);
    setOpenTabs(nextTabs);
    if (activeTab === tabToClose) {
      setActiveTab(nextTabs[nextTabs.length - 1] || "diff");
    }
  };

  // Agent Controls
  const handlePause = async () => {
    try {
      await api.pauseRun(runId, "boundary");
      refetchRun();
    } catch (e) {
      console.error(e);
    }
  };

  const handleResume = async () => {
    try {
      await api.resumeRun(runId);
      refetchRun();
    } catch (e) {
      console.error(e);
    }
  };

  const handleTerminate = async () => {
    if (window.confirm("Are you sure you want to terminate this run?")) {
      try {
        await api.terminateRun(runId, "User requested termination");
        refetchRun();
      } catch (e) {
        console.error(e);
      }
    }
  };

  const handleSendGuidance = async () => {
    if (!guidanceText.trim()) return;
    setGuidanceFeedback(null);
    try {
      setIsSendingGuidance(true);
      await api.injectGuidance(runId, guidanceText.trim());
      setGuidanceText("");
      setGuidanceFeedback({ type: "success", message: "Guidance sent to agent" });
      setTimeout(() => setGuidanceFeedback(null), 2500);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to send guidance";
      setGuidanceFeedback({ type: "error", message: msg });
    } finally {
      setIsSendingGuidance(false);
    }
  };

  const handleDownloadArtifact = async (type: "patch" | "logs") => {
    setActionError(null);
    try {
      const urls = await api.getArtifacts(runId);
      const url = type === "patch" ? urls.patch_url : urls.logs_url;
      if (url) {
        window.open(url, "_blank");
        return;
      }

      if (type === "patch") {
        const currentDiffs = diffs.length > 0 ? diffs : await api.getDiff(runId);
        const patchText = currentDiffs
          .map((d) => d.diff_patch || `--- a/${d.path}\n+++ b/${d.path}`)
          .join("\n\n");
        if (!patchText.trim()) {
          setActionError("No git diff available to download for this run.");
          return;
        }
        const blob = new Blob([patchText], { type: "text/plain;charset=utf-8" });
        const objectUrl = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = objectUrl;
        a.download = `${runId}.patch`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(objectUrl);
      }
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : "Failed to download artifact");
    }
  };

  const executeShellCommand = async (cmd: string) => {
    setIsRunningFile(true);
    setBottomTab("terminal");
    setBottomPanelExpanded(true);

    const ts = new Date().toISOString();
    const curSeq = state.lastSeenSeq;
    dispatch({
      type: "PROCESS_EVENT",
      event: {
        seq: curSeq + 1,
        ts,
        type: "terminal_output",
        payload: {
          stream: "stdout",
          data: `\r\n\x1b[1;36m$ ${cmd}\x1b[0m\r\n`,
        },
      },
    });

    try {
      const res = await api.executeCommand(runId, cmd);
      if (res.output) {
        dispatch({
          type: "PROCESS_EVENT",
          event: {
            seq: curSeq + 2,
            ts: new Date().toISOString(),
            type: "terminal_output",
            payload: {
              stream: res.exit_code === 0 ? "stdout" : "stderr",
              data: res.output.endsWith("\n") ? res.output : res.output + "\r\n",
            },
          },
        });
      } else {
        dispatch({
          type: "PROCESS_EVENT",
          event: {
            seq: curSeq + 2,
            ts: new Date().toISOString(),
            type: "terminal_output",
            payload: {
              stream: "stdout",
              data: `\x1b[90m(Execution finished with exit code ${res.exit_code})\x1b[0m\r\n`,
            },
          },
        });
      }
    } catch (err: any) {
      dispatch({
        type: "PROCESS_EVENT",
        event: {
          seq: curSeq + 2,
          ts: new Date().toISOString(),
          type: "terminal_output",
          payload: {
            stream: "stderr",
            data: `\x1b[31mExecution error: ${err?.message || err}\x1b[0m\r\n`,
          },
        },
      });
    } finally {
      setIsRunningFile(false);
    }
  };

  const handleSaveFile = async (filename: string, updatedContent: string) => {
    const targetPath = activeTab && activeTab !== "diff" ? activeTab : filename;
    setFileContents((prev) => ({ ...prev, [targetPath]: updatedContent }));
    try {
      await api.updateFileContent(runId, targetPath, updatedContent);
    } catch (e) {
      console.error("Failed to save file:", e);
    }
  };

  const dispatchRunCommand = (filename: string, withPylibs: boolean) => {
    let cmd = withPylibs ? `PYTHONPATH=/tmp/pylibs python ${filename}` : `python ${filename}`;
    if (filename.endsWith(".rs")) cmd = "cargo run";
    else if (filename.endsWith(".sh")) cmd = `bash ${filename}`;
    else if (filename.endsWith(".js")) cmd = `node ${filename}`;

    setBottomTab("terminal");
    setBottomPanelExpanded(true);

    window.dispatchEvent(
      new CustomEvent("execute-terminal-command", { detail: { command: cmd } })
    );
  };

  const handleRunFile = async (filename: string) => {
    if (filename.endsWith(".py")) {
      const code = fileContents[activeTab] || fileContents[filename] || "";
      const external = detectExternalPythonPackages(
        code,
        files.map((f) => f.path)
      ).filter((pkg) => !installedPackages.includes(pkg));

      if (external.length > 0) {
        setPendingPkgPrompt({ filename, packages: external });
        return;
      }
    }

    dispatchRunCommand(filename, installedPackages.length > 0);
  };

  const handleConfirmInstallAndRun = async () => {
    if (!pendingPkgPrompt) return;
    const { filename, packages } = pendingPkgPrompt;
    setActionError(null);
    setIsInstallingPackages(true);
    try {
      await api.installPackages(runId, packages);
      setInstalledPackages((prev) => Array.from(new Set([...prev, ...packages])));
      setPendingPkgPrompt(null);
      dispatchRunCommand(filename, true);
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : "Failed to install packages");
      setPendingPkgPrompt(null);
    } finally {
      setIsInstallingPackages(false);
    }
  };

  const handleRerunTask = async () => {
    if (!run?.task) return;
    try {
      setIsRerunning(true);
      const newRun = await api.createRun({
        task: run.task,
        repo_url: run.repo_url || undefined,
        options: run.options,
      });
      if (typeof window !== "undefined") {
        const url = new URL(window.location.href);
        url.searchParams.set("runId", newRun.id);
        window.history.pushState({}, "", url.toString());
      }
      window.location.reload();
    } catch (err: any) {
      console.error("Rerun error:", err);
    } finally {
      setIsRerunning(false);
    }
  };

  const getStatusBadge = () => {
    switch (currentStatus) {
      case "QUEUED":
        return <Badge variant="secondary">QUEUED</Badge>;
      case "PREPARING":
        return (
          <Badge variant="info" className="animate-pulse">
            <Clock className="mr-1 h-3 w-3 animate-spin" />
            PREPARING
          </Badge>
        );
      case "RUNNING":
        return (
          <Badge variant="success" className="animate-pulse">
            <Activity className="mr-1 h-3 w-3 animate-pulse" />
            {isPausing ? "PAUSING..." : "RUNNING"}
          </Badge>
        );
      case "PAUSED":
        return <Badge variant="warning">PAUSED</Badge>;
      case "SUCCEEDED":
        return (
          <Badge variant="success">
            <CheckCircle className="mr-1 h-3 w-3" />
            SUCCEEDED
          </Badge>
        );
      case "FAILED":
        return (
          <Badge variant="destructive">
            <XCircle className="mr-1 h-3 w-3" />
            FAILED
          </Badge>
        );
      case "TERMINATED":
        return <Badge variant="secondary">TERMINATED</Badge>;
      default:
        return <Badge variant="outline">{currentStatus}</Badge>;
    }
  };

  const totalAdditions = useMemo(() => diffs.reduce((s, d) => s + (d.additions || 0), 0), [diffs]);
  const totalDeletions = useMemo(() => diffs.reduce((s, d) => s + (d.deletions || 0), 0), [diffs]);

  return (
    <div className="flex h-screen flex-col bg-[#111113] text-[#ededed] overflow-hidden font-sans select-none">
      {/* IDE Title Bar */}
      <header className="flex h-12 items-center justify-between border-b border-white/[0.08] bg-[#161619] px-4 text-xs">
        <div className="flex items-center gap-3 truncate">
          {onBack && (
            <button
              onClick={onBack}
              className="flex h-7 items-center gap-1.5 rounded-lg border border-white/[0.08] bg-[#1e1e22] hover:bg-[#27272c] px-2.5 text-[#a1a1a6] hover:text-[#ededed] transition-colors"
              title="Return to sessions"
            >
              <ArrowLeft className="h-3.5 w-3.5" strokeWidth={1.5} />
              <span className="font-medium text-xs">Sessions</span>
            </button>
          )}

          <div className="flex items-center gap-2">
            <Layers className="h-4 w-4 text-[#a1a1a6] shrink-0" strokeWidth={1.5} />
            <span className="font-mono font-medium text-[#ededed] shrink-0">
              {runId.slice(0, 8)}
            </span>
            {run?.task && (
              <span className="hidden sm:inline truncate max-w-sm lg:max-w-md text-[#a1a1a6] border-l border-white/[0.08] pl-2.5">
                {run.task}
              </span>
            )}
          </div>
        </div>

        {/* Center: Status & Metrics */}
        <div className="flex items-center gap-3 shrink-0 tabular-nums">
          <div className="hidden md:flex items-center gap-1.5 text-[#a1a1a6] font-mono text-xs">
            <Clock className="h-3.5 w-3.5 text-[#85858b]" strokeWidth={1.5} />
            <span>{formattedDuration}</span>
          </div>

          <div className="hidden sm:flex items-center gap-1.5 font-mono text-xs bg-[#0b0b0d] border border-white/[0.08] px-2 py-0.5 rounded-md">
            <span className="text-[#4cc38a]">+{totalAdditions}</span>
            <span className="text-[#e5484d]">-{totalDeletions}</span>
          </div>

          {getStatusBadge()}
        </div>

        {/* Right: Execution Controls */}
        <div className="flex items-center gap-2 shrink-0">
          {currentStatus === "RUNNING" && !run?.options?.multi_agent && (
            <button
              onClick={handlePause}
              disabled={isPausing}
              className="flex h-7 items-center gap-1.5 rounded-lg border border-[#d29922]/40 bg-[#d29922]/10 hover:bg-[#d29922]/20 disabled:opacity-50 px-3 text-xs font-medium text-[#d29922] transition-colors"
              title="Pause at step boundary"
            >
              <Pause className="h-3 w-3" strokeWidth={1.5} />
              <span>{isPausing ? "Pausing..." : "Pause"}</span>
            </button>
          )}

          {currentStatus === "PAUSED" && (
            <button
              onClick={handleResume}
              className="flex h-7 items-center gap-1.5 rounded-lg bg-[#ededed] hover:bg-white px-3 text-xs font-medium text-[#0b0b0d] transition-colors"
              title="Resume execution"
            >
              <Play className="h-3 w-3 fill-current" strokeWidth={1.5} />
              <span>Resume</span>
            </button>
          )}

          {["QUEUED", "PREPARING", "RUNNING", "PAUSED"].includes(currentStatus) && (
            <button
              onClick={handleTerminate}
              className="flex h-7 items-center gap-1.5 rounded-lg border border-white/[0.08] bg-[#1e1e22] hover:bg-[#e5484d]/15 hover:text-[#e5484d] hover:border-[#e5484d]/40 px-3 text-xs font-medium text-[#a1a1a6] transition-colors"
              title="Terminate run"
            >
              <Square className="h-3 w-3" strokeWidth={1.5} />
              <span>Stop</span>
            </button>
          )}

          {["SUCCEEDED", "FAILED", "TERMINATED"].includes(currentStatus) && (
            <button
              onClick={handleRerunTask}
              disabled={isRerunning}
              className="flex h-7 items-center gap-1.5 rounded-lg bg-[#ededed] hover:bg-white px-3 text-xs font-medium text-[#0b0b0d] transition-colors"
              title="Start a new run with the same task"
            >
              <RotateCcw className={`h-3 w-3 ${isRerunning ? "animate-spin" : ""}`} strokeWidth={1.5} />
              <span>{isRerunning ? "Starting..." : "Re-run Task"}</span>
            </button>
          )}

          {["SUCCEEDED", "FAILED", "TERMINATED"].includes(currentStatus) && (
            <button
              onClick={() => handleDownloadArtifact("patch")}
              className="flex h-7 items-center gap-1.5 rounded-lg border border-white/[0.08] bg-[#1e1e22] hover:bg-[#27272c] px-3 text-xs font-medium text-[#ededed] transition-colors"
              title="Download patch diff"
            >
              <Download className="h-3 w-3 text-[#a1a1a6]" strokeWidth={1.5} />
              <span>Download Patch</span>
            </button>
          )}

          <button
            type="button"
            onClick={() => {
              if (!openTabs.includes("agents")) {
                setOpenTabs((prev) => ["agents", ...prev]);
              }
              setActiveTab("agents");
            }}
            className={`flex h-7 items-center gap-1.5 rounded-lg border px-2.5 text-xs font-medium transition-colors ${
              activeTab === "agents"
                ? "border-[#2f81f7]/40 bg-[#2f81f7]/15 text-[#ededed]"
                : "border-white/[0.08] bg-[#1e1e22] hover:bg-[#27272c] text-[#a1a1a6] hover:text-[#ededed]"
            }`}
            title="View parallel sub-agent windows"
          >
            <Layers className="h-3 w-3" strokeWidth={1.5} />
            <span>Sub-Agents</span>
          </button>

          <button
            type="button"
            onClick={() => setChatOpen((o) => !o)}
            className={`flex h-7 items-center gap-1.5 rounded-lg border px-2.5 text-xs font-medium transition-colors ${
              chatOpen
                ? "border-[#2f81f7]/40 bg-[#2f81f7]/15 text-[#ededed]"
                : "border-white/[0.08] bg-[#1e1e22] hover:bg-[#27272c] text-[#a1a1a6] hover:text-[#ededed]"
            }`}
            title="Toggle Agent Chat"
          >
            <Sparkles className="h-3 w-3" strokeWidth={1.5} />
            <span>Agent Chat</span>
          </button>
        </div>
      </header>

      {(actionError || (currentStatus === "FAILED" && run?.error_reason)) && (
        <div className="flex items-center justify-between gap-2 border-b border-[#e5484d]/30 bg-[#e5484d]/10 px-4 py-2 text-xs text-[#e5484d]">
          <div className="flex items-center gap-2 truncate">
            <XCircle className="h-3.5 w-3.5 shrink-0" strokeWidth={1.5} />
            <span className="truncate font-mono">{actionError || run?.error_reason}</span>
          </div>
          {actionError && (
            <button
              type="button"
              onClick={() => setActionError(null)}
              className="text-[#e5484d] hover:text-white shrink-0"
            >
              <X className="h-3.5 w-3.5" strokeWidth={1.5} />
            </button>
          )}
        </div>
      )}

      {/* Main IDE Workspace */}
      <div className="flex flex-1 overflow-hidden">
        <ActivityBar
          activeTab={activeSidebarTab}
          onTabChange={setActiveSidebarTab}
          diffCount={diffs.length}
          connectionStatus={connectionStatus}
          onBack={onBack}
        />

        <div className="w-64 xl:w-72 shrink-0 overflow-hidden flex flex-col">
          <ExplorerSidebar
            activeView={activeSidebarTab}
            files={files}
            selectedFile={activeTab}
            onSelectFile={handleSelectFile}
            run={run}
            diffs={diffs}
            guidanceText={guidanceText}
            onGuidanceChange={setGuidanceText}
            onSendGuidance={handleSendGuidance}
            isSendingGuidance={isSendingGuidance}
            guidanceFeedback={guidanceFeedback}
            totalTokens={state.events.length * 35}
            stepCount={state.events.filter((e) => e.type === "tool_call").length}
          />
        </div>

        {/* Center & Right: Editor Area + Bottom Panel */}
        <div className="flex flex-1 flex-col overflow-hidden bg-[#111113]">
          {/* Editor Tabs Bar */}
          <div className="flex h-9 items-center border-b border-white/[0.08] bg-[#161619] px-1 overflow-x-auto select-none">
            {openTabs.map((tab) => {
              const isDiffTab = tab === "diff";
              const isAgentsTab = tab === "agents";
              const isActive = activeTab === tab;
              const tabLabel = isAgentsTab
                ? "Sub-Agents (5)"
                : isDiffTab
                  ? "Git Changes"
                  : tab.split("/").pop();

              return (
                <div
                  key={tab}
                  onClick={() => {
                    if (isAgentsTab) {
                      setActiveTab("agents");
                    } else {
                      handleSelectFile(tab);
                    }
                  }}
                  className={`group flex h-full cursor-pointer items-center gap-2 border-r border-white/[0.06] px-3 text-xs transition-colors ${
                    isActive
                      ? "bg-[#111113] text-[#ededed] font-medium border-t-2 border-t-[#2f81f7]"
                      : "text-[#85858b] hover:bg-white/[0.03] hover:text-[#ededed]"
                  }`}
                >
                  {isAgentsTab ? (
                    <Layers className="h-3.5 w-3.5 text-[#2f81f7] shrink-0" strokeWidth={1.5} />
                  ) : isDiffTab ? (
                    <GitBranch className="h-3.5 w-3.5 text-[#a1a1a6] shrink-0" strokeWidth={1.5} />
                  ) : (
                    <FileCode className="h-3.5 w-3.5 text-[#a1a1a6] shrink-0" strokeWidth={1.5} />
                  )}
                  <span className="truncate max-w-[140px]">{tabLabel}</span>

                  {openTabs.length > 1 && (
                    <button
                      onClick={(e) => handleCloseTab(tab, e)}
                      className="ml-1 rounded p-0.5 text-[#85858b] hover:bg-[#1e1e22] hover:text-[#ededed]"
                    >
                      <X className="h-3 w-3" strokeWidth={1.5} />
                    </button>
                  )}
                </div>
              );
            })}
          </div>

          {/* Active Editor Content View */}
          <div className="flex-1 overflow-hidden relative">
            {activeTab === "agents" ? (
              <AgentWindowsGrid
                runId={runId}
                events={state.events}
                onLaunchSwarm={handleLaunchSwarm}
                isLaunching={isLaunchingSwarm}
              />
            ) : activeTab === "diff" ? (
              <DiffViewer runId={runId} diffs={diffs} onRefresh={refreshDiffs} />
            ) : (
              <CodeEditorView
                filename={activeTab.split("/").pop() || activeTab}
                content={fileContents[activeTab] || "# Loading file content..."}
                onRunFile={handleRunFile}
                onSaveFile={handleSaveFile}
                isRunning={isRunningFile}
              />
            )}
          </div>

          {/* Bottom Panel (Terminal / Reasoning / Tool Activity) */}
          <div
            className={`border-t border-white/[0.08] bg-[#161619] flex flex-col transition-colors ${
              bottomPanelExpanded ? "h-64 xl:h-72" : "h-9"
            }`}
          >
            {/* Bottom Panel Header */}
            <div className="flex h-9 items-center justify-between border-b border-white/[0.08] px-3 text-xs select-none">
              <div className="flex items-center gap-1">
                <button
                  onClick={() => {
                    setBottomTab("terminal");
                    setBottomPanelExpanded(true);
                  }}
                  className={`flex items-center gap-1.5 px-3 py-1 rounded-md text-xs font-medium transition-colors ${
                    bottomTab === "terminal" && bottomPanelExpanded
                      ? "bg-[#1e1e22] text-[#ededed]"
                      : "text-[#85858b] hover:text-[#ededed]"
                  }`}
                >
                  <TerminalIcon className="h-3.5 w-3.5" strokeWidth={1.5} />
                  <span>Terminal</span>
                </button>

                <button
                  onClick={() => {
                    setBottomTab("thoughts");
                    setBottomPanelExpanded(true);
                  }}
                  className={`flex items-center gap-1.5 px-3 py-1 rounded-md text-xs font-medium transition-colors ${
                    bottomTab === "thoughts" && bottomPanelExpanded
                      ? "bg-[#1e1e22] text-[#ededed]"
                      : "text-[#85858b] hover:text-[#ededed]"
                  }`}
                >
                  <Sparkles className="h-3.5 w-3.5" strokeWidth={1.5} />
                  <span>Agent thoughts</span>
                </button>

                <button
                  onClick={() => {
                    setBottomTab("actions");
                    setBottomPanelExpanded(true);
                  }}
                  className={`flex items-center gap-1.5 px-3 py-1 rounded-md text-xs font-medium transition-colors tabular-nums ${
                    bottomTab === "actions" && bottomPanelExpanded
                      ? "bg-[#1e1e22] text-[#ededed]"
                      : "text-[#85858b] hover:text-[#ededed]"
                  }`}
                >
                  <Activity className="h-3.5 w-3.5" strokeWidth={1.5} />
                  <span>Actions ({state.toolCalls.size})</span>
                </button>
              </div>

              <button
                onClick={() => setBottomPanelExpanded(!bottomPanelExpanded)}
                className="p-1 text-[#85858b] hover:text-[#ededed] rounded hover:bg-[#1e1e22] transition-colors"
                title={bottomPanelExpanded ? "Collapse panel" : "Expand panel"}
              >
                {bottomPanelExpanded ? (
                  <ChevronDown className="h-4 w-4" strokeWidth={1.5} />
                ) : (
                  <ChevronUp className="h-4 w-4" strokeWidth={1.5} />
                )}
              </button>
            </div>

            {bottomPanelExpanded && (
              <div className="flex-1 overflow-hidden">
                {bottomTab === "terminal" && (
                  <TerminalView
                    runId={runId}
                    chunks={state.terminalChunks}
                    isTruncated={state.isTerminalTruncated}
                    truncationMessage={state.truncationMessage}
                    onExecuteCommand={executeShellCommand}
                  />
                )}

                {bottomTab === "thoughts" && (
                  <div className="h-full overflow-y-auto p-3 bg-[#0b0b0d]">
                    <ReasoningStream
                      events={state.events}
                      toolCalls={state.toolCalls}
                    />
                  </div>
                )}

                {bottomTab === "actions" && (
                  <div className="h-full overflow-y-auto p-3 space-y-2 font-mono text-xs bg-[#0b0b0d]">
                    {Array.from(state.toolCalls.values()).map((tc) => (
                      <div
                        key={tc.id}
                        className="rounded-lg border border-white/[0.08] bg-[#161619] p-3 space-y-1.5"
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-medium text-[#ededed]">{tc.name}</span>
                          <span className={`text-[11px] ${tc.status === "error" ? "text-[#e5484d]" : "text-[#4cc38a]"}`}>
                            {tc.status === "error" ? "ERROR" : tc.status === "running" ? "RUNNING" : "OK"}
                          </span>
                        </div>
                        {tc.arguments && (
                          <div className="text-[11px] text-[#a1a1a6] truncate">
                            {JSON.stringify(tc.arguments)}
                          </div>
                        )}
                        {tc.output && (
                          <div className="text-[11px] text-[#ededed] max-h-20 overflow-y-auto bg-[#0b0b0d] border border-white/[0.06] p-2 rounded">
                            {tc.output}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Right: Antigravity-style Agent Chat Panel */}
        {chatOpen && (
          <AgentChatPanel
            runId={runId}
            run={run}
            status={currentStatus}
            fileContents={fileContents}
            onClose={() => setChatOpen(false)}
          />
        )}
      </div>

      {/* Confirm External Python Package Install Dialog */}
      <Dialog
        open={Boolean(pendingPkgPrompt)}
        onOpenChange={(open) => {
          if (!open && !isInstallingPackages) setPendingPkgPrompt(null);
        }}
      >
        <DialogContent className="border-white/[0.1] bg-[#161619] text-[#ededed] sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-base font-medium text-[#ededed]">
              Install external Python packages?
            </DialogTitle>
            <DialogDescription className="text-xs text-[#a1a1a6] leading-relaxed">
              <span className="font-mono text-[#ededed]">{pendingPkgPrompt?.filename}</span>{" "}
              imports external libraries not in the Python standard library. They will be temporarily installed into{" "}
              <span className="font-mono text-[#ededed]">/tmp/pylibs</span> inside this session&apos;s isolated sandbox and removed when the session ends.
            </DialogDescription>
          </DialogHeader>

          <div className="flex flex-wrap gap-1.5 py-2">
            {pendingPkgPrompt?.packages.map((pkg) => (
              <span
                key={pkg}
                className="rounded-md border border-white/[0.08] bg-[#0b0b0d] px-2.5 py-1 font-mono text-xs text-[#ededed]"
              >
                {pkg}
              </span>
            ))}
          </div>

          <DialogFooter className="gap-2 sm:gap-2">
            <button
              type="button"
              disabled={isInstallingPackages}
              onClick={() => {
                const file = pendingPkgPrompt?.filename;
                setPendingPkgPrompt(null);
                if (file) dispatchRunCommand(file, installedPackages.length > 0);
              }}
              className="h-8 rounded-lg border border-white/[0.08] bg-[#1e1e22] hover:bg-[#27272c] px-3 text-xs font-medium text-[#a1a1a6] hover:text-[#ededed] transition-colors"
            >
              Run without installing
            </button>
            <button
              type="button"
              disabled={isInstallingPackages}
              onClick={handleConfirmInstallAndRun}
              className="h-8 rounded-lg bg-[#ededed] hover:bg-white disabled:opacity-50 px-3.5 text-xs font-medium text-[#0b0b0d] transition-colors"
            >
              {isInstallingPackages ? "Installing..." : "Install & Run"}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
