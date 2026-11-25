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

  const renderItem = (event: RunEvent) => {
    switch (event.type) {
      case "status_change": {
        const status = event.payload?.new_status ?? event.payload?.status;
        const errorReason = event.payload?.reason ?? event.payload?.error_reason;
        const isPausing = event.payload?.is_pausing;

        return (
          <div
            key={`status-${event.seq}`}
            className="my-2 flex items-center justify-center"
          >
            <div className="flex items-center gap-2 rounded-lg border border-white/[0.08] bg-[#161619] px-3 py-1 text-xs text-[#a1a1a6]">
              <Activity className="h-3.5 w-3.5 text-[#2f81f7]" strokeWidth={1.5} />
              <span>Status:</span>
              <span className="font-mono font-medium text-[#ededed]">{status}</span>
              {isPausing && (
                <span className="text-[11px] text-[#d29922]">(Pausing requested)</span>
              )}
              {errorReason && (
                <span className="text-[11px] text-[#e5484d]">({errorReason})</span>
              )}
              <span className="font-mono text-[10px] text-[#85858b] tabular-nums">
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
            className="my-2 rounded-xl border border-[#2f81f7]/30 bg-[#2f81f7]/[0.06] p-3"
          >
            <div className="flex items-center gap-2 text-[#ededed]">
              <MessageSquare className="h-3.5 w-3.5 text-[#2f81f7]" strokeWidth={1.5} />
              <span className="text-xs font-medium">User Steering Guidance</span>
              <span className="font-mono text-[10px] text-[#85858b] tabular-nums">
                {new Date(event.ts).toLocaleTimeString()}
              </span>
            </div>
            <p className="mt-1.5 text-xs text-[#ededed] whitespace-pre-wrap">
              {event.payload?.message}
            </p>
          </div>
        );
      }

      case "agent_message": {
        const agent = event.payload?.agent || "agent";
        const toAgent = event.payload?.to_agent;
        return (
          <div
            key={`agent-msg-${event.seq}`}
            className="my-2 rounded-xl border border-white/[0.08] bg-[#161619] p-3"
          >
            <div className="flex items-center justify-between text-[11px] font-mono text-[#85858b] mb-1">
              <span className="text-[#ededed]">
                @{agent}
                {toAgent ? ` -> @${toAgent}` : ""}
              </span>
              <span className="tabular-nums">{new Date(event.ts).toLocaleTimeString()}</span>
            </div>
            <div className="text-xs text-[#a1a1a6] whitespace-pre-wrap line-clamp-4">
              {event.payload?.content}
            </div>
          </div>
        );
      }

      case "reasoning": {
        return (
          <div
            key={`thought-${event.seq}`}
            className="my-2 rounded-xl border border-white/[0.08] bg-[#161619] p-3.5"
          >
            <div className="flex items-center justify-between text-[#a1a1a6] mb-1.5">
              <div className="flex items-center gap-2">
                <Lightbulb className="h-3.5 w-3.5 text-[#d29922]" strokeWidth={1.5} />
                <span className="text-xs font-medium text-[#ededed]">Model Reasoning</span>
              </div>
              <span className="font-mono text-[10px] text-[#85858b] tabular-nums">
                {new Date(event.ts).toLocaleTimeString()}
              </span>
            </div>
            <div className="text-xs text-[#a1a1a6] leading-relaxed whitespace-pre-wrap">
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
            className="my-2 rounded-xl border border-white/[0.08] bg-[#161619] p-3.5"
          >
            <div className="flex items-center gap-2 text-[#ededed] mb-2">
              <ListOrdered className="h-3.5 w-3.5 text-[#2f81f7]" strokeWidth={1.5} />
              <span className="text-xs font-medium">Agent Plan</span>
            </div>
            <ul className="space-y-1 text-xs text-[#a1a1a6] list-disc list-inside">
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
            className="my-2 rounded-xl border border-white/[0.08] bg-[#161619] p-3"
          >
            <div className="flex items-center gap-2 text-[#4cc38a] mb-1">
              <Compass className="h-3.5 w-3.5" strokeWidth={1.5} />
              <span className="text-xs font-medium">Decision</span>
            </div>
            <p className="text-xs text-[#ededed] whitespace-pre-wrap">
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

        const args = event.payload?.arguments || {};
        let primaryArg = "";
        if (args.command) primaryArg = args.command;
        else if (args.path) primaryArg = args.path;
        else if (args.summary) primaryArg = args.summary;
        else primaryArg = JSON.stringify(args);

        return (
          <div
            key={`tool-call-${id || event.seq}`}
            className="my-2 overflow-hidden rounded-xl border border-white/[0.08] bg-[#161619]"
          >
            <div
              onClick={() => id && toggleToolExpanded(id)}
              className="flex cursor-pointer items-center justify-between px-3 py-2 hover:bg-[#1e1e22] transition-colors"
            >
              <div className="flex items-center gap-2 overflow-hidden mr-2">
                <button
                  type="button"
                  aria-label={isExpanded ? "Collapse tool details" : "Expand tool details"}
                  className="text-[#85858b]"
                >
                  {isExpanded ? (
                    <ChevronDown className="h-3.5 w-3.5" strokeWidth={1.5} />
                  ) : (
                    <ChevronRight className="h-3.5 w-3.5" strokeWidth={1.5} />
                  )}
                </button>
                <ToolIcon className="h-3.5 w-3.5 text-[#a1a1a6] shrink-0" strokeWidth={1.5} />
                <span className="text-xs font-medium text-[#ededed]">{name}</span>
                <span className="truncate text-xs font-mono text-[#85858b]">
                  {primaryArg}
                </span>
              </div>

              <div className="flex items-center gap-2 shrink-0">
                {isRunning && (
                  <Badge variant="outline" className="text-[10px] text-[#2f81f7] border-[#2f81f7]/30">
                    <Clock className="mr-1 h-3 w-3" strokeWidth={1.5} />
                    Running
                  </Badge>
                )}
                {isSuccess && (
                  <Badge variant="success" className="text-[10px]">
                    <CheckCircle2 className="mr-1 h-3 w-3 text-[#4cc38a]" strokeWidth={1.5} />
                    Exit {toolItem?.exitCode !== undefined ? toolItem.exitCode : 0}
                  </Badge>
                )}
                {isError && (
                  <Badge variant="destructive" className="text-[10px]">
                    <XCircle className="mr-1 h-3 w-3 text-[#e5484d]" strokeWidth={1.5} />
                    Error {toolItem?.exitCode !== undefined ? `(${toolItem.exitCode})` : ""}
                  </Badge>
                )}
                <span className="font-mono text-[10px] text-[#85858b] tabular-nums">
                  {new Date(event.ts).toLocaleTimeString()}
                </span>
              </div>
            </div>

            {isExpanded && (
              <div className="border-t border-white/[0.08] bg-[#0b0b0d] p-3 text-xs space-y-2">
                <div>
                  <div className="font-medium text-[#85858b] mb-1">Arguments:</div>
                  <pre className="overflow-x-auto rounded-lg border border-white/[0.06] bg-[#111113] p-2 font-mono text-[11px] text-[#ededed]">
                    {JSON.stringify(args, null, 2)}
                  </pre>
                </div>

                {toolItem?.output && (
                  <div>
                    <div className="font-medium text-[#85858b] mb-1">Output:</div>
                    <pre className="max-h-48 overflow-y-auto rounded-lg border border-white/[0.06] bg-[#111113] p-2 font-mono text-[11px] text-[#ededed] whitespace-pre-wrap">
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
      ["status_change", "guidance", "reasoning", "plan", "decision", "tool_call", "agent_message"].includes(
        e.type
      )
    );
  }, [events]);

  return (
    <div className="relative flex flex-col h-full bg-[#0b0b0d]">
      <div className="flex items-center justify-between border-b border-white/[0.08] bg-[#161619] px-4 py-2">
        <div className="flex items-center gap-2">
          <Lightbulb className="h-3.5 w-3.5 text-[#a1a1a6]" strokeWidth={1.5} />
          <h2 className="text-xs font-medium text-[#ededed]">Reasoning & Execution Log</h2>
        </div>
        <span className="font-mono text-[11px] text-[#85858b] tabular-nums">
          {visibleEvents.length} events
        </span>
      </div>

      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto p-3 space-y-1"
      >
        {visibleEvents.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-center text-[#85858b]">
            <Activity className="h-6 w-6 mb-2 text-[#52525b]" strokeWidth={1.5} />
            <p className="text-xs">Awaiting agent execution events...</p>
          </div>
        ) : (
          visibleEvents.map((ev) => renderItem(ev))
        )}
      </div>

      {isScrolledUp && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-10">
          <Button
            size="sm"
            onClick={() => scrollToBottom("smooth")}
            className="rounded-lg bg-[#ededed] hover:bg-white px-3 py-1 text-xs text-[#0b0b0d]"
          >
            <ArrowDown className="mr-1.5 h-3.5 w-3.5" strokeWidth={1.5} />
            Jump to latest
            {unreadCount > 0 && (
              <span className="ml-1.5 rounded bg-[#0b0b0d]/15 px-1.5 font-mono text-[10px] tabular-nums">
                {unreadCount}
              </span>
            )}
          </Button>
        </div>
      )}
    </div>
  );
}
