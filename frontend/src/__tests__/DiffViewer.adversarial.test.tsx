import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { DiffViewer } from "../components/run/DiffViewer";
import type { FileDiff } from "../types/run";

describe("DiffViewer Adversarial & Extreme Payload Tests", () => {
  it("should render binary files with the purple binary badge and fallback message without text diffs", () => {
    const binaryDiffs: FileDiff[] = [
      {
        path: "assets/logo.png",
        status: "binary",
        additions: 0,
        deletions: 0,
        old_content: null,
        new_content: null,
        diff_patch: null,
      },
    ];

    render(<DiffViewer runId="run_binary_test" diffs={binaryDiffs} />);

    // Assert file path is in the sidebar and header
    const elements = screen.getAllByText("assets/logo.png");
    expect(elements.length).toBeGreaterThanOrEqual(1);

    // Assert binary fallback explanation is displayed
    expect(
      screen.getByText(/Binary file modified; diff cannot be displayed in text viewer/i)
    ).toBeInTheDocument();
  });

  it("should handle paths containing unicode emojis, spaces, and complex characters", () => {
    const unicodeDiffs: FileDiff[] = [
      {
        path: "src/components/😀/🚀_rocket widget.tsx",
        status: "modified",
        additions: 1,
        deletions: 1,
        old_content: "const icon = '⏳';",
        new_content: "const icon = '✨';",
        diff_patch: "--- a/src/components/😀/🚀_rocket widget.tsx\n+++ b/src/components/😀/🚀_rocket widget.tsx\n@@ -1,1 +1,1 @@\n-const icon = '⏳';\n+const icon = '✨';",
      },
    ];

    render(<DiffViewer runId="run_unicode_test" diffs={unicodeDiffs} />);

    const elements = screen.getAllByText("src/components/😀/🚀_rocket widget.tsx");
    expect(elements.length).toBeGreaterThanOrEqual(1);
  });

  it("should render a huge 10,000-line diff without throwing or hanging", () => {
    // Generate a 10,000 line unified diff
    const oldLines: string[] = [];
    const newLines: string[] = [];
    for (let i = 1; i <= 5000; i++) {
      oldLines.push(`console.log("Old line ${i}");`);
      newLines.push(`console.log("New optimized line ${i}");`);
    }

    const hugeDiff: FileDiff[] = [
      {
        path: "src/generated/massive_table.ts",
        status: "modified",
        additions: 5000,
        deletions: 5000,
        old_content: oldLines.join("\n"),
        new_content: newLines.join("\n"),
        diff_patch: "@@ -1,5000 +1,5000 @@\n" + oldLines.map((l) => `-${l}`).join("\n") + "\n" + newLines.map((l) => `+${l}`).join("\n"),
      },
    ];

    expect(() => {
      render(<DiffViewer runId="run_huge_diff_test" diffs={hugeDiff} />);
    }).not.toThrow();

    const elements = screen.getAllByText("src/generated/massive_table.ts");
    expect(elements.length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("+5000").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("-5000").length).toBeGreaterThanOrEqual(1);
  });

  it("should gracefully handle malformed, empty, or unparseable diff patches", () => {
    const malformedDiffs: FileDiff[] = [
      {
        path: "empty.txt",
        status: "modified",
        additions: 0,
        deletions: 0,
        old_content: null,
        new_content: null,
        diff_patch: "",
      },
      {
        path: "garbage.txt",
        status: "modified",
        additions: 0,
        deletions: 0,
        old_content: null,
        new_content: null,
        diff_patch: "This is completely invalid unified diff garbage with no @@ markers",
      },
    ];

    render(<DiffViewer runId="run_malformed_test" diffs={malformedDiffs} />);

    expect(screen.getAllByText("empty.txt").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("garbage.txt").length).toBeGreaterThanOrEqual(1);

    // Clicking between files in the sidebar does not throw
    const sidebarGarbage = screen.getAllByText("garbage.txt")[0];
    fireEvent.click(sidebarGarbage);
    expect(screen.getAllByText("garbage.txt").length).toBeGreaterThanOrEqual(1);
  });
});
