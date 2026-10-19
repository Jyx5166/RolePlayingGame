import { createHash } from "node:crypto";
import { copyFile, readFile, rename, rm, writeFile } from "node:fs/promises";

const artifacts = ["app.js", "app.js.map", "app.css"];
const builtAppUrl = new URL("../.build/app.js", import.meta.url);
const builtApp = await readFile(builtAppUrl, "utf8");

if (/\bprocess\.env\./.test(builtApp)) {
  throw new Error("Production bundle contains an unresolved process.env reference");
}

for (const artifact of artifacts) {
  const temporaryPath = `${artifact}.next`;
  await copyFile(new URL(`../.build/${artifact}`, import.meta.url), new URL(`../${temporaryPath}`, import.meta.url));
  await rm(new URL(`../${artifact}`, import.meta.url), { force: true });
  await rename(new URL(`../${temporaryPath}`, import.meta.url), new URL(`../${artifact}`, import.meta.url));
}

const indexUrl = new URL("../index.html", import.meta.url);
let html = await readFile(indexUrl, "utf8");
for (const asset of ["app.js", "styles.css", "app.css"]) {
  const bytes = await readFile(new URL(`../${asset}`, import.meta.url));
  const version = createHash("sha256").update(bytes).digest("hex").slice(0, 16);
  const reference = new RegExp(`/static/${asset.replace(".", "\\.")}(?:\\?v=[a-f0-9]+)?(?=")`, "g");
  if ([...html.matchAll(reference)].length !== 1) {
    throw new Error(`Expected exactly one entry reference for ${asset}`);
  }
  html = html.replace(reference, `/static/${asset}?v=${version}`);
}
await writeFile(new URL("../index.html.next", import.meta.url), html, "utf8");
await rename(new URL("../index.html.next", import.meta.url), indexUrl);
