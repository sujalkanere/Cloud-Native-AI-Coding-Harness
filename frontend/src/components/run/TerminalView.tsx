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
    const host = window.location.host || `${window.location.hostname || "127.0.0.1"}:8000`;
    const wsUrl = `${protocol}//${host}/api/runs/${runId}/terminal`;

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
      if (!cmd) return;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(cmd + "\r");
      } else if (onExecuteRef.current) {
        onExecuteRef.current(cmd);
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
      fontFamily: '"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
      fontSize: 12,
      theme: {
        background: "#0b0b0d",
        foreground: "#ededed",
        cursor: "#2f81f7",
        selectionBackground: "rgba(47, 129, 247, 0.28)",
        black: "#161619",
        red: "#e5484d",
        green: "#4cc38a",
        yellow: "#d29922",
        blue: "#2f81f7",
        magenta: "#a1a1a6",
        cyan: "#2f81f7",
        white: "#ededed",
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
    <div className="flex flex-col h-full bg-[#0b0b0d]">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-white/[0.08] bg-[#161619] px-4 py-1.5">
        <div className="flex items-center gap-2">
          <TerminalIcon className="h-3.5 w-3.5 text-[#a1a1a6]" strokeWidth={1.5} />
          <span className="text-xs font-medium text-[#ededed]">Execution console</span>
        </div>

        <div className="flex items-center gap-2">
          {isTruncated && (
            <Badge variant="destructive" className="text-[11px] bg-[#e5484d]/10 text-[#e5484d] border-[#e5484d]/40">
              <AlertTriangle className="mr-1 h-3 w-3" strokeWidth={1.5} />
              Output Capped (5MB)
            </Badge>
          )}
          <span className="text-[11px] text-[#85858b] font-mono tabular-nums">
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
        className="flex items-center border-t border-white/[0.08] bg-[#161619] px-3 py-1.5 gap-2"
      >
        <div className="flex items-center font-mono text-xs text-[#2f81f7] shrink-0 font-medium select-none">
          <span>$</span>
        </div>
        <input
          type="text"
          value={commandInput}
          onChange={(e) => setCommandInput(e.target.value)}
          placeholder="Type command or input (e.g. python hangman.py, pytest)..."
          className="flex-1 bg-transparent text-xs font-mono text-[#ededed] placeholder:text-[#85858b] focus:outline-none"
        />
        <button
          type="submit"
          disabled={!commandInput.trim()}
          className="rounded-lg bg-[#ededed] hover:bg-white disabled:opacity-40 px-3 py-1 text-xs font-medium text-[#0b0b0d] transition-colors flex items-center gap-1 shrink-0"
        >
          <span>Send</span>
          <CornerDownLeft className="h-3 w-3" strokeWidth={1.5} />
        </button>
      </form>
    </div>
  );
}
