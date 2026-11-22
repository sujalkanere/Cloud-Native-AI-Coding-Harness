/**
 * Typed REST API Client & WebSocket URL builder for Milestone 6 Frontend
 */
import type {
  ArtifactUrls,
  ControlResponse,
  CreateRunJsonPayload,
  FileDiff,
  GuidanceRequest,
  GuidanceResponse,
  HealthResponse,
  PauseMode,
  PauseRequest,
  ReadyResponse,
  Run,
  RunEvent,
  TerminateRequest,
} from "../types/run";

const API_BASE = "/api";

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers || {});
  if (!headers.has("Content-Type") && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let errorMessage = `HTTP Error ${response.status}: ${response.statusText}`;
    try {
      const errorJson = await response.json();
      if (errorJson && errorJson.detail) {
        errorMessage = typeof errorJson.detail === "string" ? errorJson.detail : JSON.stringify(errorJson.detail);
      }
    } catch {
      // ignore json parse errors
    }
    throw new Error(errorMessage);
  }

  return response.json() as Promise<T>;
}

export const api = {
  /**
   * Submits a new run via JSON payload or FormData (for tarball archive upload).
   */
  async createRun(payload: CreateRunJsonPayload | FormData): Promise<Run> {
    if (payload instanceof FormData) {
      return request<Run>("/runs", {
        method: "POST",
        body: payload,
      });
    }
    return request<Run>("/runs", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /**
   * Lists all runs for current authenticated user.
   */
  async listRuns(): Promise<Run[]> {
    return request<Run[]>("/runs", { method: "GET" });
  },

  /**
   * Retrieves single run details.
   */
  async getRun(id: string): Promise<Run> {
    return request<Run>(`/runs/${id}`, { method: "GET" });
  },

  /**
   * Requests run pause (boundary or now).
   */
  async pauseRun(id: string, mode: PauseMode = "boundary"): Promise<ControlResponse> {
    const body: PauseRequest = { mode };
    return request<ControlResponse>(`/runs/${id}/pause`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  /**
   * Resumes paused run or cancels pending boundary pause.
   */
  async resumeRun(id: string): Promise<ControlResponse> {
    return request<ControlResponse>(`/runs/${id}/resume`, {
      method: "POST",
    });
  },

  /**
   * Terminates active run and extracts patch before container destruction.
   */
  async terminateRun(id: string, reason: string = "User terminated"): Promise<ControlResponse> {
    const body: TerminateRequest = { reason };
    return request<ControlResponse>(`/runs/${id}/terminate`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  /**
   * Injects steering guidance into agent context.
   */
  async injectGuidance(id: string, message: string): Promise<GuidanceResponse> {
    const body: GuidanceRequest = { message };
    return request<GuidanceResponse>(`/runs/${id}/guidance`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  /**
   * Polls events strictly with seq > after.
   */
  async getEvents(id: string, after: number = 0): Promise<RunEvent[]> {
    return request<RunEvent[]>(`/runs/${id}/events?after=${after}`, {
      method: "GET",
    });
  },

  /**
   * Retrieves presigned artifact download URLs for patch, logs, transcript.
   */
  async getArtifacts(id: string): Promise<ArtifactUrls> {
    return request<ArtifactUrls>(`/runs/${id}/artifacts`, {
      method: "GET",
    });
  },

  /**
   * Retrieves per-file diffs against baseline SHA.
   */
  async getDiff(id: string): Promise<FileDiff[]> {
    return request<FileDiff[]>(`/runs/${id}/diff`, {
      method: "GET",
    });
  },

  /**
   * Lists files present or created in workspace.
   */
  async listFiles(id: string): Promise<Array<{ path: string; name: string }>> {
    return request<Array<{ path: string; name: string }>>(`/runs/${id}/files`, {
      method: "GET",
    });
  },

  /**
   * Gets content of a specific file.
   */
  async getFileContent(id: string, path: string): Promise<{ path: string; content: string }> {
    return request<{ path: string; content: string }>(`/runs/${id}/files/content?path=${encodeURIComponent(path)}`, {
      method: "GET",
    });
  },

  /**
   * Executes a shell command inside the sandbox.
   */
  async executeCommand(id: string, command: string): Promise<{ command: string; exit_code: number; output: string }> {
    return request<{ command: string; exit_code: number; output: string }>(`/runs/${id}/execute`, {
      method: "POST",
      body: JSON.stringify({ command }),
    });
  },

  /**
   * Health probes.
   */
  async getHealthz(): Promise<HealthResponse> {
    return request<HealthResponse>("/healthz", { method: "GET" });
  },

  async getReadyz(): Promise<ReadyResponse> {
    return request<ReadyResponse>("/readyz", { method: "GET" });
  },

  /**
   * Builds WebSocket streaming URL with after=seq and token.
   */
  buildWebSocketUrl(id: string, after: number = 0, token?: string): string {
    const protocol = typeof window !== "undefined" && window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = typeof window !== "undefined" ? window.location.host : "localhost:3000";
    const query = new URLSearchParams();
    query.set("after", after.toString());
    if (token) query.set("token", token);
    return `${protocol}//${host}/api/runs/${id}/stream?${query.toString()}`;
  },
};
