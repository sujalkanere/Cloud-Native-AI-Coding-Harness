import { useState, useEffect, useMemo, useCallback } from "react";
import ReactDiffViewer from "react-diff-viewer-continued";
import {
  FileCode,
  FilePlus,
  FileMinus,
  FileText,
  Columns,
  Square,
  RefreshCw,
  Binary,
} from "lucide-react";
import type { FileDiff } from "../../types/run";
import { api } from "../../services/api";
import { Button } from "../ui/button";
import { Badge } from "../ui/badge";

export interface DiffViewerProps {
  runId: string;
  diffs?: FileDiff[];
  onRefresh?: () => void;
}

function parseUnifiedDiffToOldAndNew(diffPatch: string): { oldText: string; newText: string } {
  const lines = diffPatch.split("\n");
  const oldLines: string[] = [];
  const newLines: string[] = [];

  let inHunk = false;
  for (const line of lines) {
    if (line.startsWith("@@")) {
      inHunk = true;
      continue;
    }
    if (!inHunk) continue;

    if (line.startsWith("+")) {
      newLines.push(line.slice(1));
    } else if (line.startsWith("-")) {
      oldLines.push(line.slice(1));
    } else if (line.startsWith(" ")) {
      oldLines.push(line.slice(1));
      newLines.push(line.slice(1));
    }
  }

  return {
    oldText: oldLines.join("\n"),
    newText: newLines.join("\n"),
  };
}

export function DiffViewer({ runId, diffs: initialDiffs, onRefresh }: DiffViewerProps) {
  const [diffs, setDiffs] = useState<FileDiff[]>(initialDiffs || []);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [splitView, setSplitView] = useState<boolean>(true);
  const [loading, setLoading] = useState<boolean>(false);

  const fetchDiffs = useCallback(async () => {
    try {
      setLoading(true);
      const data = await api.getDiff(runId);
      setDiffs(data || []);
      if (data && data.length > 0) {
        setSelectedPath((prev) => prev || data[0].path);
      }
    } catch (err) {
      console.error("Failed to fetch diffs:", err);
    } finally {
      setLoading(false);
      onRefresh?.();
    }
  }, [runId, onRefresh]);

  useEffect(() => {
    if (initialDiffs && initialDiffs.length > 0) {
      setDiffs(initialDiffs);
      setSelectedPath((prev) => prev || initialDiffs[0].path);
    } else if (runId) {
      fetchDiffs();
    }
  }, [runId, initialDiffs, fetchDiffs]);

  // Keep selected file in sync if list updates
  useEffect(() => {
    if (diffs.length > 0 && (!selectedPath || !diffs.some((d) => d.path === selectedPath))) {
      setSelectedPath(diffs[0].path);
    }
  }, [diffs, selectedPath]);

  const activeDiff = useMemo(() => {
    return diffs.find((d) => d.path === selectedPath) || null;
  }, [diffs, selectedPath]);

  const { oldText, newText } = useMemo(() => {
    if (!activeDiff) return { oldText: "", newText: "" };

    if (activeDiff.old_content !== null && activeDiff.new_content !== null) {
      return {
        oldText: activeDiff.old_content || "",
        newText: activeDiff.new_content || "",
      };
    }

    if (activeDiff.diff_patch) {
      return parseUnifiedDiffToOldAndNew(activeDiff.diff_patch);
    }

    return { oldText: "", newText: "" };
  }, [activeDiff]);

  const totalAdditions = useMemo(
    () => diffs.reduce((sum, d) => sum + (d.additions || 0), 0),
    [diffs]
  );
  const totalDeletions = useMemo(
    () => diffs.reduce((sum, d) => sum + (d.deletions || 0), 0),
    [diffs]
  );

  const customDarkThemeStyles = {
    variables: {
      dark: {
        diffViewerBackground: "#090d16",
        diffViewerColor: "#cbd5e1",
        addedBackground: "rgba(16, 185, 129, 0.15)",
        addedColor: "#a7f3d0",
        removedBackground: "rgba(244, 63, 94, 0.15)",
        removedColor: "#fecdd3",
        wordAddedBackground: "rgba(16, 185, 129, 0.35)",
        wordRemovedBackground: "rgba(244, 63, 94, 0.35)",
        addedGutterBackground: "rgba(16, 185, 129, 0.2)",
        removedGutterBackground: "rgba(244, 63, 94, 0.2)",
        gutterBackground: "#0f172a",
        gutterBackgroundDark: "#0b1120",
        highlightBackground: "#1e293b",
        highlightGutterBackground: "#334155",
        codeFoldGutterBackground: "#1e293b",
        codeFoldBackground: "#1e293b",
        emptyLineBackground: "#090d16",
        gutterColor: "#64748b",
        addedGutterColor: "#34d399",
        removedGutterColor: "#fb7185",
      },
    },
    line: {
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
      fontSize: "12px",
      lineHeight: "18px",
    },
  };

  return (
    <div className="flex h-full flex-col bg-slate-950">
      {/* Diff Top Bar */}
      <div className="flex items-center justify-between border-b border-slate-800 bg-slate-900/70 px-4 py-2">
        <div className="flex items-center space-x-2">
          <FileCode className="h-4 w-4 text-blue-400" />
          <span className="text-xs font-semibold text-white">Workspace Changes</span>
          <div className="flex items-center space-x-1 ml-2">
            <span className="text-[11px] font-mono text-emerald-400">+{totalAdditions}</span>
            <span className="text-[11px] font-mono text-rose-400">-{totalDeletions}</span>
          </div>
        </div>

        <div className="flex items-center space-x-2">
          {/* Split vs Unified Toggle */}
          <div className="inline-flex rounded-md border border-slate-700 bg-slate-900 p-0.5">
            <button
              type="button"
              onClick={() => setSplitView(true)}
              className={`flex items-center px-2 py-0.5 rounded text-[11px] transition ${
                splitView ? "bg-slate-800 text-white font-medium" : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Columns className="h-3 w-3 mr-1" />
              Split
            </button>
            <button
              type="button"
              onClick={() => setSplitView(false)}
              className={`flex items-center px-2 py-0.5 rounded text-[11px] transition ${
                !splitView ? "bg-slate-800 text-white font-medium" : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Square className="h-3 w-3 mr-1" />
              Unified
            </button>
          </div>

          <Button
            variant="outline"
            size="sm"
            onClick={fetchDiffs}
            disabled={loading}
            className="h-7 px-2 border-slate-700 text-slate-300 hover:bg-slate-800"
          >
            <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </div>
      </div>

      {/* Main Diff Content: Sidebar + Viewer */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left: Files List Sidebar */}
        <div className="w-56 shrink-0 border-r border-slate-800 bg-slate-950 overflow-y-auto">
          <div className="p-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400 border-b border-slate-800/60">
            Files ({diffs.length})
          </div>
          {diffs.length === 0 ? (
            <div className="p-4 text-center text-xs text-slate-500">
              No files modified yet.
            </div>
          ) : (
            <div className="divide-y divide-slate-800/40">
              {diffs.map((diff) => {
                const isSelected = diff.path === selectedPath;
                return (
                  <div
                    key={diff.path}
                    onClick={() => setSelectedPath(diff.path)}
                    className={`flex cursor-pointer items-center justify-between p-2 text-xs transition ${
                      isSelected
                        ? "bg-slate-800/90 text-white font-medium"
                        : "text-slate-300 hover:bg-slate-900"
                    }`}
                  >
                    <div className="flex items-center space-x-1.5 overflow-hidden mr-1">
                      {diff.status === "added" ? (
                        <FilePlus className="h-3.5 w-3.5 text-emerald-400 shrink-0" />
                      ) : diff.status === "deleted" ? (
                        <FileMinus className="h-3.5 w-3.5 text-rose-400 shrink-0" />
                      ) : diff.status === "binary" ? (
                        <Binary className="h-3.5 w-3.5 text-purple-400 shrink-0" />
                      ) : (
                        <FileText className="h-3.5 w-3.5 text-blue-400 shrink-0" />
                      )}
                      <span className="truncate font-mono text-[11px]">
                        {diff.path}
                      </span>
                    </div>

                    <div className="flex items-center space-x-1 text-[10px] font-mono shrink-0">
                      {diff.additions > 0 && (
                        <span className="text-emerald-400">+{diff.additions}</span>
                      )}
                      {diff.deletions > 0 && (
                        <span className="text-rose-400">-{diff.deletions}</span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Right: Code Diff Viewer Area */}
        <div className="flex-1 overflow-y-auto bg-[#090d16]">
          {!activeDiff ? (
            <div className="flex h-full flex-col items-center justify-center p-8 text-center text-slate-500">
              <FileCode className="h-10 w-10 mb-2 text-slate-700" />
              <p className="text-sm">Select a file from the list to inspect changes.</p>
            </div>
          ) : activeDiff.status === "binary" ? (
            <div className="flex h-full flex-col items-center justify-center p-8 text-center text-slate-400">
              <Binary className="h-12 w-12 mb-3 text-purple-400" />
              <p className="font-semibold text-white">{activeDiff.path}</p>
              <p className="text-xs text-slate-400 mt-1">
                Binary file modified; diff cannot be displayed in text viewer.
              </p>
            </div>
          ) : (
            <div>
              {/* File details bar */}
              <div className="flex items-center justify-between border-b border-slate-800/80 bg-slate-900/50 px-4 py-1.5 text-xs text-slate-300">
                <span className="font-mono font-medium text-white">
                  {activeDiff.path}
                </span>
                <div className="flex items-center space-x-2">
                  <Badge variant="outline" className="text-[10px] capitalize">
                    {activeDiff.status}
                  </Badge>
                  <span className="text-[10px] font-mono text-emerald-400">
                    +{activeDiff.additions}
                  </span>
                  <span className="text-[10px] font-mono text-rose-400">
                    -{activeDiff.deletions}
                  </span>
                </div>
              </div>

              {/* React Diff Viewer */}
              <div className="text-xs font-mono">
                <ReactDiffViewer
                  oldValue={oldText}
                  newValue={newText}
                  splitView={splitView}
                  useDarkTheme={true}
                  styles={customDarkThemeStyles}
                  hideLineNumbers={false}
                  showDiffOnly={false}
                />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
