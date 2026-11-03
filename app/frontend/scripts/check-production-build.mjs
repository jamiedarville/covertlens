// CL-67: a non-demo build must carry no demo-role picker and never send
// X-Demo-Role. Builds with VITE_DEMO_BUILD=off into a temp dir and
// fails if either marker survives tree-shaking.
import { build } from "vite";
import { mkdtemp, readdir, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

process.env.VITE_DEMO_BUILD = "off";
const outDir = await mkdtemp(join(tmpdir(), "covertlens-prod-build-"));
try {
  await build({ logLevel: "error", build: { outDir, emptyOutDir: true } });
  const assets = join(outDir, "assets");
  const markers = ["X-Demo-Role", "demo role — not authentication"];
  const found = [];
  for (const name of await readdir(assets)) {
    if (!name.endsWith(".js")) continue;
    const text = await readFile(join(assets, name), "utf8");
    for (const marker of markers) if (text.includes(marker)) found.push(`${name}: ${marker}`);
  }
  if (found.length) {
    console.error("non-demo build still contains demo-role code:\n" + found.join("\n"));
    process.exitCode = 1;
  } else {
    console.log("non-demo build: no demo-role picker, no X-Demo-Role header");
  }
} finally {
  await rm(outDir, { recursive: true, force: true });
}
