import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useWebSocketStream } from "../hooks/useWebSocketStream";

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

describe("useWebSocketStream", () => {
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

  it("should connect to WebSocket endpoint with initial after=0", async () => {
    const { result } = renderHook(() =>
      useWebSocketStream({
        runId: "run_test1",
        enabled: true,
      })
    );

    expect(MockWebSocket.instances.length).toBe(1);
    expect(MockWebSocket.instances[0].url).toContain("/api/runs/run_test1/stream?after=0");

    await act(async () => {
      vi.advanceTimersByTime(15);
    });

    expect(result.current.status).toBe("connected");
  });

  it("should update lastSeenSeq and call onEvent when messages arrive", async () => {
    const onEvent = vi.fn();
    const { result } = renderHook(() =>
      useWebSocketStream({
        runId: "run_test1",
        enabled: true,
        onEvent,
      })
    );

    await act(async () => {
      vi.advanceTimersByTime(15);
    });

    const ws = MockWebSocket.instances[0];

    act(() => {
      ws.simulateMessage({
        seq: 5,
        ts: "2026-11-22T08:00:00Z",
        type: "reasoning",
        payload: { thought: "Test thought" },
      });
    });

    expect(onEvent).toHaveBeenCalledTimes(1);
    expect(result.current.lastSeenSeq).toBe(5);
  });

  it("should reconnect with exponential backoff on unexpected closure using updated lastSeenSeq", async () => {
    const { result } = renderHook(() =>
      useWebSocketStream({
        runId: "run_test1",
        enabled: true,
      })
    );

    await act(async () => {
      vi.advanceTimersByTime(15);
    });

    const ws1 = MockWebSocket.instances[0];
    act(() => {
      ws1.simulateMessage({
        seq: 7,
        ts: "2026-11-22T08:00:00Z",
        type: "status_change",
        payload: { status: "RUNNING" },
      });
    });

    expect(result.current.lastSeenSeq).toBe(7);

    // Simulate unexpected drop (code 1006)
    act(() => {
      ws1.simulateClose(1006, "Abnormal closure");
    });

    expect(result.current.status).toBe("reconnecting");

    // Advance timers for backoff delay (baseDelay 500ms + max jitter 300ms)
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });

    expect(MockWebSocket.instances.length).toBe(2);
    const ws2 = MockWebSocket.instances[1];
    expect(ws2.url).toContain("/api/runs/run_test1/stream?after=7");
  });

  it("should abort reconnection immediately on 4404 close code (run not found / access denied)", async () => {
    const { result } = renderHook(() =>
      useWebSocketStream({
        runId: "run_forbidden",
        enabled: true,
      })
    );

    await act(async () => {
      vi.advanceTimersByTime(15);
    });

    const ws1 = MockWebSocket.instances[0];

    act(() => {
      ws1.simulateClose(4404, "Run not found");
    });

    expect(result.current.status).toBe("error");
    expect(result.current.error).toContain("404");

    // Advance time and assert no new connections are attempted
    await act(async () => {
      vi.advanceTimersByTime(10000);
    });

    expect(MockWebSocket.instances.length).toBe(1);
  });

  it("should not reconnect on normal 1000 closure", async () => {
    const { result } = renderHook(() =>
      useWebSocketStream({
        runId: "run_test1",
        enabled: true,
      })
    );

    await act(async () => {
      vi.advanceTimersByTime(15);
    });

    const ws1 = MockWebSocket.instances[0];

    act(() => {
      ws1.simulateClose(1000, "Normal closure");
    });

    expect(result.current.status).toBe("disconnected");

    await act(async () => {
      vi.advanceTimersByTime(5000);
    });

    expect(MockWebSocket.instances.length).toBe(1);
  });

  it("should maintain a single WebSocket instance and never recreate or close when receiving sequential events", async () => {
    const onEvent = vi.fn();
    const { result } = renderHook(() =>
      useWebSocketStream({
        runId: "run_stream_stability",
        enabled: true,
        onEvent,
      })
    );

    await act(async () => {
      vi.advanceTimersByTime(15);
    });

    expect(MockWebSocket.instances.length).toBe(1);
    const ws = MockWebSocket.instances[0];

    // Stream 5 events in sequence
    for (let seq = 1; seq <= 5; seq++) {
      act(() => {
        ws.simulateMessage({
          seq,
          ts: `2026-11-22T08:00:0${seq}Z`,
          type: "reasoning",
          payload: { thought: `Step ${seq}` },
        });
      });

      await act(async () => {
        vi.advanceTimersByTime(10);
      });
    }

    // Instances must remain exactly 1, and close must not be called
    expect(MockWebSocket.instances.length).toBe(1);
    expect(ws.close).not.toHaveBeenCalled();
    expect(result.current.lastSeenSeq).toBe(5);
    expect(onEvent).toHaveBeenCalledTimes(5);
  });
});
