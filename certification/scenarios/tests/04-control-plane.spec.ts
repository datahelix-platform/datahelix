import { test, expect, emulateGraphqlProxy } from "../support/fixtures";
import { collectionUrl, sel, waitForApp } from "../support/app";
import { gql, gqlContext } from "../support/graphql";

// GOLDEN PATH 4 of 5 — CONTROL-PLANE SAVED VIEWS / DRAFTS
// Seam exercised: the Aperture control-plane document type (Aperture ADR-0032) —
// `{kind,name,payload}` documents on a structurally-recognized Mosaic collection.
// Proves: with the ApertureDocument recipe seeded, a saved view is persisted
// SERVER-SIDE (survives a full reload / new browser context), not just in
// localStorage. This is the scenario that only holds when the recipe is present
// — if the SPA fell back to localStorage the footer would say so and the
// server-side assertion below would (correctly) fail.

test("a saved view persists to the control-plane store and survives reload", async ({ page }) => {
  await page.goto(collectionUrl("books", { filters: "" , q: "Le Guin" }));
  await waitForApp(page);

  // The shell must report the Mosaic-backed control plane (not local fallback).
  // Asserted positively — the real footer says "LinkML-on-Mosaic document
  // store" when Mosaic-backed and "this browser only (…)" on local fallback, so
  // only a positive match actually proves the recipe was recognized.
  await expect(sel.controlPlaneStatus(page)).toHaveText(/document store/i);

  const viewName = `cert-view-${Date.now()}`;
  await sel.saveViewButton(page).click();
  await page.getByTestId("save-view-name").or(page.getByLabel(/name/i)).first().fill(viewName);
  await page.getByRole("button", { name: /save|confirm/i }).click();

  // The save is asynchronous (list-then-upsert against Mosaic); the nav's
  // saved-views section refreshes only after the put lands. Waiting on it
  // keeps the server-side check below from racing the write.
  await expect(sel.savedViewNamed(page, viewName)).toBeVisible();

  // Verify server-side: an ApertureDocument of kind=savedView with this name
  // exists and carries a versioned envelope payload. Query is tolerant of the
  // generated plural name via a small fallback list.
  const ctx = await gqlContext();
  const doc = await findSavedView(ctx, viewName);
  expect(doc, "saved view was not persisted to the Mosaic control-plane store").toBeTruthy();
  const envelope = JSON.parse(doc!.payload);
  expect(envelope).toHaveProperty("v");   // versioned envelope {v, data} (ADR-0032)
  expect(envelope).toHaveProperty("data");
  await ctx.dispose();

  // Survives a brand-new browser context (proves it's not browser-local).
  const fresh = await page.context().browser()!.newContext();
  await emulateGraphqlProxy(fresh); // same nginx-proxy emulation as the fixture page
  const p2 = await fresh.newPage();
  await p2.goto(collectionUrl("books"));
  await waitForApp(p2);
  await expect(sel.savedViewNamed(p2, viewName)).toBeVisible();
  await fresh.close();
});

// Mosaic's generated list field returns a page envelope and takes the generic
// filter list ({field, value} pairs over LinkML slot names).
async function findSavedView(
  ctx: Awaited<ReturnType<typeof gqlContext>>,
  name: string,
): Promise<{ kind: string; name: string; payload: string } | null> {
  const data = await gql<{ apertureDocuments: { items: any[] } }>(
    ctx,
    `query CertCP {
       apertureDocuments(
         filters: [{ field: "kind", value: "savedView" }]
         limit: 500
         offset: 0
       ) { items { kind name payload } }
     }`,
  );
  return (
    (data.apertureDocuments?.items ?? []).find((d) => d.name === name) ?? null
  );
}
