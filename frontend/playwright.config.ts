import { defineConfig } from "@playwright/test";

/** Smoke-level E2E: catches exactly the class of bug unit tests and `tsc`/`vite build` can't
 * — a runtime-only React error (e.g. a missing <BrowserRouter> around react-router-dom's
 * <Routes>/<NavLink>) that renders a blank page while every static check stays green. Starts
 * its own dev server; the backend is NOT started automatically — pages that need real API
 * data will show their loading/error state rather than data, which is fine for this level of
 * test (it asserts the shell renders and nothing crashes, not that data loads).
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  webServer: {
    command: "npm run dev -- --host 127.0.0.1 --port 5174",
    url: "http://127.0.0.1:5174",
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
    stdout: "pipe",
    stderr: "pipe",
  },
  use: {
    baseURL: "http://127.0.0.1:5174",
  },
});
