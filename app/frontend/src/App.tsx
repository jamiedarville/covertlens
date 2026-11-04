import { useEffect, useState } from "react";
import AgentDemo from "./pages/AgentDemo";
import Landing from "./pages/Landing";
import Analyze from "./pages/Analyze";
import Generate from "./pages/Generate";
import LiveGate from "./pages/LiveGate";
import Review from "./pages/Review";
import Trace from "./pages/Trace";
import Benchmarks from "./pages/Benchmarks";
import Leaderboard from "./pages/Leaderboard";
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

// Short menu names; each page's heading says the rest.
export const NAV: { page: string; href: string; label: string; title: string }[] = [
  { page: "demo", href: "/demo", label: "Two-agent demo", title: "Two-agent demo" },
  { page: "analyze", href: "/analyze", label: "Check an image", title: "Check an image" },
  { page: "generate", href: "/generate", label: "Make a test image", title: "Make a test image" },
  { page: "gate", href: "/gate", label: "Delivery gate", title: "Delivery gate" },
  { page: "review", href: "/review", label: "Review images", title: "Review held-back images" },
  { page: "trace", href: "/trace", label: "Timeline", title: "Timeline of a session" },
  { page: "benchmarks", href: "/benchmarks", label: "Accuracy", title: "How accurate is CovertLens?" },
  { page: "leaderboard", href: "/leaderboard", label: "Leaderboard", title: "Leaderboard" },
  { page: "scorecard", href: "/scorecard", label: "Release decision", title: "Release decision" },
];

export default function App() {
  const [path, navigate] = usePath();
  const [versionLine, setVersionLine] = useState<string | null>(null);
  const page =
    path === "/demo"
      ? "demo"
      : path === "/analyze"
      ? "analyze"
      : path === "/generate"
        ? "generate"
        : path === "/gate"
          ? "gate"
          : path === "/review"
            ? "review"
            : path === "/trace"
              ? "trace"
              : path === "/benchmarks"
            ? "benchmarks"
            : path === "/leaderboard"
            ? "leaderboard"
            : path === "/scorecard"
              ? "scorecard"
              : "landing";

  useEffect(() => {
    const item = NAV.find((n) => n.page === page);
    document.title = item ? `${item.title} — CovertLens` : "CovertLens";
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
          <span className="wordmark-tagline">
            Checks images AI agents send each other for hidden messages
          </span>
        </a>
        <nav aria-label="Primary">
          {NAV.map((item) => (
            <a
              key={item.href}
              href={item.href}
              onClick={go(item.href)}
              aria-current={page === item.page ? "page" : undefined}
            >
              {item.label}
            </a>
          ))}
          <a href="/docs">API docs</a>
        </nav>
      </header>
      <main id="main" className="page">
        {page === "demo" ? (
          <AgentDemo />
        ) : page === "analyze" ? (
          <Analyze />
        ) : page === "generate" ? (
          <Generate navigate={navigate} />
        ) : page === "gate" ? (
          <LiveGate />
        ) : page === "review" ? (
          <Review />
        ) : page === "trace" ? (
          <Trace />
        ) : page === "benchmarks" ? (
          <Benchmarks />
        ) : page === "leaderboard" ? (
          <Leaderboard />
        ) : page === "scorecard" ? (
          <Scorecard />
        ) : (
          <Landing navigate={navigate} />
        )}
      </main>
      <footer className="site-footer">
        <p>
          CovertLens results are warning signs, not proof. On their own,
          they never mean that a person or agent did something wrong. An
          image that was held back is recorded as “not seen by the
          recipient”, never as a hidden message that got through.
        </p>
        <p>
          {versionLine ? `${versionLine} · ` : ""}
          <a href="/docs">Developer API docs (OpenAPI)</a> ·{" "}
          <a href="/scorecard" onClick={go("/scorecard")}>
            Release decision and its evidence
          </a>
        </p>
      </footer>
    </>
  );
}
