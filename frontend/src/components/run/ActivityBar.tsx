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
    <div className="flex w-12 flex-col items-center justify-between border-r border-white/[0.08] bg-[#0b0b0d] py-3 select-none shrink-0 z-10">
      <div className="flex flex-col items-center gap-2">
        {onBack && (
          <button
            onClick={onBack}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-[#85858b] hover:bg-[#1e1e22] hover:text-[#ededed] transition-colors"
            title="Back to Sessions"
          >
            <ArrowLeft className="h-4 w-4" strokeWidth={1.5} />
          </button>
        )}

        <button
          onClick={() => onTabChange("files")}
          className={`relative flex h-8 w-8 items-center justify-center rounded-lg transition-colors ${
            activeTab === "files"
              ? "text-[#ededed] bg-[#1e1e22] before:absolute before:-left-2 before:top-1.5 before:bottom-1.5 before:w-0.5 before:bg-[#2f81f7]"
              : "text-[#85858b] hover:text-[#ededed] hover:bg-[#161619]"
          }`}
          title="Workspace files"
        >
          <Files className="h-4 w-4" strokeWidth={1.5} />
        </button>

        <button
          onClick={() => onTabChange("git")}
          className={`relative flex h-8 w-8 items-center justify-center rounded-lg transition-colors ${
            activeTab === "git"
              ? "text-[#ededed] bg-[#1e1e22] before:absolute before:-left-2 before:top-1.5 before:bottom-1.5 before:w-0.5 before:bg-[#2f81f7]"
              : "text-[#85858b] hover:text-[#ededed] hover:bg-[#161619]"
          }`}
          title="Git changes"
        >
          <GitBranch className="h-4 w-4" strokeWidth={1.5} />
          {diffCount > 0 && (
            <span className="absolute -top-1 -right-1 flex h-4 min-w-[16px] items-center justify-center rounded bg-[#2f81f7] px-1 font-mono text-[10px] font-medium text-white tabular-nums">
              {diffCount}
            </span>
          )}
        </button>

        <button
          onClick={() => onTabChange("agent")}
          className={`relative flex h-8 w-8 items-center justify-center rounded-lg transition-colors ${
            activeTab === "agent"
              ? "text-[#ededed] bg-[#1e1e22] before:absolute before:-left-2 before:top-1.5 before:bottom-1.5 before:w-0.5 before:bg-[#2f81f7]"
              : "text-[#85858b] hover:text-[#ededed] hover:bg-[#161619]"
          }`}
          title="Agent steering"
        >
          <Sparkles className="h-4 w-4" strokeWidth={1.5} />
        </button>
      </div>

      <div className="flex flex-col items-center">
        <div
          title={`Connection: ${connectionStatus}`}
          className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/[0.08] bg-[#161619]"
        >
          {connectionStatus === "connected" ? (
            <Wifi className="h-3.5 w-3.5 text-[#4cc38a]" strokeWidth={1.5} />
          ) : (
            <WifiOff className="h-3.5 w-3.5 text-[#d29922]" strokeWidth={1.5} />
          )}
        </div>
      </div>
    </div>
  );
};
