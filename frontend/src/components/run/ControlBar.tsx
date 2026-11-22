import React, { useState } from "react";
import {
  Play,
  Pause,
  AlertTriangle,
  Send,
  Download,
  Loader2,
  FileCode,
  FileText,
  Terminal,
  ChevronDown,
} from "lucide-react";
import type { ArtifactUrls, Run, RunStatus } from "../../types/run";
import { api } from "../../services/api";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";

export interface ControlBarProps {
  run: Run;
  isPausing?: boolean;
  status?: RunStatus;
  artifacts?: ArtifactUrls | null;
  onControlAction?: (actionName: string) => void;
}

export function ControlBar({
  run,
  isPausing: propIsPausing,
  status: propStatus,
  artifacts: propArtifacts,
  onControlAction,
}: ControlBarProps) {
  const currentStatus = propStatus ?? run.status;
  const isPausing = propIsPausing ?? run.is_pausing;

  const [guidance, setGuidance] = useState("");
  const [isSendingGuidance, setIsSendingGuidance] = useState(false);
  const [guidanceSuccess, setGuidanceSuccess] = useState(false);

  const [terminateOpen, setTerminateOpen] = useState(false);
  const [terminateReason, setTerminateReason] = useState("User terminated");
  const [isTerminating, setIsTerminating] = useState(false);

  const [isPausingAction, setIsPausingAction] = useState(false);
  const [isResumingAction, setIsResumingAction] = useState(false);

  const [artifacts, setArtifacts] = useState<ArtifactUrls | null>(propArtifacts ?? null);
  const [isLoadingArtifacts, setIsLoadingArtifacts] = useState(false);

  const isTerminal = ["SUCCEEDED", "FAILED", "TERMINATED"].includes(currentStatus);
  const isRunning = currentStatus === "RUNNING";
  const isPaused = currentStatus === "PAUSED";

  const handlePause = async (mode: "boundary" | "now" = "boundary") => {
    try {
      setIsPausingAction(true);
      await api.pauseRun(run.id, mode);
      onControlAction?.(`pause_${mode}`);
    } catch (err) {
      console.error("Failed to pause run:", err);
    } finally {
      setIsPausingAction(false);
    }
  };

  const handleResume = async () => {
    try {
      setIsResumingAction(true);
      await api.resumeRun(run.id);
      onControlAction?.("resume");
    } catch (err) {
      console.error("Failed to resume run:", err);
    } finally {
      setIsResumingAction(false);
    }
  };

  const handleSendGuidance = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!guidance.trim() || isSendingGuidance || isTerminal) return;

    try {
      setIsSendingGuidance(true);
      await api.injectGuidance(run.id, guidance.trim());
      setGuidance("");
      setGuidanceSuccess(true);
      setTimeout(() => setGuidanceSuccess(false), 2500);
      onControlAction?.("guidance");
    } catch (err) {
      console.error("Failed to inject guidance:", err);
    } finally {
      setIsSendingGuidance(false);
    }
  };

  const handleTerminateConfirm = async () => {
    try {
      setIsTerminating(true);
      await api.terminateRun(run.id, terminateReason.trim() || "User terminated");
      setTerminateOpen(false);
      onControlAction?.("terminate");
    } catch (err) {
      console.error("Failed to terminate run:", err);
    } finally {
      setIsTerminating(false);
    }
  };

  const loadArtifacts = async () => {
    try {
      setIsLoadingArtifacts(true);
      const res = await api.getArtifacts(run.id);
      setArtifacts(res);
    } catch (err) {
      console.error("Failed to load artifacts:", err);
    } finally {
      setIsLoadingArtifacts(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 bg-slate-900/90 px-4 py-2.5 backdrop-blur">
      {/* Left: Execution Controls (Pause, Resume, Terminate) */}
      <div className="flex items-center space-x-2">
        {/* Pause Button / Dropdown */}
        {isPausing ? (
          <Button
            variant="outline"
            size="sm"
            disabled
            className="border-amber-700 bg-amber-950/40 text-amber-300"
          >
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin text-amber-400" />
            Pausing...
          </Button>
        ) : (
          <div className="inline-flex rounded-md shadow-sm">
            <Button
              variant="outline"
              size="sm"
              disabled={!isRunning || isPausingAction}
              onClick={() => handlePause("boundary")}
              className="rounded-r-none border-slate-700 text-slate-200 hover:bg-slate-800 hover:text-white"
            >
              {isPausingAction ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Pause className="mr-1.5 h-3.5 w-3.5 text-amber-400" />
              )}
              Pause
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!isRunning || isPausingAction}
                  className="rounded-l-none border-l-0 border-slate-700 px-1.5 text-slate-400 hover:text-white"
                >
                  <ChevronDown className="h-3 w-3" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start">
                <DropdownMenuItem onClick={() => handlePause("boundary")}>
                  <Pause className="mr-2 h-3.5 w-3.5 text-amber-400" />
                  Boundary Pause (Wait for step)
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => handlePause("now")}>
                  <AlertTriangle className="mr-2 h-3.5 w-3.5 text-rose-400" />
                  Pause Now (Cancel command)
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        )}

        {/* Resume Button (Enabled when PAUSED or when isPausing to cancel boundary pause) */}
        <Button
          variant="outline"
          size="sm"
          disabled={(!isPaused && !isPausing) || isResumingAction}
          onClick={handleResume}
          className={
            isPausing
              ? "border-amber-600 bg-amber-950/30 text-amber-300 hover:bg-amber-900/50"
              : "border-slate-700 text-slate-200 hover:bg-slate-800 hover:text-white"
          }
        >
          {isResumingAction ? (
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
          ) : (
            <Play className="mr-1.5 h-3.5 w-3.5 text-emerald-400" />
          )}
          {isPausing ? "Cancel Pause" : "Resume"}
        </Button>

        {/* Terminate Button */}
        <Button
          variant="destructive"
          size="sm"
          disabled={isTerminal}
          onClick={() => setTerminateOpen(true)}
          className="bg-rose-950/80 text-rose-300 border border-rose-800 hover:bg-rose-900 hover:text-white"
        >
          <AlertTriangle className="mr-1.5 h-3.5 w-3.5 text-rose-400" />
          Terminate
        </Button>
      </div>

      {/* Center: Guidance Input Form */}
      <form
        onSubmit={handleSendGuidance}
        className="flex flex-1 max-w-md items-center space-x-2"
      >
        <div className="relative flex-1">
          <Input
            value={guidance}
            onChange={(e) => setGuidance(e.target.value)}
            placeholder={
              isTerminal
                ? "Run is complete — guidance disabled"
                : "Steer agent (e.g. check test_calc.py:42)..."
            }
            disabled={isTerminal || isSendingGuidance}
            className="h-8 text-xs bg-slate-950 border-slate-700 text-slate-100 placeholder:text-slate-500 pr-8"
          />
          {guidanceSuccess && (
            <span className="absolute right-2.5 top-1.5 text-[10px] font-semibold text-emerald-400">
              Sent!
            </span>
          )}
        </div>
        <Button
          type="submit"
          size="sm"
          disabled={!guidance.trim() || isSendingGuidance || isTerminal}
          className="h-8 px-3 text-xs"
        >
          {isSendingGuidance ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Send className="h-3 w-3 mr-1" />
          )}
          Send
        </Button>
      </form>

      {/* Right: Artifacts Download Menu */}
      <div className="flex items-center space-x-2">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="outline"
              size="sm"
              onClick={loadArtifacts}
              className="border-slate-700 text-slate-200 hover:bg-slate-800 text-xs"
            >
              {isLoadingArtifacts ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Download className="mr-1.5 h-3.5 w-3.5 text-blue-400" />
              )}
              Artifacts
              <ChevronDown className="ml-1 h-3 w-3" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuItem
              disabled={!artifacts?.patch_url}
              onClick={() => {
                if (artifacts?.patch_url) window.open(artifacts.patch_url, "_blank");
              }}
            >
              <FileCode className="mr-2 h-4 w-4 text-emerald-400" />
              <div className="flex flex-col">
                <span className="font-medium">Git Patch</span>
                <span className="text-[10px] text-slate-400">Unified .diff patch</span>
              </div>
            </DropdownMenuItem>
            <DropdownMenuItem
              disabled={!artifacts?.logs_url}
              onClick={() => {
                if (artifacts?.logs_url) window.open(artifacts.logs_url, "_blank");
              }}
            >
              <Terminal className="mr-2 h-4 w-4 text-amber-400" />
              <div className="flex flex-col">
                <span className="font-medium">Execution Logs</span>
                <span className="text-[10px] text-slate-400">Full raw sandbox logs</span>
              </div>
            </DropdownMenuItem>
            <DropdownMenuItem
              disabled={!artifacts?.transcript_url}
              onClick={() => {
                if (artifacts?.transcript_url) window.open(artifacts.transcript_url, "_blank");
              }}
            >
              <FileText className="mr-2 h-4 w-4 text-sky-400" />
              <div className="flex flex-col">
                <span className="font-medium">Run Transcript</span>
                <span className="text-[10px] text-slate-400">Complete JSONL event log</span>
              </div>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {/* Terminate Confirmation Modal */}
      <Dialog open={terminateOpen} onOpenChange={setTerminateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center text-rose-400">
              <AlertTriangle className="mr-2 h-5 w-5 text-rose-500" />
              Terminate Agent Run?
            </DialogTitle>
            <DialogDescription>
              Terminating will halt the agent execution loop, extract the current
              git diff patch, and destroy the container within 5 seconds. This
              action cannot be undone.
            </DialogDescription>
          </DialogHeader>

          <div className="my-4 space-y-2">
            <label className="text-xs font-medium text-slate-300">
              Termination Reason (Optional):
            </label>
            <Input
              value={terminateReason}
              onChange={(e) => setTerminateReason(e.target.value)}
              placeholder="e.g. Taking too long, heading down wrong direction"
              className="bg-slate-950 border-slate-700 text-sm"
            />
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              size="sm"
              disabled={isTerminating}
              onClick={() => setTerminateOpen(false)}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              size="sm"
              disabled={isTerminating}
              onClick={handleTerminateConfirm}
            >
              {isTerminating ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : null}
              Terminate Now
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
