import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const API_BASE = "http://127.0.0.1:8000";

async function isUp() {
  try {
    const res = await fetch(`${API_BASE}/health`);
    return res.ok;
  } catch {
    return false;
  }
}

async function waitForHealth(timeoutMs = 20000) {
  const start = Date.now();
  let lastErr;
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(`${API_BASE}/health`);
      if (res.ok) return;
    } catch (err) {
      lastErr = err;
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`mock-api failed to start: ${lastErr}`);
}

export default async function setup() {
  if (await isUp()) {
    return () => {};
  }

  const mockApiDir = join(
    dirname(fileURLToPath(import.meta.url)),
    "../../../mock-api",
  );
  const child = spawn(
    "python3",
    ["-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"],
    {
      cwd: mockApiDir,
      stdio: ["ignore", "pipe", "pipe"],
      env: {
        ...process.env,
        PATH: `${process.env.HOME}/.local/bin:${process.env.PATH}`,
      },
    },
  );

  await waitForHealth();

  return async () => {
    child.kill("SIGTERM");
  };
}
