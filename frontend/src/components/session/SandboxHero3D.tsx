import React, { useState, useRef } from "react";
import { Terminal, FileCode, ShieldCheck, Copy, Check } from "lucide-react";

type DemoTab = "sandbox" | "diff" | "pty";

const DEMO_TABS: { id: DemoTab; label: string; icon: React.ReactNode }[] = [
  { id: "sandbox", label: "exec", icon: <Terminal className="h-3.5 w-3.5" strokeWidth={1.5} /> },
  { id: "diff", label: "patch", icon: <FileCode className="h-3.5 w-3.5" strokeWidth={1.5} /> },
  { id: "pty", label: "pty", icon: <ShieldCheck className="h-3.5 w-3.5" strokeWidth={1.5} /> },
];

export function SandboxHero3D() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [tilt, setTilt] = useState({ x: 2.5, y: -4 });
  const [activeTab, setActiveTab] = useState<DemoTab>("sandbox");
  const [copiedCmd, setCopiedCmd] = useState(false);

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const nx = (e.clientX - rect.left) / rect.width - 0.5;
    const ny = (e.clientY - rect.top) / rect.height - 0.5;
    setTilt({
      x: Number((-ny * 8).toFixed(2)),
      y: Number((nx * 10).toFixed(2)),
    });
  };

  const handleMouseLeave = () => {
    setTilt({ x: 2.5, y: -4 });
  };

  const handleCopySpec = async () => {
    try {
      await navigator.clipboard.writeText(
        "docker run --read-only --network=none --cap-drop=ALL --user 1000:1000 harness-sandbox"
      );
      setCopiedCmd(true);
      setTimeout(() => setCopiedCmd(false), 1800);
    } catch {
      // ignore
    }
  };

  return (
    <div
      ref={containerRef}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      className="relative w-full py-4 select-none"
      style={{ perspective: "1200px" }}
    >
      <div
        className="relative transition-transform duration-300 ease-craft"
        style={{
          transformStyle: "preserve-3d",
          transform: `rotateX(${tilt.x}deg) rotateY(${tilt.y}deg)`,
        }}
      >
        {/* Backplane: Host Kernel Boundary */}
        <div
          aria-hidden="true"
          className="absolute -inset-3 rounded-2xl border border-white/[0.06] bg-[#0b0b0d]/80"
          style={{
            transform: "translateZ(-28px)",
            backgroundImage:
              "radial-gradient(rgba(237,237,237,0.06) 1px, transparent 1px)",
            backgroundSize: "16px 16px",
          }}
        >
          <div className="flex items-center justify-between px-4 py-2 text-[11px] font-mono text-[#85858b]">
            <span>host-boundary</span>
            <span>egress: blocked</span>
          </div>
        </div>

        {/* Main 3D Slab: Sandbox Container Console */}
        <div
          className="relative rounded-2xl border border-white/[0.1] bg-[#161619] shadow-[0_24px_60px_rgba(0,0,0,0.65)] overflow-hidden"
          style={{
            transform: "translateZ(0px)",
            boxShadow:
              "0 24px 60px rgba(0,0,0,0.65), inset 0 1px 0 rgba(255,255,255,0.08)",
          }}
        >
          {/* Window Chrome */}
          <div className="flex items-center justify-between border-b border-white/[0.08] bg-[#0b0b0d] px-4 py-3">
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-full bg-white/[0.12]" />
                <span className="h-2.5 w-2.5 rounded-full bg-white/[0.12]" />
                <span className="h-2.5 w-2.5 rounded-full bg-white/[0.12]" />
              </div>
              <span className="font-mono text-xs text-[#a1a1a6]">
                sandbox://run_3477d399
              </span>
            </div>

            <div className="flex items-center gap-2">
              <span className="inline-flex items-center gap-1.5 rounded-md bg-[#1e1e22] border border-white/[0.08] px-2 py-0.5 font-mono text-[11px] text-[#ededed]">
                <span className="h-1.5 w-1.5 rounded-full bg-[#4cc38a]" />
                uid 1000
              </span>
            </div>
          </div>

          {/* Interactive Scenario Tabs */}
          <div className="flex items-center justify-between border-b border-white/[0.08] bg-[#111113] px-3 py-2">
            <div className="flex items-center gap-1">
              {DEMO_TABS.map((tab) => {
                const isActive = activeTab === tab.id;
                return (
                  <button
                    key={tab.id}
                    type="button"
                    onClick={() => setActiveTab(tab.id)}
                    className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-mono transition-colors ${
                      isActive
                        ? "bg-[#1e1e22] text-[#ededed] border border-white/[0.08]"
                        : "text-[#85858b] hover:text-[#ededed] border border-transparent"
                    }`}
                  >
                    {tab.icon}
                    <span>{tab.label}</span>
                  </button>
                );
              })}
            </div>

            <button
              type="button"
              onClick={handleCopySpec}
              className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px] font-mono text-[#85858b] hover:text-[#ededed] transition-colors"
              title="Copy Docker isolation flags"
            >
              {copiedCmd ? (
                <>
                  <Check className="h-3 w-3 text-[#4cc38a]" strokeWidth={1.5} />
                  <span className="text-[#4cc38a]">Copied</span>
                </>
              ) : (
                <>
                  <Copy className="h-3 w-3" strokeWidth={1.5} />
                  <span>Copy flags</span>
                </>
              )}
            </button>
          </div>

          {/* Live Code / Terminal Viewport */}
          <div className="bg-[#0b0b0d] p-4 pb-12 sm:pr-12 font-mono text-xs leading-6 text-[#a1a1a6] min-h-[240px] tabular-nums">
            {activeTab === "sandbox" && (
              <div className="space-y-1.5">
                <div className="text-[#85858b]">
                  <span className="text-[#2f81f7]">sandbox@1000</span>:/workspace$ pytest -q
                </div>
                <div className="text-[#ededed]">............ [100%]</div>
                <div className="text-[#4cc38a]">12 passed in 0.42s</div>
                <div className="pt-2 text-[#85858b]">
                  <span className="text-[#2f81f7]">sandbox@1000</span>:/workspace$ id -un
                </div>
                <div className="text-[#ededed]">sandbox (uid=1000, rootfs=ro)</div>
                <div className="pt-2 text-[#85858b]">
                  <span className="text-[#2f81f7]">sandbox@1000</span>:/workspace$ git status -s
                </div>
                <div className="text-[#4cc38a]">A  guess_game.py</div>
              </div>
            )}

            {activeTab === "diff" && (
              <div className="space-y-1">
                <div className="text-[#85858b]">diff --git a/guess_game.py b/guess_game.py</div>
                <div className="text-[#85858b]">@@ -18,4 +18,7 @@ def get_int(prompt: str) -&gt; int:</div>
                <div className="text-[#a1a1a6]">     while True:</div>
                <div className="text-[#e5484d] bg-[#e5484d]/10 px-1 rounded">-        return int(input(prompt))</div>
                <div className="text-[#4cc38a] bg-[#4cc38a]/10 px-1 rounded">+        raw = input(prompt).strip()</div>
                <div className="text-[#4cc38a] bg-[#4cc38a]/10 px-1 rounded">+        if raw.isdigit():</div>
                <div className="text-[#4cc38a] bg-[#4cc38a]/10 px-1 rounded">+            return int(raw)</div>
                <div className="pt-2 text-[#85858b]">1 file changed, 3 insertions(+), 1 deletion(-)</div>
              </div>
            )}

            {activeTab === "pty" && (
              <div className="space-y-1.5">
                <div className="text-[#85858b]">
                  <span className="text-[#2f81f7]">sandbox@1000</span>:/workspace$ python3 guess_game.py
                </div>
                <div className="text-[#ededed]">You have 10 attempts to guess it.</div>
                <div className="text-[#ededed]">
                  Attempt 1: Your guess? <span className="text-[#ededed] bg-white/10 px-1 rounded">50</span>
                </div>
                <div className="text-[#a1a1a6]">Lower</div>
                <div className="text-[#ededed]">
                  Attempt 2: Your guess? <span className="text-[#ededed] bg-white/10 px-1 rounded">25</span>
                </div>
                <div className="text-[#4cc38a]">Correct in 2 attempts</div>
              </div>
            )}
          </div>
        </div>

        {/* Floating Z-Layer: Isolation Spec Card */}
        <div
          className="hidden sm:block sm:absolute -bottom-7 -right-4 w-56 rounded-xl border border-white/[0.12] bg-[#1e1e22] p-3.5 shadow-[0_16px_40px_rgba(0,0,0,0.7)]"
          style={{
            transform: "translateZ(32px)",
            boxShadow:
              "0 16px 40px rgba(0,0,0,0.7), inset 0 1px 0 rgba(255,255,255,0.1)",
          }}
        >
          <div className="flex items-center justify-between pb-2 mb-2 border-b border-white/[0.08]">
            <span className="text-xs font-medium text-[#ededed]">Container spec</span>
            <span className="font-mono text-[11px] text-[#4cc38a]">ro</span>
          </div>
          <div className="space-y-1.5 font-mono text-[11px] tabular-nums">
            <div className="flex items-center justify-between">
              <span className="text-[#85858b]">rootfs</span>
              <span className="text-[#ededed]">read-only</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[#85858b]">network</span>
              <span className="text-[#ededed]">isolated</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[#85858b]">cap-drop</span>
              <span className="text-[#ededed]">ALL</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[#85858b]">pty</span>
              <span className="text-[#2f81f7]">tty=true</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
