import { useState, useEffect, useRef, useMemo } from "react";
import {
  Lightbulb,
  Terminal,
  FileEdit,
  FileSearch,
  Folder,
  CheckCircle2,
  XCircle,
  Clock,
  ChevronDown,
  ChevronRight,
  ArrowDown,
  MessageSquare,
  Activity,
  ListOrdered,
  Compass,
} from "lucide-react";
import type { RunEvent, ToolCallItem } from "../../types/run";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";

export interface ReasoningStreamProps {
  events: RunEvent[];
  toolCalls?: Map<string, ToolCallItem>;
}

export function ReasoningStream({ events, toolCalls }: ReasoningStreamProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [isScrolledUp, setIsScrolledUp] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [expandedTools, setExpandedTools] = useState<Record<string, boolean>>({});

  // Auto-scroll logic
  const handleScroll = () => {
    if (!containerRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = containerRef.current;
    const distanceToBottom = scrollHeight - (scrollTop + clientHeight);

    if (distanceToBottom > 80) {
      setIsScrolledUp(true);
    } else {
      setIsScrolledUp(false);
      setUnreadCount(0);
    }
  };

  const scrollToBottom = (behavior: ScrollBehavior = "smooth") => {
    if (!containerRef.current) return;
    if (typeof containerRef.current.scrollTo === "function") {
      containerRef.current.scrollTo({
        top: containerRef.current.scrollHeight,
        behavior,
      });
    } else {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
    setIsScrolledUp(false);
    setUnreadCount(0);
  };

  useEffect(() => {
    if (!isScrolledUp) {
      scrollToBottom("smooth");
    } else {
      setUnreadCount((prev) => prev + 1);
    }
  }, [events.length, isScrolledUp]);

  const toggleToolExpanded = (id: string) => {
    setExpandedTools((prev) => ({
      ...prev,
      [id]: !prev[id],
    }));
  };

  // Group or render chronological items
  const renderItem = (event: RunEvent) => {
    switch (event.type) {
      case "status_change": {
        const status = event.payload?.status;
        const errorReason = event.payload?.error_reason;
        const isPausing = event.payload?.is_pausing;

        return (
          <div
            key={`status-${event.seq}`}
            className="my-2 flex items-center justify-center"
          >
            <div className="flex items-center space-x-2 rounded-full border border-slate-800 bg-slate-900/90 px-3 py-1 text-xs text-slate-300 shadow">
              <Activity className="h-3.5 w-3.5 text-blue-400" />
              <span>Status:</span>
              <span className="font-semibold text-white">{status}</span>
              {isPausing && (
                <span className="text-[10px] text-amber-400">(Pausing requested)</span>
              )}
              {errorReason && (
                <span className="text-[10px] text-rose-400">({errorReason})</span>
              )}
              <span className="text-[10px] text-slate-500">
                {new Date(event.ts).toLocaleTimeString()}
              </span>
            </div>
          </div>
        );
      }

      case "guidance": {
        return (
          <div
            key={`guidance-${event.seq}`}
            className="my-3 rounded-lg border border-indigo-700/60 bg-indigo-950/40 p-3 shadow"
          >
            <div className="flex items-center space-x-2 text-indigo-300">
              <MessageSquare className="h-4 w-4 text-indigo-400" />
              <span className="text-xs font-semibold uppercase tracking-wider">
                User Steering Guidance
              </span>
              <span className="text-[10px] text-indigo-400/80">
                {new Date(event.ts).toLocaleTimeString()}
              </span>
            </div>
            <p className="mt-1.5 text-sm text-indigo-100 whitespace-pre-wrap">
              {event.payload?.message}
            </p>
          </div>
        );
      }

      case "reasoning": {
        return (
          <div
            key={`thought-${event.seq}`}
            className="my-3 rounded-lg border border-slate-800 bg-slate-900/60 p-3.5 shadow-sm"
          >
            <div className="flex items-center justify-between text-slate-400 mb-2">
              <div className="flex items-center space-x-2">
                <Lightbulb className="h-4 w-4 text-amber-400" />
                <span className="text-xs font-semibold text-slate-200">
                  Model Reasoning
                </span>
              </div>
              <span className="text-[10px] text-slate-500">
                {new Date(event.ts).toLocaleTimeString()}
              </span>
            </div>
            <div className="text-sm text-slate-300 leading-relaxed whitespace-pre-wrap font-sans">
              {event.payload?.thought}
            </div>
          </div>
        );
      }

      case "plan": {
        const steps = event.payload?.steps;
        const stepsList = Array.isArray(steps)
          ? steps
          : typeof steps === "string"
          ? [steps]
          : [];

        return (
          <div
            key={`plan-${event.seq}`}
            className="my-3 rounded-lg border border-sky-800/60 bg-sky-950/30 p-3.5 shadow-sm"
          >
            <div className="flex items-center space-x-2 text-sky-400 mb-2">
              <ListOrdered className="h-4 w-4" />
              <span className="text-xs font-semibold uppercase tracking-wider">
                Agent Plan
              </span>
            </div>
            <ul className="space-y-1.5 text-xs text-sky-100 list-disc list-inside">
              {stepsList.map((step, idx) => (
                <li key={idx} className="leading-relaxed">
                  {step}
                </li>
              ))}
            </ul>
          </div>
        );
      }

      case "decision": {
        return (
          <div
            key={`decision-${event.seq}`}
            className="my-3 rounded-lg border border-emerald-800/50 bg-emerald-950/30 p-3 shadow-sm"
          >
            <div className="flex items-center space-x-2 text-emerald-400 mb-1">
              <Compass className="h-4 w-4" />
              <span className="text-xs font-semibold uppercase tracking-wider">
                Decision
              </span>
            </div>
            <p className="text-sm text-emerald-200 whitespace-pre-wrap">
              {event.payload?.decision}
            </p>
          </div>
        );
      }

      case "tool_call": {
        const id = event.payload?.id;
        const toolItem = toolCalls?.get(id);
        const name = event.payload?.name || "unknown";
        const isExpanded = expandedTools[id] ?? false;

        let ToolIcon = Terminal;
        if (name === "write_file") ToolIcon = FileEdit;
        else if (name === "read_file") ToolIcon = FileSearch;
        else if (name === "list_dir") ToolIcon = Folder;
        else if (name === "finish") ToolIcon = CheckCircle2;

        const isRunning = !toolItem || toolItem.status === "running";
        const isSuccess = toolItem?.status === "success";
        const isError = toolItem?.status === "error";

        let primaryArg = "";
        const args = event.payload?.arguments || {};
        if (args.command) primaryArg = args.command;
        else if (args.path) primaryArg = args.path;
        else if (args.summary) primaryArg = args.summary;
        else primaryArg = JSON.stringify(args);

        return (
          <div
            key={`tool-call-${id || event.seq}`}
            className="my-2 overflow-hidden rounded-lg border border-slate-800 bg-slate-900/80 shadow transition"
          >
            {/* Header */}
            <div
              onClick={() => id && toggleToolExpanded(id)}
              className="flex cursor-pointer items-center justify-between px-3 py-2 hover:bg-slate-800/60 transition"
            >
              <div className="flex items-center space-x-2 overflow-hidden mr-2">
                <button
                  type="button"
                  aria-label={isExpanded ? "Collapse tool details" : "Expand tool details"}
                  className="text-slate-400"
                >
                  {isExpanded ? (
                    <ChevronDown className="h-4 w-4 text-slate-400" />
                  ) : (
                    <ChevronRight className="h-4 w-4 text-slate-400" />
                  )}
                </button>
                <ToolIcon className="h-4 w-4 text-blue-400 shrink-0" />
                <span className="text-xs font-semibold text-slate-200">{name}</span>
                <span className="truncate text-xs font-mono text-slate-400">
                  {primaryArg}
                </span>
              </div>

              <div className="flex items-center space-x-2 shrink-0">
                {isRunning && (
                  <Badge variant="outline" className="text-[10px] text-blue-400 border-blue-800 animate-pulse">
                    <Clock className="mr-1 h-3 w-3 animate-spin" />
                    Running
                  </Badge>
                )}
                {isSuccess && (
                  <Badge variant="success" className="text-[10px]">
                    <CheckCircle2 className="mr-1 h-3 w-3 text-emerald-400" />
                    Exit {toolItem?.exitCode !== undefined ? toolItem.exitCode : 0}
                  </Badge>
                )}
                {isError && (
                  <Badge variant="destructive" className="text-[10px]">
                    <XCircle className="mr-1 h-3 w-3 text-rose-400" />
                    Error {toolItem?.exitCode !== undefined ? `(${toolItem.exitCode})` : ""}
                  </Badge>
                )}
                <span className="text-[10px] text-slate-500">
                  {new Date(event.ts).toLocaleTimeString()}
                </span>
              </div>
            </div>

            {/* Expandable Body */}
            {isExpanded && (
              <div className="border-t border-slate-800 bg-slate-950 p-3 text-xs space-y-2">
                <div>
                  <div className="font-semibold text-slate-400 mb-1">Arguments:</div>
                  <pre className="overflow-x-auto rounded bg-slate-900 p-2 font-mono text-[11px] text-slate-300">
                    {JSON.stringify(args, null, 2)}
                  </pre>
                </div>

                {toolItem?.output && (
                  <div>
                    <div className="font-semibold text-slate-400 mb-1">Output:</div>
                    <pre className="max-h-48 overflow-y-auto rounded bg-slate-900 p-2 font-mono text-[11px] text-slate-300 whitespace-pre-wrap">
                      {toolItem.output}
                    </pre>
                  </div>
                )}
              </div>
            )}
          </div>
        );
      }

      default:
        return null;
    }
  };

  const visibleEvents = useMemo(() => {
    return events.filter((e) =>
      ["status_change", "guidance", "reasoning", "plan", "decision", "tool_call"].includes(
        e.type
      )
    );
  }, [events]);

  return (
    <div className="relative flex flex-col h-full bg-slate-950">
      {/* Panel Header */}
      <div className="flex items-center justify-between border-b border-slate-800 bg-slate-900/70 px-4 py-2.5">
        <div className="flex items-center space-x-2">
          <Lightbulb className="h-4 w-4 text-amber-400" />
          <h2 className="text-sm font-semibold text-white">Reasoning & Execution Log</h2>
        </div>
        <span className="text-xs text-slate-400">
          {visibleEvents.length} events
        </span>
      </div>

      {/* Stream List */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto p-4 space-y-1"
      >
        {visibleEvents.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-center text-slate-500">
            <Activity className="h-8 w-8 mb-2 animate-pulse text-slate-600" />
            <p className="text-sm">Awaiting agent execution events...</p>
          </div>
        ) : (
          visibleEvents.map((ev) => renderItem(ev))
        )}
      </div>

      {/* Floating Jump to Latest Button */}
      {isScrolledUp && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-10">
          <Button
            size="sm"
            onClick={() => scrollToBottom("smooth")}
            className="rounded-full bg-blue-600 px-3.5 py-1 text-xs text-white shadow-lg hover:bg-blue-700 animate-in fade-in zoom-in-95"
          >
            <ArrowDown className="mr-1.5 h-3.5 w-3.5" />
            Jump to latest
            {unreadCount > 0 && (
              <span className="ml-1.5 rounded-full bg-blue-800 px-1.5 py-0.2 text-[10px] font-bold">
                {unreadCount}
              </span>
            )}
          </Button>
        </div>
      )}
    </div>
  );
}
