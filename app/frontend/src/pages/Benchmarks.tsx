import { useEffect, useState } from "react";

type Interval = {
  estimate: number | null;
  ci_low: number;
  ci_high: number;
  n: number;
};
type Point = {
  threshold: number;
  recall?: Interval;
  false_positive_rate?: Interval;
};
type Provenance = {
  library_version: string;
  config_version: string;
  computed_at: string;
  source: string;
};
type FamilyReport = {
  detector: { config: { version: string } };
  roc_auc: { estimate: number | null };
  sweep: Point[];
  by_payload_band: Record<
    string,
    {
      positive_count: number;
      roc_auc_vs_negatives: number | null;
      sweep: Point[];
    }
  >;
};
type GeoRow = {
  classifications: Record<string, number>;
  false_structure_claims?: {
    rate: number | null;
    wilson_95: { low: number; high: number };
  };
  structure_recall?: {
    rate: number | null;
    wilson_95: { low: number; high: number };
  };
};
export type Reports = {
  lsb: FamilyReport;
  dct: FamilyReport;
  metadata: { benchmark: FamilyReport };
  frozen: {
    held_out: {
      families: Record<
        string,
        {
          recall_at_triage: {
            value: number;
            wilson95: { low: number; high: number };
          };
          enforcement_precision: {
            value: number;
            wilson95: { low: number; high: number };
          };
          recall_by_band: Record<
            string,
            { value: number; wilson95: { low: number; high: number } }
          >;
        }
      >;
    };
    tradeoffs: string[];
  };
  geometric: { subfamilies: Record<string, { rows: Record<string, GeoRow> }> };
  ablations: {
    arms: Record<
      string,
      {
        auc: number;
        recall: number;
        precision: number;
        false_positive_rate: number;
      }
    >;
    findings: string[];
  };
  latency: {
    classes: {
      class: string;
      media: string;
      p95_s: number;
      meets_proposal: boolean;
      statuses: Record<string, number>;
    }[];
    tradeoffs: string[];
  };
  robustness: {
    experiments: {
      name: string;
      outcome: string;
      attempts: { n: number; at_triage: number; withheld: number };
      controls: { n: number; withheld: number };
    }[];
    coverage_limitations: string[];
  };
};

export function ProvenanceLine({
  value,
  detectorConfig,
}: {
  value?: Provenance;
  detectorConfig?: string;
}) {
  return (
    <p className="note">
      How these numbers were produced — software (library) version{" "}
      {value?.library_version ?? "unavailable"} · settings (config)
      version {value?.config_version ?? "unavailable"}
      {detectorConfig ? ` · this check’s settings version ${detectorConfig}` : ""} ·
      calculated on {value?.computed_at ?? "unavailable"} · produced by:{" "}
      {value?.source}. If the versions change, treat the numbers as
      belonging to the old version until they are measured again.
    </p>
  );
}

export function ExactData({ value }: { value: unknown }) {
  return (
    <details>
      <summary>Show the exact numbers behind this section (for specialists)</summary>
      <pre className="source-values">{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}

function Roc({ points, title }: { points: Point[]; title: string }) {
  const valid = points.filter(
    (p) =>
      p.recall?.estimate != null && p.false_positive_rate?.estimate != null,
  );
  if (!valid.length) return <p>No test pictures with hidden information were available at this hiding amount, so there is nothing to draw. Choose “All amounts” above.</p>;
  return (
    <svg
      className="chart"
      viewBox="0 0 600 300"
      role="img"
      aria-label={`${title}: how many cheating pictures are caught (upwards) against how many innocent pictures are wrongly flagged (sideways), for each possible cut-off. Curves towards the top-left are better.`}
    >
      <title>{title}</title>
      <path d="M 50 15 V 255 H 575" fill="none" className="chart-axis" />
      <path d="M 50 255 L 575 15" fill="none" className="chart-gridline" />
      {valid.map((p, i) => (
        <line
          key={i}
          x1={50 + (p.false_positive_rate?.estimate ?? 0) * 525}
          x2={50 + (p.false_positive_rate?.estimate ?? 0) * 525}
          y1={255 - (p.recall?.ci_low ?? 0) * 240}
          y2={255 - (p.recall?.ci_high ?? 1) * 240}
          className="chart-gridline"
        />
      ))}
      <polyline
        fill="none"
        className="chart-line-sequence"
        points={valid
          .map(
            (p) =>
              `${50 + (p.false_positive_rate?.estimate ?? 0) * 525},${255 - (p.recall?.estimate ?? 0) * 240}`,
          )
          .join(" ")}
      />
      {valid.map((p, i) => (
        <circle
          key={i}
          cx={50 + (p.false_positive_rate?.estimate ?? 0) * 525}
          cy={255 - (p.recall?.estimate ?? 0) * 240}
          r="3"
          className="chart-dot-sequence"
        >
          <title>
            Cut-off {p.threshold}; share of cheating pictures caught {p.recall?.estimate}; share of innocent pictures wrongly flagged {p.false_positive_rate?.estimate}
          </title>
        </circle>
      ))}
      <text x="50" y="280" className="chart-text">
        0 · Share of innocent pictures wrongly flagged
      </text>
      <text x="575" y="280" textAnchor="end" className="chart-text">
        1
      </text>
      <text x="8" y="20" className="chart-text">
        1
      </text>
      <text x="8" y="255" className="chart-text">
        0
      </text>
    </svg>
  );
}

function Bars({
  rows,
  title,
}: {
  rows: { label: string; value: number }[];
  title: string;
}) {
  const maximum = Math.max(1, ...rows.map((r) => r.value));
  return (
    <svg
      className="chart"
      viewBox={`0 0 700 ${rows.length * 36 + 25}`}
      role="img"
      aria-label={title}
    >
      <title>{title}</title>
      {rows.map((row, i) => (
        <g key={row.label}>
          <text x="0" y={i * 36 + 20} className="chart-text">
            {row.label}
          </text>
          <rect
            x="220"
            y={i * 36 + 4}
            width={(380 * row.value) / maximum}
            height="20"
            fill="currentColor"
            opacity=".45"
          />
          <text x="610" y={i * 36 + 20} className="chart-text">
            {row.value}
          </text>
        </g>
      ))}
    </svg>
  );
}

function Rate({ value }: { value?: Interval }) {
  return (
    <>
      {value?.estimate == null
        ? "not measured"
        : `${value.estimate} (true value likely between ${value.ci_low} and ${value.ci_high}; based on ${value.n} test pictures)`}
    </>
  );
}

function FamilyChart({
  report,
  name,
  provenance,
}: {
  report: FamilyReport;
  name: string;
  provenance?: Provenance;
}) {
  const [band, setBand] = useState("all");
  const bandRow = report.by_payload_band[band];
  const points =
    band === "all"
      ? report.sweep
      : (bandRow?.sweep ?? []).map((p, i) => ({
          ...p,
          false_positive_rate:
            p.false_positive_rate ?? report.sweep[i]?.false_positive_rate,
        }));
  return (
    <article className="panel">
      <h3>{name}</h3>
      <ProvenanceLine
        value={provenance}
        detectorConfig={report.detector.config.version}
      />
      <label>
        How much was hidden? (“payload band” — hiding more is usually easier to catch){" "}
        <select value={band} onChange={(e) => setBand(e.target.value)}>
          <option value="all">All amounts together</option>
          {Object.keys(report.by_payload_band).map((b) => (
            <option key={b}>{b}</option>
          ))}
        </select>
      </label>
      <p>
        Overall ability to tell cheating from innocent pictures (ROC
        AUC — 1 is perfect, 0.5 is no better than guessing):{" "}
        {band === "all"
          ? report.roc_auc.estimate
          : (bandRow?.roc_auc_vs_negatives ?? "not measured")}
        . The thin vertical lines on the chart show the likely range for
        each point (a 95% “Wilson” interval — long lines mean few test
        pictures, so the value is uncertain).
      </p>
      <Roc points={points} title={`${name}, ${band === "all" ? "all hiding amounts" : band}`} />
      <div className="table-scroll">
        <table>
          <caption>
            The exact numbers behind the chart: for each possible
            cut-off, the share of cheating pictures caught and the share
            of innocent pictures wrongly flagged, each with its likely
            range.
          </caption>
          <thead>
            <tr>
              <th>Score cut-off (flag if score is at least this)</th>
              <th>Share of cheating pictures caught (“recall”)</th>
              <th>Share of innocent pictures wrongly flagged (“false positive rate”)</th>
            </tr>
          </thead>
          <tbody>
            {points.map((p, i) => (
              <tr key={i}>
                <td>{p.threshold}</td>
                <td>
                  <Rate value={p.recall} />
                </td>
                <td>
                  <Rate value={p.false_positive_rate} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
  );
}

export default function Benchmarks() {
  const [reports, setReports] = useState<Reports | null>(null);
  const [provenance, setProvenance] = useState<Record<string, Provenance>>({});
  const [message, setMessage] = useState("Loading the saved accuracy reports…");
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const names = [
          "lsb",
          "dct",
          "metadata",
          "frozen",
          "geometric",
          "ablations",
          "latency",
          "robustness",
          "provenance",
        ];
        const responses = await Promise.all(
          names.map((name) => fetch(`/api/benchmarks/${name}`)),
        );
        if (cancelled) return;
        if (responses.some((r) => r.status === 202)) {
          setMessage(
            "The accuracy reports are being calculated on the server. This can take a while; this page will refresh itself when they are ready — you can leave it open.",
          );
          timer = setTimeout(load, 5000);
          return;
        }
        if (responses.some((r) => !r.ok))
          throw new Error("The accuracy reports could not be loaded. What to do: reload this page to try again.");
        const payloads = await Promise.all(
          responses.map((r) => r.json() as Promise<unknown>),
        );
        if (!cancelled) {
          const all = Object.fromEntries(
            names.map((name, i) => [name, payloads[i]]),
          );
          setReports(all as unknown as Reports);
          setProvenance(all.provenance as Record<string, Provenance>);
        }
      } catch (error) {
        if (!cancelled) setMessage(String(error));
      }
    };
    void load();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);
  if (!reports)
    return (
      <>
        <h1>How accurate are the checks?</h1>
        <p>
          This page will show measured test results: of pictures known to
          hide something, how many were caught — and of innocent
          pictures, how many were wrongly flagged.
        </p>
        <p role="status">{message}</p>
      </>
    );
  return <BenchmarkResults reports={reports} provenance={provenance} />;
}

export function BenchmarkResults({
  reports,
  provenance,
  initialView = "frozen",
}: {
  reports: Reports;
  provenance: Record<string, Provenance>;
  initialView?: string;
}) {
  const [view, setView] = useState(initialView);
  const tabLabels: Record<string, string> = {
    frozen: "Main test (unseen pictures, fixed settings)",
    curves: "Trade-off curves (choosing a cut-off)",
    geometric: "Shape-pattern tests",
    ablations: "Which parts of the checker matter?",
    latency: "How fast is it?",
    robustness: "Tricky attempts to sneak past",
  };
  return (
    <>
      <h1>How accurate are the checks? (benchmarks)</h1>
      <p>
        CovertLens was tested on pictures where the truth is known: some
        really do hide information, others are innocent. This page shows,
        for each kind of test, how many cheating pictures were caught and
        how many innocent ones were wrongly flagged. The first tab (“Main
        test”) is the one that counts most: fixed settings, tested on
        pictures that were kept aside and never used while setting the
        cut-offs.
      </p>
      <div className="card">
        <h2>Words used on this page</h2>
        <dl className="kv kv-wide">
          <div><dt>Caught share (“recall”)</dt><dd>Of pictures that really hid something, the share that were flagged. Higher is better.</dd></div>
          <div><dt>Wrongly flagged share (“false positive rate”)</dt><dd>Of innocent pictures, the share wrongly flagged. Lower is better.</dd></div>
          <div><dt>Accuracy of flags (“precision”)</dt><dd>Of pictures that were flagged or held back, the share that really were cheating. Higher is better.</dd></div>
          <div><dt>Likely range (“Wilson 95% interval”)</dt><dd>The true value probably lies inside this range. A wide range means few test pictures — be cautious.</dd></div>
          <div><dt>Cut-off (“threshold”)</dt><dd>The score at or above which a picture is flagged or held back.</dd></div>
          <div><dt>“Frozen” settings, “held-out” pictures</dt><dd>Settings were locked first, then tested on pictures kept aside — like marking an exam with a fixed answer key on unseen questions.</dd></div>
        </dl>
      </div>
      <p className="note">
        Every result only covers the kinds of pictures actually tested
        (stated with each report). Good results on these tests do not
        promise the same on different kinds of pictures.
      </p>
      <div className="report-tabs" role="group" aria-label="Which set of test results to show">
        {[
          "frozen",
          "curves",
          "geometric",
          "ablations",
          "latency",
          "robustness",
        ].map((name) => (
          <button
            key={name}
            aria-pressed={view === name}
            onClick={() => setView(name)}
          >
            {tabLabels[name] ?? name}
          </button>
        ))}
      </div>
      {view === "frozen" && (
        <section>
          <h2>Main test: fixed settings, unseen pictures</h2>
          <p>
            The cut-offs were locked (“frozen”) using separate practice
            pictures, then applied unchanged to these kept-aside
            (“held-out”) pictures. Start with the first table:
            “flagged for attention” is the gentler outcome (delivered but
            marked); “held back or run stopped” is the strict, blocking
            outcome.
          </p>
          <ProvenanceLine value={provenance.frozen} />
          <table>
            <caption>
              Each value is a share from 0 to 1, followed by its likely
              range (wide ranges mean few test pictures).
            </caption>
            <thead>
              <tr>
                <th>Check</th>
                <th>Cheating pictures at least flagged for attention</th>
                <th>When a picture was held back or the run stopped, share that really were cheating</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(reports.frozen.held_out.families).map(
                ([name, row]) => (
                  <tr key={name}>
                    <th>{name}</th>
                    <td>
                      {row.recall_at_triage.value}{" "}
                      {JSON.stringify(row.recall_at_triage.wilson95)}
                    </td>
                    <td>
                      {row.enforcement_precision.value}{" "}
                      {JSON.stringify(row.enforcement_precision.wilson95)}
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
          {Object.entries(reports.frozen.held_out.families).map(
            ([name, row]) => (
              <article key={name}>
                <h3>{name}: does hiding more make it easier to catch?</h3>
                <table>
                  <caption>Share caught at the “flag for attention” cut-off, split by how much was hidden (the “payload band”).</caption>
                  <thead>
                    <tr>
                      <th>Amount hidden</th>
                      <th>Share caught, with likely range</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(row.recall_by_band).map(
                      ([band, result]) => (
                        <tr key={band}>
                          <th>{band}</th>
                          <td>
                            {result.value} {JSON.stringify(result.wilson95)}
                          </td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              </article>
            ),
          )}
          <h3>Trade-offs the project accepted, in the report’s own words</h3>
          <ul>
            {reports.frozen.tradeoffs.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
          <ExactData value={reports.frozen} />
        </section>
      )}
      {view === "curves" && (
        <section>
          <h2>The trade-off in choosing a cut-off</h2>
          <p>
            Moving the cut-off trades one error for another: a stricter
            (higher) cut-off wrongly flags fewer innocent pictures but
            catches fewer cheating ones. Each chart sweeps through all
            possible cut-offs on the practice (“development”) pictures —
            curves bowing towards the top-left corner are better. These
            practice results are for choosing cut-offs; they do not add to
            the main test’s claims.
          </p>
          <FamilyChart
            name="Tiny pixel changes (spatial LSB)"
            report={reports.lsb}
            provenance={provenance.lsb}
          />
          <FamilyChart
            name="JPEG compression data (DCT)"
            report={reports.dct}
            provenance={provenance.dct}
          />
          <FamilyChart
            name="Information stored in the file (metadata)"
            report={reports.metadata.benchmark}
            provenance={provenance.metadata}
          />
        </section>
      )}
      {view === "geometric" && (
        <section>
          <h2>Shape-pattern tests, by hiding place</h2>
          <ProvenanceLine value={provenance.geometric} />
          <p>
            For each hiding place in the visible pattern (heights, gaps,
            brightness, tilt, colour), three kinds of test picture were
            used: values with no regular spacing (“continuous”); values on
            a regular spacing but in no meaningful order (“quantized
            unstructured” — like an ordinary chart); and values on a
            regular spacing arranged to carry a code (“quantized
            structured”). The checker should blame only the third kind.
            Good results for one hiding place say nothing about the
            others, so each is reported separately.
          </p>
          {Object.entries(reports.geometric.subfamilies).map(
            ([name, block]) => (
              <article key={name}>
                <h3>Hiding place: {name}</h3>
                <table>
                  <thead>
                    <tr>
                      <th>Kind of test picture (exact name)</th>
                      <th>How the checker classified them (counts)</th>
                      <th>Share reported as deliberately arranged, with likely range</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(block.rows).map(([kind, row]) => (
                      <tr key={kind}>
                        <th>
                          {kind === "continuous"
                            ? "No regular spacing ("
                            : kind === "quantized_unstructured"
                              ? "Regular spacing, no meaningful order ("
                              : kind === "quantized_structured"
                                ? "Regular spacing carrying a code ("
                                : "("}
                          {kind})
                        </th>
                        <td>{JSON.stringify(row.classifications)}</td>
                        <td>
                          {
                            (row.structure_recall ?? row.false_structure_claims)
                              ?.rate
                          }{" "}
                          {JSON.stringify(
                            (row.structure_recall ?? row.false_structure_claims)
                              ?.wilson_95,
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </article>
            ),
          )}
          <ExactData value={reports.geometric} />
        </section>
      )}
      {view === "ablations" && (
        <section>
          <h2>Which parts of the checker actually help?</h2>
          <p>
            Each row is a version of the checker with some information
            taken away (“ablated”) — for example, looking at the picture
            alone versus also using surrounding context. Comparing the
            rows shows whether each part earns its keep, or whether
            adding it actually makes decisions worse.
          </p>
          <ProvenanceLine value={provenance.ablations} />
          <Bars
            rows={Object.entries(reports.ablations.arms).map(
              ([label, row]) => ({ label, value: row.auc }),
            )}
            title="Overall ability to tell cheating from innocent pictures (AUC; 1 is perfect), by version of the checker"
          />
          <table>
            <caption>All shares run from 0 to 1. The first three are “higher is better”; wrongly flagged is “lower is better”.</caption>
            <thead>
              <tr>
                <th>Version of the checker (exact name)</th>
                <th>Overall separation ability (AUC)</th>
                <th>Cheating caught</th>
                <th>Flags that were right</th>
                <th>Innocent wrongly flagged</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(reports.ablations.arms).map(([name, row]) => (
                <tr key={name}>
                  <th>{name}</th>
                  <td>{row.auc}</td>
                  <td>{row.recall}</td>
                  <td>{row.precision}</td>
                  <td>{row.false_positive_rate}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <ExactData value={reports.ablations} />
        </section>
      )}
      {view === "latency" && (
        <section>
          <h2>How long does checking take?</h2>
          <p>
            “P95 seconds” means: 95 out of 100 pictures of that kind were
            checked within this time. The project aimed for 2 seconds;
            the “2-second aim met?” column says plainly where that aim was
            missed. A missed aim means slower delivery — it does not
            change any accuracy result.
          </p>
          <ProvenanceLine value={provenance.latency} />
          <Bars
            rows={reports.latency.classes.map((row) => ({
              label: `${row.class}/${row.media}`,
              value: row.p95_s,
            }))}
            title="Time to check 95 out of 100 pictures, in seconds, by picture size and type"
          />
          <table>
            <thead>
              <tr>
                <th>Picture size / type</th>
                <th>95% checked within (seconds)</th>
                <th>2-second aim met?</th>
                <th>How the checks ended (counts)</th>
              </tr>
            </thead>
            <tbody>
              {reports.latency.classes.map((row) => (
                <tr key={`${row.class}/${row.media}`}>
                  <th>
                    {row.class}/{row.media}
                  </th>
                  <td>{row.p95_s}</td>
                  <td>{row.meets_proposal ? "yes" : "no — slower than aimed for"}</td>
                  <td>{JSON.stringify(row.statuses)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h3>Trade-offs, in the report’s own words</h3>
          <ul>
            {reports.latency.tradeoffs.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
          <ExactData value={reports.latency} />
        </section>
      )}
      {view === "robustness" && (
        <section>
          <h2>Tricky attempts to sneak past the checker</h2>
          <p>
            Separate from the main test, attackers who knew how the
            checker works tried to evade it (for example by hiding less,
            or using unusual pictures). “Controls” are matching innocent
            pictures run alongside, to make sure the gate was not simply
            blocking everything. These extra experiments explore
            weaknesses honestly; they never feed into the main test’s
            numbers.
          </p>
          <ProvenanceLine value={provenance.robustness} />
          <Bars
            rows={reports.robustness.experiments.map((row) => ({
              label: row.name,
              value: row.attempts.withheld,
            }))}
            title="Sneak attempts that were held back, counted per experiment"
          />
          <table>
            <caption>“At least flagged” counts pictures delivered but marked for attention or worse; “held back” counts only the blocking outcomes.</caption>
            <thead>
              <tr>
                <th>Experiment (the trick that was tried)</th>
                <th>Overall outcome</th>
                <th>Attempts made</th>
                <th>At least flagged</th>
                <th>Held back</th>
                <th>Innocent controls held back / total</th>
              </tr>
            </thead>
            <tbody>
              {reports.robustness.experiments.map((row) => (
                <tr key={row.name}>
                  <th>{row.name}</th>
                  <td>{row.outcome}</td>
                  <td>{row.attempts.n}</td>
                  <td>{row.attempts.at_triage}</td>
                  <td>{row.attempts.withheld}</td>
                  <td>
                    {row.controls.withheld}/{row.controls.n}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <h3>What these experiments do not cover, in the report’s own words</h3>
          <ul>
            {reports.robustness.coverage_limitations.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
          <ExactData value={reports.robustness} />
        </section>
      )}
    </>
  );
}
