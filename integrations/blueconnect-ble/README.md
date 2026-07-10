# blueconnect-ble: a from-scratch passive BLE integration

**Repo:** <https://github.com/nledenyi/blueconnect-ble> (HACS custom repository, [v0.1.0](https://github.com/nledenyi/blueconnect-ble/releases/tag/v0.1.0))
**Device:** 2026-generation Zodiac Blue Connect Gold pool/spa water sensor
**Community thread:** [Zodiac 2026 Blue Connect protocol](https://community.home-assistant.io/t/zodiac-2026-version-blue-connect-pool-water-quality-monitor/1015005) (protocol groundwork by mattsday)

Unlike the other entries in this portfolio (bug fixes in existing
integrations), this one was built from scratch: BLE protocol reverse
engineering, integration architecture, multi-agent pre-release review, HACS
publication. Full byte map with per-field confidence lives in the repo's
[`docs/PROTOCOL.md`](https://github.com/nledenyi/blueconnect-ble/blob/main/docs/PROTOCOL.md).

## What made the reverse engineering hard

The device broadcasts **two interleaved advertisement streams under the same
manufacturer ID** from one MAC:

- a frequent 27-byte beacon with a rolling, high-entropy payload, and
- a sparse 18-byte plaintext readings advert that only ships with a
  measurement (roughly hourly).

Early captures kept landing on the 27-byte beacon, so every decode attempt
produced garbage and spawned increasingly elaborate wrong theories, each
falsified by a cheap decisive experiment before the simple truth emerged:

1. *"The payload is encrypted"* - refuted by entropy structure analysis: the
   churn was a fine-grained advert counter plus framing, not ciphertext.
2. *"The readings are in a BLE-5 extended advert the ESP32 proxies can't
   receive"* - internally consistent (it even explained the proxy fleet's
   silence) and completely wrong.
3. A **phone-side nRF Connect capture** settled it in minutes: a legacy
   18-byte advert, decodable with the community byte map, values matching the
   vendor app (pH exact, ORP within 4 mV).

Lessons that generalize: when a decode yields garbage, first verify you are
decoding **the right payload**, not just the right offsets; and prefer the
cheapest experiment that can kill a theory over the analysis that supports it.
Validation was ground-truth correlation throughout: timestamped captures
paired with vendor-app readings on a real salt-water pool.

## Architecture: rotating MAC as the design driver

The sensor rotates its BLE address, so the textbook
`PassiveBluetoothProcessorCoordinator` (address-bound) would silently die on
every rotation. Instead:

- live data via `async_register_callback` matching on **manufacturer ID**
  (MAC-agnostic, passive scanning mode);
- device identity = the stable serial parsed from the advertised name, never
  the MAC; discovery aborts until the name has been seen;
- on rotation, the coordinator rebinds unavailability tracking to the new
  address, and rediscovery persists it via
  `_abort_if_unique_id_configured(updates=...)`;
- `RestoreSensor` bridges HA restarts, since the next readings advert can be
  an hour away.

## Pre-release multi-agent review

Before publishing, the repo went through a 67-agent review workflow: six
parallel dimensions (HACS compatibility, HA compliance, code quality, protocol
vs docs consistency, privacy sweep, docs accuracy), every finding then
adversarially verified by independent agents. 20 findings survived
verification, including four functional bugs (availability tracking pinned to
a pre-rotation MAC, entities unavailable after every restart, a rotating-MAC
`unique_id` fallback, polling never disabled on push entities) and one
memorable Unicode trap: `"µS/cm"` typed with U+00B5 renders identically to,
but compares unequal with, HA core's U+03BC constant, producing a warning on
every install.

The distilled playbook is the
[`ha-custom-integration`](../../skills/ha-custom-integration/) skill in this
repo.
