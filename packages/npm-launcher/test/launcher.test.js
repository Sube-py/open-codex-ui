import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { existsSync, writeFileSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { delimiter, join } from "node:path";
import test from "node:test";

import {
  buildChildEnvironment,
  buildUvxArguments,
  cachedUvxPath,
  findUvx,
  installUv,
  resolveInstallDirectory,
  runUvx,
} from "../src/launcher.js";

test("resolves a platform-specific private uv directory", () => {
  assert.equal(
    resolveInstallDirectory({
      platform: "linux",
      env: { XDG_CACHE_HOME: "/cache" },
      home: "/home/tester",
    }),
    join("/cache", "open-codex-ui", "uv"),
  );
  assert.equal(
    resolveInstallDirectory({
      platform: "win32",
      env: { LOCALAPPDATA: "C:\\Users\\tester\\AppData\\Local" },
      home: "C:\\Users\\tester",
    }),
    join("C:\\Users\\tester\\AppData\\Local", "open-codex-ui", "uv"),
  );
});

test("prefers uvx already available on PATH", () => {
  const uvxPath = findUvx({
    env: { PATH: "/usr/bin" },
    spawnSyncImpl: () => ({ status: 0 }),
  });

  assert.equal(uvxPath, "uvx");
});

test("falls back to the cached uvx executable", () => {
  const installDirectory = "/cache/open-codex-ui/uv";
  const expected = cachedUvxPath(installDirectory, "linux");
  const uvxPath = findUvx({
    platform: "linux",
    installDirectory,
    spawnSyncImpl: () => ({ error: new Error("not found"), status: null }),
    existsSyncImpl: (path) => path === expected,
  });

  assert.equal(uvxPath, expected);
});

test("installs uv with the official installer without modifying PATH", async () => {
  const installDirectory = await mkdtemp(join(tmpdir(), "open-codex-ui-test-"));
  const expected = cachedUvxPath(installDirectory, "linux");
  let invocation;
  let requestedUrl;

  try {
    const result = await installUv({
      platform: "linux",
      env: { PATH: "/usr/bin" },
      installDirectory,
      fetchImpl: async (url) => {
        requestedUrl = url;
        return {
          ok: true,
          status: 200,
          statusText: "OK",
          text: async () => "#!/bin/sh\n",
        };
      },
      spawnSyncImpl: (command, args, options) => {
        invocation = { command, args, options };
        writeFileSync(expected, "");
        return { status: 0 };
      },
      existsSyncImpl: existsSync,
    });

    assert.equal(result, expected);
    assert.equal(requestedUrl, "https://astral.sh/uv/0.11.32/install.sh");
    assert.equal(invocation.command, "/bin/sh");
    assert.equal(invocation.options.env.UV_INSTALL_DIR, installDirectory);
    assert.equal(invocation.options.env.UV_NO_MODIFY_PATH, "1");
    assert.equal(existsSync(invocation.args[0]), false);
  } finally {
    await rm(installDirectory, { force: true, recursive: true });
  }
});

test("pins the Python package and forwards all CLI arguments", () => {
  assert.deepEqual(buildUvxArguments("0.1.6", ["daemon", "status"]), [
    "--from",
    "open-codex-ui==0.1.6",
    "open-codex-ui",
    "daemon",
    "status",
  ]);
});

test("adds a private uv directory to the child PATH", () => {
  const uvxPath = join("/cache", "uv", "uvx");
  const env = buildChildEnvironment(uvxPath, { PATH: "/usr/bin" });

  assert.equal(env.PATH, `${join("/cache", "uv")}${delimiter}/usr/bin`);
});

test("runs uvx with inherited IO and returns its exit status", async () => {
  const child = new EventEmitter();
  let invocation;
  const resultPromise = runUvx("uvx", ["open-codex-ui", "--help"], {
    env: { PATH: "/usr/bin" },
    spawnImpl: (command, args, options) => {
      invocation = { command, args, options };
      return child;
    },
  });
  child.emit("exit", 0, null);

  assert.deepEqual(await resultPromise, { code: 0, signal: null });
  assert.equal(invocation.command, "uvx");
  assert.deepEqual(invocation.args, ["open-codex-ui", "--help"]);
  assert.equal(invocation.options.stdio, "inherit");
});
