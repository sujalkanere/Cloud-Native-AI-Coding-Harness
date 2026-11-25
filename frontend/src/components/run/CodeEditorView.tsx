import React, { useState, useEffect, useRef } from "react";
import { Copy, Check, FileCode, Play, Eye, Code2, Save } from "lucide-react";

export interface CodeEditorViewProps {
  filename: string;
  content: string;
  language?: string;
  onRunFile?: (filename: string) => void;
  onSaveFile?: (filename: string, content: string) => Promise<void> | void;
  isRunning?: boolean;
}

function inferLanguage(filename: string, fallback?: string): string {
  const lower = filename.toLowerCase();
  if (lower.endsWith(".html") || lower.endsWith(".htm")) return "html";
  if (lower.endsWith(".py")) return "python";
  if (lower.endsWith(".rs")) return "rust";
  if (lower.endsWith(".ts") || lower.endsWith(".tsx")) return "typescript";
  if (lower.endsWith(".js") || lower.endsWith(".jsx")) return "javascript";
  if (lower.endsWith(".css")) return "css";
  if (lower.endsWith(".json")) return "json";
  if (lower.endsWith(".md")) return "markdown";
  return fallback || "text";
}

export const CodeEditorView: React.FC<CodeEditorViewProps> = ({
  filename,
  content,
  language,
  onRunFile,
  onSaveFile,
  isRunning = false,
}) => {
  const detectedLanguage = inferLanguage(filename, language);
  const isHtml = detectedLanguage === "html";

  const [copied, setCopied] = useState(false);
  const [viewMode, setViewMode] = useState<"code" | "preview">(isHtml ? "preview" : "code");
  const [draft, setDraft] = useState(content);
  const [isSaving, setIsSaving] = useState(false);
  const [savedNotice, setSavedNotice] = useState(false);
  const gutterRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setViewMode(isHtml ? "preview" : "code");
  }, [filename, isHtml]);

  useEffect(() => {
    setDraft(content);
  }, [filename, content]);

  const isLoaded = Boolean(draft && draft !== "# Loading file content...");
  const isDirty = isLoaded && draft !== content;

  const handleSave = async (nextContent = draft) => {
    if (!onSaveFile || !isLoaded || nextContent === content) return;
    try {
      setIsSaving(true);
      await onSaveFile(filename, nextContent);
      setSavedNotice(true);
      setTimeout(() => setSavedNotice(false), 1800);
    } finally {
      setIsSaving(false);
    }
  };

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(draft);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore
    }
  };

  const handleEditorScroll = () => {
    if (gutterRef.current && textareaRef.current) {
      gutterRef.current.scrollTop = textareaRef.current.scrollTop;
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
      e.preventDefault();
      handleSave();
      return;
    }

    if (e.key === "Tab") {
      e.preventDefault();
      const target = e.currentTarget;
      const start = target.selectionStart;
      const end = target.selectionEnd;
      const next = draft.slice(0, start) + "  " + draft.slice(end);
      setDraft(next);
      requestAnimationFrame(() => {
        target.selectionStart = target.selectionEnd = start + 2;
      });
    }
  };

  const lines = draft ? draft.split("\n") : [""];

  return (
    <div className="flex h-full flex-col bg-[#111113] font-mono text-xs select-text overflow-hidden">
      {/* Editor Breadcrumb & Actions */}
      <div className="flex items-center justify-between border-b border-white/[0.08] bg-[#161619] px-4 py-2">
        <div className="flex items-center gap-2 text-[#85858b]">
          <FileCode className="h-4 w-4 text-[#a1a1a6]" strokeWidth={1.5} />
          <span>workspace /</span>
          <span className="font-medium text-[#ededed]">{filename}</span>
          {isDirty && (
            <span
              className="h-2 w-2 rounded-full bg-[#2f81f7]"
              title="Unsaved changes"
            />
          )}
          <span className="rounded border border-white/[0.08] bg-[#0b0b0d] px-1.5 py-0.5 text-[11px] text-[#a1a1a6]">
            {detectedLanguage}
          </span>
          <span className="text-white/[0.12]">|</span>
          <span className="text-[11px] tabular-nums">{lines.length} lines</span>
        </div>

        <div className="flex items-center gap-2">
          {onSaveFile && (isDirty || savedNotice) && (
            <button
              type="button"
              onClick={() => handleSave()}
              disabled={isSaving || !isDirty}
              className="inline-flex h-7 items-center gap-1.5 rounded-lg border border-white/[0.08] bg-[#1e1e22] hover:bg-[#27272c] disabled:opacity-70 px-3 text-xs font-sans font-medium text-[#ededed] transition-colors"
              title="Save changes (Ctrl+S)"
            >
              {savedNotice ? (
                <>
                  <Check className="h-3 w-3 text-[#4cc38a]" strokeWidth={1.5} />
                  <span className="text-[#4cc38a]">Saved</span>
                </>
              ) : (
                <>
                  <Save className="h-3 w-3 text-[#2f81f7]" strokeWidth={1.5} />
                  <span>{isSaving ? "Saving..." : "Save"}</span>
                </>
              )}
            </button>
          )}

          {isHtml && (
            <div className="inline-flex rounded-lg border border-white/[0.08] bg-[#0b0b0d] p-0.5 font-sans">
              <button
                type="button"
                onClick={() => {
                  if (isDirty) handleSave();
                  setViewMode("preview");
                }}
                className={`inline-flex h-6 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium transition-colors ${
                  viewMode === "preview"
                    ? "bg-[#1e1e22] text-[#ededed]"
                    : "text-[#85858b] hover:text-[#ededed]"
                }`}
              >
                <Eye className="h-3 w-3" strokeWidth={1.5} />
                <span>Preview</span>
              </button>
              <button
                type="button"
                onClick={() => setViewMode("code")}
                className={`inline-flex h-6 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium transition-colors ${
                  viewMode === "code"
                    ? "bg-[#1e1e22] text-[#ededed]"
                    : "text-[#85858b] hover:text-[#ededed]"
                }`}
              >
                <Code2 className="h-3 w-3" strokeWidth={1.5} />
                <span>Code</span>
              </button>
            </div>
          )}

          {onRunFile && !isHtml && (
            <button
              onClick={async () => {
                if (isDirty) await handleSave();
                onRunFile(filename);
              }}
              disabled={isRunning}
              className="inline-flex h-7 items-center gap-1.5 rounded-lg bg-[#ededed] hover:bg-white disabled:opacity-50 px-3 text-xs font-sans font-medium text-[#0b0b0d] transition-colors"
              title={`Execute ${filename} in sandbox`}
            >
              <Play className="h-3 w-3 fill-current" strokeWidth={1.5} />
              <span>{isRunning ? "Running..." : "Run File"}</span>
            </button>
          )}

          <button
            onClick={handleCopy}
            className="inline-flex h-7 items-center gap-1.5 rounded-lg border border-white/[0.08] bg-[#1e1e22] hover:bg-[#27272c] px-3 text-xs font-sans text-[#ededed] transition-colors"
            title="Copy code"
          >
            {copied ? (
              <>
                <Check className="h-3 w-3 text-[#4cc38a]" strokeWidth={1.5} />
                <span className="text-[#4cc38a]">Copied</span>
              </>
            ) : (
              <>
                <Copy className="h-3 w-3 text-[#a1a1a6]" strokeWidth={1.5} />
                <span>Copy</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Rendered HTML Preview or Click-to-Edit Code Surface */}
      {isHtml && viewMode === "preview" ? (
        <div className="flex-1 overflow-hidden bg-[#0b0b0d] p-3">
          {isLoaded ? (
            <iframe
              title={`Preview of ${filename}`}
              srcDoc={draft}
              sandbox="allow-scripts allow-forms allow-modals"
              className="h-full w-full rounded-lg border border-white/[0.08] bg-white"
            />
          ) : (
            <div className="flex h-full items-center justify-center text-xs font-sans text-[#85858b]">
              Loading preview...
            </div>
          )}
        </div>
      ) : (
        <div className="flex flex-1 overflow-hidden">
          <div
            ref={gutterRef}
            aria-hidden="true"
            className="select-none overflow-hidden py-3 pr-4 pl-3 text-right text-[#52525b] font-mono text-[12px] leading-5 shrink-0 border-r border-white/[0.06] tabular-nums"
          >
            {lines.map((_, idx) => (
              <div key={idx} className="h-5">
                {idx + 1}
              </div>
            ))}
          </div>

          <textarea
            ref={textareaRef}
            aria-label={`Code editor for ${filename}`}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onScroll={handleEditorScroll}
            onKeyDown={handleKeyDown}
            onBlur={() => {
              if (isDirty) handleSave();
            }}
            spellCheck={false}
            autoCapitalize="off"
            autoComplete="off"
            autoCorrect="off"
            className="flex-1 resize-none bg-transparent py-3 px-4 font-mono text-[12px] leading-5 text-[#ededed] focus:outline-none whitespace-pre overflow-auto"
          />
        </div>
      )}
    </div>
  );
};
