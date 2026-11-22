import { describe, it, expect } from "vitest";
import { eventReducer, initialRunState } from "../state/eventReducer";
import type { RunEvent } from "../types/run";

describe("eventReducer", () => {
  it("should process a single event and update lastSeenSeq", () => {
    const event: RunEvent = {
      seq: 1,
      ts: "2026-11-22T08:00:00Z",
      type: "status_change",
      payload: { status: "PREPARING" },
    };

    const nextState = eventReducer(initialRunState, {
      type: "PROCESS_EVENT",
      event,
    });

    expect(nextState.lastSeenSeq).toBe(1);
    expect(nextState.status).toBe("PREPARING");
    expect(nextState.events).toHaveLength(1);
  });

  it("should enforce deduplication by ignoring events with seq <= lastSeenSeq", () => {
    const event1: RunEvent = {
      seq: 1,
      ts: "2026-11-22T08:00:00Z",
      type: "status_change",
      payload: { status: "PREPARING" },
    };

    const state1 = eventReducer(initialRunState, {
      type: "PROCESS_EVENT",
      event: event1,
    });

    // Replay duplicate seq=1
    const state2 = eventReducer(state1, {
      type: "PROCESS_EVENT",
      event: event1,
    });

    expect(state2.events).toHaveLength(1);
    expect(state2.lastSeenSeq).toBe(1);
  });

  it("should sort batch events strictly ascending by seq and skip duplicates", () => {
    const events: RunEvent[] = [
      {
        seq: 3,
        ts: "2026-11-22T08:00:03Z",
        type: "reasoning",
        payload: { thought: "Third thought" },
      },
      {
        seq: 1,
        ts: "2026-11-22T08:00:01Z",
        type: "status_change",
        payload: { status: "RUNNING" },
      },
      {
        seq: 2,
        ts: "2026-11-22T08:00:02Z",
        type: "reasoning",
        payload: { thought: "Second thought" },
      },
    ];

    const nextState = eventReducer(initialRunState, {
      type: "BATCH_EVENTS",
      events,
    });

    expect(nextState.events.map((e) => e.seq)).toEqual([1, 2, 3]);
    expect(nextState.lastSeenSeq).toBe(3);
    expect(nextState.status).toBe("RUNNING");
    expect(nextState.thoughts).toHaveLength(2);
  });

  it("should pair tool_call with tool_result by id and preserve arguments/output", () => {
    const callEvent: RunEvent = {
      seq: 2,
      ts: "2026-11-22T08:00:02Z",
      type: "tool_call",
      payload: {
        id: "call_abc123",
        name: "run_command",
        arguments: { command: "pytest", purpose: "test" },
      },
    };

    const state1 = eventReducer(initialRunState, {
      type: "PROCESS_EVENT",
      event: callEvent,
    });

    expect(state1.toolCalls.has("call_abc123")).toBe(true);
    const tool1 = state1.toolCalls.get("call_abc123")!;
    expect(tool1.status).toBe("running");
    expect(tool1.name).toBe("run_command");
    expect(state1.toolCallOrder).toEqual(["call_abc123"]);

    const resultEvent: RunEvent = {
      seq: 3,
      ts: "2026-11-22T08:00:05Z",
      type: "tool_result",
      payload: {
        id: "call_abc123",
        name: "run_command",
        output: "2 passed in 0.4s",
        is_error: false,
        exit_code: 0,
      },
    };

    const state2 = eventReducer(state1, {
      type: "PROCESS_EVENT",
      event: resultEvent,
    });

    const tool2 = state2.toolCalls.get("call_abc123")!;
    expect(tool2.status).toBe("success");
    expect(tool2.output).toBe("2 passed in 0.4s");
    expect(tool2.exitCode).toBe(0);
  });

  it("should aggregate terminal_output into terminalChunks distinguishing stdout and stderr", () => {
    const stdoutEvent: RunEvent = {
      seq: 4,
      ts: "2026-11-22T08:00:04Z",
      type: "terminal_output",
      payload: { stream: "stdout", data: "Running tests...\n" },
    };
    const stderrEvent: RunEvent = {
      seq: 5,
      ts: "2026-11-22T08:00:05Z",
      type: "terminal_output",
      payload: { stream: "stderr", data: "Warning: deprecated package\n" },
    };

    let state = eventReducer(initialRunState, {
      type: "PROCESS_EVENT",
      event: stdoutEvent,
    });
    state = eventReducer(state, {
      type: "PROCESS_EVENT",
      event: stderrEvent,
    });

    expect(state.terminalChunks).toHaveLength(2);
    expect(state.terminalChunks[0]).toEqual({
      stream: "stdout",
      data: "Running tests...\n",
      seq: 4,
    });
    expect(state.terminalChunks[1]).toEqual({
      stream: "stderr",
      data: "Warning: deprecated package\n",
      seq: 5,
    });
  });

  it("should handle truncation_marker event and flag isTerminalTruncated", () => {
    const markerEvent: RunEvent = {
      seq: 6,
      ts: "2026-11-22T08:00:06Z",
      type: "truncation_marker",
      payload: {
        message: "Run output exceeded limit of 5242880 bytes; terminal output truncated.",
        limit: 5242880,
      },
    };

    const nextState = eventReducer(initialRunState, {
      type: "PROCESS_EVENT",
      event: markerEvent,
    });

    expect(nextState.isTerminalTruncated).toBe(true);
    expect(nextState.truncationMessage).toContain("5242880 bytes");
  });

  it("should track is_pausing and reset is_pausing when state reaches PAUSED", () => {
    const boundaryPauseEvent: RunEvent = {
      seq: 2,
      ts: "2026-11-22T08:00:02Z",
      type: "status_change",
      payload: { status: "RUNNING", is_pausing: true },
    };

    const state1 = eventReducer(initialRunState, {
      type: "PROCESS_EVENT",
      event: boundaryPauseEvent,
    });
    expect(state1.isPausing).toBe(true);
    expect(state1.status).toBe("RUNNING");

    // Once step finishes, status reaches PAUSED
    const pausedEvent: RunEvent = {
      seq: 3,
      ts: "2026-11-22T08:00:05Z",
      type: "status_change",
      payload: { status: "PAUSED" },
    };

    const state2 = eventReducer(state1, {
      type: "PROCESS_EVENT",
      event: pausedEvent,
    });
    expect(state2.isPausing).toBe(false);
    expect(state2.status).toBe("PAUSED");
  });

  it("should record guidance and plan events", () => {
    const guidanceEvent: RunEvent = {
      seq: 1,
      ts: "2026-11-22T08:00:01Z",
      type: "guidance",
      payload: { message: "Focus on edge cases" },
    };
    const planEvent: RunEvent = {
      seq: 2,
      ts: "2026-11-22T08:00:02Z",
      type: "plan",
      payload: { steps: ["Read file", "Modify test", "Run pytest"] },
    };

    let state = eventReducer(initialRunState, {
      type: "PROCESS_EVENT",
      event: guidanceEvent,
    });
    state = eventReducer(state, {
      type: "PROCESS_EVENT",
      event: planEvent,
    });

    expect(state.guidanceMessages).toHaveLength(1);
    expect(state.guidanceMessages[0].message).toBe("Focus on edge cases");
    expect(state.planSteps).toHaveLength(1);
    expect(state.planSteps[0].steps).toHaveLength(3);
  });
});
