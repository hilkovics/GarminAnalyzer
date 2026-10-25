// Writes dist/.source-hash: a hash of every frontend source that shapes the build, so a Python test can
// tell when the committed dist/ is older than its sources (users run the app without Node).
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";

const root = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const inputs = ["src", "public", "index.html", "vite.config.ts", "package-lock.json"];

function files(path) {
  const full = join(root, path);
  if (statSync(full).isDirectory()) {
    return readdirSync(full).sort().flatMap((name) => files(join(path, name)));
  }
  return [path];
}

// CRLF → LF on the raw bytes: a Windows checkout (core.autocrlf) must give the same hash.
function lf(bytes) {
  const out = [];
  for (let i = 0; i < bytes.length; i++) {
    if (!(bytes[i] === 13 && bytes[i + 1] === 10)) out.push(bytes[i]);
  }
  return Buffer.from(out);
}

const hash = createHash("sha256");
const posix = inputs.flatMap(files).map((f) => relative(root, join(root, f)).split("\\").join("/"));
for (const file of posix.filter((f) => !f.includes(".test.") && !f.includes("/test/"))) {
  hash.update(file);
  hash.update("\0");
  hash.update(lf(readFileSync(join(root, file))));
  hash.update("\0");
}
writeFileSync(join(root, "dist", ".source-hash"), hash.digest("hex") + "\n");
