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
  totalTokens = 0,
  stepCount = 0,
}) => {
  const getFileIcon = (filename: string) => {
    if (filename.endsWith(".py")) {
      return <span className="font-bold text-amber-400 text-[10px]">PY</span>;
    }
    if (filename.endsWith(".rs")) {
      return <span className="font-bold text-orange-500 text-[10px]">RS</span>;
    }
    if (filename.endsWith(".ts") || filename.endsWith(".tsx")) {
      return <span className="font-bold text-blue-400 text-[10px]">TS</span>;
    }
    if (filename.endsWith(".json")) {
      return <span className="font-bold text-yellow-300 text-[10px]">{"{}"}</span>;
    }
    if (filename.endsWith(".md")) {
      return <span className="font-bold text-sky-300 text-[10px]">MD</span>;
    }
    return <FileCode className="h-3.5 w-3.5 text-slate-400" />;
  };

  if (activeView === "files") {
    return (
      <div className="flex h-full flex-col bg-[#0f172a] border-r border-slate-800 select-none">
        {/* Explorer Header */}
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-800 text-[11px] font-bold tracking-wider text-slate-400 uppercase">
          <div className="flex items-center space-x-1.5">
            <FolderOpen className="h-3.5 w-3.5 text-blue-400" />
            <span>Workspace Files</span>
          </div>
          <span className="rounded-full bg-slate-800 px-2 py-0.5 text-[10px] text-slate-300">
            {files.length}
          </span>
        </div>

        {/* Files List */}
        <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
          {files.length === 0 ? (
            <div className="p-4 text-center text-xs text-slate-500">
              <p className="animate-pulse">Waiting for agent to create files...</p>
            </div>
          ) : (
            files.map((file) => {
              const isSelected = selectedFile === file.path;
              return (
                <button
                  key={file.path}
                  onClick={() => onSelectFile(file.path)}
                  className={`flex w-full items-center justify-between rounded px-2.5 py-1.5 text-left text-xs transition-colors ${
                    isSelected
                      ? "bg-blue-600/20 text-blue-200 border-l-2 border-blue-500 font-medium"
                      : "text-slate-300 hover:bg-slate-800/60 hover:text-white"
                  }`}
                >
                  <div className="flex items-center space-x-2 truncate">
                    <div className="flex h-4 w-4 shrink-0 items-center justify-center">
                      {getFileIcon(file.name)}
                    </div>
                    <span className="truncate">{file.name}</span>
                  </div>

                  {file.status === "added" && (
                    <span className="shrink-0 text-[10px] font-mono text-emerald-400 bg-emerald-950/60 border border-emerald-800/40 rounded px-1.5">
                      +new
                    </span>
                  )}
                  {file.status === "modified" && (
                    <span className="shrink-0 text-[10px] font-mono text-blue-400 bg-blue-950/60 border border-blue-800/40 rounded px-1.5">
                      mod
                    </span>
                  )}
                </button>
              );
            })
          )}
        </div>

        {/* Summary Footer */}
        <div className="border-t border-slate-800 p-3 bg-slate-900/60 text-[11px] text-slate-400 space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-slate-500">Task Mode</span>
            <span className="font-mono text-slate-300">{run?.options?.verification || "required"}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-slate-500">Total Steps</span>
            <span className="font-mono text-slate-300">{stepCount}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-slate-500">Tokens</span>
            <span className="font-mono text-slate-300">{totalTokens.toLocaleString()}</span>
          </div>
        </div>
      </div>
    );
  }

  if (activeView === "git") {
    const totalAdditions = diffs.reduce((sum, d) => sum + (d.additions || 0), 0);
    const totalDeletions = diffs.reduce((sum, d) => sum + (d.deletions || 0), 0);

    return (
      <div className="flex h-full flex-col bg-[#0f172a] border-r border-slate-800 select-none">
        {/* Source Control Header */}
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-800 text-[11px] font-bold tracking-wider text-slate-400 uppercase">
          <div className="flex items-center space-x-1.5">
            <GitBranch className="h-3.5 w-3.5 text-blue-400" />
            <span>Git Changes</span>
          </div>
          <div className="flex items-center space-x-1 font-mono text-[10px]">
            <span className="text-emerald-400 font-bold">+{totalAdditions}</span>
            <span className="text-rose-400 font-bold">-{totalDeletions}</span>
          </div>
        </div>

        {/* Diff Changes List */}
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {diffs.length === 0 ? (
            <div className="p-4 text-center text-xs text-slate-500">
              <p>No changes detected yet.</p>
            </div>
          ) : (
            diffs.map((diff) => (
              <button
                key={diff.path}
                onClick={() => onSelectFile(`diff:${diff.path}`)}
                className="flex w-full items-center justify-between rounded px-2.5 py-1.5 text-left text-xs text-slate-300 hover:bg-slate-800/60 hover:text-white transition-colors"
              >
                <div className="flex items-center space-x-2 truncate">
                  <div className="flex h-4 w-4 shrink-0 items-center justify-center">
                    {getFileIcon(diff.path)}
                  </div>
                  <span className="truncate">{diff.path}</span>
                </div>
                <div className="flex items-center space-x-1 font-mono text-[10px] shrink-0">
                  <span className="text-emerald-400">+{diff.additions}</span>
                  <span className="text-rose-400">-{diff.deletions}</span>
                </div>
              </button>
            ))
          )}
        </div>
      </div>
    );
  }

  // Agent Guidance & Controls
  return (
    <div className="flex h-full flex-col bg-[#0f172a] border-r border-slate-800 p-4 space-y-4">
      <div className="flex items-center space-x-2 text-xs font-bold text-slate-300 uppercase tracking-wider">
        <Sparkles className="h-4 w-4 text-blue-400" />
        <span>Steer Agent</span>
      </div>

      <p className="text-xs text-slate-400 leading-relaxed">
        Inject direct steering instructions into the running agent loop at the next execution boundary.
      </p>

      <div className="space-y-2">
        <textarea
          value={guidanceText}
          onChange={(e) => onGuidanceChange(e.target.value)}
          placeholder="e.g. Add unit tests with pytest, make words list configurable..."
          className="w-full h-28 rounded-lg bg-slate-950 border border-slate-800 p-2.5 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-blue-500 transition-colors"
        />

        <button
          onClick={onSendGuidance}
          disabled={!guidanceText.trim() || isSendingGuidance}
          className="flex w-full items-center justify-center space-x-1.5 rounded-full bg-blue-600 hover:bg-blue-500 disabled:opacity-50 px-4 py-2 text-xs font-semibold text-white transition-colors shadow-sm"
        >
          <Send className="h-3 w-3" />
          <span>{isSendingGuidance ? "Sending..." : "Send Guidance"}</span>
        </button>
      </div>

      <div className="rounded-lg bg-slate-900/80 border border-slate-800/80 p-3 space-y-2 text-xs">
        <div className="flex items-center justify-between text-slate-400">
          <span>Engine Status</span>
          <span className="text-emerald-400 font-medium">Ready</span>
        </div>
        <div className="flex items-center justify-between text-slate-400">
          <span>Provider</span>
          <span className="text-slate-200 font-mono">GROQ</span>
        </div>
        <div className="flex items-center justify-between text-slate-400">
          <span>Model</span>
          <span className="text-slate-200 font-mono text-[10px]">openai/gpt-oss-120b</span>
        </div>
      </div>
    </div>
  );
};
