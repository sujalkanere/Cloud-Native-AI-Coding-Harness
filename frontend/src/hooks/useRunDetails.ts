import { useEffect, useState, useCallback } from "react";
import type { Run } from "../types/run";
import { api } from "../services/api";

interface UseRunDetailsOptions {
  runId: string | null;
  pollInterval?: number | null; // e.g. 5000ms, or null to disable polling
}

export function useRunDetails({ runId, pollInterval = null }: UseRunDetailsOptions) {
  const [run, setRun] = useState<Run | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const fetchRun = useCallback(async () => {
    if (!runId) {
      setRun(null);
      return;
    }
    try {
      setLoading(true);
      setError(null);
      const data = await api.getRun(runId);
      setRun(data);
    } catch (err: any) {
      setError(err?.message || "Failed to fetch run details");
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    fetchRun();
  }, [fetchRun]);

  useEffect(() => {
    if (!runId || !pollInterval) return;

    const interval = setInterval(() => {
      api.getRun(runId)
        .then((data) => setRun(data))
        .catch(() => {});
    }, pollInterval);

    return () => clearInterval(interval);
  }, [runId, pollInterval]);

  return {
    run,
    setRun,
    loading,
    error,
    refetch: fetchRun,
  };
}
