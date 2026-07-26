import { randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import { chmod, mkdir, rm, writeFile } from "node:fs/promises";
import { homedir, tmpdir } from "node:os";
import { delimiter, dirname, join } from "node:path";
import { spawn, spawnSync } from "node:child_process";

const UV_VERSION = "0.11.32";
const INSTALLER_URLS = {
  win32: `https://astral.sh/uv/${UV_VERSION}/install.ps1`,
  default: `https://astral.sh/uv/${UV_VERSION}/install.sh`,
};

export function resolveInstallDirectory({
  platform = process.platform,
  env = process.env,
  home = homedir(),
} = {}) {
  if (env.OPEN_CODEX_UI_UV_DIR) {
    return env.OPEN_CODEX_UI_UV_DIR;
  }
  if (platform === "win32") {
    return join(
      env.LOCALAPPDATA || join(home, "AppData", "Local"),
      "open-codex-ui",
      "uv",
    );
  }
  return join(
    env.XDG_CACHE_HOME || join(home, ".cache"),
    "open-codex-ui",
    "uv",
  );
}

export function cachedUvxPath(installDirectory, platform = process.platform) {
  return join(installDirectory, platform === "win32" ? "uvx.exe" : "uvx");
}

export function findUvx({
  platform = process.platform,
  env = process.env,
  installDirectory = resolveInstallDirectory({ platform, env }),
  spawnSyncImpl = spawnSync,
  existsSyncImpl = existsSync,
} = {}) {
  if (env.OPEN_CODEX_UI_UVX) {
    return env.OPEN_CODEX_UI_UVX;
  }

  const probe = spawnSyncImpl("uvx", ["--version"], {
    env,
    stdio: "ignore",
  });
  if (!probe.error && probe.status === 0) {
    return "uvx";
  }

  const cachedPath = cachedUvxPath(installDirectory, platform);
  return existsSyncImpl(cachedPath) ? cachedPath : null;
}

export async function installUv({
  platform = process.platform,
  env = process.env,
  installDirectory = resolveInstallDirectory({ platform, env }),
  fetchImpl = fetch,
  spawnSyncImpl = spawnSync,
  existsSyncImpl = existsSync,
} = {}) {
  const isWindows = platform === "win32";
  const installerUrl = isWindows
    ? INSTALLER_URLS.win32
    : INSTALLER_URLS.default;
  const response = await fetchImpl(installerUrl, { redirect: "follow" });
  if (!response.ok) {
    throw new Error(
      `Unable to download the official uv installer (${response.status} ${response.statusText}).`,
    );
  }

  await mkdir(installDirectory, { recursive: true });
  const scriptPath = join(
    tmpdir(),
    `open-codex-ui-uv-${randomUUID()}.${isWindows ? "ps1" : "sh"}`,
  );
  await writeFile(scriptPath, await response.text(), "utf8");
  if (!isWindows) {
    await chmod(scriptPath, 0o700);
  }

  const command = isWindows ? "powershell.exe" : "/bin/sh";
  const args = isWindows
    ? ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", scriptPath]
    : [scriptPath];
  let result;
  try {
    result = spawnSyncImpl(command, args, {
      env: {
        ...env,
        UV_INSTALL_DIR: installDirectory,
        UV_NO_MODIFY_PATH: "1",
      },
      stdio: "inherit",
    });
  } finally {
    await rm(scriptPath, { force: true });
  }

  if (result.error) {
    throw new Error(
      `Unable to run the official uv installer: ${result.error.message}`,
    );
  }
  if (result.status !== 0) {
    throw new Error(
      `The official uv installer exited with code ${result.status}.`,
    );
  }

  const uvxPath = cachedUvxPath(installDirectory, platform);
  if (!existsSyncImpl(uvxPath)) {
    throw new Error(`The official uv installer did not create ${uvxPath}.`);
  }
  return uvxPath;
}

export async function ensureUvx(options = {}) {
  return findUvx(options) || installUv(options);
}

export function buildUvxArguments(version, forwardedArguments) {
  return [
    "--from",
    `open-codex-ui==${version}`,
    "open-codex-ui",
    ...forwardedArguments,
  ];
}

export function buildChildEnvironment(uvxPath, env = process.env) {
  if (uvxPath === "uvx") {
    return { ...env };
  }
  const pathKey =
    Object.keys(env).find((name) => name.toLowerCase() === "path") || "PATH";
  const currentPath = env[pathKey] || "";
  return {
    ...env,
    [pathKey]: [dirname(uvxPath), currentPath].filter(Boolean).join(delimiter),
  };
}

export function runUvx(
  uvxPath,
  args,
  { env = process.env, spawnImpl = spawn } = {},
) {
  return new Promise((resolve, reject) => {
    const child = spawnImpl(uvxPath, args, {
      env: buildChildEnvironment(uvxPath, env),
      stdio: "inherit",
    });
    child.once("error", reject);
    child.once("exit", (code, signal) => resolve({ code, signal }));
  });
}
