import { useEffect, useState } from "react";
import Landing from "./pages/Landing";
import Analyze from "./pages/Analyze";
import Generate from "./pages/Generate";
import LiveGate from "./pages/LiveGate";
import Benchmarks from "./pages/Benchmarks";
import Scorecard from "./pages/Scorecard";
import { fetchVersionLine } from "./api";

function usePath(): [string, (to: string) => void] {
  const [path, setPath] = useState(window.location.pathname);
  useEffect(() => {
    const onPop = () => setPath(window.location.pathname);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const navigate = (to: string) => {
    window.history.pushState(null, "", to);
    setPath(window.location.pathname);
    window.scrollTo(0, 0);
  };
  return [path, navigate];
}

export default function App() {
  const [path, navigate] = usePath();
  const [versionLine, setVersionLine] = useState<string | null>(null);
  const page =
    path === "/analyze"
      ? "analyze"
      : path === "/generate"
        ? "generate"
        : path === "/gate"
          ? "gate"
          : path === "/benchmarks"
            ? "benchmarks"
            : path === "/scorecard"
              ? "scorecard"
              : "landing";

  useEffect(() => {
    document.title =
      page === "analyze"
        ? "Analyze — CovertLens"
        : page === "generate"
          ? "Generate — CovertLens"
          : page === "gate"
            ? "Live Gate — CovertLens"
            : page === "benchmarks"
              ? "Benchmarks — CovertLens"
              : page === "scorecard"
                ? "Scorecard — CovertLens"
                : "CovertLens";
  }, [page]);

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
          <a
            href="/analyze"
            onClick={go("/analyze")}
            aria-current={page === "analyze" ? "page" : undefined}
          >
            Analyze
          </a>
          <a
            href="/generate"
            onClick={go("/generate")}
            aria-current={page === "generate" ? "page" : undefined}
          >
            Generate
          </a>
          <a
            href="/gate"
            onClick={go("/gate")}
            aria-current={page === "gate" ? "page" : undefined}
          >
            Live Gate
          </a>
          <a
            href="/benchmarks"
            onClick={go("/benchmarks")}
            aria-current={page === "benchmarks" ? "page" : undefined}
          >
            Benchmarks
          </a>
          <a
            href="/scorecard"
            onClick={go("/scorecard")}
            aria-current={page === "scorecard" ? "page" : undefined}
          >
            Scorecard
          </a>
          <a href="/docs">API docs</a>
        </nav>
      </header>
      <main id="main" className="page">
        {page === "analyze" ? (
          <Analyze />
        ) : page === "generate" ? (
          <Generate navigate={navigate} />
        ) : page === "gate" ? (
          <LiveGate />
        ) : page === "benchmarks" ? (
          <Benchmarks />
        ) : page === "scorecard" ? (
          <Scorecard />
        ) : (
          <Landing navigate={navigate} />
        )}
      </main>
      <footer className="site-footer">
        <p>
          Scores are evidence, never accusations. A withheld image is recorded
          as not observed, never as a successful hidden transfer.
        </p>
        <p>
          {versionLine ? `${versionLine} · ` : ""}
          <a href="/docs">OpenAPI</a> ·{" "}
          <a href="/scorecard" onClick={go("/scorecard")}>
            Release scorecard
          </a>
        </p>
      </footer>
    </>
  );
}
