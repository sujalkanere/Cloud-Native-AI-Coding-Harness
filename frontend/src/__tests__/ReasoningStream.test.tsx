import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ReasoningStream } from "../components/run/ReasoningStream";
import type { RunEvent, ToolCallItem } from "../types/run";

describe("ReasoningStream", () => {
  const mockEvents: RunEvent[] = [
    {
      seq: 1,
      ts: "2026-11-22T08:00:01Z",
      type: "status_change",
      payload: { status: "PREPARING" },
    },
    {
      seq: 2,
      ts: "2026-11-22T08:00:02Z",
      type: "guidance",
      payload: { message: "Pay attention to test_calculator.py" },
    },
    {
      seq: 3,
      ts: "2026-11-22T08:00:03Z",
      type: "reasoning",
      payload: { thought: "Let me check the implementation of divide()." },
    },
    {
      seq: 4,
      ts: "2026-11-22T08:00:04Z",
      type: "plan",
      payload: { steps: ["Inspect file", "Fix division", "Run tests"] },
    },
    {
      seq: 5,
      ts: "2026-11-22T08:00:05Z",
      type: "tool_call",
      payload: {
        id: "tc_pytest",
        name: "run_command",
        arguments: { command: "pytest tests/" },
      },
    },
  ];

  const mockToolCalls = new Map<string, ToolCallItem>([
    [
      "tc_pytest",
      {
        id: "tc_pytest",
        name: "run_command",
        arguments: { command: "pytest tests/" },
        status: "success",
        output: "2 passed in 0.1s",
        exitCode: 0,
        timestamp: "2026-11-22T08:00:05Z",
      },
    ],
  ]);

  it("should render thoughts, plans, guidance, and status changes", () => {
    render(<ReasoningStream events={mockEvents} toolCalls={mockToolCalls} />);

    expect(screen.getByText("PREPARING")).toBeInTheDocument();
    expect(screen.getByText(/user steering guidance/i)).toBeInTheDocument();
    expect(screen.getByText("Pay attention to test_calculator.py")).toBeInTheDocument();
    expect(screen.getByText(/let me check the implementation of divide\(\)\./i)).toBeInTheDocument();
    expect(screen.getByText("Inspect file")).toBeInTheDocument();
    expect(screen.getByText("Fix division")).toBeInTheDocument();
  });

  it("should expand and collapse tool call cards on click", () => {
    render(<ReasoningStream events={mockEvents} toolCalls={mockToolCalls} />);

    expect(screen.getByText("run_command")).toBeInTheDocument();
    expect(screen.getByText("pytest tests/")).toBeInTheDocument();

    // Body should initially be collapsed
    expect(screen.queryByText("2 passed in 0.1s")).not.toBeInTheDocument();

    // Click header to expand
    const toolHeader = screen.getByText("run_command").closest("div");
    fireEvent.click(toolHeader!);

    // Body should now be visible
    expect(screen.getByText("2 passed in 0.1s")).toBeInTheDocument();

    // Click again to collapse
    fireEvent.click(toolHeader!);
    expect(screen.queryByText("2 passed in 0.1s")).not.toBeInTheDocument();
  });

  it("should show 'Jump to latest' button when scrolled away from bottom and trigger scrollTo", () => {
    const { container } = render(<ReasoningStream events={mockEvents} toolCalls={mockToolCalls} />);

    const scrollContainer = container.querySelector(".overflow-y-auto") as HTMLDivElement;
    expect(scrollContainer).toBeInTheDocument();

    // Mock scrollHeight, clientHeight, scrollTop
    Object.defineProperty(scrollContainer, "scrollHeight", { value: 1000, configurable: true });
    Object.defineProperty(scrollContainer, "clientHeight", { value: 400, configurable: true });
    Object.defineProperty(scrollContainer, "scrollTop", { value: 100, configurable: true, writable: true });

    scrollContainer.scrollTo = vi.fn();

    // Trigger scroll event
    fireEvent.scroll(scrollContainer);

    // Jump button should appear
    const jumpBtn = screen.getByRole("button", { name: /jump to latest/i });
    expect(jumpBtn).toBeInTheDocument();

    // Click jump button
    fireEvent.click(jumpBtn);

    expect(scrollContainer.scrollTo).toHaveBeenCalledWith({
      top: 1000,
      behavior: "smooth",
    });
  });
});
