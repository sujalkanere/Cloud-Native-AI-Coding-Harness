import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ControlBar } from "../components/run/ControlBar";
import { api } from "../services/api";
import type { Run } from "../types/run";

vi.mock("../services/api", () => ({
  api: {
    pauseRun: vi.fn().mockResolvedValue({ action: "boundary_pause_requested", changed: true }),
    resumeRun: vi.fn().mockResolvedValue({ action: "resumed", changed: true }),
    terminateRun: vi.fn().mockResolvedValue({ action: "terminated", changed: true }),
    injectGuidance: vi.fn().mockResolvedValue({ status: "guidance_injected" }),
    getArtifacts: vi.fn().mockResolvedValue({
      patch_url: "http://example.com/patch.diff",
      logs_url: "http://example.com/logs.txt",
      transcript_url: "http://example.com/transcript.json",
    }),
  },
}));

describe("ControlBar", () => {
  const mockRun: Run = {
    id: "run_test_123",
    user_id: "user_dev_001",
    repo_url: null,
    task: "Test task",
    status: "RUNNING",
    options: { verification: "required" },
    is_pausing: false,
    baseline_sha: null,
    error_reason: null,
    created_at: "2026-11-22T08:00:00Z",
    updated_at: "2026-11-22T08:00:00Z",
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("should render Pause, Resume, Guidance, Terminate, and Artifacts controls", () => {
    render(<ControlBar run={mockRun} />);

    expect(screen.getByRole("button", { name: /pause/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /resume/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /terminate/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /artifacts/i })).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/steer agent/i)).toBeInTheDocument();
  });

  it("should trigger boundary pause when clicking Pause button", async () => {
    const onControlAction = vi.fn();
    render(<ControlBar run={mockRun} onControlAction={onControlAction} />);

    const pauseBtn = screen.getByRole("button", { name: /^pause$/i });
    expect(pauseBtn).not.toBeDisabled();

    fireEvent.click(pauseBtn);

    await waitFor(() => {
      expect(api.pauseRun).toHaveBeenCalledWith("run_test_123", "boundary");
      expect(onControlAction).toHaveBeenCalledWith("pause_boundary");
    });
  });

  it("should show 'Pausing...' spinner and disable Pause button when is_pausing=true", () => {
    render(<ControlBar run={mockRun} isPausing={true} />);

    const pausingBtn = screen.getByRole("button", { name: /pausing\.\.\./i });
    expect(pausingBtn).toBeInTheDocument();
    expect(pausingBtn).toBeDisabled();
  });

  it("should enable Resume button with 'Cancel Pause' label when is_pausing=true and cancel pause on click", async () => {
    const onControlAction = vi.fn();
    render(<ControlBar run={mockRun} isPausing={true} onControlAction={onControlAction} />);

    const cancelPauseBtn = screen.getByRole("button", { name: /cancel pause/i });
    expect(cancelPauseBtn).toBeInTheDocument();
    expect(cancelPauseBtn).not.toBeDisabled();

    fireEvent.click(cancelPauseBtn);

    await waitFor(() => {
      expect(api.resumeRun).toHaveBeenCalledWith("run_test_123");
      expect(onControlAction).toHaveBeenCalledWith("resume");
    });
  });

  it("should enable Resume button when status is PAUSED", async () => {
    const onControlAction = vi.fn();
    render(<ControlBar run={{ ...mockRun, status: "PAUSED" }} onControlAction={onControlAction} />);

    const resumeBtn = screen.getByRole("button", { name: /resume/i });
    expect(resumeBtn).not.toBeDisabled();

    fireEvent.click(resumeBtn);

    await waitFor(() => {
      expect(api.resumeRun).toHaveBeenCalledWith("run_test_123");
      expect(onControlAction).toHaveBeenCalledWith("resume");
    });
  });

  it("should open confirmation modal on Terminate and trigger API on confirmation", async () => {
    const onControlAction = vi.fn();
    render(<ControlBar run={mockRun} onControlAction={onControlAction} />);

    const terminateBtn = screen.getByRole("button", { name: /terminate/i });
    fireEvent.click(terminateBtn);

    // Modal should now be open
    expect(screen.getByText(/terminate agent run\?/i)).toBeInTheDocument();
    expect(screen.getByText(/destroy the container within 5 seconds/i)).toBeInTheDocument();

    const confirmBtn = screen.getByRole("button", { name: /terminate now/i });
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(api.terminateRun).toHaveBeenCalledWith("run_test_123", "User terminated");
      expect(onControlAction).toHaveBeenCalledWith("terminate");
    });
  });

  it("should send guidance message when clicking Send", async () => {
    const user = userEvent.setup();
    const onControlAction = vi.fn();
    render(<ControlBar run={mockRun} onControlAction={onControlAction} />);

    const input = screen.getByPlaceholderText(/steer agent/i);
    await user.type(input, "Check calculator.py line 42");

    const sendBtn = screen.getByRole("button", { name: /send/i });
    await user.click(sendBtn);

    await waitFor(() => {
      expect(api.injectGuidance).toHaveBeenCalledWith("run_test_123", "Check calculator.py line 42");
      expect(onControlAction).toHaveBeenCalledWith("guidance");
    });
  });
});
