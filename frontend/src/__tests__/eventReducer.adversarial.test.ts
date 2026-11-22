import { describe, it, expect } from "vitest";
import { eventReducer, initialRunState } from "../state/eventReducer";
import type { RunEvent } from "../types/run";

describe("Adversarial eventReducer Stress Tests", () => {
  // Helper to generate events
  function makeEvent(
    seq: number,
    type: RunEvent["type"] = "reasoning",
    payload: any = {}
  ): RunEvent {
    return {
      seq,
      ts: new Date(1700000000000 + seq * 1000).toISOString(),
      type,
      payload,
    };
  }

  describe("Monotonic Deduplication & Sequence Invariants", () => {
    it("should drop single events with duplicate sequence numbers", () => {
      let state = initialRunState;
      state = eventReducer(state, {
        type: "PROCESS_EVENT",
        event: makeEvent(1, "reasoning", { thought: "Thought 1" }),
      });
      expect(state.lastSeenSeq).toBe(1);
      expect(state.thoughts).toHaveLength(1);

      // Re-send exact same seq
      state = eventReducer(state, {
        type: "PROCESS_EVENT",
        event: makeEvent(1, "reasoning", { thought: "Mutated Thought 1" }),
      });
      expect(state.lastSeenSeq).toBe(1);
      expect(state.thoughts).toHaveLength(1);
      expect(state.thoughts[0].thought).toBe("Thought 1"); // NOT mutated
    });

    it("should drop single events with lower sequence numbers (regressive replay)", () => {
      let state = initialRunState;
      state = eventReducer(state, {
        type: "PROCESS_EVENT",
        event: makeEvent(10, "status_change", { status: "RUNNING" }),
      });
      expect(state.lastSeenSeq).toBe(10);
      expect(state.status).toBe("RUNNING");

      // Adversarial regressive events
      for (const seq of [9, 8, 5, 2, 1, 0, -5]) {
        state = eventReducer(state, {
          type: "PROCESS_EVENT",
          event: makeEvent(seq, "status_change", { status: "TERMINATED" }),
        });
        expect(state.lastSeenSeq).toBe(10);
        expect(state.status).toBe("RUNNING"); // Should NOT transition to TERMINATED
        expect(state.events).toHaveLength(1);
      }
    });

    it("should enforce deduplication when sequence numbers are repeated 1000 times", () => {
      let state = initialRunState;
      // Send seq 1..10, each repeated 100 times randomly
      const stream: RunEvent[] = [];
      for (let i = 1; i <= 10; i++) {
        for (let r = 0; r < 100; r++) {
          stream.push(makeEvent(i, "reasoning", { thought: `Thought ${i} copy ${r}` }));
        }
      }

      for (const ev of stream) {
        state = eventReducer(state, { type: "PROCESS_EVENT", event: ev });
      }

      expect(state.lastSeenSeq).toBe(10);
      expect(state.events).toHaveLength(10);
      expect(state.thoughts).toHaveLength(10);
      for (let i = 0; i < 10; i++) {
        expect(state.thoughts[i].seq).toBe(i + 1);
        expect(state.thoughts[i].thought).toBe(`Thought ${i + 1} copy 0`);
      }
    });
  });

  describe("Out-of-Order Batches & Stress Shuffling", () => {
    it("should correctly sort, deduplicate, and process a heavily scrambled batch", () => {
      // 50 unique events
      const rawEvents: RunEvent[] = [];
      for (let i = 1; i <= 50; i++) {
        rawEvents.push(makeEvent(i, "reasoning", { thought: `Step ${i}` }));
      }

      // Add duplicate events with identical seqs
      for (let i = 1; i <= 20; i++) {
        rawEvents.push(makeEvent(i, "reasoning", { thought: `Duplicate Step ${i}` }));
      }

      // Shuffle using Fisher-Yates
      const shuffled = [...rawEvents];
      for (let i = shuffled.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
      }

      const nextState = eventReducer(initialRunState, {
        type: "BATCH_EVENTS",
        events: shuffled,
      });

      expect(nextState.lastSeenSeq).toBe(50);
      expect(nextState.events).toHaveLength(50);
      expect(nextState.thoughts).toHaveLength(50);
      for (let i = 0; i < 50; i++) {
        expect(nextState.events[i].seq).toBe(i + 1);
        expect(nextState.thoughts[i].seq).toBe(i + 1);
      }
    });

    it("should filter out batch events where seq <= current lastSeenSeq", () => {
      let state = initialRunState;
      state = eventReducer(state, {
        type: "PROCESS_EVENT",
        event: makeEvent(25, "status_change", { status: "RUNNING" }),
      });
      expect(state.lastSeenSeq).toBe(25);

      // Batch containing seqs 1..50
      const batch: RunEvent[] = [];
      for (let i = 50; i >= 1; i--) {
        batch.push(makeEvent(i, "reasoning", { thought: `Thought ${i}` }));
      }

      state = eventReducer(state, {
        type: "BATCH_EVENTS",
        events: batch,
      });

      expect(state.lastSeenSeq).toBe(50);
      // Only seqs 26..50 should have been added (25 events) + the 1 initial event = 26 events
      expect(state.events).toHaveLength(26);
      expect(state.thoughts).toHaveLength(25);
      expect(state.thoughts[0].seq).toBe(26);
      expect(state.thoughts[24].seq).toBe(50);
    });

    it("should handle empty batch and batch with only already-seen events without state mutation", () => {
      let state = initialRunState;
      state = eventReducer(state, {
        type: "PROCESS_EVENT",
        event: makeEvent(5, "status_change", { status: "RUNNING" }),
      });

      // Empty batch
      const state2 = eventReducer(state, { type: "BATCH_EVENTS", events: [] });
      expect(state2).toBe(state); // Same reference

      // Already seen batch
      const state3 = eventReducer(state, {
        type: "BATCH_EVENTS",
        events: [makeEvent(1), makeEvent(3), makeEvent(5)],
      });
      expect(state3.lastSeenSeq).toBe(5);
      expect(state3.events).toHaveLength(1);
    });

    it("should handle completely reversed batches", () => {
      const reversedBatch: RunEvent[] = [];
      for (let i = 100; i >= 1; i--) {
        reversedBatch.push(makeEvent(i, "reasoning", { thought: `Reversed ${i}` }));
      }

      const state = eventReducer(initialRunState, {
        type: "BATCH_EVENTS",
        events: reversedBatch,
      });

      expect(state.lastSeenSeq).toBe(100);
      expect(state.events).toHaveLength(100);
      for (let i = 0; i < 100; i++) {
        expect(state.events[i].seq).toBe(i + 1);
      }
    });
  });

  describe("Tool Call Correlation in Scrambled Batches", () => {
    it("should properly pair tool_call and tool_result even if batch was inverted", () => {
      const callEvent = makeEvent(10, "tool_call", {
        id: "call_999",
        name: "run_command",
        arguments: { command: "npm test" },
      });
      const resultEvent = makeEvent(11, "tool_result", {
        id: "call_999",
        name: "run_command",
        output: "Tests passed",
        exit_code: 0,
        is_error: false,
      });

      // Pass inverted in batch: result (11) before call (10)
      const state = eventReducer(initialRunState, {
        type: "BATCH_EVENTS",
        events: [resultEvent, callEvent],
      });

      expect(state.lastSeenSeq).toBe(11);
      const tool = state.toolCalls.get("call_999")!;
      expect(tool).toBeDefined();
      expect(tool.name).toBe("run_command");
      expect(tool.arguments).toEqual({ command: "npm test" });
      expect(tool.status).toBe("success");
      expect(tool.output).toBe("Tests passed");
      expect(tool.exitCode).toBe(0);
      expect(state.toolCallOrder).toEqual(["call_999"]);
    });

    it("should handle orphaned tool_result (result arrives without preceding tool_call)", () => {
      const resultEvent = makeEvent(5, "tool_result", {
        id: "orphaned_call",
        name: "write_file",
        output: "Wrote 100 bytes",
        is_error: false,
      });

      const state = eventReducer(initialRunState, {
        type: "PROCESS_EVENT",
        event: resultEvent,
      });

      expect(state.toolCalls.has("orphaned_call")).toBe(true);
      const tool = state.toolCalls.get("orphaned_call")!;
      expect(tool.status).toBe("success");
      expect(tool.output).toBe("Wrote 100 bytes");
      expect(state.toolCallOrder).toEqual(["orphaned_call"]);
    });
  });

  describe("Complex Lifecycle & State Reset Immutability", () => {
    it("should correctly transition through lifecycle states when delivered out of order in a batch", () => {
      const events: RunEvent[] = [
        makeEvent(5, "status_change", { status: "SUCCEEDED" }),
        makeEvent(2, "status_change", { status: "RUNNING" }),
        makeEvent(1, "status_change", { status: "PREPARING" }),
        makeEvent(3, "status_change", { status: "RUNNING", is_pausing: true }),
        makeEvent(4, "status_change", { status: "PAUSED" }),
      ];

      const state = eventReducer(initialRunState, {
        type: "BATCH_EVENTS",
        events,
      });

      expect(state.lastSeenSeq).toBe(5);
      expect(state.status).toBe("SUCCEEDED");
      expect(state.isPausing).toBe(false);
    });

    it("should guarantee RESET_STATE creates independent collections without shared references", () => {
      let state = initialRunState;
      state = eventReducer(state, {
        type: "PROCESS_EVENT",
        event: makeEvent(1, "tool_call", { id: "c1", name: "t1" }),
      });
      state = eventReducer(state, {
        type: "PROCESS_EVENT",
        event: makeEvent(2, "terminal_output", { data: "abc", stream: "stdout" }),
      });

      const resetState = eventReducer(state, { type: "RESET_STATE" });

      expect(resetState.lastSeenSeq).toBe(0);
      expect(resetState.events).toEqual([]);
      expect(resetState.terminalChunks).toEqual([]);
      expect(resetState.toolCalls.size).toBe(0);
      expect(resetState.toolCallOrder).toEqual([]);

      // Mutate previous state and verify resetState is isolated
      state.toolCalls.set("c2", { id: "c2", name: "t2", status: "running", timestamp: "", arguments: {} });
      state.toolCallOrder.push("c2");
      state.terminalChunks.push({ seq: 3, stream: "stdout", data: "xyz" });

      expect(resetState.toolCalls.has("c2")).toBe(false);
      expect(resetState.toolCallOrder).toEqual([]);
      expect(resetState.terminalChunks).toEqual([]);
    });
  });
});
