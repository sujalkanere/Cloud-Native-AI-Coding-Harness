/**
 * Pure Event Reducer for Cloud-Native AI Coding Harness
 * Enforces monotonic gap-free sequencing, deduplication, terminal chunk aggregation,
 * and tool call correlation.
 */
import type {
  RunEvent,
  RunStatus,
  TerminalChunk,
  ToolCallItem,
} from "../types/run";

export interface RunState {
  events: RunEvent[];
  lastSeenSeq: number;
  status: RunStatus;
  isPausing: boolean;
  errorReason: string | null;
  guidanceMessages: Array<{ seq: number; message: string; timestamp: string }>;
  thoughts: Array<{ seq: number; thought: string; timestamp: string }>;
  planSteps: Array<{ seq: number; steps: string[] | string; timestamp: string }>;
  decisions: Array<{ seq: number; decision: string; timestamp: string }>;
  toolCalls: Map<string, ToolCallItem>;
  toolCallOrder: string[]; // preserves execution order of tool IDs
  terminalChunks: TerminalChunk[];
  isTerminalTruncated: boolean;
  truncationMessage: string | null;
}

export const initialRunState: RunState = {
  events: [],
  lastSeenSeq: 0,
  status: "QUEUED",
  isPausing: false,
  errorReason: null,
  guidanceMessages: [],
  thoughts: [],
  planSteps: [],
  decisions: [],
  toolCalls: new Map(),
  toolCallOrder: [],
  terminalChunks: [],
  isTerminalTruncated: false,
  truncationMessage: null,
};

export type EventAction =
  | { type: "PROCESS_EVENT"; event: RunEvent }
  | { type: "BATCH_EVENTS"; events: RunEvent[] }
  | { type: "RESET_STATE"; initialState?: Partial<RunState> };

export function eventReducer(state: RunState, action: EventAction): RunState {
  switch (action.type) {
    case "PROCESS_EVENT":
      return processSingleEvent(state, action.event);

    case "BATCH_EVENTS": {
      // Sort batch strictly ascending by seq and filter out already seen seqs
      const sorted = [...action.events]
        .filter((e) => e.seq > state.lastSeenSeq)
        .sort((a, b) => a.seq - b.seq);

      let nextState = state;
      for (const ev of sorted) {
        nextState = processSingleEvent(nextState, ev);
      }
      return nextState;
    }

    case "RESET_STATE": {
      return {
        ...initialRunState,
        ...action.initialState,
        toolCalls: action.initialState?.toolCalls
          ? new Map(action.initialState.toolCalls)
          : new Map(),
        toolCallOrder: action.initialState?.toolCallOrder
          ? [...action.initialState.toolCallOrder]
          : [],
        events: action.initialState?.events
          ? [...action.initialState.events]
          : [],
        terminalChunks: action.initialState?.terminalChunks
          ? [...action.initialState.terminalChunks]
          : [],
      };
    }

    default:
      return state;
  }
}

function processSingleEvent(state: RunState, event: RunEvent): RunState {
  // Deduplication: ignore if sequence number has already been processed
  if (event.seq <= state.lastSeenSeq) {
    return state;
  }

  const nextSeq = event.seq;
  const newEvents = [...state.events, event];

  switch (event.type) {
    case "status_change": {
      const payload = event.payload || {};
      const status = (payload.status as RunStatus) || state.status;
      const errorReason =
        payload.error_reason !== undefined
          ? payload.error_reason
          : state.errorReason;
      const isPausing =
        typeof payload.is_pausing === "boolean"
          ? payload.is_pausing
          : state.isPausing;

      return {
        ...state,
        events: newEvents,
        lastSeenSeq: nextSeq,
        status,
        errorReason,
        // When transitioning to PAUSED, isPausing is fulfilled and reset to false
        isPausing: status === "PAUSED" ? false : isPausing,
      };
    }

    case "reasoning": {
      const thought = event.payload?.thought || "";
      return {
        ...state,
        events: newEvents,
        lastSeenSeq: nextSeq,
        thoughts: [
          ...state.thoughts,
          { seq: nextSeq, thought, timestamp: event.ts },
        ],
      };
    }

    case "plan": {
      const steps = event.payload?.steps || [];
      return {
        ...state,
        events: newEvents,
        lastSeenSeq: nextSeq,
        planSteps: [
          ...state.planSteps,
          { seq: nextSeq, steps, timestamp: event.ts },
        ],
      };
    }

    case "decision": {
      const decision = event.payload?.decision || "";
      return {
        ...state,
        events: newEvents,
        lastSeenSeq: nextSeq,
        decisions: [
          ...state.decisions,
          { seq: nextSeq, decision, timestamp: event.ts },
        ],
      };
    }

    case "guidance": {
      const message = event.payload?.message || "";
      return {
        ...state,
        events: newEvents,
        lastSeenSeq: nextSeq,
        guidanceMessages: [
          ...state.guidanceMessages,
          { seq: nextSeq, message, timestamp: event.ts },
        ],
      };
    }

    case "tool_call": {
      const id = event.payload?.id;
      const newCalls = new Map(state.toolCalls);
      const newOrder = [...state.toolCallOrder];

      if (id) {
        if (!newCalls.has(id)) {
          newOrder.push(id);
        }
        newCalls.set(id, {
          id,
          name: event.payload.name || "unknown",
          arguments: event.payload.arguments || {},
          status: "running",
          timestamp: event.ts,
        });
      }

      return {
        ...state,
        events: newEvents,
        lastSeenSeq: nextSeq,
        toolCalls: newCalls,
        toolCallOrder: newOrder,
      };
    }

    case "tool_result": {
      const id = event.payload?.id;
      const newCalls = new Map(state.toolCalls);
      const newOrder = [...state.toolCallOrder];

      if (id) {
        const existing = newCalls.get(id);
        if (existing) {
          newCalls.set(id, {
            ...existing,
            status: event.payload.is_error ? "error" : "success",
            output: event.payload.output,
            exitCode: event.payload.exit_code,
            purpose: event.payload.purpose,
            path: event.payload.path,
            command: event.payload.command,
            summary: event.payload.summary,
          });
        } else {
          newOrder.push(id);
          newCalls.set(id, {
            id,
            name: event.payload.name || "unknown",
            arguments: {},
            status: event.payload.is_error ? "error" : "success",
            output: event.payload.output,
            exitCode: event.payload.exit_code,
            purpose: event.payload.purpose,
            path: event.payload.path,
            command: event.payload.command,
            summary: event.payload.summary,
            timestamp: event.ts,
          });
        }
      }

      return {
        ...state,
        events: newEvents,
        lastSeenSeq: nextSeq,
        toolCalls: newCalls,
        toolCallOrder: newOrder,
      };
    }

    case "terminal_output": {
      const chunk: TerminalChunk = {
        stream: event.payload?.stream === "stderr" ? "stderr" : "stdout",
        data: event.payload?.data || "",
        seq: nextSeq,
      };
      return {
        ...state,
        events: newEvents,
        lastSeenSeq: nextSeq,
        terminalChunks: [...state.terminalChunks, chunk],
      };
    }

    case "truncation_marker": {
      return {
        ...state,
        events: newEvents,
        lastSeenSeq: nextSeq,
        isTerminalTruncated: true,
        truncationMessage:
          event.payload?.message ||
          "Run output exceeded limit of 5242880 bytes; terminal output truncated.",
      };
    }

    default:
      return {
        ...state,
        events: newEvents,
        lastSeenSeq: nextSeq,
      };
  }
}
