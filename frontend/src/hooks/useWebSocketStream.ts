import { useEffect, useRef, useState, useCallback } from "react";
import type { RunEvent } from "../types/run";

export type ConnectionStatus =
  | "idle"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "disconnected"
  | "error";

export interface UseWebSocketStreamOptions {
  runId: string | null;
  token?: string;
  initialSeq?: number;
  enabled?: boolean;
  onEvent?: (event: RunEvent) => void;
  onStatusChange?: (status: ConnectionStatus) => void;
}

export function useWebSocketStream({
  runId,
  token = "",
  initialSeq = 0,
  enabled = true,
  onEvent,
  onStatusChange,
}: UseWebSocketStreamOptions) {
  const [status, setStatusState] = useState<ConnectionStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [lastSeenSeq, setLastSeenSeq] = useState<number>(initialSeq);
  const lastSeenSeqRef = useRef<number>(initialSeq);
  const initialSeqRef = useRef<number>(initialSeq);
  initialSeqRef.current = initialSeq;
  const reconnectAttemptRef = useRef<number>(0);
  const wsRef = useRef<WebSocket | null>(null);
  const isUnmountedRef = useRef<boolean>(false);
  const reconnectTimerRef = useRef<number | null>(null);
  const prevRunIdRef = useRef<string | null>(runId);

  // Keep callback refs fresh
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const onStatusChangeRef = useRef(onStatusChange);
  onStatusChangeRef.current = onStatusChange;

  const setStatus = useCallback(
    (action: ConnectionStatus | ((prev: ConnectionStatus) => ConnectionStatus)) => {
      setStatusState((prev) => {
        const next = typeof action === "function" ? action(prev) : action;
        onStatusChangeRef.current?.(next);
        return next;
      });
    },
    []
  );

  const clearTimer = () => {
    if (reconnectTimerRef.current !== null) {
      window.clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  };

  const connect = useCallback(() => {
    if (!runId || !enabled || isUnmountedRef.current) return;

    // Guard: never open duplicate sockets if one is already active or connecting
    if (wsRef.current && (wsRef.current.readyState === 0 || wsRef.current.readyState === 1)) {
      return;
    }

    clearTimer();

    // Determine WS protocol and host based on window.location
    const protocol = typeof window !== "undefined" && window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = typeof window !== "undefined" ? window.location.host : "localhost:3000";
    const query = new URLSearchParams();
    query.set("after", lastSeenSeqRef.current.toString());
    if (token) query.set("token", token);

    const wsUrl = `${protocol}//${host}/api/runs/${runId}/stream?${query.toString()}`;

    setStatus((prev) => (prev === "connected" ? "reconnecting" : "connecting"));

    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        if (isUnmountedRef.current || ws !== wsRef.current) {
          ws.close();
          return;
        }
        setStatus("connected");
        setError(null);
        reconnectAttemptRef.current = 0;
      };

      ws.onmessage = (msgEvent) => {
        if (isUnmountedRef.current || ws !== wsRef.current) return;
        try {
          const event: RunEvent = JSON.parse(msgEvent.data);
          if (event && typeof event.seq === "number") {
            lastSeenSeqRef.current = Math.max(lastSeenSeqRef.current, event.seq);
            setLastSeenSeq(lastSeenSeqRef.current);
            onEventRef.current?.(event);
          }
        } catch (err) {
          console.error("Failed to parse WebSocket message:", err);
        }
      };

      ws.onclose = (closeEvent) => {
        if (isUnmountedRef.current || ws !== wsRef.current) return;

        // Handle 4404 per-user isolation / run not found
        if (closeEvent.code === 4404) {
          setStatus("error");
          setError("Run not found or access denied (404).");
          return; // Do NOT attempt reconnection
        }

        // Normal closure
        if (closeEvent.code === 1000) {
          setStatus("disconnected");
          return;
        }

        // Reconnect with exponential backoff + jitter
        setStatus("reconnecting");
        const attempt = reconnectAttemptRef.current;
        const baseDelay = 500;
        const maxDelay = 10000;
        const jitter = Math.random() * 300;
        const delay = Math.min(maxDelay, baseDelay * Math.pow(2, attempt)) + jitter;

        reconnectAttemptRef.current += 1;
        clearTimer();
        reconnectTimerRef.current = window.setTimeout(() => {
          connect();
        }, delay);
      };

      ws.onerror = () => {
        if (isUnmountedRef.current || ws !== wsRef.current) return;
        setError("WebSocket connection encountered an error.");
      };
    } catch (err: any) {
      if (isUnmountedRef.current) return;
      setError(err?.message || "Failed to establish WebSocket connection.");
      setStatus("error");
    }
  }, [runId, token, enabled, setStatus]);

  useEffect(() => {
    isUnmountedRef.current = false;

    if (prevRunIdRef.current !== runId) {
      prevRunIdRef.current = runId;
      lastSeenSeqRef.current = initialSeqRef.current;
      setLastSeenSeq(initialSeqRef.current);
      reconnectAttemptRef.current = 0;
    }

    if (enabled && runId) {
      connect();
    } else {
      if (wsRef.current) {
        const wsToClose = wsRef.current;
        wsRef.current = null;
        wsToClose.close(1000, "Disabled");
      }
      setStatus("idle");
    }

    return () => {
      isUnmountedRef.current = true;
      clearTimer();
      if (wsRef.current) {
        const wsToClose = wsRef.current;
        wsRef.current = null;
        wsToClose.close(1000, "Component unmounted");
      }
    };
  }, [runId, enabled, connect, setStatus]);

  const manualReconnect = useCallback(() => {
    reconnectAttemptRef.current = 0;
    if (wsRef.current) {
      const wsToClose = wsRef.current;
      wsRef.current = null;
      wsToClose.close(1000, "Manual reconnect");
    }
    connect();
  }, [connect]);

  return {
    status,
    error,
    lastSeenSeq,
    reconnect: manualReconnect,
  };
}
