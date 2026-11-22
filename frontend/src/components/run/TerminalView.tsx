import { useEffect, useRef, useState } from "react";
import { Terminal as XTerm } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { Terminal as TerminalIcon, AlertTriangle, CornerDownLeft } from "lucide-react";
import type { TerminalChunk } from "../../types/run";
import { Badge } from "../ui/badge";

export interface TerminalViewProps {
  runId?: string;
  chunks: TerminalChunk[];
  isTruncated?: boolean;
  truncationMessage?: string | null;
  onExecuteCommand?: (command: string) => Promise<void> | void;
}

export function TerminalView({
  runId,
  chunks,
  isTruncated = false,
  truncationMessage,
  onExecuteCommand,
}: TerminalViewProps) {
  const [commandInput, setCommandInput] = useState("");
  const terminalRef = useRef<HTMLDivElement>(null);
  const xtermInstance = useRef<XTerm | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  const renderedSeqWatermark = useRef<number>(0);
  const isTruncationPrinted = useRef<boolean>(false);
  const onExecuteRef = useRef(onExecuteCommand);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    onExecuteRef.current = onExecuteCommand;
  }, [onExecuteCommand]);

  // Connect to interactive PTY WebSocket for real bidirectional terminal session
  useEffect(() => {
    if (!runId) return;

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.hostname || "127.0.0.1";
    const wsUrl = `${protocol}//${host}:8000/api/runs/${runId}/terminal`;

    let ws: WebSocket | null = null;
    try {
      ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onmessage = (event) => {
        if (xtermInstance.current && typeof event.data === "string") {
          xtermInstance.current.write(event.data);
        }
      };

      ws.onerror = (err) => {
        console.debug("Terminal WebSocket connection error:", err);
      };
    } catch {
      // Fallback
    }

    // Listen for custom trigger to execute commands in terminal
    const handleCommandTrigger = (e: Event) => {
      const customEvent = e as CustomEvent<{ command: string }>;
      const cmd = customEvent.detail?.command;
      if (cmd && ws && ws.readyState === WebSocket.OPEN) {
        ws.send(cmd + "\r");
      }
    };
    window.addEventListener("execute-terminal-command", handleCommandTrigger);

    return () => {
      window.removeEventListener("execute-terminal-command", handleCommandTrigger);
      if (ws) {
        ws.close();
      }
      wsRef.current = null;
    };
  }, [runId]);

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
      disableStdin: false,
    });

    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);

    term.open(terminalRef.current);
    xtermInstance.current = term;
    fitAddonRef.current = fitAddon;

    // Interactive keystroke handler directly inside xterm canvas
    let currentLine = "";
    const onDataDisposable = term.onData((data) => {
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(data);
        return;
      }
      // Enter key (\r or \n)
      if (data === "\r" || data === "\n") {
        term.write("\r\n");
        const toExec = currentLine.trim();
        currentLine = "";
        if (toExec && onExecuteRef.current) {
          onExecuteRef.current(toExec);
        } else {
          term.write("\x1b[1;36m$ \x1b[0m");
        }
      }
      // Backspace (\x7f or \b)
      else if (data === "\x7f" || data === "\b") {
        if (currentLine.length > 0) {
          currentLine = currentLine.slice(0, -1);
          term.write("\b \b");
        }
      }
      // Ctrl+C (\x03)
      else if (data === "\x03") {
        currentLine = "";
        term.write("^C\r\n\x1b[1;36m$ \x1b[0m");
      }
      // Printable characters
      else if (data >= " ") {
        currentLine += data;
        term.write(data);
      }
    });

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
      onDataDisposable.dispose();
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

      {/* Interactive Command Input Bar */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const cmd = commandInput.trim();
          if (!cmd) return;
          if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
            wsRef.current.send(cmd + "\r");
            setCommandInput("");
          } else if (onExecuteCommand) {
            onExecuteCommand(cmd);
            setCommandInput("");
          }
        }}
        className="flex items-center border-t border-slate-800 bg-[#0d1424] px-3 py-1.5 space-x-2"
      >
        <div className="flex items-center space-x-1.5 font-mono text-xs text-blue-400 shrink-0 font-bold select-none">
          <span>$</span>
        </div>
        <input
          type="text"
          value={commandInput}
          onChange={(e) => setCommandInput(e.target.value)}
          placeholder="Type command or input (e.g. python hangman.py, pytest, a, b)..."
          className="flex-1 bg-transparent text-xs font-mono text-slate-100 placeholder:text-slate-600 focus:outline-none"
        />
        <button
          type="submit"
          disabled={!commandInput.trim()}
          className="rounded-full bg-blue-600 hover:bg-blue-500 disabled:opacity-40 px-3 py-1 text-[11px] font-bold text-white transition-colors flex items-center space-x-1 shrink-0"
        >
          <span>Send</span>
          <CornerDownLeft className="h-3 w-3" />
        </button>
      </form>
    </div>
  );
}
