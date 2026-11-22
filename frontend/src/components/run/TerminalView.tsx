import { useEffect, useRef } from "react";
import { Terminal as XTerm } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { Terminal as TerminalIcon, AlertTriangle } from "lucide-react";
import type { TerminalChunk } from "../../types/run";
import { Badge } from "../ui/badge";

export interface TerminalViewProps {
  chunks: TerminalChunk[];
  isTruncated?: boolean;
  truncationMessage?: string | null;
}

export function TerminalView({
  chunks,
  isTruncated = false,
  truncationMessage,
}: TerminalViewProps) {
  const terminalRef = useRef<HTMLDivElement>(null);
  const xtermInstance = useRef<XTerm | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  const renderedSeqWatermark = useRef<number>(0);
  const isTruncationPrinted = useRef<boolean>(false);

  // Initialize xterm
  useEffect(() => {
    if (!terminalRef.current) return;

    const term = new XTerm({
      cursorBlink: true,
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
      fontSize: 12,
      theme: {
        background: "#090d16",
        foreground: "#e2e8f0",
        cursor: "#38bdf8",
        selectionBackground: "#1e3a8a",
        black: "#0f172a",
        red: "#f87171",
        green: "#4ade80",
        yellow: "#facc15",
        blue: "#60a5fa",
        magenta: "#c084fc",
        cyan: "#38bdf8",
        white: "#f8fafc",
      },
      convertEol: true,
      scrollback: 5000,
      disableStdin: true,
    });

    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);

    term.open(terminalRef.current);
    xtermInstance.current = term;
    fitAddonRef.current = fitAddon;

    // Initial safe fit
    const safeFit = () => {
      try {
        if (
          terminalRef.current &&
          terminalRef.current.clientWidth > 0 &&
          terminalRef.current.clientHeight > 0
        ) {
          fitAddon.fit();
        }
      } catch {
        // ignore fit failures during early rendering
      }
    };

    requestAnimationFrame(safeFit);

    // ResizeObserver for automatic layout fitting
    let resizeObserver: ResizeObserver | null = null;
    if (typeof ResizeObserver !== "undefined") {
      resizeObserver = new ResizeObserver(() => {
        requestAnimationFrame(safeFit);
      });
      resizeObserver.observe(terminalRef.current);
    }

    return () => {
      resizeObserver?.disconnect();
      term.dispose();
      xtermInstance.current = null;
      fitAddonRef.current = null;
      renderedSeqWatermark.current = 0;
      isTruncationPrinted.current = false;
    };
  }, []);

  // Stream new chunks to xterm
  useEffect(() => {
    const term = xtermInstance.current;
    if (!term) return;

    // Filter chunks with seq > renderedSeqWatermark
    const newChunks = chunks.filter((c) => c.seq > renderedSeqWatermark.current);

    if (newChunks.length > 0) {
      for (const chunk of newChunks) {
        if (chunk.stream === "stderr") {
          // Format stderr with ANSI yellow/red
          term.write(`\x1b[33m${chunk.data}\x1b[0m`);
        } else {
          term.write(chunk.data);
        }
        renderedSeqWatermark.current = Math.max(
          renderedSeqWatermark.current,
          chunk.seq
        );
      }
    }
  }, [chunks]);

  // Handle truncation banner
  useEffect(() => {
    const term = xtermInstance.current;
    if (!term) return;

    if (isTruncated && !isTruncationPrinted.current) {
      isTruncationPrinted.current = true;
      const msg =
        truncationMessage ||
        "Run output exceeded limit of 5242880 bytes; terminal output truncated.";
      term.write(
        `\r\n\x1b[41;37;1m [TERMINAL OUTPUT TRUNCATED] \x1b[0m \x1b[31m${msg}\x1b[0m\r\n`
      );
    }
  }, [isTruncated, truncationMessage]);

  return (
    <div className="flex flex-col h-full bg-[#090d16]">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-800 bg-slate-900/70 px-4 py-2">
        <div className="flex items-center space-x-2">
          <TerminalIcon className="h-4 w-4 text-emerald-400" />
          <span className="text-xs font-semibold text-white">Execution Console</span>
        </div>

        <div className="flex items-center space-x-2">
          {isTruncated && (
            <Badge variant="destructive" className="text-[10px] bg-rose-950 text-rose-300 border-rose-800">
              <AlertTriangle className="mr-1 h-3 w-3" />
              Output Capped (5MB)
            </Badge>
          )}
          <span className="text-[10px] text-slate-500 font-mono">
            {chunks.length} chunks
          </span>
        </div>
      </div>

      {/* Terminal Container */}
      <div
        ref={terminalRef}
        className="flex-1 w-full overflow-hidden p-1"
        style={{ minHeight: "150px" }}
      />
    </div>
  );
}
