import { useState, useEffect } from "react";
import { SessionManager } from "./components/session/SessionManager";
import { RunView } from "./components/run/RunView";

export function App() {
  const [selectedRunId, setSelectedRunId] = useState<string | null>(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      return params.get("runId");
    }
    return null;
  });

  const handleSelectRun = (runId: string) => {
    setSelectedRunId(runId);
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.searchParams.set("runId", runId);
      window.history.pushState({}, "", url.toString());
    }
  };

  const handleBackToSessions = () => {
    setSelectedRunId(null);
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.searchParams.delete("runId");
      window.history.pushState({}, "", url.toString());
    }
  };

  useEffect(() => {
    const handlePopState = () => {
      const params = new URLSearchParams(window.location.search);
      setSelectedRunId(params.get("runId"));
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  if (selectedRunId) {
    return <RunView runId={selectedRunId} onBack={handleBackToSessions} />;
  }

  return <SessionManager onSelectRun={handleSelectRun} />;
}

export default App;
