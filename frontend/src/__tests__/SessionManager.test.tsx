import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SessionManager } from "../components/session/SessionManager";
import { api } from "../services/api";
import type { Run } from "../types/run";

vi.mock("../services/api", () => ({
  api: {
    listRuns: vi.fn(),
    createRun: vi.fn(),
  },
}));

describe("SessionManager", () => {
  const mockRuns: Run[] = [
    {
      id: "run_alpha",
      user_id: "user_dev_001",
      repo_url: "https://github.com/example/repo.git",
      task: "Fix math bug",
      status: "RUNNING",
      options: { verification: "required" },
      is_pausing: false,
      baseline_sha: null,
      error_reason: null,
      created_at: "2026-11-22T08:00:00Z",
      updated_at: "2026-11-22T08:00:00Z",
    },
    {
      id: "run_beta",
      user_id: "user_dev_001",
      repo_url: null,
      task: "Add feature",
      status: "SUCCEEDED",
      options: { verification: "none" },
      is_pausing: false,
      baseline_sha: null,
      error_reason: null,
      created_at: "2026-11-22T07:00:00Z",
      updated_at: "2026-11-22T07:10:00Z",
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    (api.listRuns as any).mockResolvedValue(mockRuns);
  });

  it("should render header, create run card, and recent runs table", async () => {
    render(<SessionManager onSelectRun={vi.fn()} />);

    expect(screen.getByText(/cloud-native ai coding harness/i)).toBeInTheDocument();
    expect(screen.getByText(/start new coding run/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("run_alpha")).toBeInTheDocument();
      expect(screen.getByText("run_beta")).toBeInTheDocument();
      expect(screen.getByText("Fix math bug")).toBeInTheDocument();
    });
  });

  it("should validate required task field before submission", async () => {
    render(<SessionManager onSelectRun={vi.fn()} />);

    const submitBtn = screen.getByRole("button", { name: /launch autonomous run/i });
    fireEvent.click(submitBtn);

    expect(await screen.findByText(/field 'task' is required/i)).toBeInTheDocument();
    expect(api.createRun).not.toHaveBeenCalled();
  });

  it("should toggle between Git URL and Archive file upload", async () => {
    render(<SessionManager onSelectRun={vi.fn()} />);

    expect(screen.getByPlaceholderText(/https:\/\/github\.com/i)).toBeInTheDocument();

    const archiveBtn = screen.getByRole("button", { name: /upload archive/i });
    fireEvent.click(archiveBtn);

    expect(screen.queryByPlaceholderText(/https:\/\/github\.com/i)).not.toBeInTheDocument();
    expect(screen.getByText(/choose archive file/i)).toBeInTheDocument();
  });

  it("should reject archive files exceeding 50MB", async () => {
    render(<SessionManager onSelectRun={vi.fn()} />);

    const archiveBtn = screen.getByRole("button", { name: /upload archive/i });
    fireEvent.click(archiveBtn);

    // Create 55MB mock file
    const largeFile = new File([new ArrayBuffer(55 * 1024 * 1024)], "huge.tar.gz", {
      type: "application/gzip",
    });

    const fileInput = document.querySelector("#archive-upload") as HTMLInputElement;
    expect(fileInput).toBeInTheDocument();

    fireEvent.change(fileInput, { target: { files: [largeFile] } });

    expect(await screen.findByText(/archive size exceeds 50mb limit/i)).toBeInTheDocument();
  });

  it("should submit new run with verification mode selector", async () => {
    const user = userEvent.setup();
    const onSelectRun = vi.fn();
    (api.createRun as any).mockResolvedValue({
      id: "run_new_123",
      status: "QUEUED",
      task: "Fix unit tests",
    });

    render(<SessionManager onSelectRun={onSelectRun} />);

    // Select "none" verification mode
    const noneOption = screen.getByText(/^None$/i);
    fireEvent.click(noneOption);

    // Fill task
    const taskInput = screen.getByPlaceholderText(/describe what the agent should implement/i);
    await user.type(taskInput, "Fix unit tests");

    const submitBtn = screen.getByRole("button", { name: /launch autonomous run/i });
    await user.click(submitBtn);

    await waitFor(() => {
      expect(api.createRun).toHaveBeenCalledWith({
        task: "Fix unit tests",
        repo_url: undefined,
        options: { verification: "none" },
      });
      expect(onSelectRun).toHaveBeenCalledWith("run_new_123");
    });
  });

  it("should call onSelectRun when clicking View in recent runs table", async () => {
    const onSelectRun = vi.fn();
    render(<SessionManager onSelectRun={onSelectRun} />);

    await waitFor(() => {
      expect(screen.getByText("run_alpha")).toBeInTheDocument();
    });

    const viewButtons = screen.getAllByRole("button", { name: /view/i });
    fireEvent.click(viewButtons[0]);

    expect(onSelectRun).toHaveBeenCalledWith("run_alpha");
  });
});
