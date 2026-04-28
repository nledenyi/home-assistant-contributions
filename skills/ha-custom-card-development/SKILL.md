---
name: ha-custom-card-development
description: Build, test, and deploy a Lovelace custom card from scratch in TypeScript + Lit. Use when the user asks to create a new HA Lovelace card (one that gets installed under /config/www/community/<name>/<name>.js and registered as a `custom:<name>` card type), as opposed to composing a dashboard out of existing cards. Examples - "build me a journey viewer card", "I want a custom HA card that shows X", "make a Lovelace card for ...".
argument-hint: "[card-name]"
---

# HA Lovelace custom-card development

Reference playbook for building a custom card that ships as a single ES module under `/config/www/community/<name>/<name>.js`, registered via `customElements.define` and the `window.customCards` registry, with optional visual editor.

Distinct from:

- `ha-section-card` - composes dashboards using existing cards. No TS/Lit code.
- `ha-integration-fix` - patches Python integrations + their clients. No frontend code.

## Step 0. Project shape

Single-file ES module. All deps (Lit, Leaflet, etc.) inlined at build time. The whole card is one `<script type="module">` that HA loads as a Lovelace resource.

```
journey-viewer-card/
├── src/
│   ├── card.ts              # main entry: extends LitElement
│   ├── editor/
│   │   ├── editor.ts        # visual editor (lazy-loaded)
│   │   ├── schema.ts        # ha-form schemas per section
│   │   └── stat-catalogue.ts
│   ├── types.ts             # CardConfig, sub-configs, all interfaces
│   ├── format.ts            # pure helpers (no DOM)
│   ├── data.ts              # reading from hass.states[entity].attributes
│   └── decorators.ts        # threshold/gradient/bar pure functions
├── dev/
│   ├── index.html           # Vite HMR harness
│   └── main.ts              # mounts card with mocked hass
├── public/
│   └── sample-data.json     # fixture for the dev harness
├── dist/<name>.js           # build output, deployed to HA
├── vite.config.ts           # lib mode + inlineDynamicImports
├── package.json
└── tsconfig.json
```

Vite config essentials:

```ts
build: {
  lib: { entry: "src/card.ts", formats: ["es"], fileName: () => "<name>.js" },
  rollupOptions: { output: { inlineDynamicImports: true } },  // single-file
  target: "es2022",
  sourcemap: true,
},
```

## Step 1. The Lovelace card contract

Five lifecycle methods you MUST implement correctly. Each is a known landmine area.

### 1a. Class definition - DO NOT use `@customElement` decorator

The Lit `@customElement(name)` decorator throws synchronously on duplicate registration. HACS, manual resource reload, and `import()` of the bundle from another script all re-evaluate the module. The decorator path crashes those.

**Wrong**:

```ts
@customElement("journey-viewer-card")
export class JourneyViewerCard extends LitElement { ... }
```

**Right**:

```ts
export class JourneyViewerCard extends LitElement { ... }

// At the bottom of the file:
if (!customElements.get("journey-viewer-card")) {
  customElements.define("journey-viewer-card", JourneyViewerCard);
}
```

Same pattern for the editor class. The visual editor goes in its own module (lazy import - see Step 1b) and gets the same `customElements.get` guard.

### 1b. `getConfigElement` - lazy-load the editor

The editor is its own bundle's worth of code (forms, dialogs, schemas). Don't load it on every dashboard view - only when the user clicks "Edit Card".

```ts
static async getConfigElement(): Promise<HTMLElement> {
  await import("./editor/editor.js");
  return document.createElement("<name>-card-editor");
}
```

With `inlineDynamicImports: true` the editor is in the same single file but Lit only instantiates it when called. Editor modules can be heavy (~50% of total bundle); skipping it on first render is real savings.

### 1c. `getStubConfig` + `setConfig` - default + validation

`CardConfig` should extend `LovelaceCardConfig` from custom-card-helpers (or a vendored copy) so the `type` and `[key: string]: any` indexer come for free, the editor's `setConfig(config: LovelaceCardConfig)` signature matches without a cast, and the string-literal `type` catches typos at compile time:

```ts
import type { LovelaceCardConfig } from "custom-card-helpers";

export interface JourneyViewerCardConfig extends LovelaceCardConfig {
  type: "custom:journey-viewer-card";  // string-literal narrowing
  sources: SourceConfig[];
  label?: LabelConfig;
  // ...
}
```

Then:

```ts
static getStubConfig(): Partial<JourneyViewerCardConfig> {
  return { type: "custom:journey-viewer-card", sources: [{ name: "Vehicle", entity: "" }] };
}

setConfig(config: JourneyViewerCardConfig): void {
  if (!config?.sources?.length) {
    throw new Error("journey-viewer-card: 'sources' is required");
  }
  // Validate any template tokens at config time, not at render time:
  if (config.label?.template) {
    const unknown = validateLabelTemplate(config.label.template);
    if (unknown.length) {
      throw new Error(`unknown label tokens: ${unknown.join(", ")}`);
    }
  }
  this.config = config;
}
```

Throwing in `setConfig` is the correct way to surface invalid configs - HA's editor displays the message inline and renders `hui-error-card` on the dashboard.

### 1d. Sizing: `getCardSize` (masonry) + `getGridOptions` (sections-view, HA 2024.7+)

**`getCardSize`** is for masonry-layout views (the older Lovelace default). Returns an integer in 50px units. Extract magic numbers as constants.

```ts
const CARD_HEADER_HEIGHT_PX = 60;
const STATS_ROW_HEIGHT_PX = 50;
const STATS_GRID_DEFAULT_COLS = 4;

getCardSize(): number {
  const stats = this.config?.stats_grid?.rows?.length ?? 0;
  const mapH = this.config?.map?.height ?? 280;
  const statsH = Math.ceil(stats / STATS_GRID_DEFAULT_COLS) * STATS_ROW_HEIGHT_PX;
  return Math.ceil((mapH + CARD_HEADER_HEIGHT_PX + statsH) / STATS_ROW_HEIGHT_PX);
}
```

**`getGridOptions`** (HA 2024.7+) is for sections-view layouts. Returns a grid spec where each cell is ~30px wide × 56px tall × 8px gap. Without it, sections-view users have to manually set `layout_options` in YAML.

The right return depends on whether the card has fixed or variable height content:

**Fixed-height cards** (tile-card style: icon + 1-2 text rows, predictable shape) — return integer rows. Mushroom and HA's built-in tile-card use this pattern. Each row = exactly one 56px grid row.

```ts
// Mushroom-style integer-row pattern (fixed shape)
getGridOptions(): LovelaceGridOptions {
  return { rows: 1, columns: 6, min_rows: 1, min_columns: 4 };
}
```

**Variable-height cards** (map + stats grid, configurable image, anything where content height depends on data) — return `rows: "auto"`. This is the pattern HA's own `entities-card`, `markdown-card`, and `history-graph-card` use. CSS Grid auto-row sizing makes the cell exactly fit the rendered content: no overflow into adjacent cells, no empty gap inside the cell.

```ts
// Auto-sizing pattern (variable shape) — recommended for cards with
// configurable map height, dynamic widget counts, or responsive content
getGridOptions(): LovelaceGridOptions {
  return { columns: 12, rows: "auto", min_columns: 6 };
}
```

**Don't try to pixel-arithmetic your way to a numeric `rows` value for variable-content cards** — `title_px + map_px + ceil(stats / cols) × tile_px / 64`-style formulas are brittle. Tiles with thresholds + trend arrows render ~13px taller than plain ones because text wraps; a constant tuned for plain tiles overflows on decorated ones, and a constant tuned for decorated tiles leaves visible gaps under plain ones. Confirmed in our card by repeatedly tuning `STAT_TILE_PX` between 64 and 80 and never finding a value that worked for all configs. `"auto"` solves it without the maintenance.

The UX cost of `"auto"`: the row-resize handle in section edit mode disappears (column-resize still works). For self-sizing cards that's correct — there's nothing meaningful to resize vertically when the content dictates the height.

Drop `min_rows` / `max_rows` when using `rows: "auto"` — they're meaningless. Keep `min_columns` to stop the user from squashing the card too narrow. Always implement both `getCardSize` and `getGridOptions`: `getCardSize` is consulted in masonry view + scroll-to-card calculations even when sections-view is the active layout.

The earlier `getLayoutOptions()` from HA 2024.3 was a prototype; only `getGridOptions` is the supported method now.

CSS evidence (HA frontend `src/panels/lovelace/sections/hui-grid-section.ts` lines 121-126): the `.fit-rows` class with fixed cell height is only applied when `typeof rows === "number"`. With `rows: "auto"`, the cell uses `grid-auto-rows: auto` and naturally sizes to content.

### 1e. `customCards` registration - guarded, with HACS console banner

```ts
declare global {
  interface Window {
    customCards?: Array<{ type: string; name: string; description: string; preview?: boolean }>;
  }
}

if (!customElements.get("journey-viewer-card")) {
  customElements.define("journey-viewer-card", JourneyViewerCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "journey-viewer-card",
    name: "Journey Viewer",
    description: "...",
    preview: true,
  });
  // HACS convention: styled banner in DevTools console for version verification
  console.info(
    `%c JOURNEY-VIEWER-CARD %c v${CARD_VERSION} `,
    "color: white; background: #1d8cf8; font-weight: 700;",
    "color: #1d8cf8; background: white; font-weight: 700;",
  );
}
```

### 1f. Action support (tap_action / hold_action / double_tap_action)

The official HA pattern (introduced 2023.7) is the **`hass-action` event**. The card dispatches a `CustomEvent` with `{ config, action: "tap" | "hold" | "double_tap" }`, and HA itself routes through its standard handler (toggle, call-service, navigate, url, more-info, etc.) including built-in confirmation dialogs, haptics, and PIN-protection. Don't import `handleAction` from custom-card-helpers and don't reimplement the action machinery.

```ts
private _handleAction(ev: ActionHandlerEvent): void {
  if (!this.hass || !this.config || !ev.detail.action) return;
  const event = new Event("hass-action", { bubbles: true, composed: true });
  (event as { detail?: unknown }).detail = {
    config: this.config,
    action: ev.detail.action,  // "tap" | "hold" | "double_tap"
  };
  this.dispatchEvent(event);
}
```

Pair with the `actionHandler` Lit directive (mushroom / apexcharts / button-card pattern) to get tap-vs-hold-vs-double-tap detection from a single pointer event:

```ts
render() {
  return html`<div
    @action=${this._handleAction}
    .actionHandler=${actionHandler({
      hasHold: hasAction(this.config.hold_action),
      hasDoubleClick: hasAction(this.config.double_tap_action),
    })}
  >...</div>`;
}
```

Default actions if the user doesn't specify: `tap_action` defaults to `more-info`, `hold_action` and `double_tap_action` default to `none`. Document these in your config schema.

### 1g. Type sources: `custom-card-helpers` vs vendored types

The npm package `custom-card-helpers` is the de-facto canonical source for HA frontend types: `HomeAssistant`, `LovelaceCard`, `LovelaceCardEditor`, `LovelaceCardConfig`, the `ActionConfig` union (toggle / call-service / navigate / url / more-info / none / fire-dom-event / toggle-menu / turn-on / turn-off), and ~40 utility functions (`handleAction`, `hasAction`, `fireEvent`, `computeStateDisplay`, `formatNumber`, `forwardHaptic`, `applyThemesOnElement`, `navigate`, `toggleEntity`, locale enums).

**Caveat**: the package is no longer actively maintained (last meaningful release ~2022) and its `HomeAssistant` interface drifts from upstream HA over time. Mature cards (mushroom, button-card) often vendor a hand-trimmed subset rather than depend on the npm package directly. Two reasonable options:

- **Use the package** if you need many utilities (haptics, action dispatch, theme application). Accept some interface drift.
- **Vendor a `src/ha-types.ts`** with just `HomeAssistant`, `LovelaceCard`, `LovelaceCardEditor`, `LovelaceCardConfig`, `ActionConfig`. Stays small, never drifts on HA upgrades, ~80 lines.

For our stack (already declaring `Window` ourselves), vendoring is cleaner. Pick one and document the choice in the project README.

## Step 2. Lit reactivity

### 2a. `shouldUpdate` should NOT watch all of hass

The `hass` property is a fat object that mutates on every state change in the entire HA instance. Walking it in `shouldUpdate` triggers a re-render on every unrelated entity update.

```ts
function relevantEntitiesChanged(
  oldHass: HomeAssistant | undefined,
  newHass: HomeAssistant | undefined,
  entityIds: string[],
): boolean {
  if (!oldHass) return true;
  if (!newHass) return false;
  for (const id of entityIds) {
    if (oldHass.states[id] !== newHass.states[id]) return true;
  }
  return false;
}

protected override shouldUpdate(changed: PropertyValues): boolean {
  if (!this.config) return true;
  if (changed.has("config") || changed.has("trips") || changed.has("index")) return true;
  if (changed.has("hass")) {
    const oldHass = changed.get("hass") as HomeAssistant | undefined;
    const ids = (this.config.sources ?? []).map(s => s.entity).filter(Boolean);
    return relevantEntitiesChanged(oldHass, this.hass, ids);
  }
  return false;
}
```

**Don't reach for `hass.connection.subscribeEvents("state_changed", ...)`** as a "more efficient" alternative. HA's frontend already maintains `hass.states` as a live snapshot updated via a single global subscription; per-card subscriptions add load and force you to manually reconcile against the same data. Subscribe only for things `hass.states` can't give you: template results via `subscribe_template`, fired-and-forget events like `mobile_app_notification_action`, history streams. For 95% of cards the right answer is `shouldUpdate` against `hass.states[id]`.

### 2b. Three lifecycle phases: `willUpdate`, `firstUpdated`, `updated`

Lit fires three distinct hooks. Mixing them is a common source of leaks and double-renders.

- **`willUpdate(changed)`** - reactive data refresh BEFORE render. Pure: read state, compute derived, set `@state` properties. Runs on every reactive update (including the first).
- **`firstUpdated(changed)`** - one-time DOM init AFTER the first render. Use for: instantiating Leaflet/Chart.js/etc. against a freshly-rendered container, attaching ResizeObserver / MutationObserver, registering document-level event listeners, setting initial focus. Runs exactly ONCE.
- **`updated(changed)`** - side effects AFTER every render. Use for: re-centering an existing map, scrolling to a row, recomputing measurements when config changes.

```ts
override willUpdate(changed: PropertyValues): void {
  if (changed.has("hass") || changed.has("config")) this.refreshTrips();
}

override firstUpdated(): void {
  // One-time. The map container is now rendered; instantiate the map.
  this.tripMap = new TripMap(this.shadowRoot!.querySelector(".tv-map")!);
  this.resizeObserver = new ResizeObserver(() => this.tripMap?.invalidateSize());
  this.resizeObserver.observe(this);
}

override updated(changed: PropertyValues): void {
  // Per-render side effects. Map already exists from firstUpdated.
  if (changed.has("currentTrip")) this.tripMap?.fitBounds(this.currentTrip?.bbox);
}
```

Putting Leaflet construction in `updated()` allocates a fresh map on every reactive update — guaranteed leak. Putting data computation in `updated()` triggers a second render. Putting side effects in `willUpdate()` runs them before the DOM exists.

### 2c. Memoize expensive per-row computations

When the card renders N rows of derived data (thresholds, gradients, bars, trends), the per-row work fires on every reactive update. Cache it.

```ts
private rowCache?: { trip: Trip; rows: WeakMap<StatsRow, RowComputed> };

private getRowComputed(row: StatsRow, trip: Trip): RowComputed {
  if (!this.rowCache || this.rowCache.trip !== trip) {
    this.rowCache = { trip, rows: new WeakMap() };
  }
  const cached = this.rowCache.rows.get(row);
  if (cached) return cached;
  // ... compute, cache, return
}

// Bust cache when source data changes:
private refreshTrips(): void {
  this.trips = ...;
  this.rowCache = undefined;
}
```

WeakMap keyed on the row config object means the cache auto-clears when the config changes.

### 2d. Reactive listeners - match config changes

If a config option toggles a behavior (e.g. keyboard navigation), add/remove the listener reactively, not just in `connectedCallback`.

```ts
private keyboardListenerActive = false;

private syncKeyboardListener(): void {
  const wanted = !!this.config?.pagination?.keyboard;
  if (wanted && !this.keyboardListenerActive) {
    document.addEventListener("keydown", this.handleKey);
    this.keyboardListenerActive = true;
  } else if (!wanted && this.keyboardListenerActive) {
    document.removeEventListener("keydown", this.handleKey);
    this.keyboardListenerActive = false;
  }
}

protected override willUpdate(changed: PropertyValues): void {
  if (changed.has("config")) this.syncKeyboardListener();
}
```

### 2e. `disconnectedCallback` - destroy everything you allocated

Lit doesn't auto-cleanup. Tear down: timers, ResizeObservers, MutationObservers, third-party objects (Leaflet maps), document-level event listeners.

```ts
override disconnectedCallback(): void {
  super.disconnectedCallback();
  this.tripMap?.destroy();
  this.tripMap = undefined;
  document.removeEventListener("keydown", this.handleKey);
  this.keyboardListenerActive = false;
}
```

Pair with `connectedCallback` that re-initialises after a Lovelace edit-mode toggle:

```ts
override connectedCallback(): void {
  super.connectedCallback();
  this.syncKeyboardListener();
  // Lit's `updated()` doesn't refire on reconnect alone, so manually
  // recover any DOM-bound state:
  requestAnimationFrame(() => this.ensureMap());
}
```

## Step 3. Theming + accessibility

### 3a. Theme variables with fallback chain

Always cascade through HA theme tokens before hardcoded fallbacks.

```css
:host {
  --jv-tile-bg: var(--secondary-background-color, #f3f4f6);
  --jv-radius: var(--ha-card-border-radius, 12px);
}
```

Three layers of override (highest to lowest):

1. Per-card YAML config: `map.polyline.palette.ev: "#hex"` - direct property override
2. card-mod / theme YAML: `--jv-tile-bg: ...` - cascading custom property
3. Hardcoded fallback in CSS: `var(--jv-tile-bg, #f3f4f6)`

### 3b. Icon buttons need `aria-label`, not just `title`

`title` is a tooltip, not an accessibility name. Screen readers ignore icon buttons that only have `title`.

```html
<button aria-label="Previous trip" title="Previous trip">‹</button>
```

`aria-label` for the actual semantics, `title` retained for the tooltip on hover.

### 3c. Keyboard focus styles

Browser default focus rings vanish if you've styled the button. Re-add them, but only for keyboard focus:

```css
.tv-btn:focus-visible:not([disabled]) { outline: 2px solid var(--primary-color); }
.tv-btn:focus:not(:focus-visible) { outline: none; }
```

`:focus-visible` shows the ring for keyboard users, `:focus:not(:focus-visible)` suppresses it for mouse-clicks.

### 3d. Card shell + error/warning conventions

Wrap every card render in `<ha-card>` (HA's themed card shell). It picks up theme borders, shadow, header padding, and dark-mode adjustments automatically.

For per-row warnings (entity unavailable, missing attribute, partial data), use `<hui-warning>` — it has the standard yellow warning styling and is consistent with built-in cards. For fatal errors, prefer throwing in `setConfig` so HA renders an `hui-error-card`; only render a manual error template for runtime issues that can recover (e.g. transient API failure).

```ts
render() {
  if (!this.hass || !this.config) return nothing;
  if (!this._entityAvailable()) {
    return html`
      <ha-card>
        <hui-warning>Entity ${this.config.entity} unavailable</hui-warning>
      </ha-card>`;
  }
  return html`<ha-card>${this._content()}</ha-card>`;
}
```

`hui-warning` and `hui-error-card` are HA-internal but they self-register the moment any built-in card renders, which happens on every dashboard view. Safe to use without the loader trick from Step 4d below.

### 3e. Localization (when you need it)

`hass.localize(key)` is for HA-core translation keys ONLY — passing custom keys returns the key string unchanged. The cross-card convention (mushroom, apexcharts, button-card) is a small in-card localizer:

```
src/localize/
  ├── languages/
  │   ├── en.json
  │   ├── fr.json
  │   ├── hu.json
  │   └── ...
  └── localize.ts
```

```ts
// src/localize/localize.ts
import en from "./languages/en.json";
import hu from "./languages/hu.json";

const LANGUAGES: Record<string, Record<string, unknown>> = { en, hu };

export function localize(
  key: string,
  hass?: HomeAssistant,
  search?: string,
  replace?: string,
): string {
  const lang = hass?.locale?.language ?? hass?.language ?? "en";
  const translations = LANGUAGES[lang] ?? LANGUAGES.en;
  const value = key.split(".").reduce<any>((o, k) => o?.[k], translations) ?? key;
  return search ? value.replace(search, replace ?? "") : value;
}
```

Skip this until the card has at least one stable language and a real reason to add a second. For Hungarian-only or English-only cards, hardcoded strings are fine. Document the path forward in the project README so future-you knows where to add languages without rearchitecting.

## Step 4. Editor (visual config)

The editor is a separate Lit component in its own file, lazy-imported via `getConfigElement`. Convention: same name + `-editor` suffix.

### 4a. ha-form schemas per section

HA's `ha-form` is the standard editor form. Define schemas as readonly arrays of selector definitions:

```ts
export const TOP_LEVEL_SCHEMA: Schema = [
  { name: "title", selector: { text: {} } },
  { type: "grid", schema: [
    { name: "order", selector: { select: { options: ["newest_first", "oldest_first"] } } },
    { name: "default_index", selector: { number: { min: 0, mode: "box" } } },
  ]},
];
```

Selectors that accept CSS variables (`var(...)`) or special values (`auto`, `transparent`) should use `text: {}`, NOT `text: { type: "color" }`. Color pickers only emit hex.

### 4b. `_mergeAtPath` typing - single typed entry/exit

Avoid `as unknown as CardConfig` cast chains. Cast once at function entry, once at exit:

```ts
private _mergeAtPath(
  config: CardConfig,
  path: SectionPath,
  patch: Record<string, unknown>,
): CardConfig {
  const cfg = config as Record<string, unknown>;  // single cast in
  let result: Record<string, unknown>;
  // ... build result based on path ...
  return result as CardConfig;  // single cast out
}
```

### 4c. Window globals - declare them, don't cast around them

```ts
declare global {
  interface Window {
    jsyaml?: { dump: (o: unknown) => string; load: (s: string) => unknown };
  }
}
// Then: const yaml = window.jsyaml; - clean
```

### 4d. Force-load HA internals before the editor renders (the mushroom trick)

`<ha-form>`, `<ha-entity-picker>`, `<hui-card-features-editor>` are HA-internal custom elements. They're NOT registered globally on page load — only when the user has previously opened a built-in card that uses them. If your editor opens before the user has touched a tile/entities/conditional card in this session, those tags are undefined and your editor renders blank.

The fix (taken straight from `lovelace-mushroom/src/utils/loader.ts`): trigger the lazy load by calling `getConfigElement()` on a built-in card class. That side-effect-registers the internals.

```ts
export const loadHaComponents = (): void => {
  if (!customElements.get("ha-form") || !customElements.get("hui-card-features-editor")) {
    (customElements.get("hui-tile-card") as any)?.getConfigElement?.();
  }
  if (!customElements.get("ha-entity-picker")) {
    (customElements.get("hui-entities-card") as any)?.getConfigElement?.();
  }
};

// In your editor's connectedCallback:
override connectedCallback(): void {
  super.connectedCallback();
  loadHaComponents();
}
```

Critical pattern. Without it, the editor breaks intermittently for users on a fresh dashboard load. Add it the first time you ship a visual editor, even if your testing didn't catch the issue.

## Step 5. Dev workflow

### 5a. Vite dev with live HA via server-side proxy (preferred)

The Vite harness gives you sub-second HMR while iterating. The card reads from `hass.states[entity].attributes.X`; the harness just stubs that. Two patterns for where the data comes from:

**Preferred: live HA via Vite proxy.** Real data, no synthetic-fixture maintenance, token never reaches the browser. Requires HA reachable from your dev machine.

```ts
// vite.config.ts
import { defineConfig, loadEnv } from "vite";
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, __dirname, "");
  const haUrl = env.DEV_HA_URL;
  const haToken = env.DEV_HA_TOKEN;
  return {
    server: {
      proxy: haUrl && haToken ? {
        "/ha-api": {
          target: haUrl,
          changeOrigin: true,
          rewrite: p => p.replace(/^\/ha-api/, "/api"),
          configure: (proxy) => {
            proxy.on("proxyReq", req => req.setHeader("Authorization", `Bearer ${haToken}`));
          },
        },
      } : undefined,
    },
    // ... build/lib config
  };
});
```

```ts
// dev/main.ts
const r = await fetch(`/ha-api/states/${ENTITY}`);
const state = await r.json() as { attributes?: { trips?: Trip[] } };
card.setConfig(config);
card.hass = { states: { [ENTITY]: { attributes: { trips: state.attributes?.trips ?? [] } } } } as any;
```

Token lives in `.env.local` (auto-gitignored), `.env.example` is committed as a template:

```
# .env.example
DEV_HA_URL=http://homeassistant.local:8123
DEV_HA_TOKEN=
```

The token is injected server-side by Vite into the proxied request — the browser only ever sees same-origin `/ha-api/*` requests, so CORS isn't an issue and the token never appears in DevTools Network tab. The card itself is unchanged: still reads from `hass.states[...]`, no "dev-mode branch".

**Alternative: synthetic inline data.** When HA isn't reachable (offline, CI, contributor without an HA install), inline 1-2 minimal trips directly in `dev/main.ts`. Faster to set up but you maintain fake data and won't catch issues with real-world data shapes:

```ts
const SYNTHETIC: Trip[] = [{ id: "demo", source: "demo", start: { lat: 0.10, lon: 0.10 }, ... }];
card.hass = { states: { [ENTITY]: { attributes: { trips: SYNTHETIC } } } } as any;
```

**Never commit real GPS / activity data as a fixture.** Any real route trace from your home address is PII; ship synthetic-only or use the proxy. Document this in the project's `.gitignore` with patterns like `*-trips.json` to prevent accidents.

### 5b. Deploying to HA

Single-file ES module → `/config/www/community/<name>/<name>.js`. The deploy script:

```sh
# 1. Build
npm run build

# 2. Copy into HA's container. Path on PVE host shares to VM via base64 stream:
sudo qm guest exec 101 --pass-stdin 1 -- bash -c 'cat > /tmp/build.b64' \
  < <(base64 -w0 dist/<name>.js)
sudo qm guest exec 101 -- bash -c \
  "base64 -d /tmp/build.b64 > /tmp/build.js && \
   docker cp /tmp/build.js homeassistant:/config/www/community/<name>/<name>.js"

# 3. Bump cache-bust version in lovelace_resources
sudo qm guest exec 101 -- docker exec homeassistant python -c "
import json
with open('/config/.storage/lovelace_resources') as f: d = json.load(f)
for r in d['data']['items']:
    if '<name>' in r.get('url', ''):
        b, v = r['url'].split('?v=')
        r['url'] = f'{b}?v={int(v) + 1}'
with open('/config/.storage/lovelace_resources', 'w') as f: json.dump(d, f, indent=2)
"

# 4. Reload
mcp__ha__ha_call_service(domain="homeassistant", service="reload_core_config")
```

### 5c. Mobile Companion app cache caveat

The Companion app's service worker caches the lazy-loaded editor chunk separately from the main bundle. `?v=N` cache-bust on the main resource doesn't always invalidate the editor chunk. If the user reports the editor showing stale fields after a deploy:

1. Pull-to-refresh inside the edit dialog
2. Force-close the app (swipe off recent-apps stack)
3. Settings → Companion app → Storage → Clear data
4. Last resort: uninstall + reinstall the app

The same fix sequence on web browsers: hard reload (Ctrl+Shift+R), then DevTools → Application → Service Workers → Unregister.

## Step 6. Validation + verification

### 6a. Build clean

```sh
npm run build
# Expect: ~1 single-file output under 500 KB, ~100 KB gzipped
# No vite warnings about unused exports or eval
```

### 6b. Playwright sanity check on the deployed bundle

Navigate to a dashboard view that uses the card. Then in DevTools console:

```ts
// Verify registered
console.log(!!customElements.get("<name>"));  // -> true

// Verify customCards entry
console.log((window).customCards.find(c => c.type === "<name>"));  // -> entry

// Verify lazy editor loads without throwing
const Ctor = customElements.get("<name>");
const editor = await Ctor.getConfigElement();  // should resolve without error
document.body.appendChild(editor);
// editor.shadowRoot.textContent will show the form fields once setConfig is called

// Verify re-import is idempotent (no duplicate-define error)
await import("/local/community/<name>/<name>.js?again=1");  // should resolve
```

### 6c. Showcase Lovelace view

Build a single dashboard view that exercises every documented card config option. Use real entity data, not fixtures. Each card config in the view tests one feature cluster (default look, threshold colors, custom formats, etc.). The showcase doubles as visual-regression test surface and as user-facing documentation.

## Step 7. Bundle to HACS

When the card is ready for public consumption:

- `hacs.json` at repo root with the full plugin schema:

  ```json
  {
    "name": "Journey Viewer Card",
    "filename": "journey-viewer-card.js",
    "render_readme": true,
    "homeassistant": "2024.7.0",
    "hacs": "1.34.0",
    "hide_default_branch": true,
    "country": ["EU"]
  }
  ```

  Field meanings:
  - `name` (required) - HACS card display name
  - `filename` (required for plugins) - the single ES module HACS will install
  - `render_readme` - render `README.md` instead of `info.md` in HACS UI
  - `homeassistant` - minimum HA version. Set this whenever you use a feature that requires a specific version (e.g. `getGridOptions` → 2024.7+). HACS blocks install on older HA.
  - `hacs` - minimum HACS version. Set when using newer hacs.json features.
  - `hide_default_branch: true` - prevents users from installing pre-release `main`
  - `country` - region restriction list (e.g. `["EU"]`); omit for worldwide

  Don't add `zip_release`, `persistent_directory`, or `content_in_root` — those are integration-only or build-layout-specific keys that don't apply when shipping `dist/<name>.js`.

- `info.md` (optional, for HACS card view if `render_readme` is false) — short pitch + screenshot
- `README.md` — comprehensive: feature list, screenshots from the showcase view, full config schema, examples, troubleshooting
- HACS searches your repo in this order: `dist/` → latest GitHub release assets → repo root. Shipping the build artifact in `dist/<name>.js` (default Vite output) is the right choice; HACS finds it without extra config.
- HACS picks it up automatically once the repo is added by users via "Custom repositories"

### 7a. One repo, not two

Common confusion: should there be a private "developer repo" with dev tooling and a public "user-facing" repo with just the card? Answer: **one repo**. HACS only installs the file named in `hacs.json#filename` — `dev/`, `scripts/`, `docs/`, `.env.local`, `.env.example`, `tsconfig.json`, etc. are invisible to end users at install time. All major HACS cards (mushroom, button-card, apexcharts-card) ship a single repo with full dev tooling alongside the production artifact.

What ends up where:

```
your repo                     →  what HACS user gets
──────────────────────────────────────────────────────
src/        (TS source)       →  (not installed)
dev/        (Vite harness)    →  (not installed)
scripts/    (deploy etc.)     →  (not installed)
docs/       (notes)           →  (not installed)
.env.local  (gitignored)      →  (never in repo)
.env.example                  →  (in repo, no secrets)
dist/<name>.js                →  /config/www/community/<name>/<name>.js
hacs.json                     →  (HACS reads, doesn't install)
README.md                     →  (rendered in HACS UI if render_readme)
```

### 7b. Release-cut workflow

Tag a release whenever the card is ready for users to upgrade. With `hide_default_branch: true` in `hacs.json` (recommended), HACS *requires* a tagged release — installing from `main` is blocked. Standard cycle:

```sh
# 1. Bump CARD_VERSION in src/card.ts (the `console.info` banner) AND
#    package.json#version. HACS displays the latter; the banner shows
#    in DevTools so users can verify which build is loaded.
sed -i 's/CARD_VERSION = "[^"]*"/CARD_VERSION = "0.2.0"/' src/card.ts
npm version 0.2.0 --no-git-tag-version

# 2. Build clean
rm -rf dist && npm run build
# Verify size + that you got a sourcemap
ls -la dist/

# 3. Commit + tag
git add -A
git commit -m "release: v0.2.0"
git tag v0.2.0
git push && git push --tags

# 4. Cut a GitHub release attaching the build artifact. The dist/<name>.js
#    asset is what HACS pulls down on user upgrade — the repo state at the
#    tag is fallback only.
gh release create v0.2.0 dist/<name>.js \
  --title "v0.2.0" \
  --notes "What changed: ..."
```

Releasing from a public repo: anyone with HACS configured can now install. If the repo is private, individual users would need a HACS-side GitHub token with read access — a non-default setup; flip the repo public when you're ready to share.

If you want to test HACS install before tagging, temporarily set `hide_default_branch: false` so HACS can install from `main`. Flip it back once you have releases flowing.

### 7c. Make ready vs publish

Two separate gates:

- **Make ready**: hacs.json valid, dist/ committed, README populated, LICENSE present, at least one tag. *Then* the card *can* install.
- **Publish**: flip the repo to public, optionally submit to the [HACS default repository list](https://github.com/hacs/default) for one-click install (no "Custom repositories" step required for users).

Submitting to default lists is a separate quality bar — most cards live as custom-repos forever and never bother. Don't gate on it.

## Don'ts

- Don't use `@customElement` decorator. Use `customElements.define` inside `if (!customElements.get(...))`.
- Don't import the editor at the top of the card. Lazy-load via `getConfigElement()`.
- Don't watch `hass` in `shouldUpdate` without filtering. Walk the entities you care about.
- Don't subscribe to `hass.connection.subscribeEvents("state_changed", ...)`. Read from `hass.states` and filter via `shouldUpdate`.
- Don't reimplement action handling. Dispatch the `hass-action` event and let HA route it.
- Don't call `hass.localize(your_custom_key)`. It returns the key unchanged. Ship per-language JSON + a `localize()` helper.
- Don't render bare `<div>`s for errors. Use `<hui-warning>` for recoverable, throw in `setConfig` for fatal.
- Don't ship the editor without `loadHaComponents()`. It breaks intermittently for users on fresh dashboard loads.
- Don't put Leaflet / Chart / map construction in `updated()`. Use `firstUpdated()`. Otherwise leaks every render.
- Don't put side effects in `render()` or `willUpdate()`. Use `updated()`.
- Don't recompute per-row decorations on every reactive update. Memoize.
- Don't ship icon-only buttons with only `title`. Add `aria-label`.
- Don't commit real-data fixtures (GPS traces, real device states) when the repo is destined for public. Use the live-HA proxy in dev (Step 5a) or synthetic data near coordinates that can't be reverse-geocoded to your address. Add `*-trips.json` / `sample-data.json`-style patterns to `.gitignore` so accidental writes (e.g. `strava-fixture.py --out`) can't leak.
- Don't use `as unknown as <Type>` casts to silence TS. Restructure typing.
- Don't hardcode VM IDs or paths. Read from `references/hacs-installed.md` etc.

## Real-world example

A paginated GPS journey viewer (working name: `journey-viewer-card`) reading trips from `sensor.<vehicle>_recent_trips`. ~3000 LOC of TS + Lit + Leaflet, single-file ES module ~407 KB / 102 KB gzipped. Deployed to HA + driven by [`ha_toyota:feat/recent-trips-sensor`](https://github.com/nledenyi/ha_toyota/tree/feat/recent-trips-sensor) producing the trip data. A showcase Lovelace view exercises every config option with live data. Repo not yet public; the lessons in this skill are the durable artefact.

This skill's content is distilled from the cleanup pass on that card on 2026-04-27, augmented with online research across HA developer docs, custom-card-helpers, and three reference cards (mushroom, apexcharts-card, button-card).

## Sources

Primary documentation:

- [Custom Card | Home Assistant Developer Docs](https://developers.home-assistant.io/docs/frontend/custom-ui/custom-card/) — canonical method list, error contract, `customCards` registry, schema form structure
- [Action event for custom cards (HA blog 2023-07-07)](https://developers.home-assistant.io/blog/2023/07/07/action-event-custom-cards/) — the `hass-action` event spec
- [Lit lifecycle methods](https://lit.dev/docs/components/lifecycle/) — `firstUpdated` vs `updated` vs `willUpdate`; `updateComplete` promise
- [HACS Plugin Publishing](https://www.hacs.xyz/docs/publish/plugin/) — file discovery order, naming rules
- [HACS hacs.json schema](https://manifest--hacs.netlify.app/developer/general/) — full schema reference; `homeassistant`, `country`, `hide_default_branch`

Reference cards (read the source):

- [custom-card-helpers types.ts](https://github.com/custom-cards/custom-card-helpers/blob/master/src/types.ts) — canonical `HomeAssistant`, `LovelaceCard`, `ActionConfig` union, locale enums
- [lovelace-mushroom loader.ts](https://github.com/piitaya/lovelace-mushroom/blob/main/src/utils/loader.ts) — `loadHaComponents` trick (Step 4d)
- [apexcharts-card](https://github.com/RomRider/apexcharts-card/tree/master/src) — console banner, `actionHandler` directive, `hui-warning` error rendering
- [button-card](https://github.com/custom-cards/button-card) — vendored types pattern, `tap_action` / `hold_action` / `double_tap_action` wiring
- [home-assistant-js-websocket](https://github.com/home-assistant/home-assistant-js-websocket) — only relevant when you actually need to subscribe (rarely)
