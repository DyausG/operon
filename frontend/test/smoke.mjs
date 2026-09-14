// Render the whole shell for every captured demo frame with react-dom/server.
// Catches runtime exceptions in every lifecycle state without a browser.
import { build } from "esbuild";
import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

mkdirSync("test/.out", { recursive: true });
await build({
  entryPoints: ["test/smoke-entry.jsx"], bundle: true, format: "esm", platform: "node", outfile: "test/.out/smoke.mjs",
  loader: { ".css": "empty", ".jsx": "jsx" }, jsx: "automatic", logLevel: "silent", packages: "external",
  define: { "process.env.NODE_ENV": '"production"' },
});
const mod = await import(pathToFileURL("test/.out/smoke.mjs").href);
const frames = JSON.parse(readFileSync("test/fixtures/demo-frames.json", "utf8"));
const reject = JSON.parse(readFileSync("test/fixtures/demo-frames-reject.json", "utf8"));
const artifacts = JSON.parse(readFileSync("test/fixtures/demo-artifacts.json", "utf8"));
const result = mod.run([...frames, ...reject], artifacts);
writeFileSync("test/.out/last.html", result.lastHtml);
console.log(result.report);
if (result.failures) process.exit(1);
