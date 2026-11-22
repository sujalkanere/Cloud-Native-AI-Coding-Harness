import { useEffect, useState, useMemo } from "react";
import {
  ArrowLeft,
  Activity,
  CheckCircle,
  XCircle,
  Clock,
  Shield,
  Layers,
  Wifi,
  WifiOff,
} from "lucide-react";
import type { RunStatus } from "../../types/run";
import { useRunEvents } from "../../hooks/useRunEvents";
import { useRunDetails } from "../../hooks/useRunDetails";
import { ControlBar } from "./ControlBar";
import { ReasoningStream } from "./ReasoningStream";
import { TerminalView } from "./TerminalView";
import { DiffViewer } from "./DiffViewer";
import { Button } from "../ui/button";
import { Badge } from "../ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../ui/tabs";

export interface RunViewProps {
  runId: string;
  onBack?: () => void;
}

export function RunView({ runId, onBack }: RunViewProps) {
  const { run, refetch: refetchRun } = useRunDetails({ runId, pollInterval: 5000 });
  const { state, connectionStatus } = useRunEvents({ runId, enabled: true });

  // Merge live status from WebSocket reducer or API run metadata
  const currentStatus: RunStatus = state.status !== "QUEUED" ? state.status : (run?.status ?? "QUEUED");
  const isPausing: boolean = state.isPausing || (run?.is_pausing ?? false);

  // Compute live duration
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

  return (
    <div className="flex h-screen flex-col bg-slate-950 text-slate-100 overflow-hidden">
      {/* Top Navigation & Metadata Header */}
      <header className="flex items-center justify-between border-b border-slate-800 bg-slate-900/90 px-4 py-2.5">
        <div className="flex items-center space-x-3 overflow-hidden">
          {onBack && (
            <Button
              variant="ghost"
              size="sm"
              onClick={onBack}
              className="h-8 w-8 p-0 text-slate-400 hover:text-white"
            >
              <ArrowLeft className="h-4 w-4" />
            </Button>
          )}

          <div className="flex items-center space-x-2">
            <Layers className="h-4 w-4 text-blue-500 shrink-0" />
            <span className="font-mono text-xs font-bold text-white shrink-0">
              {runId}
            </span>
            {run?.task && (
              <span className="hidden md:inline truncate max-w-md text-xs text-slate-400 border-l border-slate-800 pl-2">
                {run.task}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center space-x-3 shrink-0">
          {/* Verification Mode */}
          <div className="hidden sm:flex items-center text-xs text-slate-400">
            <Shield className="mr-1 h-3.5 w-3.5 text-blue-400" />
            <span>Mode: {run?.options?.verification || "required"}</span>
          </div>

          {/* Duration */}
          <div className="flex items-center text-xs text-slate-400 font-mono">
            <Clock className="mr-1 h-3.5 w-3.5 text-slate-500" />
            <span>{formattedDuration}</span>
          </div>

          {/* Status Badge */}
          {getStatusBadge()}

          {/* Connection Indicator */}
          <div
            title={`WebSocket: ${connectionStatus}`}
            className="flex items-center"
          >
            {connectionStatus === "connected" ? (
              <Wifi className="h-3.5 w-3.5 text-emerald-400" />
            ) : (
              <WifiOff className="h-3.5 w-3.5 text-amber-500 animate-pulse" />
            )}
          </div>
        </div>
      </header>

      {/* Control Bar (Pause, Resume, Guidance, Terminate, Artifacts) */}
      {run ? (
        <ControlBar
          run={run}
          status={currentStatus}
          isPausing={isPausing}
          onControlAction={() => refetchRun()}
        />
      ) : (
        <div className="h-10 bg-slate-900 border-b border-slate-800 animate-pulse" />
      )}

      {/* Main Workspace: Responsive Layout (1280px / 768px) */}
      <main className="flex flex-1 flex-col xl:flex-row overflow-hidden">
        {/* Left Column: Reasoning & Execution Stream */}
        <div className="h-1/2 xl:h-full w-full xl:w-[40%] 2xl:w-[38%] border-b xl:border-b-0 xl:border-r border-slate-800 overflow-hidden flex flex-col">
          <ReasoningStream
            events={state.events}
            toolCalls={state.toolCalls}
          />
        </div>

        {/* Right Column: Terminal & Diff Viewer */}
        <div className="h-1/2 xl:h-full w-full xl:w-[60%] 2xl:w-[62%] flex flex-col overflow-hidden">
          {/* Desktop (>= 1280px): Vertically split Terminal (top) and Diff (bottom) */}
          <div className="hidden xl:flex xl:flex-col h-full overflow-hidden">
            <div className="h-1/2 border-b border-slate-800 overflow-hidden">
              <TerminalView
                chunks={state.terminalChunks}
                isTruncated={state.isTerminalTruncated}
                truncationMessage={state.truncationMessage}
              />
            </div>
            <div className="h-1/2 overflow-hidden">
              <DiffViewer runId={runId} />
            </div>
          </div>

          {/* Medium / Tablet (< 1280px): Segmented Tab View */}
          <div className="flex xl:hidden flex-col h-full overflow-hidden">
            <Tabs defaultValue="terminal" className="flex-1 flex flex-col overflow-hidden">
              <div className="border-b border-slate-800 bg-slate-900/90 px-3 py-1">
                <TabsList className="bg-slate-950">
                  <TabsTrigger value="terminal">Execution Terminal</TabsTrigger>
                  <TabsTrigger value="diff">Workspace Diff</TabsTrigger>
                </TabsList>
              </div>

              <TabsContent value="terminal" className="flex-1 m-0 overflow-hidden">
                <TerminalView
                  chunks={state.terminalChunks}
                  isTruncated={state.isTerminalTruncated}
                  truncationMessage={state.truncationMessage}
                />
              </TabsContent>

              <TabsContent value="diff" className="flex-1 m-0 overflow-hidden">
                <DiffViewer runId={runId} />
              </TabsContent>
            </Tabs>
          </div>
        </div>
      </main>
    </div>
  );
}
