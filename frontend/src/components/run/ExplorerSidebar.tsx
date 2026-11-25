import React from "react";
import {
  FileCode,
  FolderOpen,
  GitBranch,
  Sparkles,
  Send,
} from "lucide-react";
import type { Run, FileDiff } from "../../types/run";

export interface WorkspaceFile {
  path: string;
  name: string;
  content?: string;
  status?: "added" | "modified" | "unchanged";
  additions?: number;
  deletions?: number;
}

export interface ExplorerSidebarProps {
  activeView: "files" | "agent" | "git";
  files: WorkspaceFile[];
  selectedFile: string | null;
  onSelectFile: (path: string) => void;
  run: Run | null;
  diffs: FileDiff[];
  guidanceText: string;
  onGuidanceChange: (val: string) => void;
  onSendGuidance: () => void;
  isSendingGuidance: boolean;
  guidanceFeedback?: { type: "success" | "error"; message: string } | null;
  totalTokens?: number;
  stepCount?: number;
}

export const ExplorerSidebar: React.FC<ExplorerSidebarProps> = ({
  activeView,
  files,
  selectedFile,
  onSelectFile,
  run,
  diffs,
  guidanceText,
  onGuidanceChange,
  onSendGuidance,
  isSendingGuidance,
  guidanceFeedback,
  totalTokens = 0,
  stepCount = 0,
}) => {
  const getFileIcon = (filename: string) => {
    if (filename.endsWith(".py")) {
      return <span className="font-mono font-medium text-[#d29922] text-[10px]">PY</span>;
    }
    if (filename.endsWith(".rs")) {
      return <span className="font-mono font-medium text-[#e5484d] text-[10px]">RS</span>;
    }
    if (filename.endsWith(".ts") || filename.endsWith(".tsx")) {
      return <span className="font-mono font-medium text-[#2f81f7] text-[10px]">TS</span>;
    }
    if (filename.endsWith(".json")) {
      return <span className="font-mono font-medium text-[#a1a1a6] text-[10px]">{"{}"}</span>;
    }
    if (filename.endsWith(".md")) {
      return <span className="font-mono font-medium text-[#a1a1a6] text-[10px]">MD</span>;
    }
    return <FileCode className="h-3.5 w-3.5 text-[#85858b]" strokeWidth={1.5} />;
  };

  if (activeView === "files") {
    return (
      <div className="flex h-full flex-col bg-[#161619] border-r border-white/[0.08] select-none">
        <div className="flex h-9 items-center justify-between px-4 border-b border-white/[0.08] text-xs font-medium text-[#a1a1a6]">
          <div className="flex items-center gap-2">
            <FolderOpen className="h-3.5 w-3.5 text-[#85858b]" strokeWidth={1.5} />
            <span>Workspace files</span>
          </div>
          <span className="font-mono text-[11px] text-[#85858b] tabular-nums">
            {files.length}
          </span>
        </div>

        <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
          {files.length === 0 ? (
            <div className="p-4 text-center text-xs text-[#85858b]">
              Waiting for files
            </div>
          ) : (
            files.map((file) => {
              const isSelected = selectedFile === file.path;
              return (
                <button
                  key={file.path}
                  onClick={() => onSelectFile(file.path)}
                  className={`flex h-8 w-full items-center justify-between rounded-md px-2.5 text-left text-xs transition-colors ${
                    isSelected
                      ? "bg-[#1e1e22] text-[#ededed] font-medium border border-white/[0.08]"
                      : "text-[#a1a1a6] hover:bg-white/[0.04] hover:text-[#ededed] border border-transparent"
                  }`}
                >
                  <div className="flex items-center gap-2 truncate">
                    <div className="flex h-4 w-4 shrink-0 items-center justify-center">
                      {getFileIcon(file.name)}
                    </div>
                    <span className="truncate">{file.name}</span>
                  </div>

                  {file.status === "added" && (
                    <span className="shrink-0 font-mono text-[10px] text-[#4cc38a]">
                      new
                    </span>
                  )}
                  {file.status === "modified" && (
                    <span className="shrink-0 font-mono text-[10px] text-[#2f81f7]">
                      mod
                    </span>
                  )}
                </button>
              );
            })
          )}
        </div>

        <div className="border-t border-white/[0.08] p-4 bg-[#111113] text-xs space-y-2 tabular-nums">
          <div className="flex items-center justify-between">
            <span className="text-[#85858b]">Verification</span>
            <span className="font-mono text-[#ededed]">{run?.options?.verification || "required"}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[#85858b]">Steps</span>
            <span className="font-mono text-[#ededed]">{stepCount}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[#85858b]">Tokens</span>
            <span className="font-mono text-[#ededed]">{totalTokens.toLocaleString()}</span>
          </div>
        </div>
      </div>
    );
  }

  if (activeView === "git") {
    const totalAdditions = diffs.reduce((sum, d) => sum + (d.additions || 0), 0);
    const totalDeletions = diffs.reduce((sum, d) => sum + (d.deletions || 0), 0);

    return (
      <div className="flex h-full flex-col bg-[#161619] border-r border-white/[0.08] select-none">
        <div className="flex h-9 items-center justify-between px-4 border-b border-white/[0.08] text-xs font-medium text-[#a1a1a6]">
          <div className="flex items-center gap-2">
            <GitBranch className="h-3.5 w-3.5 text-[#85858b]" strokeWidth={1.5} />
            <span>Git changes</span>
          </div>
          <div className="flex items-center gap-1.5 font-mono text-[11px] tabular-nums">
            <span className="text-[#4cc38a]">+{totalAdditions}</span>
            <span className="text-[#e5484d]">-{totalDeletions}</span>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
          {diffs.length === 0 ? (
            <div className="p-4 text-center text-xs text-[#85858b]">
              No changes detected yet
            </div>
          ) : (
            diffs.map((diff) => (
              <button
                key={diff.path}
                onClick={() => onSelectFile(`diff:${diff.path}`)}
                className="flex h-8 w-full items-center justify-between rounded-md px-2.5 text-left text-xs text-[#a1a1a6] hover:bg-white/[0.04] hover:text-[#ededed] transition-colors"
              >
                <div className="flex items-center gap-2 truncate">
                  <div className="flex h-4 w-4 shrink-0 items-center justify-center">
                    {getFileIcon(diff.path)}
                  </div>
                  <span className="truncate">{diff.path}</span>
                </div>
                <div className="flex items-center gap-1.5 font-mono text-[11px] shrink-0 tabular-nums">
                  <span className="text-[#4cc38a]">+{diff.additions}</span>
                  <span className="text-[#e5484d]">-{diff.deletions}</span>
                </div>
              </button>
            ))
          )}
        </div>
      </div>
    );
  }

  // Agent Guidance & Controls
  const isTerminalRun = Boolean(
    run?.status && ["SUCCEEDED", "FAILED", "TERMINATED"].includes(run.status)
  );

  return (
    <div className="flex h-full flex-col bg-[#161619] border-r border-white/[0.08] p-4 space-y-4">
      <div className="flex items-center gap-2 text-xs font-medium text-[#ededed]">
        <Sparkles className="h-4 w-4 text-[#a1a1a6]" strokeWidth={1.5} />
        <span>Steer agent</span>
      </div>

      <p className="text-xs text-[#a1a1a6] leading-relaxed">
        {isTerminalRun
          ? "Run has finished. Start a new run or Re-run Task to steer an active agent."
          : "Inject steering instructions into the running agent loop at the next step boundary."}
      </p>

      <div className="space-y-2.5">
        <textarea
          value={guidanceText}
          onChange={(e) => onGuidanceChange(e.target.value)}
          disabled={isTerminalRun || isSendingGuidance}
          placeholder={
            isTerminalRun
              ? "Guidance disabled for completed runs"
              : "Add unit tests with pytest..."
          }
          className="w-full h-28 rounded-lg bg-[#0b0b0d] border border-white/[0.08] p-3 text-xs text-[#ededed] placeholder:text-[#85858b] disabled:opacity-50 focus:outline-none focus:border-[#2f81f7] transition-colors"
        />

        <button
          type="button"
          onClick={onSendGuidance}
          disabled={isTerminalRun || !guidanceText.trim() || isSendingGuidance}
          className="flex h-8 w-full items-center justify-center gap-1.5 rounded-lg bg-[#ededed] hover:bg-white disabled:opacity-50 px-3 text-xs font-medium text-[#0b0b0d] transition-colors"
        >
          <Send className="h-3 w-3" strokeWidth={1.5} />
          <span>{isSendingGuidance ? "Sending..." : "Send guidance"}</span>
        </button>

        {guidanceFeedback && (
          <div
            className={`rounded-md border px-2.5 py-1.5 text-[11px] ${
              guidanceFeedback.type === "success"
                ? "border-[#4cc38a]/30 bg-[#4cc38a]/10 text-[#4cc38a]"
                : "border-[#e5484d]/30 bg-[#e5484d]/10 text-[#e5484d]"
            }`}
          >
            {guidanceFeedback.message}
          </div>
        )}
      </div>

      <div className="rounded-lg bg-[#111113] border border-white/[0.08] p-3 space-y-2 text-xs">
        <div className="flex items-center justify-between text-[#85858b]">
          <span>Engine</span>
          <span className="text-[#4cc38a] font-mono">ready</span>
        </div>
        <div className="flex items-center justify-between text-[#85858b]">
          <span>Provider</span>
          <span className="text-[#ededed] font-mono">groq</span>
        </div>
        <div className="flex items-center justify-between text-[#85858b]">
          <span>Model</span>
          <span className="text-[#ededed] font-mono text-[11px]">gpt-oss-120b</span>
        </div>
      </div>
    </div>
  );
};
