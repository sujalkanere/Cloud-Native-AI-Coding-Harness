import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { TerminalView } from "../components/run/TerminalView";
import type { TerminalChunk } from "../types/run";
import { Terminal as XTerm } from "@xterm/xterm";

const makeMatchMedia = () =>
  vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));

describe("TerminalView Adversarial Tests", () => {
  let writeSpy: any;

  beforeEach(() => {
    // Stub matchMedia before each test so xterm can initialize in jsdom
    vi.stubGlobal("matchMedia", makeMatchMedia());
    writeSpy = vi.spyOn(XTerm.prototype, "write");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("should stream stdout chunks in raw format and stderr chunks with ANSI yellow formatting", () => {
    const chunks: TerminalChunk[] = [
      { seq: 1, stream: "stdout", data: "Starting test suite...\r\n" },
      { seq: 2, stream: "stderr", data: "Warning: Deprecated API called\r\n" },
      { seq: 3, stream: "stdout", data: "Finished in 0.5s\r\n" },
    ];

    render(<TerminalView chunks={chunks} />);

    expect(writeSpy).toHaveBeenCalledTimes(3);
    // Chunk 1: stdout raw
    expect(writeSpy).toHaveBeenNthCalledWith(1, "Starting test suite...\r\n");
    // Chunk 2: stderr with ANSI code \x1b[33m...\x1b[0m
    expect(writeSpy).toHaveBeenNthCalledWith(2, "\x1b[33mWarning: Deprecated API called\r\n\x1b[0m");
    // Chunk 3: stdout raw
    expect(writeSpy).toHaveBeenNthCalledWith(3, "Finished in 0.5s\r\n");
  });

  it("should enforce watermark tracking and never write the same chunk twice across re-renders", () => {
    const initialChunks: TerminalChunk[] = [
      { seq: 1, stream: "stdout", data: "Line 1\n" },
      { seq: 2, stream: "stdout", data: "Line 2\n" },
    ];

    const { rerender } = render(<TerminalView chunks={initialChunks} />);
    expect(writeSpy).toHaveBeenCalledTimes(2);

    // Re-render with identical chunks array
    rerender(<TerminalView chunks={initialChunks} />);
    expect(writeSpy).toHaveBeenCalledTimes(2); // Still 2!

    // Re-render with a new chunk appended
    const updatedChunks: TerminalChunk[] = [
      ...initialChunks,
      { seq: 3, stream: "stdout", data: "Line 3\n" },
    ];
    rerender(<TerminalView chunks={updatedChunks} />);
    expect(writeSpy).toHaveBeenCalledTimes(3); // Exactly one additional write!
    expect(writeSpy).toHaveBeenNthCalledWith(3, "Line 3\n");
  });

  it("should display truncation badge and write red truncation banner when isTruncated is true", () => {
    const chunks: TerminalChunk[] = [
      { seq: 1, stream: "stdout", data: "Beginning heavy logs...\n" },
    ];

    const { rerender } = render(
      <TerminalView chunks={chunks} isTruncated={false} />
    );

    expect(screen.queryByText(/Output Capped/i)).not.toBeInTheDocument();
    expect(writeSpy).toHaveBeenCalledTimes(1);

    // Now trigger truncation
    rerender(
      <TerminalView
        chunks={chunks}
        isTruncated={true}
        truncationMessage="Exceeded maximum limit of 5242880 bytes."
      />
    );

    // Badge should be visible in DOM
    expect(screen.getByText(/Output Capped \(5MB\)/i)).toBeInTheDocument();

    // Truncation banner should be written to terminal
    expect(writeSpy).toHaveBeenCalledTimes(2);
    const lastCall = writeSpy.mock.calls[1][0];
    expect(lastCall).toContain("[TERMINAL OUTPUT TRUNCATED]");
    expect(lastCall).toContain("Exceeded maximum limit of 5242880 bytes.");
    expect(lastCall).toContain("\x1b[41;37;1m"); // Red background styling
  });

  it("should not write duplicate truncation banners across multiple re-renders", () => {
    const chunks: TerminalChunk[] = [{ seq: 1, stream: "stdout", data: "Log\n" }];

    const { rerender } = render(
      <TerminalView chunks={chunks} isTruncated={true} />
    );

    const bannerCallsFirst = writeSpy.mock.calls.filter((c: any[]) =>
      c[0]?.includes?.("[TERMINAL OUTPUT TRUNCATED]")
    );
    expect(bannerCallsFirst).toHaveLength(1);

    // Re-render 5 times while still truncated
    for (let i = 0; i < 5; i++) {
      rerender(<TerminalView chunks={chunks} isTruncated={true} />);
    }

    const bannerCallsTotal = writeSpy.mock.calls.filter((c: any[]) =>
      c[0]?.includes?.("[TERMINAL OUTPUT TRUNCATED]")
    );
    expect(bannerCallsTotal).toHaveLength(1); // Banner only written once!
  });

  it("should stream high volumes of chunks without dropping order", () => {
    const highVolumeChunks: TerminalChunk[] = [];
    for (let i = 1; i <= 200; i++) {
      highVolumeChunks.push({
        seq: i,
        stream: i % 2 === 0 ? "stderr" : "stdout",
        data: `Chunk payload ${i}\n`,
      });
    }

    render(<TerminalView chunks={highVolumeChunks} />);

    expect(writeSpy).toHaveBeenCalledTimes(200);
    for (let i = 0; i < 200; i++) {
      const isStderr = (i + 1) % 2 === 0;
      if (isStderr) {
        expect(writeSpy).toHaveBeenNthCalledWith(
          i + 1,
          `\x1b[33mChunk payload ${i + 1}\n\x1b[0m`
        );
      } else {
        expect(writeSpy).toHaveBeenNthCalledWith(
          i + 1,
          `Chunk payload ${i + 1}\n`
        );
      }
    }
  });

  it("should replay all chunks from seq 0 when remounted (late joiner scenario)", () => {
    const chunks: TerminalChunk[] = [
      { seq: 1, stream: "stdout", data: "Historical 1\n" },
      { seq: 2, stream: "stdout", data: "Historical 2\n" },
    ];

    const { unmount } = render(<TerminalView chunks={chunks} />);
    expect(writeSpy).toHaveBeenCalledTimes(2);

    unmount(); // Unmount

    // Re-mount (e.g. user navigated back to tab or opened view)
    render(<TerminalView chunks={chunks} />);
    // Should replay both chunks again in the new terminal instance
    expect(writeSpy).toHaveBeenCalledTimes(4);
    expect(writeSpy).toHaveBeenNthCalledWith(3, "Historical 1\n");
    expect(writeSpy).toHaveBeenNthCalledWith(4, "Historical 2\n");
  });
});
