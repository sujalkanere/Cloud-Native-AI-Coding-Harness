import { useEffect, useState, useMemo, useCallback } from "react";
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
import { Badge } from "../ui/badge";

export interface RunViewProps {
  runId: string;
  onBack?: () => void;
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

  // File system and diffs
  const [files, setFiles] = useState<WorkspaceFile[]>([]);
  const [fileContents, setFileContents] = useState<Record<string, string>>({});
  const [diffs, setDiffs] = useState<FileDiff[]>([]);
  const [guidanceText, setGuidanceText] = useState("");
  const [isSendingGuidance, setIsSendingGuidance] = useState(false);
  const [isRunningFile, setIsRunningFile] = useState(false);
  const [isRerunning, setIsRerunning] = useState(false);

  // Duration
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  useEffect(() => {
    if (!run?.created_at) return;
    const start = new Date(run.created_at).getTime();

    const updateTimer = () => {
      const now = Date.now();
      setElapsedSeconds(Math.max(0, Math.floor((now - start) / 1000)));
    };

    updateTimer();
    const isTerminal = ["SUCCEEDED", "FAILED", "TERMINATED"].includes(currentStatus);
    if (!isTerminal) {
      const timer = setInterval(updateTimer, 1000);
      return () => clearInterval(timer);
    }
  }, [run?.created_at, currentStatus]);

  const formattedDuration = useMemo(() => {
    const mins = Math.floor(elapsedSeconds / 60);
    const secs = elapsedSeconds % 60;
    return `${mins}m ${secs < 10 ? "0" : ""}${secs}s`;
  }, [elapsedSeconds]);

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

      // Populate from backend
      for (const bf of backendFiles) {
        fileMap.set(bf.path, { path: bf.path, name: bf.name, status: "modified" });
      }

      // Populate from tool calls (write_file)
      for (const tc of state.toolCalls.values()) {
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
            setFileContents((prev) => ({ ...prev, [p]: tc.arguments.content }));
          }
        }
      }

      // Populate from diffs
      for (const d of diffs) {
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

      // Auto-open first created file if only diff was open
      if (fileList.length > 0 && openTabs.length === 1 && openTabs[0] === "diff") {
        const firstFile = fileList[0].path;
        setOpenTabs(["diff", firstFile]);
        setActiveTab(firstFile);
        api.getFileContent(runId, firstFile).then((res) => {
          if (res?.content !== undefined) {
            setFileContents((prev) => ({ ...prev, [firstFile]: res.content }));
          }
        }).catch(() => {});
      }
    } catch {
      // ignore
    }
  }, [runId, state.toolCalls, diffs, openTabs]);

  useEffect(() => {
    refreshDiffs();
  }, [refreshDiffs, state.events.length]);

  useEffect(() => {
    refreshFiles();
    const interval = setInterval(refreshFiles, 3000);
    return () => clearInterval(interval);
  }, [refreshFiles]);

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
    try {
      setIsSendingGuidance(true);
      await api.sendGuidance(runId, guidanceText.trim());
      setGuidanceText("");
    } catch (e) {
      console.error(e);
    } finally {
      setIsSendingGuidance(false);
    }
  };

  const handleDownloadArtifact = async (type: "patch" | "logs") => {
    try {
      const urls = await api.getArtifactUrls(runId);
      const url = type === "patch" ? urls.patch_url : urls.logs_url;
      if (url) window.open(url, "_blank");
    } catch (e) {
      console.error(e);
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

  const handleRunFile = async (filename: string) => {
    let cmd = `python ${filename}`;
    if (filename.endsWith(".rs")) cmd = "cargo run";
    else if (filename.endsWith(".sh")) cmd = `bash ${filename}`;
    else if (filename.endsWith(".js")) cmd = `node ${filename}`;

    setBottomTab("terminal");
    setBottomPanelExpanded(true);

    window.dispatchEvent(
      new CustomEvent("execute-terminal-command", { detail: { command: cmd } })
    );
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
    <div className="flex h-screen flex-col bg-[#0b0f19] text-slate-100 overflow-hidden font-sans select-none">
      {/* VS Code Title Bar */}
      <header className="flex h-11 items-center justify-between border-b border-slate-800 bg-[#0d1424] px-4 text-xs">
        {/* Left: Project title & Run info */}
        <div className="flex items-center space-x-3 truncate">
          {onBack && (
            <button
              onClick={onBack}
              className="flex items-center space-x-1.5 rounded-full bg-slate-800 hover:bg-slate-700 px-3 py-1 text-slate-300 hover:text-white transition-colors"
              title="Return to sessions"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              <span className="font-medium text-[11px]">Sessions</span>
            </button>
          )}

          <div className="flex items-center space-x-2">
            <Layers className="h-4 w-4 text-blue-500 shrink-0" />
            <span className="font-mono font-bold text-white shrink-0">
              {runId.slice(0, 8)}
            </span>
            {run?.task && (
              <span className="hidden sm:inline truncate max-w-sm lg:max-w-md text-slate-400 border-l border-slate-800 pl-2">
                {run.task}
              </span>
            )}
          </div>
        </div>

        {/* Center: Status & Metrics */}
        <div className="flex items-center space-x-3 shrink-0">
          <div className="hidden md:flex items-center space-x-2 text-slate-400 font-mono text-[11px]">
            <Clock className="h-3.5 w-3.5 text-slate-500" />
            <span>{formattedDuration}</span>
          </div>

          <div className="hidden sm:flex items-center space-x-1 font-mono text-[11px] bg-slate-900 border border-slate-800 px-2 py-0.5 rounded-full">
            <span className="text-emerald-400 font-bold">+{totalAdditions}</span>
            <span className="text-rose-400 font-bold">-{totalDeletions}</span>
          </div>

          {getStatusBadge()}
        </div>

        {/* Right: Meta-style Control CTA Buttons */}
        <div className="flex items-center space-x-2 shrink-0">
          {currentStatus === "RUNNING" && (
            <button
              onClick={handlePause}
              disabled={isPausing}
              className="flex items-center space-x-1 rounded-full bg-amber-600 hover:bg-amber-500 disabled:opacity-50 px-3 py-1 text-[11px] font-semibold text-white transition-colors shadow-sm"
              title="Pause at step boundary"
            >
              <Pause className="h-3 w-3" />
              <span>{isPausing ? "Pausing..." : "Pause"}</span>
            </button>
          )}

          {currentStatus === "PAUSED" && (
            <button
              onClick={handleResume}
              className="flex items-center space-x-1 rounded-full bg-blue-600 hover:bg-blue-500 px-3 py-1 text-[11px] font-semibold text-white transition-colors shadow-sm"
              title="Resume execution"
            >
              <Play className="h-3 w-3" />
              <span>Resume</span>
            </button>
          )}

          {["QUEUED", "PREPARING", "RUNNING", "PAUSED"].includes(currentStatus) && (
            <button
              onClick={handleTerminate}
              className="flex items-center space-x-1 rounded-full bg-slate-800 hover:bg-rose-900/60 hover:text-rose-300 px-3 py-1 text-[11px] font-medium text-slate-300 transition-colors"
              title="Terminate run"
            >
              <Square className="h-3 w-3" />
              <span>Stop</span>
            </button>
          )}

          {["SUCCEEDED", "FAILED", "TERMINATED"].includes(currentStatus) && (
            <button
              onClick={handleRerunTask}
              disabled={isRerunning}
              className="flex items-center space-x-1.5 rounded-full bg-[#0064e0] hover:bg-[#0457cb] px-4 py-1.5 text-[11px] font-bold text-white transition-colors shadow-sm"
              title="Start a new run with the same task"
            >
              <RotateCcw className={`h-3 w-3 ${isRerunning ? "animate-spin" : ""}`} />
              <span>{isRerunning ? "Starting..." : "Re-run Task"}</span>
            </button>
          )}

          {["SUCCEEDED", "FAILED", "TERMINATED"].includes(currentStatus) && (
            <button
              onClick={() => handleDownloadArtifact("patch")}
              className="flex items-center space-x-1 rounded-full bg-slate-800 hover:bg-slate-700 px-3 py-1 text-[11px] font-semibold text-white transition-colors"
              title="Download patch diff"
            >
              <Download className="h-3 w-3" />
              <span>Download Patch</span>
            </button>
          )}
        </div>
      </header>

      {/* Main IDE Workspace */}
      <div className="flex flex-1 overflow-hidden">
        {/* Leftmost Activity Bar */}
        <ActivityBar
          activeTab={activeSidebarTab}
          onTabChange={setActiveSidebarTab}
          diffCount={diffs.length}
          connectionStatus={connectionStatus}
          onBack={onBack}
        />

        {/* Primary Sidebar (Explorer / Git / Agent) */}
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
            totalTokens={state.events.length * 35}
            stepCount={state.events.filter((e) => e.type === "tool_call").length}
          />
        </div>

        {/* Center & Right: Editor Area + Bottom Panel */}
        <div className="flex flex-1 flex-col overflow-hidden bg-[#090d16]">
          {/* VS Code Editor Tabs Bar */}
          <div className="flex h-9 items-center border-b border-slate-800 bg-[#0d1424] px-1 overflow-x-auto select-none">
            {openTabs.map((tab) => {
              const isDiffTab = tab === "diff";
              const isActive = activeTab === tab;
              const tabLabel = isDiffTab ? "Git Changes" : tab.split("/").pop();

              return (
                <div
                  key={tab}
                  onClick={() => handleSelectFile(tab)}
                  className={`group flex h-full cursor-pointer items-center space-x-2 border-r border-slate-800/80 px-3 text-xs transition-colors ${
                    isActive
                      ? "bg-[#0b0f19] text-white font-medium border-t-2 border-t-blue-500"
                      : "text-slate-400 hover:bg-slate-800/40 hover:text-slate-200"
                  }`}
                >
                  {isDiffTab ? (
                    <GitBranch className="h-3.5 w-3.5 text-blue-400 shrink-0" />
                  ) : (
                    <FileCode className="h-3.5 w-3.5 text-amber-400 shrink-0" />
                  )}
                  <span className="truncate max-w-[140px]">{tabLabel}</span>

                  {openTabs.length > 1 && (
                    <button
                      onClick={(e) => handleCloseTab(tab, e)}
                      className="ml-1 rounded p-0.5 text-slate-500 hover:bg-slate-700 hover:text-white"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  )}
                </div>
              );
            })}
          </div>

          {/* Active Editor Content View */}
          <div className="flex-1 overflow-hidden relative">
            {activeTab === "diff" ? (
              <DiffViewer runId={runId} diffs={diffs} onRefresh={refreshDiffs} />
            ) : (
              <CodeEditorView
                filename={activeTab.split("/").pop() || activeTab}
                content={fileContents[activeTab] || "# Loading file content..."}
                onRunFile={handleRunFile}
                isRunning={isRunningFile}
              />
            )}
          </div>

          {/* Bottom Panel (Terminal / Reasoning / Tool Activity) */}
          <div
            className={`border-t border-slate-800 bg-[#0d1424] flex flex-col transition-all duration-150 ${
              bottomPanelExpanded ? "h-64 xl:h-72" : "h-9"
            }`}
          >
            {/* Bottom Panel Header */}
            <div className="flex h-9 items-center justify-between border-b border-slate-800/80 px-3 text-xs select-none">
              <div className="flex items-center space-x-1">
                <button
                  onClick={() => {
                    setBottomTab("terminal");
                    setBottomPanelExpanded(true);
                  }}
                  className={`flex items-center space-x-1.5 px-3 py-1 rounded text-xs font-medium uppercase tracking-wider transition-colors ${
                    bottomTab === "terminal" && bottomPanelExpanded
                      ? "text-blue-400 border-b-2 border-blue-500"
                      : "text-slate-400 hover:text-white"
                  }`}
                >
                  <TerminalIcon className="h-3.5 w-3.5" />
                  <span>Terminal</span>
                </button>

                <button
                  onClick={() => {
                    setBottomTab("thoughts");
                    setBottomPanelExpanded(true);
                  }}
                  className={`flex items-center space-x-1.5 px-3 py-1 rounded text-xs font-medium uppercase tracking-wider transition-colors ${
                    bottomTab === "thoughts" && bottomPanelExpanded
                      ? "text-blue-400 border-b-2 border-blue-500"
                      : "text-slate-400 hover:text-white"
                  }`}
                >
                  <Sparkles className="h-3.5 w-3.5" />
                  <span>Agent Thoughts</span>
                </button>

                <button
                  onClick={() => {
                    setBottomTab("actions");
                    setBottomPanelExpanded(true);
                  }}
                  className={`flex items-center space-x-1.5 px-3 py-1 rounded text-xs font-medium uppercase tracking-wider transition-colors ${
                    bottomTab === "actions" && bottomPanelExpanded
                      ? "text-blue-400 border-b-2 border-blue-500"
                      : "text-slate-400 hover:text-white"
                  }`}
                >
                  <Activity className="h-3.5 w-3.5" />
                  <span>Actions ({state.toolCalls.size})</span>
                </button>
              </div>

              {/* Panel Toggle */}
              <button
                onClick={() => setBottomPanelExpanded(!bottomPanelExpanded)}
                className="p-1 text-slate-400 hover:text-white rounded hover:bg-slate-800 transition-colors"
                title={bottomPanelExpanded ? "Collapse panel" : "Expand panel"}
              >
                {bottomPanelExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4" />}
              </button>
            </div>

            {/* Bottom Panel Content */}
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
                  <div className="h-full overflow-y-auto p-3">
                    <ReasoningStream
                      events={state.events}
                      toolCalls={state.toolCalls}
                    />
                  </div>
                )}

                {bottomTab === "actions" && (
                  <div className="h-full overflow-y-auto p-3 space-y-2 font-mono text-xs">
                    {Array.from(state.toolCalls.values()).map((tc) => (
                      <div
                        key={tc.id}
                        className="rounded border border-slate-800 bg-[#090d16] p-2 space-y-1"
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-bold text-blue-400">{tc.name}</span>
                          <span className={`text-[10px] ${tc.result?.is_error ? "text-rose-400" : "text-emerald-400"}`}>
                            {tc.result?.is_error ? "ERROR" : "OK"}
                          </span>
                        </div>
                        {tc.arguments && (
                          <div className="text-[11px] text-slate-400 truncate">
                            {JSON.stringify(tc.arguments)}
                          </div>
                        )}
                        {tc.result?.output && (
                          <div className="text-[11px] text-slate-300 max-h-20 overflow-y-auto bg-slate-950 p-1.5 rounded">
                            {tc.result.output}
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
      </div>
    </div>
  );
}
