// CL-66 parity check: the static build's Python bundle, run in Pyodide
// (Node), must produce the same analysis as CPython for every example.
// Needs `npm run build:static` first.
import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import { loadPyodide } from "pyodide";

const here = process.cwd();
const site = join(here, "public-static");
const expectedDir = join(here, ".static-build", "expected");

const py = await loadPyodide({ indexURL: join(here, "node_modules", "pyodide") + "/" });
py.unpackArchive(new Uint8Array(await readFile(join(site, "covertlens-py.zip"))), "zip", {
  extractDir: "/home/pyodide/covertlens",
});
py.runPython(
  "import sys\nsys.path.insert(0, '/home/pyodide/covertlens')\nfrom app.analysis_worker import analyze_bytes",
);

// Wall-clock fields are the only values allowed to differ.
function strip(value) {
  if (Array.isArray(value)) return value.map(strip);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .filter(([key]) => key !== "elapsed_ms")
        .map(([key, v]) => [key, strip(v)]),
    );
  }
  return value;
}

let failures = 0;
const names = (await readdir(expectedDir)).filter((n) => n.endsWith(".json")).sort();
for (const name of names) {
  const image = name.replace(/\.json$/, "");
  py.FS.writeFile("/tmp/example", new Uint8Array(await readFile(join(site, "examples", image))));
  const started = Date.now();
  const actual = JSON.parse(
    py.runPython(
      "import json\njson.dumps(analyze_bytes(open('/tmp/example', 'rb').read(), 2_000_000), sort_keys=True)",
    ),
  );
  const expected = JSON.parse(await readFile(join(expectedDir, name), "utf8"));
  const same = JSON.stringify(strip(actual)) === JSON.stringify(strip(expected));
  console.log(`${same ? "ok  " : "FAIL"} ${image} (${Date.now() - started} ms in Pyodide)`);
  if (!same) failures += 1;
}
if (names.length === 0) {
  console.error("no expected outputs: run npm run build:static first");
  failures += 1;
}
process.exitCode = failures ? 1 : 0;
