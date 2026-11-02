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
      Library {value?.library_version ?? "unavailable"} · config{" "}
      {value?.config_version ?? "unavailable"}
      {detectorConfig ? ` · detector config ${detectorConfig}` : ""} · computed{" "}
      {value?.computed_at ?? "unavailable"} · {value?.source}
    </p>
  );
}

export function ExactData({ value }: { value: unknown }) {
  return (
    <details>
      <summary>Exact source values</summary>
      <pre className="source-values">{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}

function Roc({ points, title }: { points: Point[]; title: string }) {
  const valid = points.filter(
    (p) =>
      p.recall?.estimate != null && p.false_positive_rate?.estimate != null,
  );
  if (!valid.length) return <p>No positive samples for this band.</p>;
  return (
    <svg
      className="chart"
      viewBox="0 0 600 300"
      role="img"
      aria-label={`${title}: true positive rate against false positive rate`}
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
            Threshold {p.threshold}; recall {p.recall?.estimate}; false positive
            rate {p.false_positive_rate?.estimate}
          </title>
        </circle>
      ))}
      <text x="50" y="280" className="chart-text">
        0 · False positive rate
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
        : `${value.estimate} [${value.ci_low}, ${value.ci_high}] (n=${value.n})`}
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
        Payload band{" "}
        <select value={band} onChange={(e) => setBand(e.target.value)}>
          <option value="all">All bands</option>
          {Object.keys(report.by_payload_band).map((b) => (
            <option key={b}>{b}</option>
          ))}
        </select>
      </label>
      <p>
        ROC AUC:{" "}
        {band === "all"
          ? report.roc_auc.estimate
          : (bandRow?.roc_auc_vs_negatives ?? "not measured")}
        . Bars show 95% Wilson recall intervals.
      </p>
      <Roc points={points} title={`${name}, ${band}`} />
      <div className="table-scroll">
        <table>
          <caption>
            Exact operating-point values and 95% Wilson intervals
          </caption>
          <thead>
            <tr>
              <th>Threshold</th>
              <th>Recall</th>
              <th>False positive rate</th>
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
  const [message, setMessage] = useState("Loading cached reports…");
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
            "Reports are computing. This page will refresh when they are ready.",
          );
          timer = setTimeout(load, 5000);
          return;
        }
        if (responses.some((r) => !r.ok))
          throw new Error("Could not load benchmark reports. Reload to retry.");
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
        <h1>Benchmarks</h1>
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
  return (
    <>
      <h1>Benchmarks</h1>
      <p>
        Evidence at recorded configurations. Small samples produce wide
        intervals; results apply within each report’s declared coverage.
      </p>
      <div className="report-tabs" role="group" aria-label="Report category">
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
            {name}
          </button>
        ))}
      </div>
      {view === "frozen" && (
        <section>
          <h2>Frozen held-out benchmark</h2>
          <ProvenanceLine value={provenance.frozen} />
          <table>
            <thead>
              <tr>
                <th>Family</th>
                <th>Triage recall [Wilson 95%]</th>
                <th>Enforcement precision [Wilson 95%]</th>
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
                <h3>{name}: held-out payload bands</h3>
                <table>
                  <thead>
                    <tr>
                      <th>Band</th>
                      <th>Recall [Wilson 95%]</th>
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
          <h2>Development fixture ROC curves</h2>
          <p>
            Threshold sweeps over the synthetic development suite. These curves
            do not extend the frozen held-out claim.
          </p>
          <FamilyChart
            name="Spatial LSB"
            report={reports.lsb}
            provenance={provenance.lsb}
          />
          <FamilyChart
            name="JPEG DCT"
            report={reports.dct}
            provenance={provenance.dct}
          />
          <FamilyChart
            name="Metadata"
            report={reports.metadata.benchmark}
            provenance={provenance.metadata}
          />
        </section>
      )}
      {view === "geometric" && (
        <section>
          <h2>Geometric subfamilies</h2>
          <ProvenanceLine value={provenance.geometric} />
          <p>
            Each subfamily has continuous, quantized unstructured, and quantized
            structured rows. No general geometric coverage follows from a single
            subfamily.
          </p>
          {Object.entries(reports.geometric.subfamilies).map(
            ([name, block]) => (
              <article key={name}>
                <h3>{name}</h3>
                <table>
                  <thead>
                    <tr>
                      <th>Scene type</th>
                      <th>Classifications</th>
                      <th>Structure rate [Wilson 95%]</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(block.rows).map(([kind, row]) => (
                      <tr key={kind}>
                        <th>{kind}</th>
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
          <h2>Ablation arms</h2>
          <ProvenanceLine value={provenance.ablations} />
          <Bars
            rows={Object.entries(reports.ablations.arms).map(
              ([label, row]) => ({ label, value: row.auc }),
            )}
            title="AUC by ablation arm"
          />
          <table>
            <thead>
              <tr>
                <th>Arm</th>
                <th>AUC</th>
                <th>Recall</th>
                <th>Precision</th>
                <th>False positive rate</th>
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
          <h2>Latency by size and media</h2>
          <ProvenanceLine value={provenance.latency} />
          <Bars
            rows={reports.latency.classes.map((row) => ({
              label: `${row.class}/${row.media}`,
              value: row.p95_s,
            }))}
            title="P95 latency in seconds"
          />
          <table>
            <thead>
              <tr>
                <th>Class / media</th>
                <th>P95 seconds</th>
                <th>Proposal met</th>
                <th>Statuses</th>
              </tr>
            </thead>
            <tbody>
              {reports.latency.classes.map((row) => (
                <tr key={`${row.class}/${row.media}`}>
                  <th>
                    {row.class}/{row.media}
                  </th>
                  <td>{row.p95_s}</td>
                  <td>{String(row.meets_proposal)}</td>
                  <td>{JSON.stringify(row.statuses)}</td>
                </tr>
              ))}
            </tbody>
          </table>
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
          <h2>Adaptive and unseen robustness probes</h2>
          <p>
            These experiments are separate from the frozen benchmark. Their
            outcomes never enter frozen benchmark curves or rows.
          </p>
          <ProvenanceLine value={provenance.robustness} />
          <Bars
            rows={reports.robustness.experiments.map((row) => ({
              label: row.name,
              value: row.attempts.withheld,
            }))}
            title="Robustness attempts withheld, counts per experiment"
          />
          <table>
            <thead>
              <tr>
                <th>Experiment</th>
                <th>Outcome</th>
                <th>Attempts</th>
                <th>At triage</th>
                <th>Withheld</th>
                <th>Controls withheld / total</th>
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
