import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render } from "@testing-library/react";
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

describe("TerminalView ANSI Fuzzing & High-Stress Edge Cases", () => {
  let writeSpy: any;

  beforeEach(() => {
    vi.stubGlobal("matchMedia", makeMatchMedia());
    writeSpy = vi.spyOn(XTerm.prototype, "write");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("should survive malformed ANSI sequences, OSC sequences, and control characters without crashing", () => {
    const fuzzedChunks: TerminalChunk[] = [
      // Malformed SGR escape codes
      { seq: 1, stream: "stdout", data: "\x1b[99999;888888mInvalid color parameters\x1b[m\n" },
      // Operating System Command (OSC) string sequence
      { seq: 2, stream: "stdout", data: "\x1b]0;Evil Window Title\x07Normal text\n" },
      // Cursor positioning and clearing codes
      { seq: 3, stream: "stdout", data: "\x1b[2J\x1b[H\x1b[100;100HCursor jumping\n" },
      // Control bytes: nulls, bells, vertical tabs, form feeds, backspaces
      { seq: 4, stream: "stderr", data: "\x00\x07\x0b\x0c\b\b\bOverwritten line?\r\n" },
      // Incomplete trailing escape sequence
      { seq: 5, stream: "stdout", data: "Trailing partial escape: \x1b[" },
    ];

    expect(() => {
      render(<TerminalView chunks={fuzzedChunks} />);
    }).not.toThrow();

    expect(writeSpy).toHaveBeenCalledTimes(5);
  });

  it("should handle an extreme 100,000-character unbroken line without hanging or crashing", () => {
    // 100k continuous characters without any newlines
    const hugeLine = "X".repeat(100000);
    const chunks: TerminalChunk[] = [
      { seq: 1, stream: "stdout", data: hugeLine },
      { seq: 2, stream: "stderr", data: "Follow-up error line\n" },
    ];

    expect(() => {
      render(<TerminalView chunks={chunks} />);
    }).not.toThrow();

    expect(writeSpy).toHaveBeenCalledTimes(2);
    expect(writeSpy).toHaveBeenNthCalledWith(1, hugeLine);
  });

  it("should gracefully handle zero-dimension containers without throwing fit errors", () => {
    const chunks: TerminalChunk[] = [
      { seq: 1, stream: "stdout", data: "Zero dim test\n" },
    ];

    // Mock clientWidth and clientHeight as 0 (hidden tab or collapsed pane)
    const originalClientWidth = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      "clientWidth"
    );
    const originalClientHeight = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      "clientHeight"
    );

    Object.defineProperty(HTMLElement.prototype, "clientWidth", {
      configurable: true,
      value: 0,
    });
    Object.defineProperty(HTMLElement.prototype, "clientHeight", {
      configurable: true,
      value: 0,
    });

    try {
      expect(() => {
        render(<TerminalView chunks={chunks} />);
      }).not.toThrow();
    } finally {
      if (originalClientWidth) {
        Object.defineProperty(HTMLElement.prototype, "clientWidth", originalClientWidth);
      }
      if (originalClientHeight) {
        Object.defineProperty(HTMLElement.prototype, "clientHeight", originalClientHeight);
      }
    }
  });

  it("should survive rapid window resize triggering while active", () => {
    const chunks: TerminalChunk[] = [
      { seq: 1, stream: "stdout", data: "Active stream before resize\n" },
    ];

    const { unmount } = render(<TerminalView chunks={chunks} />);

    // Trigger resize events repeatedly
    for (let i = 0; i < 20; i++) {
      window.dispatchEvent(new Event("resize"));
    }

    expect(() => {
      unmount();
    }).not.toThrow();
  });
});
