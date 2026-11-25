import React, { useMemo, useState } from "react";
import {
  ListTodo,
  Search,
  Palette,
  Compass,
  Cpu,
  MessageSquare,
  Play,
  Maximize2,
  Minimize2,
} from "lucide-react";
import type { RunEvent } from "../../types/run";
import { SimpleMarkdown } from "../ui/SimpleMarkdown";

interface AgentMeta {
  id: string;
  label: string;
  role: string;
  icon: React.ReactNode;
}

const AGENTS: AgentMeta[] = [
  {
    id: "planner",
    label: "Planner",
    role: "Task breakdown & coordination",
    icon: <ListTodo className="h-3.5 w-3.5 text-[#a1a1a6]" strokeWidth={1.5} />,
  },
  {
    id: "researcher",
    label: "Research Agent",
    role: "Domain & design benchmarks",
    icon: <Search className="h-3.5 w-3.5 text-[#a1a1a6]" strokeWidth={1.5} />,
  },
  {
    id: "designer",
    label: "Design Agent",
    role: "Visual system & UX craft",
    icon: <Palette className="h-3.5 w-3.5 text-[#a1a1a6]" strokeWidth={1.5} />,
  },
  {
    id: "architect",
    label: "Architect",
    role: "Tech stack & structure · syncs with Designer",
    icon: <Compass className="h-3.5 w-3.5 text-[#a1a1a6]" strokeWidth={1.5} />,
  },
  {
    id: "system_designer",
    label: "System Designer",
    role: "System concept & implementation",
    icon: <Cpu className="h-3.5 w-3.5 text-[#a1a1a6]" strokeWidth={1.5} />,
  },
];

export interface AgentWindowsGridProps {
  runId?: string;
  events: RunEvent[];
  onLaunchSwarm?: () => void;
  isLaunching?: boolean;
}

export const AgentWindowsGrid: React.FC<AgentWindowsGridProps> = ({
  runId,
  events,
  onLaunchSwarm,
  isLaunching = false,
}) => {
  const [expandedAgentId, setExpandedAgentId] = useState<string | null>(null);

  const { statuses, messagesByAgent } = useMemo(() => {
    const statusMap: Record<string, string> = {};
    const msgMap: Record<
      string,
      Array<{ seq: number; direction: "out" | "in"; peer?: string; content: string; ts: string }>
    > = {};

    for (const a of AGENTS) {
      statusMap[a.id] = "idle";
      msgMap[a.id] = [];
    }

    for (const ev of events) {
      if (ev.type === "agent_status") {
        const agent = String(ev.payload?.agent || "");
        const st = String(ev.payload?.status || "idle");
        if (agent) statusMap[agent] = st;
      } else if (ev.type === "agent_message") {
        const from = String(ev.payload?.agent || "");
        const to = ev.payload?.to_agent ? String(ev.payload.to_agent) : undefined;
        const content = String(ev.payload?.content || "");
        const ts = new Date(ev.ts).toLocaleTimeString();

        if (from && msgMap[from]) {
          msgMap[from].push({ seq: ev.seq, direction: "out", peer: to, content, ts });
        }
        if (to) {
          for (const target of to.split(",").map((s) => s.trim())) {
            if (msgMap[target]) {
              msgMap[target].push({
                seq: ev.seq,
                direction: "in",
                peer: from,
                content,
                ts,
              });
            }
          }
        }
      }
    }

    return { statuses: statusMap, messagesByAgent: msgMap };
  }, [events]);

  const hasAgentActivity = events.some(
    (e) => e.type === "agent_status" || e.type === "agent_message"
  );

  const getStatusBadge = (st: string) => {
    let dot = "bg-[#85858b]";
    let text = "text-[#85858b]";
    if (st === "working") {
      dot = "bg-[#2f81f7]";
      text = "text-[#ededed]";
    } else if (st === "discussing") {
      dot = "bg-[#d29922]";
      text = "text-[#d29922]";
    } else if (st === "done") {
      dot = "bg-[#4cc38a]";
      text = "text-[#4cc38a]";
    } else if (st === "waiting") {
      dot = "bg-[#a1a1a6]";
      text = "text-[#a1a1a6]";
    }

    return (
      <span className={`inline-flex items-center gap-1.5 font-mono text-[11px] ${text}`}>
        <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
        <span>{st}</span>
      </span>
    );
  };

  const visibleAgents = expandedAgentId
    ? AGENTS.filter((a) => a.id === expandedAgentId)
    : AGENTS;

  return (
    <div className="flex h-full flex-col bg-[#111113] overflow-hidden">
      {/* Sub-Agents Header */}
      <div className="flex items-center justify-between border-b border-white/[0.08] bg-[#161619] px-4 py-2 text-xs">
        <div className="flex items-center gap-2 text-[#a1a1a6]">
          <span className="font-medium text-[#ededed]">Parallel sub-agent windows</span>
          <span className="rounded border border-white/[0.08] bg-[#0b0b0d] px-1.5 py-0.5 font-mono text-[11px] tabular-nums">
            5 agents · shared session{runId ? ` (${runId.slice(0, 8)})` : ""}
          </span>
        </div>

        <div className="flex items-center gap-2">
          {expandedAgentId && (
            <button
              type="button"
              onClick={() => setExpandedAgentId(null)}
              className="inline-flex h-7 items-center gap-1.5 rounded-lg border border-white/[0.08] bg-[#1e1e22] hover:bg-[#27272c] px-2.5 text-xs text-[#ededed] transition-colors"
            >
              <Minimize2 className="h-3 w-3" strokeWidth={1.5} />
              <span>Show all 5</span>
            </button>
          )}

          {!hasAgentActivity && onLaunchSwarm && (
            <button
              type="button"
              disabled={isLaunching}
              onClick={onLaunchSwarm}
              className="inline-flex h-7 items-center gap-1.5 rounded-lg bg-[#ededed] hover:bg-white disabled:opacity-50 px-3 text-xs font-medium text-[#0b0b0d] transition-colors"
            >
              <Play className="h-3 w-3 fill-current" strokeWidth={1.5} />
              <span>{isLaunching ? "Launching..." : "Launch 5-Agent Swarm"}</span>
            </button>
          )}
        </div>
      </div>

      {/* Dedicated Agent Windows */}
      <div className="flex-1 overflow-y-auto p-4">
        <div
          className={
            expandedAgentId
              ? "grid grid-cols-1 h-full gap-4"
              : "grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4"
          }
        >
          {visibleAgents.map((agent) => {
            const st = statuses[agent.id] || "idle";
            const msgs = messagesByAgent[agent.id] || [];
            const isExpanded = expandedAgentId === agent.id;

            return (
              <div
                key={agent.id}
                className={`flex flex-col rounded-xl border border-white/[0.08] bg-[#161619] overflow-hidden ${
                  isExpanded ? "h-full min-h-[360px]" : "min-h-[250px] max-h-[360px]"
                }`}
              >
                {/* Agent Window Chrome */}
                <div className="flex items-center justify-between border-b border-white/[0.08] bg-[#0b0b0d] px-3.5 py-2.5">
                  <div className="flex items-center gap-2 truncate">
                    {agent.icon}
                    <div className="truncate">
                      <div className="text-xs font-medium text-[#ededed] truncate">
                        {agent.label}
                      </div>
                      <div className="text-[10px] text-[#85858b] truncate">
                        {agent.role}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {getStatusBadge(st)}
                    <button
                      type="button"
                      onClick={() => setExpandedAgentId(isExpanded ? null : agent.id)}
                      className="rounded p-1 text-[#85858b] hover:bg-[#1e1e22] hover:text-[#ededed] transition-colors"
                      title={isExpanded ? "Restore grid" : `Maximize ${agent.label}`}
                    >
                      {isExpanded ? (
                        <Minimize2 className="h-3 w-3" strokeWidth={1.5} />
                      ) : (
                        <Maximize2 className="h-3 w-3" strokeWidth={1.5} />
                      )}
                    </button>
                  </div>
                </div>

                {/* Agent Output & Peer Messages */}
                <div className="flex-1 overflow-y-auto p-3 space-y-2.5 text-xs select-text">
                  {msgs.length === 0 ? (
                    <div className="flex h-full items-center justify-center text-[11px] font-mono text-[#85858b]">
                      {st === "working" ? "Working..." : "Waiting for assignment"}
                    </div>
                  ) : (
                    msgs.map((m, i) => (
                      <div
                        key={`${m.seq}-${i}`}
                        className={`rounded-lg border p-2.5 space-y-1.5 ${
                          m.direction === "in"
                            ? "border-[#2f81f7]/30 bg-[#2f81f7]/[0.06]"
                            : "border-white/[0.06] bg-[#111113]"
                        }`}
                      >
                        <div className="flex items-center justify-between text-[10px] font-mono text-[#85858b]">
                          <span className="inline-flex items-center gap-1">
                            {m.peer && <MessageSquare className="h-3 w-3 text-[#2f81f7]" strokeWidth={1.5} />}
                            <span>
                              {m.direction === "in"
                                ? `from @${m.peer}`
                                : m.peer
                                  ? `to @${m.peer}`
                                  : "output"}
                            </span>
                          </span>
                          <span className="tabular-nums">{m.ts}</span>
                        </div>
                        <SimpleMarkdown content={m.content} className="text-[11px]" />
                      </div>
                    ))
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
