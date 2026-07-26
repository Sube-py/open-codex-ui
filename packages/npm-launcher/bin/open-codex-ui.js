#!/usr/bin/env node

import { readFile } from "node:fs/promises";

import { buildUvxArguments, ensureUvx, runUvx } from "../src/launcher.js";

async function main() {
  const packageJson = JSON.parse(
    await readFile(new URL("../package.json", import.meta.url), "utf8"),
  );
  const uvxPath = await ensureUvx();
  const result = await runUvx(
    uvxPath,
    buildUvxArguments(packageJson.version, process.argv.slice(2)),
  );

  if (result.signal) {
    process.kill(process.pid, result.signal);
    return;
  }
  process.exitCode = result.code ?? 1;
}

main().catch((error) => {
  const detail = error instanceof Error ? error.message : String(error);
  console.error(`open-codex-ui: ${detail}`);
  process.exitCode = 1;
});
