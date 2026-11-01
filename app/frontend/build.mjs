// Placeholder build (CL-47): copies the static landing page to
// dist/. CL-48 replaces this with the React + Vite build.
import { cpSync, mkdirSync, existsSync } from "node:fs";

mkdirSync("dist", { recursive: true });
cpSync("index.html", "dist/index.html");
if (existsSync("public")) {
  cpSync("public", "dist", { recursive: true });
}
console.log("frontend placeholder built to dist/");
