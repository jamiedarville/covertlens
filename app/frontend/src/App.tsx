import { useEffect, useState } from "react";
import Landing from "./pages/Landing";
import Analyze from "./pages/Analyze";
import { fetchVersionLine } from "./api";

function usePath(): [string, (to: string) => void] {
  const [path, setPath] = useState(window.location.pathname);
  useEffect(() => {
    const onPop = () => setPath(window.location.pathname);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const navigate = (to: string) => {
    if (to !== window.location.pathname) {
      window.history.pushState(null, "", to);
    }
    setPath(to);
    window.scrollTo(0, 0);
  };
  return [path, navigate];
}

export default function App() {
  const [path, navigate] = usePath();
  const [versionLine, setVersionLine] = useState<string | null>(null);
  const isAnalyze = path === "/analyze";

  useEffect(() => {
    document.title = isAnalyze ? "Analyze — CovertLens" : "CovertLens";
  }, [isAnalyze]);

  useEffect(() => {
    let cancelled = false;
    fetchVersionLine().then((line) => {
      if (!cancelled) setVersionLine(line);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const go = (to: string) => (e: React.MouseEvent) => {
    e.preventDefault();
    navigate(to);
  };

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="site-header">
        <a className="wordmark" href="/" onClick={go("/")}>
          CovertLens
        </a>
        <nav aria-label="Primary">
          <a href="/analyze" onClick={go("/analyze")} aria-current={isAnalyze ? "page" : undefined}>
            Analyze
          </a>
          <a href="/docs">API docs</a>
        </nav>
      </header>
      <main id="main" className="page">
        {isAnalyze ? <Analyze /> : <Landing navigate={navigate} />}
      </main>
      <footer className="site-footer">
        <p>
          Scores are evidence, never accusations. A withheld image is
          recorded as not observed, never as a successful hidden transfer.
        </p>
        <p>
          {versionLine ? `${versionLine} · ` : ""}
          <a href="/docs">OpenAPI</a> · <a href="/api/scorecard">Release scorecard</a>
        </p>
      </footer>
    </>
  );
}
