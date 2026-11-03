import { build } from "esbuild";
import { mkdtemp, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

// Bundle every tests/*.test.tsx for Node and run them with node:test.
const dir = await mkdtemp(join(tmpdir(), "covertlens-frontend-tests-"));
try {
  const entries = (await readdir("tests"))
    .filter((name) => name.endsWith(".test.tsx"))
    .sort();
  const outfiles = [];
  for (const name of entries) {
    const outfile = join(dir, name.replace(/\.tsx$/, ".cjs"));
    await build({
      entryPoints: [join("tests", name)],
      outfile,
      bundle: true,
      platform: "node",
      format: "cjs",
      jsx: "automatic",
    });
    outfiles.push(outfile);
  }
  const result = spawnSync(process.execPath, ["--test", ...outfiles], {
    stdio: "inherit",
  });
  process.exitCode = result.status ?? 1;
} finally {
  await rm(dir, { recursive: true, force: true });
}
