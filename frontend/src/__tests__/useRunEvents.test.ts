import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useRunEvents } from "../hooks/useRunEvents";

vi.mock("../services/api", () => ({
  api: {
    getEvents: vi.fn().mockResolvedValue([]),
  },
}));

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event: { code: number; reason: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 0;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
    setTimeout(() => {
      this.readyState = 1;
      this.onopen?.();
    }, 10);
  }

  send = vi.fn();
  close = vi.fn((code: number = 1000, reason: string = "") => {
    this.readyState = 3;
    this.onclose?.({ code, reason });
  });

  simulateMessage(data: any) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }

  simulateClose(code: number, reason: string = "") {
    this.readyState = 3;
    this.onclose?.({ code, reason });
  }
}

describe("useRunEvents - WebSocket Lifecycle & Stability", () => {
  const originalWebSocket = globalThis.WebSocket;

  beforeEach(() => {
    vi.useFakeTimers();
    MockWebSocket.instances = [];
    (globalThis as any).WebSocket = MockWebSocket as any;
  });

  afterEach(() => {
    vi.useRealTimers();
    (globalThis as any).WebSocket = originalWebSocket;
  });

  it("maintains a single persistent WebSocket connection when receiving sequential events (no thrashing)", async () => {
    const { result } = renderHook(() =>
      useRunEvents({ runId: "run_test_stability", enabled: true })
    );

    // Initial connection established
    expect(MockWebSocket.instances.length).toBe(1);
    expect(MockWebSocket.instances[0].url).toContain("/api/runs/run_test_stability/stream?after=0");

    await act(async () => {
      vi.advanceTimersByTime(15);
    });

    expect(result.current.connectionStatus).toBe("connected");
    const ws = MockWebSocket.instances[0];

    // Stream 5 sequential events through the active socket
    for (let seq = 1; seq <= 5; seq++) {
      act(() => {
        ws.simulateMessage({
          seq,
          ts: `2026-11-22T08:00:0${seq}Z`,
          type: "reasoning",
          payload: { thought: `Step ${seq} execution` },
        });
      });

      await act(async () => {
        vi.advanceTimersByTime(50);
      });
    }

    // Critical assertions:
    // 1. WebSocket instances MUST remain exactly 1 (no thrashing/recreation)
    expect(MockWebSocket.instances.length).toBe(1);
    // 2. Active socket must not have been closed
    expect(ws.close).not.toHaveBeenCalled();
    // 3. Last seen sequence and events correctly aggregated
    expect(result.current.state.lastSeenSeq).toBe(5);
    expect(result.current.state.events.length).toBe(5);
    expect(result.current.connectionStatus).toBe("connected");
  });

  it("processes diverse event types and updates state correctly without socket recreation", async () => {
    const { result } = renderHook(() =>
      useRunEvents({ runId: "run_test_events", enabled: true })
    );

    await act(async () => {
      vi.advanceTimersByTime(15);
    });

    expect(MockWebSocket.instances.length).toBe(1);
    const ws = MockWebSocket.instances[0];

    // 1. Status change to RUNNING
    act(() => {
      ws.simulateMessage({
        seq: 1,
        ts: "2026-11-22T08:00:01Z",
        type: "status_change",
        payload: { status: "RUNNING" },
      });
    });

    // 2. Reasoning thought
    act(() => {
      ws.simulateMessage({
        seq: 2,
        ts: "2026-11-22T08:00:02Z",
        type: "reasoning",
        payload: { thought: "Analyzing project layout" },
      });
    });

    // 3. Plan steps
    act(() => {
      ws.simulateMessage({
        seq: 3,
        ts: "2026-11-22T08:00:03Z",
        type: "plan",
        payload: { steps: ["Inspect files", "Fix defects", "Run tests"] },
      });
    });

    // 4. Terminal output
    act(() => {
      ws.simulateMessage({
        seq: 4,
        ts: "2026-11-22T08:00:04Z",
        type: "terminal_output",
        payload: { stream: "stdout", data: "Running tests...\n" },
      });
    });

    await act(async () => {
      vi.advanceTimersByTime(20);
    });

    expect(MockWebSocket.instances.length).toBe(1);
    expect(ws.close).not.toHaveBeenCalled();
    expect(result.current.state.lastSeenSeq).toBe(4);
    expect(result.current.state.status).toBe("RUNNING");
    expect(result.current.state.thoughts.length).toBe(1);
    expect(result.current.state.planSteps.length).toBe(1);
    expect(result.current.state.terminalChunks.length).toBe(1);
  });

  it("closes previous WebSocket and establishes a new one when runId changes", async () => {
    const currentRunId = "run_alpha";
    const { result, rerender } = renderHook(
      ({ runId }) => useRunEvents({ runId, enabled: true }),
      { initialProps: { runId: currentRunId } }
    );

    await act(async () => {
      vi.advanceTimersByTime(15);
    });

    expect(MockWebSocket.instances.length).toBe(1);
    const ws1 = MockWebSocket.instances[0];
    expect(ws1.url).toContain("run_alpha");

    // Receive event on run_alpha
    act(() => {
      ws1.simulateMessage({
        seq: 1,
        ts: "2026-11-22T08:00:01Z",
        type: "reasoning",
        payload: { thought: "Alpha thought" },
      });
    });

    expect(result.current.state.lastSeenSeq).toBe(1);

    // Switch runId to run_beta
    rerender({ runId: "run_beta" });

    await act(async () => {
      vi.advanceTimersByTime(15);
    });

    expect(ws1.close).toHaveBeenCalledWith(1000, "Component unmounted");
    expect(MockWebSocket.instances.length).toBe(2);
    const ws2 = MockWebSocket.instances[1];
    expect(ws2.url).toContain("run_beta");
    expect(result.current.state.lastSeenSeq).toBe(0);
  });

  it("closes the WebSocket cleanly when unmounted", async () => {
    const { unmount } = renderHook(() =>
      useRunEvents({ runId: "run_unmount", enabled: true })
    );

    await act(async () => {
      vi.advanceTimersByTime(15);
    });

    expect(MockWebSocket.instances.length).toBe(1);
    const ws = MockWebSocket.instances[0];

    unmount();

    expect(ws.close).toHaveBeenCalledWith(1000, "Component unmounted");
  });
});
