import React, { useState } from "react";
import { Copy, Check } from "lucide-react";

function renderInline(text: string): React.ReactNode[] {
  const tokens = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
  return tokens.map((token, idx) => {
    if (token.startsWith("`") && token.endsWith("`") && token.length >= 2) {
      return (
        <code
          key={idx}
          className="rounded border border-white/[0.08] bg-[#0b0b0d] px-1 py-0.5 font-mono text-[0.92em] text-[#ededed]"
        >
          {token.slice(1, -1)}
        </code>
      );
    }
    if (token.startsWith("**") && token.endsWith("**") && token.length >= 4) {
      return (
        <strong key={idx} className="font-semibold text-white">
          {token.slice(2, -2)}
        </strong>
      );
    }
    return <React.Fragment key={idx}>{token}</React.Fragment>;
  });
}

function CodeBlock({ code, lang }: { code: string; lang: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      // ignore
    }
  };

  return (
    <div className="my-2 rounded-lg border border-white/[0.08] bg-[#0b0b0d] overflow-hidden">
      <div className="flex items-center justify-between border-b border-white/[0.06] bg-[#161619] px-3 py-1 text-[10px] font-mono text-[#85858b]">
        <span>{lang || "code"}</span>
        <button
          type="button"
          onClick={handleCopy}
          className="inline-flex items-center gap-1 hover:text-[#ededed] transition-colors"
        >
          {copied ? (
            <>
              <Check className="h-3 w-3 text-[#4cc38a]" strokeWidth={1.5} />
              <span className="text-[#4cc38a]">Copied</span>
            </>
          ) : (
            <>
              <Copy className="h-3 w-3" strokeWidth={1.5} />
              <span>Copy</span>
            </>
          )}
        </button>
      </div>
      <pre className="overflow-x-auto p-2.5 font-mono text-[11px] leading-relaxed text-[#ededed]">
        <code>{code}</code>
      </pre>
    </div>
  );
}

const TABLE_DIVIDER_RE = new RegExp("^\\|?[:\\s|-]+\\|?$");
export interface SimpleMarkdownProps {
  content: string;
  className?: string;
}

export const SimpleMarkdown: React.FC<SimpleMarkdownProps> = ({
  content,
  className = "",
}) => {
  if (!content) return null;

  const segments = content.split(/(```[\s\S]*?```)/g);

  return (
    <div className={`space-y-1.5 break-words ${className}`}>
      {segments.map((seg, segIdx) => {
        if (seg.startsWith("```") && seg.endsWith("```")) {
          const lines = seg.slice(3, -3).split(/\r?\n/);
          const lang = lines[0]?.trim() || "";
          const code = lines.slice(1).join("\n").trim();
          return <CodeBlock key={segIdx} code={code} lang={lang} />;
        }

        const lines = seg.split(/\r?\n/);
        return (
          <div key={segIdx} className="space-y-1">
            {lines.map((rawLine, lineIdx) => {
              const line = rawLine.trim();
              if (!line || TABLE_DIVIDER_RE.test(line)) return null;

              if (line.startsWith("### ")) {
                return (
                  <h4 key={lineIdx} className="pt-1.5 text-xs font-semibold text-white">
                    {renderInline(line.slice(4))}
                  </h4>
                );
              }
              if (line.startsWith("## ")) {
                return (
                  <h3 key={lineIdx} className="pt-2 text-xs font-semibold text-white">
                    {renderInline(line.slice(3))}
                  </h3>
                );
              }
              if (line.startsWith("# ")) {
                return (
                  <h2 key={lineIdx} className="pt-2 text-sm font-semibold text-white">
                    {renderInline(line.slice(2))}
                  </h2>
                );
              }
              if (line.startsWith("- ") || line.startsWith("* ")) {
                return (
                  <div key={lineIdx} className="flex gap-2 pl-1 text-[#ededed]">
                    <span className="text-[#85858b] select-none">•</span>
                    <span className="flex-1">{renderInline(line.slice(2))}</span>
                  </div>
                );
              }
              if (/^\d+\.\s/.test(line)) {
                const match = line.match(/^(\d+\.)\s(.*)$/);
                if (match) {
                  return (
                    <div key={lineIdx} className="flex gap-2 pl-1 text-[#ededed]">
                      <span className="font-mono text-[#85858b] shrink-0">{match[1]}</span>
                      <span className="flex-1">{renderInline(match[2])}</span>
                    </div>
                  );
                }
              }

              return (
                <p key={lineIdx} className="text-[#ededed] leading-relaxed">
                  {renderInline(line)}
                </p>
              );
            })}
          </div>
        );
      })}
    </div>
  );
};
