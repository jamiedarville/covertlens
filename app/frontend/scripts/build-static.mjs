// CL-66: build the static, zero-server Analyze page into dist-static/.
//  1. python3 scripts/build_static_bundle.py: library zip + examples
//     (+ CPython reference outputs for the parity test)
//  2. copy the Pyodide runtime from node_modules/pyodide
//  3. vite build (vite.static.config.ts)
//  4. index.html + precache.json for the service worker
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { copyFile, mkdir, readdir, readFile, rename, rm, stat, writeFile } from "node:fs/promises";
import { join, relative } from "node:path";
import { build } from "vite";

const here = process.cwd();
const repo = join(here, "..", "..");
const publicDir = join(here, "public-static");
const outDir = join(here, "dist-static");

await rm(publicDir, { recursive: true, force: true });
await mkdir(join(publicDir, "pyodide"), { recursive: true });

const python = process.env.PYTHON ?? "python3";
const bundle = spawnSync(
  python,
  [join(repo, "scripts", "build_static_bundle.py"), "--out", publicDir, "--expected", join(here, ".static-build", "expected")],
  { stdio: "inherit", env: { ...process.env, PYTHONPATH: repo } },
);
if (bundle.status !== 0) {
  process.exitCode = bundle.status ?? 1;
  throw new Error("python bundle step failed");
}

const runtime = ["pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"];
for (const name of runtime) {
  await copyFile(join(here, "node_modules", "pyodide", name), join(publicDir, "pyodide", name));
}
await copyFile(join(here, "src", "static", "sw.js"), join(publicDir, "sw.js"));

await build({ configFile: join(here, "vite.static.config.ts"), logLevel: "warn" });
await rename(join(outDir, "static.html"), join(outDir, "index.html"));

async function walk(dir) {
  const out = [];
  for (const name of await readdir(dir)) {
    const path = join(dir, name);
    if ((await stat(path)).isDirectory()) out.push(...(await walk(path)));
    else out.push(path);
  }
  return out;
}
const files = (await walk(outDir))
  .map((path) => relative(outDir, path).split("\\").join("/"))
  .filter((name) => name !== "precache.json" && name !== "sw.js")
  .sort();
const hash = createHash("sha256");
for (const name of files) {
  hash.update(name);
  hash.update(await readFile(join(outDir, name)));
}
const revision = hash.digest("hex").slice(0, 16);
await writeFile(
  join(outDir, "precache.json"),
  JSON.stringify({ revision, files: ["./", ...files, "precache.json"] }, null, 2) + "\n",
);
console.log(`static build: ${files.length} files, revision ${revision} -> ${relative(here, outDir)}/`);
