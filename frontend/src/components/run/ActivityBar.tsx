import React from "react";
import {
  Files,
  GitBranch,
  Sparkles,
  ArrowLeft,
  Wifi,
  WifiOff,
} from "lucide-react";

export type SidebarTab = "files" | "agent" | "git";

export interface ActivityBarProps {
  activeTab: SidebarTab;
  onTabChange: (tab: SidebarTab) => void;
  diffCount?: number;
  connectionStatus?: string;
  onBack?: () => void;
}

export const ActivityBar: React.FC<ActivityBarProps> = ({
  activeTab,
  onTabChange,
  diffCount = 0,
  connectionStatus = "connected",
  onBack,
}) => {
  return (
    <div className="flex w-12 flex-col items-center justify-between border-r border-slate-800 bg-[#090d16] py-3 select-none shrink-0 z-10">
      {/* Top Icons */}
      <div className="flex flex-col items-center space-y-4">
        {onBack && (
          <button
            onClick={onBack}
            className="rounded p-2 text-slate-500 hover:bg-slate-800 hover:text-white transition-colors"
            title="Back to Sessions"
          >
            <ArrowLeft className="h-5 w-5" />
          </button>
        )}

        <button
          onClick={() => onTabChange("files")}
          className={`relative rounded p-2 transition-colors ${
            activeTab === "files"
              ? "text-blue-400 bg-slate-800/80 before:absolute before:left-0 before:top-2 before:bottom-2 before:w-0.5 before:bg-blue-500"
              : "text-slate-400 hover:text-white hover:bg-slate-800/40"
          }`}
          title="Explorer: Files"
        >
          <Files className="h-5 w-5" />
        </button>

        <button
          onClick={() => onTabChange("git")}
          className={`relative rounded p-2 transition-colors ${
            activeTab === "git"
              ? "text-blue-400 bg-slate-800/80 before:absolute before:left-0 before:top-2 before:bottom-2 before:w-0.5 before:bg-blue-500"
              : "text-slate-400 hover:text-white hover:bg-slate-800/40"
          }`}
          title="Source Control / Diff"
        >
          <GitBranch className="h-5 w-5" />
          {diffCount > 0 && (
            <span className="absolute -top-1 -right-1 flex h-4 w-4 items-center justify-center rounded-full bg-blue-600 text-[9px] font-bold text-white">
              {diffCount}
            </span>
          )}
        </button>

        <button
          onClick={() => onTabChange("agent")}
          className={`relative rounded p-2 transition-colors ${
            activeTab === "agent"
              ? "text-blue-400 bg-slate-800/80 before:absolute before:left-0 before:top-2 before:bottom-2 before:w-0.5 before:bg-blue-500"
              : "text-slate-400 hover:text-white hover:bg-slate-800/40"
          }`}
          title="Agent Steer & Status"
        >
          <Sparkles className="h-5 w-5" />
        </button>
      </div>

      {/* Bottom Status Indicator */}
      <div className="flex flex-col items-center space-y-2">
        <div
          title={`Connection: ${connectionStatus}`}
          className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-900 border border-slate-800"
        >
          {connectionStatus === "connected" ? (
            <Wifi className="h-3.5 w-3.5 text-emerald-400" />
          ) : (
            <WifiOff className="h-3.5 w-3.5 text-amber-500 animate-pulse" />
          )}
        </div>
      </div>
    </div>
  );
};
