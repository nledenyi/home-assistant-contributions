---
name: ha-custom-integration
description: Develop, review and publish an own Home Assistant custom integration (HACS custom repository). Use when building a new integration, adding entities/features to an integration you maintain, or preparing/releasing to HACS. NOT for fixing third-party integrations upstream - that is ha-integration-fix.
argument-hint: "[domain or repo path]"
---

# HA custom integration development

Canonical worked example: [blueconnect-ble](https://github.com/nledenyi/blueconnect-ble)
(`blueconnect_ble`). It survived a 67-agent review + hassfest + the HACS
action; when in doubt, copy its patterns.

## Repo layout (HACS custom repository)

```
custom_components/<domain>/   # the integration - only this gets installed
  manifest.json  __init__.py  config_flow.py  const.py  coordinator.py
  sensor.py  strings.json  translations/en.json
tests/            # pure-python tests + conftest.py (see Tests)
docs/             # public docs only (see Publishing)
hacs.json  README.md  LICENSE  CONTRIBUTING.md  .gitignore
.github/workflows/validate.yml
```

## manifest.json - hassfest will check this

- Key order: `domain`, `name` first, then **alphabetical** - so `version`
  goes LAST. Wrong order fails hassfest.
- `version` is REQUIRED for custom integrations (not for core).
- Include `documentation`, `issue_tracker`, `codeowners`, `iot_class`,
  `integration_type`, `config_flow`.
- Bluetooth: `"bluetooth": [{"connectable": false, "manufacturer_id": N}]` -
  `connectable: false` is what lets passive Shelly proxies deliver adverts.

## hacs.json

`{"name": "...", "homeassistant": "<min HA>", "render_readme": true}`.
`render_readme: true` makes **README.md the HACS store page** - it must
describe the CURRENT state (entity list matching the code, correct units,
disabled-by-default entities called out). Stale "not yet implemented" text or
a sensor list that drifted from the `SENSORS` tuple is a release blocker.

## Entity / code checklist (each item was a real caught bug)

- **Push-based entities**: `_attr_should_poll = False` on the entity class.
  `PARALLEL_UPDATES = 0` does NOT disable polling; only `should_poll` does.
- **Units: ALWAYS core constants**, never string literals. Trap that bit us:
  `"µS/cm"` (U+00B5 MICRO SIGN) != core's `UnitOfConductivity
  .MICROSIEMENS_PER_CM` = `"μS/cm"` (U+03BC GREEK MU). Renders identically,
  compares unequal, warns on every install. A literal is OK only when core
  has no constant (e.g. `"g/L"` on a device_class-less sensor).
- `_attr_has_entity_name = True`, stable `_attr_unique_id`
  (`f"{serial}_{key}"`), one `DeviceInfo` per device (identifiers by serial,
  `connections={(CONNECTION_BLUETOOTH, addr)}`).
- Unconfirmed/debug fields: `EntityCategory.DIAGNOSTIC` +
  `entity_registry_enabled_default=False`.
- Sparse push sources (BLE adverts, webhooks): extend `RestoreSensor` so
  values survive restarts; gate `available` on presence + (live or restored
  value).
- `entry.runtime_data` + `type MyConfigEntry = ConfigEntry[MyCoordinator]`
  in `__init__.py`; in coordinator.py import it under `TYPE_CHECKING` to
  annotate `entry` (avoids the circular import, keeps mypy honest).
- Options that must apply instantly (e.g. calibration offsets): update
  listener calls `coordinator.async_notify_listeners()`, NOT `async_reload`
  (reload drops current state).
- strings.json may use `[%key:common::...%]` references; translations/en.json
  must carry the literal text. Every abort reason returned in code needs an
  entry in BOTH files.
- No unused imports / dead constants - `ruff check` must pass; CONTRIBUTING
  promises it.

## Bluetooth with a rotating MAC (blueconnect pattern)

- Identity = stable serial parsed from the advertised name, NEVER the MAC.
  In `async_step_bluetooth`, if the name/serial is not in the advert yet,
  `return self.async_abort(reason="no_serial")` - discovery re-triggers when
  an advert carrying the name arrives. No MAC fallback for unique_id.
- On rediscovery: `self._abort_if_unique_id_configured(updates={CONF_ADDRESS:
  info.address, CONF_NAME: info.name})` - persists the rotated address and
  reloads the entry. Same in the user step.
- Live data path: `async_register_callback` with a
  `BluetoothCallbackMatcher(manufacturer_id=...)` (MAC-agnostic), PASSIVE
  mode. Accept a different address only when the serial matches, then rebind
  `async_track_unavailable` to the new address (keep its cancel handle in an
  attribute; register one `async_on_unload` that cancels whatever is current).
- Seed on start from `async_last_service_info(hass, addr, connectable=False)`
  and `async_address_present(...)`.
- `async_discovered_service_info(hass, connectable=False)` in the user step -
  the default `connectable=True` hides devices seen only via passive proxies.

## Tests

- Keep the protocol decoder pure Python (stdlib only) so tests run without HA.
- `tests/conftest.py` loads it by file path and registers it in `sys.modules`
  under its dotted name **BEFORE `exec_module`** - dataclass machinery
  resolves the module by name during exec and crashes otherwise:
  ```python
  spec = importlib.util.spec_from_file_location(NAME, PATH)
  module = importlib.util.module_from_spec(spec)
  sys.modules[NAME] = module      # BEFORE exec
  spec.loader.exec_module(module)
  ```
- Pin real captured payloads with expected decoded values as regression
  tests; sanitize identifying serials in fixtures/docstrings first.

## Publishing to GitHub / HACS

- **.gitignore internal files from the FIRST commit** - deleting later leaves
  them in history. Exclude agent/session notes, RE/capture tooling, spec-kit
  internals, and any reverse-engineering process docs (decompilation
  write-ups of proprietary apps stay private).
- **Privacy grep over `git ls-files` before every push**: real MAC addresses
  (`([0-9A-F]{2}:){5}[0-9A-F]{2}`), device serials, LAN IPs (`192\.168\.`),
  hostnames, room names, filesystem paths that map your infrastructure.
  Replace real serials in code examples with fabricated same-shape ones.
- README needs: entity list matching code, hardware requirements, install
  steps, first-reading latency expectations, known limitations,
  "not affiliated with <vendor>" line, credits to protocol sources, and an
  AI-disclosure section if AI wrote the code.
- GitHub repo needs **topics** (the HACS action check fails with zero topics).
- CI `.github/workflows/validate.yml`: three jobs - `home-assistant/actions/
  hassfest@master`, `hacs/action@main` (`category: integration`,
  `ignore: brands` until a brands PR exists), and setup-python + `ruff check`
  + `pytest`.
- **The HACS action false-fails on PRIVATE repos**: it fetches
  hacs.json/manifest via raw URLs -> "expected a dictionary. Got None".
  Staging private for review and then flipping public is fine; just re-run
  validation after going public.
- Review-safe publish flow: create the repo `--private`, push, review the
  exact public content, then `gh repo edit <repo> --visibility public` and
  re-run validation.
- HACS versioning: no GitHub release = HACS installs the default branch;
  tagged releases (vX.Y.Z matching manifest `version`) give users pinned
  updates. Bump the manifest version with every release.

## Before first public release

Run a structured multi-dimension review (HACS compat, HA compliance, code
quality, protocol-vs-docs consistency, privacy sweep, docs accuracy - then
adversarially verify each finding). The blueconnect first pass found 20 real
issues including 4 functional bugs. Cheap insurance.
