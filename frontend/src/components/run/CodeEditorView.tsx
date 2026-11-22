import React, { useState } from "react";
import { Copy, Check, FileCode } from "lucide-react";

export interface CodeEditorViewProps {
  filename: string;
  content: string;
  language?: string;
}

export const CodeEditorView: React.FC<CodeEditorViewProps> = ({
  filename,
  content,
  language = "python",
}) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore
    }
  };

  const lines = content ? content.split("\n") : [""];

  // Simple token highlighter for high readability without bulky third-party libs
  const renderHighlightedLine = (line: string) => {
    if (!line) return <span>&nbsp;</span>;

    // Detect comment line
    if (line.trim().startsWith("#") || line.trim().startsWith("//")) {
      return <span className="text-emerald-400/80 italic">{line}</span>;
    }

    return (
      <span className="text-slate-200">
        {line}
      </span>
    );
  };

  return (
    <div className="flex h-full flex-col bg-[#0b0f19] font-mono text-xs select-text overflow-hidden">
      {/* Editor Tab Breadcrumb & Actions */}
      <div className="flex items-center justify-between border-b border-slate-800 bg-[#0d1424] px-4 py-2">
        <div className="flex items-center space-x-2 text-slate-400">
          <FileCode className="h-4 w-4 text-blue-400" />
          <span className="text-slate-500">workspace /</span>
          <span className="font-semibold text-slate-200">{filename}</span>
          <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-400">
            {language}
          </span>
          <span className="text-slate-600">|</span>
          <span className="text-[11px] text-slate-500">{lines.length} lines</span>
        </div>

        <button
          onClick={handleCopy}
          className="flex items-center space-x-1.5 rounded-full bg-slate-800 hover:bg-slate-700 px-3 py-1 text-[11px] text-slate-300 transition-colors"
          title="Copy code"
        >
          {copied ? (
            <>
              <Check className="h-3 w-3 text-emerald-400" />
              <span className="text-emerald-400 font-sans">Copied!</span>
            </>
          ) : (
            <>
              <Copy className="h-3 w-3" />
              <span className="font-sans">Copy</span>
            </>
          )}
        </button>
      </div>

      {/* Editor Gutter and Lines */}
      <div className="flex-1 overflow-auto p-2">
        <div className="flex min-w-full">
          {/* Line Numbers Gutter */}
          <div className="select-none pr-4 text-right text-slate-600 font-mono text-[12px] leading-5 shrink-0 border-r border-slate-800/80 mr-4">
            {lines.map((_, idx) => (
              <div key={idx} className="h-5">
                {idx + 1}
              </div>
            ))}
          </div>

          {/* Line Content */}
          <div className="flex-1 font-mono text-[12px] leading-5 whitespace-pre">
            {lines.map((line, idx) => (
              <div key={idx} className="h-5 hover:bg-slate-800/30">
                {renderHighlightedLine(line)}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
