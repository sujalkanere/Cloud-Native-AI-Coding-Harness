import { useReducer, useCallback, useEffect } from "react";
import { eventReducer, initialRunState } from "../state/eventReducer";
import { useWebSocketStream } from "./useWebSocketStream";
import type { RunEvent } from "../types/run";
import { api } from "../services/api";

interface UseRunEventsOptions {
  runId: string | null;
  token?: string;
  initialSeq?: number;
  enabled?: boolean;
}

export function useRunEvents({
  runId,
  token = "",
  initialSeq = 0,
  enabled = true,
}: UseRunEventsOptions) {
  const [state, dispatch] = useReducer(eventReducer, initialRunState);

  // Reset state when runId changes
  useEffect(() => {
    if (runId) {
      dispatch({ type: "RESET_STATE" });
      // Fetch initial events or diff if desirable
      api.getEvents(runId, 0)
        .then((events) => {
          if (events && events.length > 0) {
            dispatch({ type: "BATCH_EVENTS", events });
          }
        })
        .catch(() => {
          // WebSocket will also replay events with after=seq
        });
    }
  }, [runId]);

  const handleEvent = useCallback((event: RunEvent) => {
    dispatch({ type: "PROCESS_EVENT", event });
  }, []);

  const { status, error, reconnect } = useWebSocketStream({
    runId,
    token,
    initialSeq,
    enabled: enabled && !!runId,
    onEvent: handleEvent,
  });

  return {
    state,
    connectionStatus: status,
    error,
    reconnect,
    dispatch,
  };
}
