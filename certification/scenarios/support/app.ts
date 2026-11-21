import { Page, expect, Locator } from "@playwright/test";

// --- URL state ---------------------------------------------------------------
// Aperture drives its main view off URL state (nuqs keys, documented in
// web/src/features/collections/urlState.ts): collection, page, q, filters,
// entity, form, workflow. Navigating by URL is the most stable way to place the
// SPA into a known state for a golden-path step, independent of nav-chrome DOM.

export function collectionUrl(collection: string, extra: Record<string, string> = {}): string {
  const p = new URLSearchParams({ collection, ...extra });
  return `/?${p.toString()}`;
}

export function newEntityFormUrl(collection: string): string {
  return `/?${new URLSearchParams({ collection, form: "new" }).toString()}`;
}

export function workflowUrl(workflowId: string): string {
  return `/?${new URLSearchParams({ workflow: workflowId }).toString()}`;
}

// The query builder (Aperture ADR-0035/0041). `qs` is the executed QuerySpec
// and `cols` the column choices -- together they are the shareable state a
// saved query view stores (aperture#75, #81).
export function queryUrl(qs?: object, cols?: object): string {
  const p = new URLSearchParams({ view: "query" });
  if (qs) p.set("qs", JSON.stringify(qs));
  if (cols) p.set("cols", JSON.stringify(cols));
  return `/?${p.toString()}`;
}

// --- Resilient locators ------------------------------------------------------
// Centralized so that when the built SPA's DOM firms up (aperture#15/#16) only
// this file changes. Each locator prefers a data-testid, then falls back to an
// accessible role/name — the SPA emits serializable view-descriptions
// (Aperture ADR-0009), so stable testids/roles are the intended contract.

export const sel = {
  collectionTable: (p: Page): Locator =>
    p.getByTestId("collection-table").or(p.getByRole("table")).first(),

  rowsFor: (p: Page): Locator =>
    p.getByTestId("collection-row").or(p.getByRole("row")),

  facetPanel: (p: Page): Locator =>
    p.getByTestId("facet-panel").or(p.getByRole("complementary")).first(),

  facetOption: (p: Page, value: string): Locator =>
    p.getByTestId(`facet-option-${value}`).or(
      p.getByRole("checkbox", { name: new RegExp(value, "i") }),
    ),

  entityForm: (p: Page): Locator =>
    p.getByTestId("entity-form").or(p.getByRole("form")).first(),

  fieldInput: (p: Page, field: string): Locator =>
    p.getByTestId(`field-${field}`).or(p.getByLabel(new RegExp(field, "i"))),

  submitButton: (p: Page): Locator =>
    p.getByTestId("form-submit").or(p.getByRole("button", { name: /save|create|submit/i })),

  saveViewButton: (p: Page): Locator =>
    p.getByTestId("save-view").or(p.getByRole("button", { name: /save view/i })),

  // Saved views render as nav BUTTONS in the real DOM (CollectionsNav), not
  // links. The `saved-view-<name>` testid is the stable contract and is unique;
  // the role fallback must be `exact` so it does not also match the sibling
  // "Remove saved view \"<name>\"" button aperture 0.3.0 added (#41) — whose
  // accessible name contains <name> — which would trip Playwright strict mode.
  savedViewNamed: (p: Page, name: string): Locator =>
    p.getByTestId(`saved-view-${name}`).or(
      p.getByRole("button", { name, exact: true }),
    ),

  // The real footer reads "Control plane: LinkML-on-Mosaic document store"
  // (Mosaic-backed) or "Control plane: this browser only (…)" (local fallback).
  controlPlaneStatus: (p: Page): Locator =>
    p.getByTestId("control-plane-status").or(p.getByText(/^control plane:/i)).first(),

  workflowNext: (p: Page): Locator =>
    p.getByTestId("workflow-next").or(p.getByRole("button", { name: /next|continue/i })),

  // The review screen gates commit behind an explicit whole-set dry-run
  // (Aperture ADR-0028) — the golden path clicks validate, then commit.
  workflowValidate: (p: Page): Locator =>
    p.getByTestId("workflow-validate").or(p.getByRole("button", { name: /validate/i })),

  // Anchored so the stepper's "Review & commit" chip (also a button) never
  // collides with the commit action.
  workflowCommit: (p: Page): Locator =>
    p.getByTestId("workflow-commit").or(p.getByRole("button", { name: /^(commit|finish|create all)/i })),

  workflowSuccess: (p: Page): Locator =>
    p.getByTestId("workflow-success").or(p.getByText(/committed|created|success/i)).first(),

  // --- Query builder + result table (Aperture ADR-0041) ---------------------
  queryAnchor: (p: Page): Locator => p.getByTestId("query-anchor"),
  queryRun: (p: Page): Locator => p.getByTestId("query-run"),
  queryResults: (p: Page): Locator => p.getByTestId("query-results"),
  queryTable: (p: Page): Locator => p.getByTestId("query-results").getByRole("table"),
  // "6 matching books" -- counts ANCHORS, whatever the table's grain.
  queryTotal: (p: Page): Locator =>
    p.getByTestId("query-results").getByRole("status").filter({ hasText: /matching/i }).first(),
  // "Exploded by … — N rows from M <anchors> on this page" (ADR-0041 item 6).
  queryGrain: (p: Page): Locator => p.getByTestId("query-grain"),
  fieldsButton: (p: Page): Locator =>
    p.getByTestId("query-results").getByRole("button", { name: /^Fields/ }),
  // One "Through a reference" link group in the Fields panel, by its label
  // (e.g. "its co authors"). Its toggle is the group's first button.
  referenceLink: (p: Page, label: RegExp): Locator =>
    p.getByTestId("fields-related-edge").filter({ hasText: label }).first(),
  // A link the endpoint offers only as a filter: listed with its reason, never
  // silently absent (Aperture ADR-0029).
  gatedReferenceLink: (p: Page, label: RegExp): Locator =>
    p.getByTestId("fields-related-gated").filter({ hasText: label }).first(),
  // A field row inside a link group, found by its checkbox's accessible name.
  // (Row text grows once a list link's mode choices appear, so match the
  // checkbox, not the text.)
  referenceField: (group: Locator, field: string): Locator =>
    group.getByRole("listitem").filter({
      has: group.page().getByRole("checkbox", { name: field, exact: true }),
    }),
  exportButton: (p: Page, kind: "CSV" | "JSON"): Locator =>
    p.getByTestId("query-results").getByRole("button", { name: `Export ${kind}` }),
  // The page's areas (aperture 0.7.1, #85): the Fields panel opened over a
  // result, the table's own scroll box, and the pager under it.
  fieldsPanel: (p: Page): Locator =>
    p.getByTestId("query-results").getByTestId("fields-panel")
      .or(p.getByTestId("query-results").getByRole("region", { name: "Fields" })).first(),
  queryTableBox: (p: Page): Locator => p.getByTestId("query-table-scroll"),
  queryPager: (p: Page): Locator =>
    p.getByTestId("query-results").getByRole("button", { name: "Previous" }),
  exportNote: (p: Page): Locator =>
    p.getByTestId("query-results").getByRole("status").filter({ hasText: /^Exported/ }).first(),
};

// Wait for the SPA shell + first data render. The SPA derives its capabilities
// from a `ApertureIntrospection` query on load; the table is our "ready" signal.
export async function waitForApp(p: Page): Promise<void> {
  await expect(p.locator("body")).toBeVisible();
  // The collection view should render a table once introspection + list resolve.
  await expect(sel.collectionTable(p)).toBeVisible({ timeout: 20_000 });
}
