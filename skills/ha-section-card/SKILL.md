---
name: ha-section-card
description: Build a Home Assistant dashboard section card for a specific device/system (boiler, ventilation, solar inverter, sprinkler, etc.) following the user's unified-look design pattern. Use when the user asks to create a new card/section for controlling or monitoring a device in HA, especially if they mention "section card" or "unified look" or reference the Vitodens card.
argument-hint: "[device-name]"
---

# HA Section Card (unified-look pattern)

The user's preferred pattern for dashboards: a single **sections-view section** per device, with a **40% opacity section background** acting as the unified visual container, and **transparent inner cards** that mix card types (tile, bubble-card, entities) as best fits each entity - so you can pick the right tool per entity but keep a cohesive look.

Reference example: `lovelace-playground/teszt` dashboard → both **Vitodens kazán** and **Hoval szellőztető** sections use the module-based pattern documented here. Read either one via `ha_config_get_dashboard` for a working baseline to adapt.

## Prerequisites

- **Bubble-Card** (HACS frontend, v3.1+) and **Bubble-Card-Tools** (HACS custom integration, `Clooos/Bubble-Card-Tools`) - together they provide a *module store* under `/config/bubble_card/modules/` that holds named CSS snippets attachable to any bubble-card via `modules: [id]`. Check with `ha_hacs_list_installed`. If Tools is missing, add via `ha_hacs_add_repository("Clooos/Bubble-Card-Tools", category="integration")` then `ha_hacs_download` + restart + run the config flow.
- `card-mod` must be loaded (still required for tile/entities-card ha-card transparency - modules don't reach those).
- Sections-view support (HA 2024.3+).

## Modules (unified-look vocabulary)

Four bubble-card modules encode the static CSS for this pattern. Each bubble-card references one module (or none) and only inlines per-card dynamic bits (state-reactive colors, preset highlight templates).

| Module | Purpose | Where to use |
|---|---|---|
| `unified-look-hero` | Strips all wrapper backgrounds + 28px icon + typography bump | The main state card directly below the section heading |
| `unified-look-separator` | Softened divider line (2px / 55% / translucent white) | Every `card_type: separator` |
| `unified-look-control` | Soft translucent pill + typography | Sliders (the pill IS the track) and conditional lock-readout cards paired with a slider |
| `unified-look-control-flat` | Transparent container + typography + dropdown-arrow dim | Preset sub-button heroes, selects - anywhere a pill feels heavy |

**Verify modules exist before authoring.** List via the `bubble_card_tools/list_modules` WebSocket command or `ls /config/bubble_card/modules/`. If any are missing, install from the appendix at the bottom of this skill.

**These modules are not composable with each other** - each represents a distinct visual role. Use exactly one per bubble-card.

**Tiles and entities cards don't use modules** - keep the `card_mod` ha-card-transparent wrapper on them. Modules only reach the inside of a bubble-card's shadow DOM.

## Architecture

```
┌─ SECTION (type: grid, column_span: 1, background: {opacity: 40}) ───┐
│                                                                       │
│  [Heading card]  title + icon + optional badge top-right              │
│                                                                       │
│  [Main status card]  bubble-card state+sub-buttons, show_background:  │
│                      false, transparent .bubble-container/icon-cnt,   │
│                      state_color for liveliness                       │
│                                                                       │
│  [Separator]  bubble-card separator, softened line (2px / 55% / tint) │
│                                                                       │
│  [Readouts]  tiles (one per reading) or pairs via columns: 6          │
│              all with card_mod stripping ha-card background           │
│                                                                       │
│  [Separator]  "Controls" zone                                         │
│                                                                       │
│  [Controls]  bubble-card sliders (softened translucent pill bg) for   │
│              number entities; visibility conditions for mode swaps    │
│                                                                       │
│  [Separator]  "Switches" zone                                         │
│                                                                       │
│  [Switches]  plain entities card with custom icons, tight padding     │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
```

## Workflow

1. **Gather entities.** Before designing, enumerate what the device exposes in HA:
   - Numeric readouts (sensor.*) → go in tiles
   - Binary states (binary_sensor.*) → go as sub-button icons on the main status card
   - User-settable numbers (number.*) → bubble-card sliders
   - Switches (switch.*) → entities card at the bottom
   - A primary "alive" reading (most dynamic %/°C/W) → main card's primary entity for `state_color: true` liveliness
   - A nameplate/identity reading (max capacity, device id) → candidate for heading badge

2. **Identify grouping.** Decide which separator zones to create (typically 3-4: "Mérések"/Measurements, "Vezérlés"/Controls, "Kapcsolók"/Switches). If the user is Hungarian, use Hungarian labels matching their existing conventions.

3. **Plan visibility/conditionals.** If the device has modes (auto vs manual, on vs off), plan which cards swap via `visibility:` conditions.

4. **Write the section.** Use `ha_config_set_dashboard` with `python_transform` to append to the target view's sections. Use `ha_dashboard_find_card` first to get a fresh `config_hash` and locate the target view index (indices shift if the dashboard is edited concurrently).

5. **Verify and iterate.** Ask the user to screenshot and call out what's off. Typical rounds: icon size, background opacity, slider contrast, divider softness, naming consistency, conditional visibility.

## Section boilerplate

```yaml
type: grid
column_span: 1            # 1 = narrow; bump to 2 for wider device dashboards
background:
  opacity: 40             # THE unified-look trick: section bg provides the container
cards:
  # cards go here
```

## Card building blocks

Where `<cm>` appears below, it's this transparent-wrapper card_mod applied to every card that HA puts inside an ha-card:

```yaml
card_mod:
  style: |
    ha-card {
      background: none !important;
      box-shadow: none !important;
      border: none !important;
    }
```

### 1. Heading card with top-right entity badge

```yaml
type: heading
heading_style: title
icon: mdi:home-thermometer         # pick a device-specific icon, avoid overloading mdi:fire etc.
heading: "Device name"
badges:
  - type: entity
    entity: sensor.primary_readout  # the "at-a-glance" value (e.g. boiler water temp)
    name: "Short label"
    show_state: true
    show_icon: true
card_mod:
  style: |
    .container .title { font-size: 22px !important; font-weight: 600 !important; }
    .content { font-size: 22px !important; }
    ha-icon, ha-svg-icon { --mdc-icon-size: 28px !important; }
```

### 2. Main status card (bubble-card state + sub-button icons)

The dense "heart" of the section. Primary entity is the most dynamic live value (%, W, °C); sub-buttons are binary statuses rendered as icons. `modules: [unified-look-hero]` handles transparent wrappers + 28px icons + typography; only per-card state-reactive colors stay inline.

```yaml
type: custom:bubble-card
card_type: button
button_type: state
entity: sensor.live_value           # e.g. burner modulation %, inverter power W
name: "Live label"
icon: mdi:fire                       # main icon (can differ from heading icon)
show_state: true
show_background: false               # bubble-card's native transparent-pill switch
card_layout: large                   # room for sub-buttons beside the main state
state_color: true                    # tints everything when entity is "active"
modules:
  - unified-look-hero                # transparency + typography + 28px sub-button icons
sub_button:
  - entity: binary_sensor.status_1
    icon: mdi:...                    # override with a clearer icon
    show_icon: true
    show_name: false
    show_state: false
    show_background: false
  - entity: binary_sensor.status_2
    icon: mdi:...
    show_icon: true
    show_name: false
    show_state: false
    show_background: false
  # ... up to 4-5 status icons
styles: |
  # ONLY per-card dynamic bits stay here - all static transparency/typography is in the module.
  # ALWAYS use optional chaining ?.state (see Common pitfalls #1).
  .bubble-sub-button-1 ha-icon { color: ${hass.states['binary_sensor.status_1']?.state === 'on' ? '#f44336' : 'var(--secondary-text-color)'} !important; }
  .bubble-sub-button-2 ha-icon { color: ${hass.states['binary_sensor.status_2']?.state === 'on' ? '#f44336' : 'var(--secondary-text-color)'} !important; }
  .bubble-sub-button-3 ha-icon { color: ${hass.states['binary_sensor.fault']?.state === 'on' ? '#f44336' : '#4caf50'} !important; }
card_mod: <cm>
```

**Sub-button indexing**: `.bubble-sub-button-1` through `-4` target each sub-button in order. Use this to color-code individual icons based on their own state (e.g., fault indicator green when OK, red when fault).

### 3. Separator (softened)

```yaml
type: custom:bubble-card
card_type: separator
name: "Mérések"                      # or "Controls", "Switches", etc.
icon: mdi:gauge
modules:
  - unified-look-separator           # 2px / 55% / translucent-white line
card_mod: <cm>
```

### 4. Tile (numeric readouts)

One tile per sensor reading. Pair them side-by-side with `grid_options: {columns: 6}`:

```yaml
type: tile
entity: sensor.xyz
name: "Label"
grid_options:
  columns: 6                         # 12-col HA grid → 6 = half-width pairs
card_mod: <cm>
```

**Showing an attribute on the tile** (e.g. `last_period` of a utility_meter):

```yaml
type: tile
entity: sensor.gas_monthly
name: "Previous month"
icon: mdi:calendar-arrow-left
state_content:
  - last_period                      # renders the attribute's value as the tile state
card_mod:
  style: |
    ha-card {
      background: none !important;
      box-shadow: none !important;
      border: none !important;
    }
    /* Attribute states don't get the entity's unit suffix automatically.
       Append it via CSS ::after on the tile's secondary text element. */
    ha-tile-info $ .secondary::after {
      content: ' kWh';
    }
```

The `::after` CSS trick appends the unit string to the rendered attribute value. The `$` syntax is card_mod's shadow-DOM pierce syntax (needed because `ha-tile-info` renders its content inside a shadow root). Change `kWh` to whatever unit your source entity uses.

If the `::after` doesn't land due to HA version differences in the tile card's internal structure, the fallback is to bake the unit into the card's name: `name: "Previous month (kWh)"`.

### 5. Bubble-card slider (numeric input)

For `number.*` entities where the user wants continuous control. `modules: [unified-look-control]` gives the pill (which IS the slider's track) + typography.

```yaml
type: custom:bubble-card
card_type: button
button_type: slider
entity: number.setpoint
name: "Label"
icon: mdi:...
show_state: true
slider_live_update: true
grid_options:
  columns: 6                         # half-width so pairs fit side-by-side
modules:
  - unified-look-control             # pill version - the pill IS the track
card_mod: <cm>
```

**Important:** sliders REQUIRE the pill variant (`unified-look-control`). The container IS the visible track - going pill-less makes the slider invisible.

**When NOT to use a slider**: the user strongly prefers **preset buttons** over sliders when the useful values are discrete (e.g., fan speed 25/50/75/100%, humidifier 40/45/50/55%). Continuous sliders force visually over-precise control and feel like lost functionality vs preset buttons. Only use the slider when the user really does want 1%-granular values. For discrete presets see §5b below.

Also: bubble-card's slider button_type with `fan` / `humidifier` entities shows state `"on"`/`"off"` as the visible value (not the percentage/humidity) - another reason to prefer presets for those domains.

### 5b. Preset buttons (discrete values)

Preferred pattern for discrete choices: a bubble-card state card whose sub-buttons are tap-to-set preset values. Active preset is highlighted via a styles template. Works for `fan.set_percentage`, `humidifier.set_humidity`, `light.turn_on` with brightness presets, any `call-service` target really.

```yaml
type: custom:bubble-card
card_type: button
button_type: state
entity: sensor.live_value        # something that shows the current live % nicely
                                 # (e.g. sensor.normal_ventilation_modulation reads 50%)
                                 # avoid fan/humidifier as primary - they show on/off text
name: "Speed"
icon: mdi:fan
show_state: true
card_layout: large               # room for the 4 preset sub-buttons beside the state
sub_button:
  - name: "25"
    show_name: true
    show_icon: false
    tap_action:
      action: call-service
      service: fan.set_percentage
      service_data:
        entity_id: fan.xxx
        percentage: 25
  - name: "50"
    show_name: true
    show_icon: false
    tap_action:
      action: call-service
      service: fan.set_percentage
      service_data:
        entity_id: fan.xxx
        percentage: 50
  # ... 75, 100
modules:
  - unified-look-control-flat        # pill-less - sub-button highlighting IS the visual language
styles: |
  # Only the active-preset highlight stays inline (per-card entity + per-card preset values).
  .bubble-sub-button-1 { background-color: ${hass.states['fan.xxx'].attributes.percentage === 25 ? 'rgba(3, 169, 244, 0.35)' : 'transparent'} !important; }
  .bubble-sub-button-2 { background-color: ${hass.states['fan.xxx'].attributes.percentage === 50 ? 'rgba(3, 169, 244, 0.35)' : 'transparent'} !important; }
  .bubble-sub-button-3 { background-color: ${hass.states['fan.xxx'].attributes.percentage === 75 ? 'rgba(3, 169, 244, 0.35)' : 'transparent'} !important; }
  .bubble-sub-button-4 { background-color: ${hass.states['fan.xxx'].attributes.percentage === 100 ? 'rgba(3, 169, 244, 0.35)' : 'transparent'} !important; }
card_mod: <cm>
```

**For humidifier entities** specifically: use `show_state: false, show_attribute: true, attribute: humidity` to display the target humidity value (e.g. "50") as the main state, since the raw entity state is "on"/"off".

**Cyan (#03a9f4 / rgba(3,169,244,...))** is the user's established "active preset" highlight color (matches their reference paper-buttons-row pattern).

### 5c. Bubble-card select (dropdown modes)

For `select.*` entities with a small-to-medium set of options (operating modes, scenes, etc.), use bubble-card's native `select` card type. It renders cleaner than HA's default entities-card dropdown. Go pill-less to match presets in the same Vezérlés zone - the dropdown arrow is enough affordance.

```yaml
type: custom:bubble-card
card_type: select
entity: select.operating_mode
name: "Mode label"
icon: mdi:cog
show_state: true
modules:
  - unified-look-control-flat        # pill-less; the dropdown arrow (dimmed by module) is enough affordance
card_mod: <cm>
```

Place it alongside the other controls in the "Vezérlés" zone, not in "Kapcsolók".

### 6. Conditional card via `visibility:`

Swap between two cards based on a state (e.g., auto mode vs manual mode). Each card has `grid_options: {columns: 6}` and mutually exclusive visibility, so they occupy the same slot:

```yaml
# Card A: shown when auto mode is ON (read-only sensor + lock icon)
- type: custom:bubble-card
  card_type: button
  button_type: state
  entity: sensor.effective_value
  name: "Label"
  icon: mdi:radiator
  show_state: true
  sub_button:
    - icon: mdi:lock
      show_icon: true
      show_name: false
      show_state: false
      show_background: false
  tap_action:     { action: none }
  hold_action:    { action: none }
  double_tap_action: { action: none }
  grid_options: { columns: 6 }
  visibility:
    - condition: state
      entity: switch.mode
      state: "on"
  modules:
    - unified-look-control             # pill matches the sibling slider, so there's no visual jump when the mode toggles

# Card B: shown when auto mode is OFF (live slider)
- type: custom:bubble-card
  card_type: button
  button_type: slider
  entity: number.manual_setpoint
  name: "Label"
  icon: mdi:radiator
  show_state: true
  slider_live_update: true
  grid_options: { columns: 6 }
  visibility:
    - condition: state
      entity: switch.mode
      state: "off"
  modules:
    - unified-look-control             # slider requires the pill (it IS the track)
  card_mod: <cm>
```

Use `visibility:` NOT the `conditional` card wrapper - `visibility:` hides the card entirely (no phantom grid slot).

### 7. Switches (entities card with tight padding + icon/horizontal alignment)

Plain HA entities card at the bottom. Two card_mod tweaks make it sit alongside tile/bubble cards without looking like the runt:
- `padding: 0 8px` on `.card-content` — strips top/bottom (tighten gap to preceding separator) and reduces left/right to ~8px so entity-row icons align horizontally with bubble-card icons.
- Bump `state-badge` to 24px icon / 40px circle so entities icons match the visual weight of tile/bubble icons (default state-badge is smaller).

Override each switch's icon to match the section's visual language:

```yaml
type: entities
entities:
  - entity: switch.mode_auto
    name: "Auto mód (leírás)"
    icon: mdi:weather-partly-cloudy
  - entity: switch.enable_a
    name: "A engedélyezve"
    icon: mdi:radiator
  - entity: switch.enable_b
    name: "B engedélyezve"
    icon: mdi:water-boiler
card_mod:
  style: |
    ha-card {
      background: none !important;
      box-shadow: none !important;
      border: none !important;
      overflow: visible !important;           /* kill scrollbar from padding-reduction */
    }
    .card-content {
      padding: 0 8px !important;              /* tighten top + reduce L/R for icon alignment */
      overflow: visible !important;
    }
    state-badge {
      --mdc-icon-size: 24px !important;
      width: 40px !important;
      height: 40px !important;
    }
```

**DON'T** try to force entity rows to match bubble-card row height with `display: flex / min-height / margin-top` on `#states > *`. It breaks the native row layout: toggles get stretched, secondary text wraps weirdly, and the `multiple-entity-row` content collapses. The mismatch in vertical row height between entities (~40px) and bubble cards (~50px) is acceptable - users tolerate that more than visibly broken toggles.

### 7b. Single-row entities readout (status line under the hero)

When a device has one long-string status (`sensor.xxx_status` = "Normal ventilation") that you'd otherwise split across two tiles (§odd-count handling), a single-row `entities` card placed directly under the hero works well. Same icon/row look as the switches card, but one sensor row instead of multiple switches.

Critical alignment fix: HA's entity-row sets `.info { padding-left: 16px }` by default, which pushes the label text 4px RIGHT of where the bubble-card hero's name starts. To line them up, pierce into the row's nested shadow with card_mod's object form and reduce to 12px:

```yaml
type: entities
entities:
  - entity: sensor.xxx_status
    name: "Állapot"
    icon: mdi:hvac
card_mod:
  style:
    ".": |
      ha-card { background: none !important; box-shadow: none !important; border: none !important; overflow: visible !important; }
      .card-content { padding: 0 8px !important; overflow: visible !important; }
      state-badge { --mdc-icon-size: 24px !important; width: 40px !important; height: 40px !important; }
    hui-sensor-entity-row:
      $:
        hui-generic-entity-row:
          $: |
            .info { padding-left: 12px !important; }
```

**Card-mod nested-pierce syntax cheat**: `style` can be a string (CSS applied to the card's own shadow root) OR an object. In object form, the key `.` means "this card's shadow root", and any other key is an element selector. To enter that element's shadow, nest a `$` key whose value is another object with further selectors, recursing as needed. Do NOT write `"hui-sensor-entity-row $"` (selector with trailing space) as a key - that silently fails; card_mod expects the `$` as its own nested key. And when you switch from string style to object style, you MUST put your original base CSS under the `.` key - otherwise it disappears and card defaults come back (e.g. `.card-content` reverts to 16px padding).

**Ellipsis caveat**: the state text lives in the right half of the row and will ellipsize for long strings like "Summer humidity (free cooling)". If that shows up in the wild, fall back to the split-tile-pair (§7 "Prefer even tile counts" > split-tile-pair).

**When not to use**: in the Mérések zone (inconsistent with chunkier tiles around it). This pattern is for a solo status line directly under the hero, OR replacing the split-tile pair when you want a single card.

## User preferences (learned through iteration)

- **Column width**: `column_span: 1` by default. Only widen to 2 if pairs feel cramped.
- **2-col pairs via `grid_options: {columns: 6}`** for tiles and slider-bubble pairs.
- **Icon overloading**: don't reuse the same icon 3+ times. Pick distinct icons per role (section header, main card, sub-buttons).
- **Max 3 hero sub-buttons** (mobile layout - 4+ starts to crowd). When you have >3 candidate signals, demote the least-critical one to a Mérések tile or drop it if redundant with an existing tile (e.g. a status-text tile already conveys it). Keep only critical + clearly actionable signals on the hero.
- **Max 1 decimal precision** for temperature, percentage, pressure, flow, and other numeric displays in headings / badges / tiles. For sensors that report more precision (e.g. ESPHome reports `49.59765625`), set `display_precision: 1` on the entity registry via WebSocket: `hass.callWS({type: 'config/entity_registry/update', entity_id, options_domain: 'sensor', options: {display_precision: 1}})`. This is a per-entity one-time setting; it persists across restarts.
- **Prefer even tile counts in Mérések**. An odd count visually unbalances the 2-column grid (leaves one tile half-width alone at the end). If a device naturally produces an odd count, handle it in this order of preference:
  1. **Split-tile pair** for variable-length text (PREFERRED): if one readout carries a status/enum/mode/fault string that could run long (e.g. `sensor.hoval_homevent_status` = "Summer humidity (free cooling)"), split it across **two half-width tiles** referencing the same entity. Left tile shows icon + name with the state hidden; right tile shows only the state value (icon and name hidden). This keeps the section's tile aesthetic, gives the long state value its own half-width text slot (no truncation), AND occupies one full row to keep the count even.
     ```yaml
     # Left half: name + icon, no state
     - type: tile
       entity: sensor.xxx_status
       name: "Állapot"
       icon: mdi:hvac
       hide_state: true                # built-in tile option, cleanest
       grid_options: { columns: 6 }
       card_mod:
         style: |
           ha-card { background: none !important; box-shadow: none !important; border: none !important; }
     # Right half: just the state value, right-aligned
     - type: tile
       entity: sensor.xxx_status
       name: " "                       # space prevents friendly_name fallback
       grid_options: { columns: 6 }
       card_mod:
         style: |
           ha-card { background: none !important; box-shadow: none !important; border: none !important; }
           ha-tile-icon { display: none !important; }
           ha-tile-info { width: 100% !important; }
           ha-tile-info span[slot="primary"] { display: none !important; }
           ha-tile-info span[slot="secondary"] { display: block !important; width: 100% !important; text-align: right !important; padding-right: 8px !important; font-size: 14px !important; font-weight: 500 !important; color: var(--primary-text-color) !important; }
     ```
     **Tile shadow DOM cheat**: the state-text element is a *light-DOM SPAN* child of `<ha-tile-info>` with `slot="secondary"` - NOT with class `secondary` (that older selector matches nothing on current HA). Target it via `ha-tile-info span[slot="secondary"]` as a regular descendant selector through card_mod. Do NOT use card_mod's `$` pierce syntax - that targets the `<slot>` projection nodes inside ha-tile-info's shadow, not the visible span.

     **Right-aligning the value**: the ha-tile-info's `.info` div is `display: flex` and only as wide as its content by default. To push text to the right edge you need `ha-tile-info { width: 100% }` AND `span[slot="secondary"] { display: block; width: 100%; text-align: right; padding-right: 8px }`. Without the width rules the span shrinks to its content and `text-align: right` is a no-op.
     
     **Why not full-width single tile**: a full-width tile still stacks name above state on the LEFT side, wasting the right half and visually unbalancing.
     
     **Why not single-row entities card** (in Mérések): looks "thin" and inconsistent next to the chunkier tiles in the Mérések group. Note: a single-row entities card CAN work for a solo readout directly under the hero (outside Mérések) - see the "Single-row entities readout" subsection below.
  2. Drop a redundant tile already represented on the hero or in Vezérlés.
  3. Add a small complementary readout (e.g. setpoint alongside the measured value).
  4. Ask the user which direction they prefer.
  
  Do not silently ship an odd-count narrow-tile Mérések.
- **Bubble-card sliders**: keep the pill-style track visible but softened (rgba 0.08 alpha). A fully transparent slider is unusable.
- **Dividers**: softened to 2px / 0.55 opacity / 0.5 alpha white.
- **Main icon opacity**: always force `.bubble-main-icon { opacity: 1 !important }` - bubble-card dims to 0.6 when state is "off-like", which looks wrong when the entity is a sensor reading 0 (not actually off).
- **Hungarian naming convention**: match user's existing patterns. Current conventions:
  - "Mérések" (Measurements), "Vezérlés" (Controls), "Kapcsolók" (Switches)
  - "Fűtés" (CH/heating), "Melegvíz" (DHW/hot water) - prefer "Melegvíz" over "HMV" in user-facing labels
  - "Szellőztető" (ventilator), "Működési mód" (operating mode), "Sebesség" (speed), "Páratartalom cél" (humidity target)
  - Monthly meters: "{zone} aktuális hó" / "{zone} előző hó"
- **Typography uniformity**: bubble-card defaults (13px bold name + 12px/0.7 state) read smaller than tile defaults (~14px / ~14px). When mixing transparent bubble cards alongside tiles in the same section, bump bubble typography to `14px` name and `14px normal / 0.85 opacity` state so both card types feel like siblings. Apply via the bubble card's `styles:` block.

## CSS cheat sheet for bubble-card internals

Bubble-card uses Shadow DOM with several nested background layers. To kill or tint each:

| Class | What it is | Typical override |
|---|---|---|
| `.bubble-button-card-container` | Outer wrapper - applies state-colored bg when `state_color: true` AND entity is non-zero/"on". Must override to transparent when you want the hero to integrate with section bg | `background: transparent !important` |
| `.bubble-button-container` | Sibling outer wrapper that also carries state-color bg | `background: transparent !important` |
| `.bubble-main-icon-container` | Circular container behind the main icon, also state-colored | `background: transparent !important` |
| `.bubble-container` | Outer 50px pill, the visible rounded bg of every bubble card | `background-color: transparent` (state/button) or `rgba(255,255,255,0.08)` (slider) |
| `.bubble-background` | Inner hover/active fill layer | `background-color: transparent !important; opacity: 0 !important` |
| `.bubble-icon-container` | Dark circle behind the main icon | `background-color: transparent` or soft tint |
| `.bubble-main-icon` | The actual `<ha-icon>` element of the main icon | `opacity: 1 !important` (force full opacity regardless of state) |
| `.bubble-sub-button` | Each sub-button container | Usually fine at defaults |
| `.bubble-sub-button ha-icon` | Sub-button icon element | `--mdc-icon-size: 28px` to enlarge |
| `.bubble-sub-button-N ha-icon` (N = 1..4) | Nth sub-button icon specifically | Target for per-sub-button color coding via `${...}` template |
| `.bubble-line` | Separator's divider line | `height: 2px; opacity: 0.55; background: rgba(255,255,255,0.5)` |
| `.bubble-name` | Card's primary label text | Default 13px bold; override to `font-size: 14px !important; font-weight: 500 !important;` to match tile primary |
| `.bubble-state` | Card's state/value text | Default 12px / 0.7 opacity; override to `font-size: 13px !important;` to match tile secondary |
| `.bubble-dropdown-arrow` | Chevron on select card | `opacity: 0.4` to soften |
| `state-badge` (entities card) | Entity-row icon container | `--mdc-icon-size: 24px; width: 40px; height: 40px` to match tile/bubble icon weight |
| `.card-content` (entities card) | Entities card inner content wrapper | `padding: 0 8px` to align entity-row icons horizontally with bubble icons (and tighten top gap) |

**`styles:` vs `card_mod:`** - bubble-card has its own `styles:` property that targets its internal DOM (classes above). Use `styles:` for bubble-card internals. Use `card_mod:` for the outer `ha-card` wrapper (strip bg/shadow/border). Both can coexist on the same card.

**Templating in styles**: bubble-card's `styles:` supports JS template literals `${hass.states['entity.id'].state === 'on' ? '...' : '...'}` for state-reactive CSS. Reference: https://github.com/Clooos/Bubble-Card

## Common extensions

### State-reactive color (green OK / red fault)

Applied to a specific sub-button in the main status card:

```css
.bubble-sub-button-4 ha-icon {
  color: ${hass.states['binary_sensor.fault']?.state === 'on' ? '#f44336' : '#4caf50'} !important;
}
```

### State-reactive main icon color

For heroes with a `state_color: true` main entity, override the main icon's color directly based on an entity state (or numeric threshold). This is how the Vitodens hero shows a RED flame when burner_modulation > 0 and a RED faucet when DHW is actively drawing hot water:

```css
/* numeric threshold (e.g. modulation > 0) */
.bubble-main-icon {
  color: ${(parseFloat(hass.states['sensor.burner_modulation']?.state) || 0) > 0 ? '#f44336' : 'var(--secondary-text-color)'} !important;
}

/* binary state (e.g. active radiator) — use on a sub-button */
.bubble-sub-button-1 ha-icon {
  color: ${hass.states['binary_sensor.ch_active']?.state === 'on' ? '#f44336' : 'var(--secondary-text-color)'} !important;
}
.bubble-sub-button-2 ha-icon {
  color: ${hass.states['binary_sensor.dhw_active']?.state === 'on' ? '#f44336' : 'var(--secondary-text-color)'} !important;
}
```

Note: always use `?.state` (optional chaining) and a default fallback via `|| 0` for numeric cases - see "Common pitfalls" section above.

### State-attribute-derived tile (when HA tile doesn't show the unit)

For utility_meter or similar entities where you want to display the `last_period` attribute as a tile but need the unit suffix (e.g. `kWh`), do NOT rely on the `state_content: [last_period]` + CSS `::after { content: ' kWh' }` trick - HA's tile shadow DOM changes across versions and the `::after` often doesn't land. Instead, create a template sensor that exposes the attribute as its own state with the proper unit, then point the tile at the template sensor:

```yaml
# In configuration.yaml under template:
- sensor:
    - name: "Gas CH Last Month"
      unique_id: gas_ch_last_month
      state: "{{ state_attr('sensor.gas_ch_monthly', 'last_period') | float(0) | round(2) }}"
      unit_of_measurement: "kWh"
      device_class: energy
      state_class: total
```

Then in the tile, just use the template sensor as a normal entity - HA will show the state with the unit automatically. Works across HA versions.

### Monthly utility meter pair (current + previous month)

For a `utility_meter` helper cycling monthly, show both in 4 tiles:

```yaml
# Current month
- type: tile
  entity: sensor.gas_ch_monthly
  name: "Fűtés aktuális hó"
  grid_options: { columns: 6 }
  card_mod: <cm>
# Previous month (via last_period attribute)
- type: tile
  entity: sensor.gas_ch_monthly
  name: "Fűtés előző hó"
  icon: mdi:calendar-arrow-left
  state_content: [last_period]
  grid_options: { columns: 6 }
  card_mod: <cm>
```

## Reference example

The canonical implementation is the **Vitodens kazán** section in the `lovelace-playground/teszt` view. Before building a new card, fetch it for a current working baseline:

```
ha_dashboard_find_card(url_path="lovelace-playground", heading="Vitodens kazán")
ha_config_get_dashboard(url_path="lovelace-playground")
# Then jq to .config.views[N].sections[M] where N/M come from find_card
```

The section covers: boiler water temp (heading badge), burner modulation (main card primary), 4 status icons (flame/CH/DHW/fault with color template), gas meters (current + prev month tiles), pressure tile, CH setpoint active tile, conditional CH slider/locked-readout via visibility on auto-mode switch, DHW slider, 3 switches with custom icons.

## Tool usage notes

- Use `python_transform` over `jq_transform` - works cross-platform and supports more expressive edits.
- **Never use negative list indices** in python_transform (forbidden). Use explicit positive indices from `ha_dashboard_find_card` output.
- After any structural change (delete/insert cards), get a fresh `config_hash` before the next edit - stale hashes fail with "Dashboard modified since last read".
- `ha_config_get_dashboard` output can be very large (100KB+); the tool saves to a file and you should `jq` into specific paths rather than reading the whole thing.

### python_transform sandbox gotchas

The Python sandbox is strict. These common idioms are **forbidden**:
- `def` function definitions → inline the logic instead.
- `range()`, `enumerate()` builtins → unroll small loops or use list literals.
- `try/except` → validate in advance instead.
- Negative indices like `cards[-1]` → use explicit positive index.

**What IS allowed**: assignment, `for x in list_literal:`, list comprehensions `[... for x in ...]`, if/else, dict/list methods (`.append`, `.insert`, `.pop`, `.get`, `.update`), string methods, `del config['k']`.

**Practical consequence**: when you need to build N similar sub-button configs with indexed CSS selectors (e.g. `.bubble-sub-button-1 ... -4`), **don't try to generate them programmatically** - just write out the 3-5 repetitive blocks explicitly. Reads fine and the sandbox accepts it.

Example of what NOT to do inside python_transform:

```python
# ❌ FAILS: def forbidden
def make_preset(i, v): return {"name": str(v), ...}

# ❌ FAILS: enumerate forbidden
for i, v in enumerate(presets): styles += f"..."

# ❌ FAILS: range forbidden
for i in range(4): styles += f"..."
```

Example of what works:

```python
# ✅ OK: list literal, no iteration helpers needed
styles = (
  ".bubble-sub-button-1 { ... === 25 ... }\n"
  ".bubble-sub-button-2 { ... === 50 ... }\n"
  ".bubble-sub-button-3 { ... === 75 ... }\n"
  ".bubble-sub-button-4 { ... === 100 ... }\n"
)

# ✅ OK: for-in over list literal
presets = [25, 50, 75, 100]
subs = [{"name": str(v), "tap_action": {...}} for v in presets]
```

## Common pitfalls with bubble-card `styles:` block

Most of the tricky static CSS now lives in the modules (verified once) - these pitfalls apply to the per-card inline `styles:` block that stays on heroes (state-reactive colors) and preset cards (active-highlight templates).

These are all silent failures - the styles look correct in the config but don't apply to the rendered DOM. Diagnose by opening Playwright against the dashboard and reading the bubble-card's shadow DOM `<style>` tags: if they are empty while the config has `styles`, the parser failed.

1. **Template-literal reference to a non-existent entity.**
   `${hass.states['binary_sensor.foo'].state === 'on' ...}` throws when `states['binary_sensor.foo']` is `undefined` (the entity hasn't been created yet, or was removed). Bubble-card catches the throw and **discards the entire styles block**, not just the broken line. Always use optional chaining: `hass.states['...']?.state === 'on'`. This matters especially after you add new entities to `configuration.yaml` but the user hasn't reloaded MQTT / restarted HA yet.

2. **CSS comments `/* ... */` inside the styles block.** Bubble-card's template-literal parser treats the whole block as a JS template string, and `/* */` can confuse it. Keep all comments OUTSIDE the `styles:` value. If you want annotations, put them in a YAML `# comment` above the `styles:` line.

3. **Multi-line CSS selectors.** Write each rule on a single line:
   ```css
   .bubble-container, .bubble-background { background: transparent !important; }   /* GOOD */
   ```
   Do NOT do:
   ```css
   .bubble-container,
   .bubble-background {
     background: transparent !important;
   }                                                                                 /* BAD - silently drops */
   ```

4. **`.bubble-container { background-color: transparent }` alone doesn't fully kill the hero's dark pill.** When `state_color: true` AND the entity is in a non-zero / non-off state, bubble-card paints *multiple* wrapper elements: `.bubble-button-card-container`, `.bubble-button-container`, `.bubble-main-icon-container`. All of them need explicit `background: transparent !important`. The CSS cheat sheet above lists every class that needs overriding. If your hero's entity happens to read 0/"off" during development, this bug will be INVISIBLE (no bg painted) until the entity becomes active in production.

5. **Static icon size vs state-conditional color for sub-buttons coexist — separately.** Put `.bubble-sub-button ha-icon { --mdc-icon-size: 28px }` as a blanket rule, and then add per-button color rules `.bubble-sub-button-N ha-icon { color: ${...} }` after. Don't try to merge them into one rule - bubble-card's parser handles separate rules more reliably than compound ones with template literals.

6. **Hero font-size vs tile font-size mismatch.** Bubble-card defaults (13px name, 12px state) render visibly smaller than tile defaults (14px primary, 13px secondary). In mixed sections this makes the hero look "less important" than readouts below it. Always bump hero to `.bubble-name { font-size: 14px !important; font-weight: 500 !important; } .bubble-state { font-size: 13px !important; }`.

7. **Diagnostic recipe.** When styles aren't applying:
   - Playwright: `document.querySelector('home-assistant').hass.states['entity.id']` - does the entity exist?
   - Walk the bubble-card's shadow DOM and find all `<style>` elements. The `styles:` config value should appear in one of them. If it's empty or missing text you wrote, the parser dropped it.
   - Diff against a bubble-card that IS working (e.g. the Vitodens one) - usually the difference is one of pitfalls 1-3 above.

## Don'ts

- Don't create documentation files, helper sensors, or template scaffolding unless the user asks. This skill produces a dashboard section; other artifacts are separate conversations.
- Don't auto-ship changes to the user's main dashboard (`lovelace-home`). Work in `lovelace-playground` until they explicitly say to promote.
- Don't reference device-specific Hungarian labels ("Fűtés", "Melegvíz") as canonical - those are Vitodens-specific. For a new device, ask the user for their preferred naming or pick neutral Hungarian/English.
- Don't use `show_background: false` alone and assume bubble-card's bg is gone. That only affects the `.bubble-background` layer; you also need `.bubble-container { background-color: transparent }` for a fully transparent pill. See the CSS cheat sheet.

## Appendix: module YAML (install on a fresh HA instance)

If the 4 unified-look modules aren't present in `/config/bubble_card/modules/`, install them via the Bubble-Card-Tools WebSocket API (`bubble_card_tools/write_module`) with these files. Each is a top-level YAML dict keyed by the module id.

### `unified-look-hero.yaml`

```yaml
unified-look-hero:
  name: Unified look - hero/status card
  version: v1.0
  creator: nledenyi
  description: Strips all background layers and bumps typography so a bubble-card hero/status card blends into a section background (opacity 40%). Use on the main state card that sits just under the section heading.
  supported: [button, select, sub-buttons]
  code: |
    .bubble-button-card-container { background: transparent !important; background-color: transparent !important; }
    .bubble-button-container { background: transparent !important; background-color: transparent !important; }
    .bubble-background { background: transparent !important; background-color: transparent !important; opacity: 0 !important; }
    .bubble-icon-container { background: transparent !important; background-color: transparent !important; }
    .bubble-main-icon-container { background: transparent !important; background-color: transparent !important; width: 42px !important; height: 42px !important; }
    .bubble-container { background-color: transparent !important; }
    .bubble-main-icon { --mdc-icon-size: 28px !important; opacity: 1 !important; }
    .bubble-name { font-size: 14px !important; font-weight: 500 !important; }
    .bubble-state { font-size: 13px !important; }
    .bubble-sub-button ha-icon { --mdc-icon-size: 28px !important; }
```

### `unified-look-separator.yaml`

```yaml
unified-look-separator:
  name: Unified look - softened separator
  version: v1.0
  creator: nledenyi
  description: Softens the divider line on a bubble-card separator (2px height, 0.55 opacity, translucent white). Use on every separator inside a unified-look section.
  supported: [separator]
  code: |
    .bubble-line { height: 2px !important; opacity: 0.55 !important; background: rgba(255, 255, 255, 0.5) !important; }
```

### `unified-look-control.yaml`

```yaml
unified-look-control:
  name: Unified look - control pill
  version: v1.0
  creator: nledenyi
  description: Soft translucent pill style for bubble-card controls where the pill is useful (sliders, conditional lock-readout cards that pair with a slider). Preset highlighting and state-reactive bits stay inline per-card.
  supported: [button, select, sub-buttons]
  code: |
    .bubble-container { background-color: rgba(255, 255, 255, 0.08) !important; }
    .bubble-icon-container { background-color: rgba(255, 255, 255, 0.12) !important; }
    .bubble-main-icon { opacity: 1 !important; }
    .bubble-name { font-size: 14px !important; }
    .bubble-state { font-size: 14px !important; font-weight: normal !important; opacity: 0.85 !important; }
    .bubble-dropdown-arrow { opacity: 0.4 !important; }
```

### `unified-look-control-flat.yaml`

```yaml
unified-look-control-flat:
  name: Unified look - flat (pill-less) control
  version: v1.0
  creator: nledenyi
  description: Transparent container + typography bump for bubble-card controls that should blend into the section background (no pill). Works for preset sub-button heroes, selects, and anywhere the pill would feel heavy. Preset highlighting and state-reactive bits stay inline per-card.
  supported: [button, select, sub-buttons]
  code: |
    .bubble-container { background-color: transparent !important; }
    .bubble-icon-container { background-color: transparent !important; }
    .bubble-main-icon { opacity: 1 !important; }
    .bubble-name { font-size: 14px !important; }
    .bubble-state { font-size: 14px !important; font-weight: normal !important; opacity: 0.85 !important; }
    .bubble-dropdown-arrow { opacity: 0.4 !important; }
```

Install script (Python, using `websockets`):

```python
# Send this websocket command for each file:
{"type": "bubble_card_tools/write_module", "name": "unified-look-hero.yaml", "content": "<file contents>"}
```
