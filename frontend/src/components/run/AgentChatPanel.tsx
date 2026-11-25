import React, { useState, useRef, useEffect } from "react";
import {
  Sparkles,
  ArrowUp,
  ChevronDown,
  X,
  Palette,
  FlaskConical,
  Layers,
  ShieldCheck,
  Bug,
  Trash2,
  Paperclip,
  Loader2,
} from "lucide-react";
import type { Run, RunStatus } from "../../types/run";
import { api } from "../../services/api";
import { SimpleMarkdown } from "../ui/SimpleMarkdown";

export interface SlashAgentCommand {
  command: string;
  agent: string;
  label: string;
  description: string;
  icon: React.ReactNode;
}

export const SLASH_COMMANDS: SlashAgentCommand[] = [
  {
    command: "/designer",
    agent: "designer",
    label: "Designer",
    description: "Audit layout, typography, spacing, and UI craft",
    icon: <Palette className="h-3.5 w-3.5 text-[#a1a1a6]" strokeWidth={1.5} />,
  },
  {
    command: "/tester",
    agent: "tester",
    label: "Tester",
    description: "Generate pytest / vitest suites and edge-case checks",
    icon: <FlaskConical className="h-3.5 w-3.5 text-[#a1a1a6]" strokeWidth={1.5} />,
  },
  {
    command: "/architect",
    agent: "architect",
    label: "Architect",
    description: "Design module boundaries, APIs, and clean refactors",
    icon: <Layers className="h-3.5 w-3.5 text-[#a1a1a6]" strokeWidth={1.5} />,
  },
  {
    command: "/reviewer",
    agent: "reviewer",
    label: "Reviewer",
    description: "Inspect code for security, correctness, and regressions",
    icon: <ShieldCheck className="h-3.5 w-3.5 text-[#a1a1a6]" strokeWidth={1.5} />,
  },
  {
    command: "/debugger",
    agent: "debugger",
    label: "Debugger",
    description: "Diagnose stack traces and propose minimal fixes",
    icon: <Bug className="h-3.5 w-3.5 text-[#a1a1a6]" strokeWidth={1.5} />,
  },
  {
    command: "/clear",
    agent: "clear",
    label: "Clear chat",
    description: "Reset conversation messages in this panel",
    icon: <Trash2 className="h-3.5 w-3.5 text-[#a1a1a6]" strokeWidth={1.5} />,
  },
];

export const AVAILABLE_MODELS = [
  { id: "openai/gpt-oss-120b", label: "GPT-OSS 120B", provider: "GROQ" },
  { id: "llama-3.3-70b-versatile", label: "Llama 3.3 70B", provider: "GROQ" },
  { id: "qwen-qwq-32b", label: "Qwen QwQ 32B", provider: "GROQ" },
  { id: "deepseek-r1-distill-llama-70b", label: "DeepSeek R1 70B", provider: "GROQ" },
  { id: "gpt-4o", label: "GPT-4o", provider: "APINEX" },
  { id: "claude-3.5-sonnet", label: "Claude 3.5 Sonnet", provider: "APINEX" },
];

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  agent?: string;
  model?: string;
  ts: string;
}

export interface AgentChatPanelProps {
  runId: string;
  run: Run | null;
  status: RunStatus;
  fileContents: Record<string, string>;
  onClose?: () => void;
}

export const AgentChatPanel: React.FC<AgentChatPanelProps> = ({
  runId,
  run,
  status,
  fileContents,
  onClose,
}) => {
  const isTerminal = ["SUCCEEDED", "FAILED", "TERMINATED"].includes(status);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [selectedModel, setSelectedModel] = useState(AVAILABLE_MODELS[0].id);
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const [activeAgent, setActiveAgent] = useState<SlashAgentCommand | null>(null);
  const [chatMode, setChatMode] = useState<"chat" | "steer">("chat");
  const [includeContext, setIncludeContext] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [slashIndex, setSlashIndex] = useState(0);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setMessages([]);
  }, [runId]);

  useEffect(() => {
    if (isTerminal && chatMode === "steer") {
      setChatMode("chat");
    }
  }, [isTerminal, chatMode]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isSending]);

  const showSlashMenu = input.startsWith("/") && !input.includes(" ");
  const slashQuery = showSlashMenu ? input.slice(1).toLowerCase() : "";
  const filteredCommands = SLASH_COMMANDS.filter(
    (c) =>
      c.command.slice(1).includes(slashQuery) ||
      c.label.toLowerCase().includes(slashQuery)
  );

  useEffect(() => {
    setSlashIndex(0);
  }, [slashQuery]);

  const selectSlashCommand = (cmd: SlashAgentCommand) => {
    if (cmd.agent === "clear") {
      setMessages([]);
      setInput("");
      setActiveAgent(null);
      return;
    }
    setActiveAgent(cmd);
    setInput("");
    textareaRef.current?.focus();
  };

  const handleSend = async () => {
    const trimmed = input.trim();
    if (!trimmed || isSending) return;

    // Check inline slash command like "/designer review this"
    let chosenAgent = activeAgent?.agent;
    let cleanText = trimmed;
    if (trimmed.startsWith("/")) {
      const [firstWord, ...rest] = trimmed.split(/\s+/);
      const matched = SLASH_COMMANDS.find((c) => c.command === firstWord.toLowerCase());
      if (matched) {
        if (matched.agent === "clear") {
          setMessages([]);
          setInput("");
          return;
        }
        chosenAgent = matched.agent;
        cleanText = rest.join(" ").trim() || `Run ${matched.label} analysis on this workspace.`;
      }
    }

    const userMsg: ChatMessage = {
      id: `u_${Date.now()}`,
      role: "user",
      content: cleanText,
      agent: chosenAgent,
      ts: new Date().toLocaleTimeString(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setIsSending(true);

    try {
      if (chatMode === "steer" && !isTerminal) {
        await api.injectGuidance(runId, cleanText);
        setMessages((prev) => [
          ...prev,
          {
            id: `s_${Date.now()}`,
            role: "system",
            content: "Steering guidance injected into active sandbox loop.",
            ts: new Date().toLocaleTimeString(),
          },
        ]);
      } else {
        const filesPayload = includeContext
          ? Object.entries(fileContents)
              .filter(([, content]) => content && content !== "# Loading file content...")
              .map(([path, content]) => ({ path, content }))
          : [];

        const historyPayload = messages
          .filter((m) => m.role === "user" || m.role === "assistant")
          .map((m) => ({ role: m.role, content: m.content }));

        const res = await api.chatWithAgent(runId, {
          message: cleanText,
          model: selectedModel,
          agent: chosenAgent,
          files: filesPayload,
          history: historyPayload,
        });

        setMessages((prev) => [
          ...prev,
          {
            id: `a_${Date.now()}`,
            role: "assistant",
            content: res.reply,
            agent: res.agent,
            model: res.model,
            ts: new Date().toLocaleTimeString(),
          },
        ]);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to reach agent";
      setMessages((prev) => [
        ...prev,
        {
          id: `e_${Date.now()}`,
          role: "system",
          content: msg,
          ts: new Date().toLocaleTimeString(),
        },
      ]);
    } finally {
      setIsSending(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (showSlashMenu && filteredCommands.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSlashIndex((i) => (i + 1) % filteredCommands.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSlashIndex((i) => (i - 1 + filteredCommands.length) % filteredCommands.length);
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        selectSlashCommand(filteredCommands[slashIndex]);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setInput("");
        return;
      }
    }

    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const currentModelObj =
    AVAILABLE_MODELS.find((m) => m.id === selectedModel) || AVAILABLE_MODELS[0];
  const contextFileCount = Object.keys(fileContents).length;

  return (
    <aside className="flex h-full w-80 xl:w-96 shrink-0 flex-col border-l border-white/[0.08] bg-[#161619] select-none">
      {/* Chat Header */}
      <div className="flex h-9 items-center justify-between border-b border-white/[0.08] px-3.5 text-xs">
        <div className="flex items-center gap-2">
          <Sparkles className="h-3.5 w-3.5 text-[#2f81f7]" strokeWidth={1.5} />
          <span className="font-medium text-[#ededed]">Agent</span>
          {activeAgent && (
            <span className="inline-flex items-center gap-1 rounded bg-[#1e1e22] border border-white/[0.08] px-1.5 py-0.5 font-mono text-[10px] text-[#ededed]">
              /{activeAgent.agent}
            </span>
          )}
        </div>

        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setMessages([])}
            className="rounded p-1 text-[#85858b] hover:bg-[#1e1e22] hover:text-[#ededed] transition-colors"
            title="Clear chat"
          >
            <Trash2 className="h-3.5 w-3.5" strokeWidth={1.5} />
          </button>
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="rounded p-1 text-[#85858b] hover:bg-[#1e1e22] hover:text-[#ededed] transition-colors"
              title="Close agent panel"
            >
              <X className="h-3.5 w-3.5" strokeWidth={1.5} />
            </button>
          )}
        </div>
      </div>

      {/* Messages Viewport */}
      <div className="flex-1 overflow-y-auto p-3.5 space-y-3 select-text bg-[#111113]">
        {/* Initial Run Context Card */}
        {run?.task && (
          <div className="rounded-xl border border-white/[0.08] bg-[#161619] p-3 space-y-1.5">
            <div className="flex items-center justify-between text-[11px] font-mono text-[#85858b]">
              <span>run objective</span>
              <span>{status}</span>
            </div>
            <p className="text-xs text-[#ededed] leading-relaxed">{run.task}</p>
          </div>
        )}

        {messages.length === 0 && (
          <div className="rounded-xl border border-dashed border-white/[0.08] p-4 space-y-2.5 text-xs text-[#a1a1a6]">
            <p className="text-[#ededed] font-medium">
              Ask a question or invoke an agent with <span className="font-mono text-[#2f81f7]">/</span>
            </p>
            <div className="flex flex-wrap gap-1.5">
              {SLASH_COMMANDS.slice(0, 5).map((cmd) => (
                <button
                  key={cmd.command}
                  type="button"
                  onClick={() => selectSlashCommand(cmd)}
                  className="inline-flex items-center gap-1.5 rounded-md border border-white/[0.08] bg-[#161619] hover:bg-[#1e1e22] px-2 py-1 font-mono text-[11px] text-[#a1a1a6] hover:text-[#ededed] transition-colors"
                >
                  {cmd.icon}
                  <span>{cmd.command}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`rounded-xl px-3.5 py-2.5 text-xs leading-relaxed ${
              msg.role === "user"
                ? "ml-6 border border-white/[0.08] bg-[#1e1e22] text-[#ededed]"
                : msg.role === "system"
                  ? "border border-[#2f81f7]/30 bg-[#2f81f7]/10 text-[#a1a1a6] font-mono text-[11px]"
                  : "mr-2 border border-white/[0.06] bg-[#161619] text-[#ededed]"
            }`}
          >
            <div className="flex items-center justify-between gap-2 mb-1 text-[10px] font-mono text-[#85858b]">
              <span>
                {msg.role === "user"
                  ? msg.agent
                    ? `you -> /${msg.agent}`
                    : "you"
                  : msg.role === "system"
                    ? "system"
                    : `${msg.agent || "assistant"} · ${msg.model || selectedModel}`}
              </span>
              <span>{msg.ts}</span>
            </div>
            {msg.role === "assistant" ? (
              <SimpleMarkdown content={msg.content} className="text-xs" />
            ) : (
              <div className="whitespace-pre-wrap break-words">{msg.content}</div>
            )}
          </div>
        ))}

        {isSending && (
          <div className="flex items-center gap-2 px-2 py-1 text-xs text-[#85858b] font-mono">
            <Loader2 className="h-3.5 w-3.5 animate-spin text-[#2f81f7]" strokeWidth={1.5} />
            <span>{currentModelObj.label} thinking...</span>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Antigravity-style Composer */}
      <div className="relative border-t border-white/[0.08] bg-[#161619] p-3">
        {/* Slash Command Palette */}
        {showSlashMenu && filteredCommands.length > 0 && (
          <div className="absolute bottom-full left-3 right-3 mb-2 rounded-xl border border-white/[0.1] bg-[#1e1e22] p-1.5 shadow-[0_16px_40px_rgba(0,0,0,0.65)] z-30">
            <div className="px-2 py-1 text-[10px] font-mono text-[#85858b]">
              Slash commands
            </div>
            {filteredCommands.map((cmd, idx) => (
              <button
                key={cmd.command}
                type="button"
                onClick={() => selectSlashCommand(cmd)}
                className={`flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-left text-xs transition-colors ${
                  idx === slashIndex
                    ? "bg-[#2f81f7]/15 text-[#ededed]"
                    : "text-[#a1a1a6] hover:bg-white/[0.04] hover:text-[#ededed]"
                }`}
              >
                <div className="flex items-center gap-2.5 truncate">
                  {cmd.icon}
                  <div className="truncate">
                    <div className="font-mono font-medium text-[#ededed]">
                      {cmd.command}
                    </div>
                    <div className="text-[11px] text-[#85858b] truncate">
                      {cmd.description}
                    </div>
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}

        <div className="rounded-xl border border-white/[0.08] bg-[#0b0b0d] focus-within:border-[#2f81f7] transition-colors">
          {/* Active Agent / Context Chips */}
          {(activeAgent || includeContext) && (
            <div className="flex flex-wrap items-center gap-1.5 px-3 pt-2.5">
              {activeAgent && (
                <span className="inline-flex items-center gap-1 rounded-md border border-[#2f81f7]/40 bg-[#2f81f7]/10 px-2 py-0.5 font-mono text-[11px] text-[#ededed]">
                  <span>@{activeAgent.agent}</span>
                  <button
                    type="button"
                    onClick={() => setActiveAgent(null)}
                    className="text-[#a1a1a6] hover:text-white"
                  >
                    <X className="h-3 w-3" strokeWidth={1.5} />
                  </button>
                </span>
              )}
              <button
                type="button"
                onClick={() => setIncludeContext((v) => !v)}
                className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 font-mono text-[11px] transition-colors ${
                  includeContext
                    ? "border-white/[0.08] bg-[#161619] text-[#a1a1a6]"
                    : "border-transparent text-[#85858b] hover:text-[#a1a1a6]"
                }`}
                title="Toggle workspace file context"
              >
                <Paperclip className="h-3 w-3" strokeWidth={1.5} />
                <span>{includeContext ? `${contextFileCount} files` : "No context"}</span>
              </button>
            </div>
          )}

          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={2}
            placeholder="Ask anything, or type / for agents (/designer, /tester)..."
            className="w-full resize-none bg-transparent px-3 py-2.5 text-xs text-[#ededed] placeholder:text-[#85858b] focus:outline-none"
          />

          {/* Bottom Composer Toolbar: Model Picker, Mode, Send */}
          <div className="flex items-center justify-between border-t border-white/[0.06] px-2.5 py-1.5">
            <div className="flex items-center gap-1.5">
              {/* Model Selector */}
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setModelMenuOpen((o) => !o)}
                  className="inline-flex h-6 items-center gap-1 rounded-md border border-white/[0.08] bg-[#161619] hover:bg-[#1e1e22] px-2 text-[11px] font-mono text-[#a1a1a6] hover:text-[#ededed] transition-colors"
                >
                  <span className="max-w-[118px] truncate">{currentModelObj.label}</span>
                  <ChevronDown className="h-3 w-3 shrink-0" strokeWidth={1.5} />
                </button>

                {modelMenuOpen && (
                  <div className="absolute bottom-full left-0 mb-1.5 w-56 rounded-xl border border-white/[0.1] bg-[#1e1e22] p-1 shadow-[0_16px_40px_rgba(0,0,0,0.65)] z-30">
                    {AVAILABLE_MODELS.map((m) => (
                      <button
                        key={m.id}
                        type="button"
                        onClick={() => {
                          setSelectedModel(m.id);
                          setModelMenuOpen(false);
                        }}
                        className={`flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-left text-xs transition-colors ${
                          m.id === selectedModel
                            ? "bg-[#2f81f7]/15 text-[#ededed]"
                            : "text-[#a1a1a6] hover:bg-white/[0.04] hover:text-[#ededed]"
                        }`}
                      >
                        <span className="truncate font-medium">{m.label}</span>
                        <span className="font-mono text-[10px] text-[#85858b]">{m.provider}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {/* Chat vs Steer Mode */}
              {!isTerminal && (
                <button
                  type="button"
                  onClick={() => setChatMode((m) => (m === "chat" ? "steer" : "chat"))}
                  className={`h-6 rounded-md border px-2 text-[11px] font-mono transition-colors ${
                    chatMode === "steer"
                      ? "border-[#2f81f7]/40 bg-[#2f81f7]/15 text-[#ededed]"
                      : "border-white/[0.08] bg-[#161619] text-[#85858b] hover:text-[#ededed]"
                  }`}
                  title="Switch between direct Agent Chat and live loop Steering"
                >
                  {chatMode === "steer" ? "Steer" : "Chat"}
                </button>
              )}
            </div>

            <button
              type="button"
              onClick={handleSend}
              disabled={!input.trim() || isSending}
              className="flex h-6 w-6 items-center justify-center rounded-md bg-[#ededed] hover:bg-white disabled:opacity-40 text-[#0b0b0d] transition-colors"
              title="Send (Enter)"
            >
              <ArrowUp className="h-3.5 w-3.5" strokeWidth={1.75} />
            </button>
          </div>
        </div>
      </div>
    </aside>
  );
};
