import { expect, test } from "@playwright/test";

const ROUTES = ["/", "/queue", "/benchmark", "/audit", "/simulation"];

for (const route of ROUTES) {
  test(`${route || "/"} renders without a client-side crash`, async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (err) => pageErrors.push(err.message));

    await page.goto(route);
    await expect(page.getByRole("heading", { name: "RecoveryOS" })).toBeVisible();

    // The nav bar is the one thing every page shares and that requires the router context
    // to be wired correctly — this is exactly what silently failed before the
    // <BrowserRouter> fix (see git history / docs/decisions.md).
    await expect(page.getByRole("link", { name: "Command Center" })).toBeVisible();

    expect(pageErrors, `uncaught render error(s) on ${route}: ${pageErrors.join("; ")}`).toEqual([]);
  });
}

test("navigating between pages via the nav bar never crashes", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (err) => pageErrors.push(err.message));

  await page.goto("/");
  for (const name of ["Recovery Queue", "Benchmark", "Audit Ledger", "Simulation", "Command Center"]) {
    await page.getByRole("link", { name }).click();
    await expect(page.getByRole("heading", { name: "RecoveryOS" })).toBeVisible();
  }

  expect(pageErrors).toEqual([]);
});
