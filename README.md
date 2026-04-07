# ha-cameconnect

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-%3E%3D2023.1-blue)](https://www.home-assistant.io)

**Native Home Assistant integration for CAME Connect gates and barriers.**  
No add-on. No proxy. No extra port. Talks directly to the CAME Connect cloud API.

---

## How it works

```
Home Assistant
  └── ha-cameconnect
        └── CAME Connect Cloud API (www.cameconnect.net)
              └── Physical gate / barrier
```

The integration handles OAuth2 Authorization Code + PKCE authentication internally, persists the token via HA's native storage, and refreshes it automatically on expiry.

---

## Prerequisites

You need CAME Connect OAuth credentials:

| Credential | Where to find it |
|---|---|
| **Client ID** | CAME Connect developer portal |
| **Client Secret** | CAME Connect developer portal |
| **Username** | Your CAME Connect username |
| **Password** | Your CAME Connect password |
| **Device ID** | Numeric ID of your gate, visible in the CAME Connect app |

---

## Installation via HACS

1. Open HACS → **Integrations** → ⋮ → **Custom repositories**
2. Add `https://github.com/yashijoe/ha-cameconnect` — Category: **Integration**
3. Search for **CAME Connect** and install
4. Restart Home Assistant

---

## Setup

Go to **Settings → Devices & Services → Add Integration → CAME Connect**.

### Step 1 — Credentials
Enter your CAME Connect OAuth credentials. The integration tests them live against the API before proceeding.

| Field | Description |
|---|---|
| Client ID | OAuth application client ID |
| Client Secret | OAuth application client secret |
| Username | Your CAME Connect username |
| Password | Your CAME Connect password |

### Step 2 — Device
| Field | Description | Example |
|---|---|---|
| **Device name** | Friendly name — used for all entity names | `Main Gate` |
| **Device ID** | Numeric device ID from CAME Connect | `215596` |

To add a second gate, run the integration setup again with a different Device ID and name.

---

## Entities

For each configured device, three entities are created under the same Device card:

### `cover.<device_name>`
Native HA cover entity — `device_class: gate`.

**Supported actions:**

| Action | HA Service | Command ID |
|---|---|---|
| Open | `cover.open_cover` | 2 |
| Close | `cover.close_cover` | 5 |
| Stop | `cover.stop_cover` | 129 |
| Partial open | `cover.open_cover_tilt` | 4 |
| Open/Close toggle | `cover.toggle` | 8 |

**Extra attributes:**

| Attribute | Description |
|---|---|
| `moving` | `true` while gate is in motion |
| `direction` | `opening` / `closing` / `stopped` / `unknown` |
| `online` | Device reachability |
| `raw_code` | Raw numeric state code from CAME API |
| `updated_at` | Timestamp of last state update |
| `maneuvers` | Total maneuver counter |

### `sensor.<device_name>_status`
Raw state string — useful for automations and history graphs.

Values: `open` · `closed` · `opening` · `closing` · `stopped` · `moving` · `unknown`

### `sensor.<device_name>_maneuvers`
Total maneuver counter — incremental sensor tracking the cumulative number of gate operations. Useful for maintenance scheduling.

---

## Example automations

### Notify when gate is left open
```yaml
automation:
  trigger:
    - platform: state
      entity_id: cover.main_gate
      to: open
      for: "00:05:00"
  action:
    - service: notify.mobile_app
      data:
        message: "Gate has been open for 5 minutes!"
```

### Close gate at midnight
```yaml
automation:
  trigger:
    - platform: time
      at: "00:00:00"
  action:
    - service: cover.close_cover
      target:
        entity_id: cover.main_gate
```

### Partial open for pedestrians
```yaml
script:
  gate_pedestrian:
    sequence:
      - service: cover.open_cover_tilt
        target:
          entity_id: cover.main_gate
```

### Alert on maneuver threshold
```yaml
automation:
  trigger:
    - platform: numeric_state
      entity_id: sensor.main_gate_maneuvers
      above: 10000
  action:
    - service: notify.mobile_app
      data:
        message: "Gate has exceeded 10,000 maneuvers — schedule maintenance."
```

---

## Supported languages

🇮🇹 Italian · 🇬🇧 English · 🇫🇷 French · 🇩🇪 German · 🇪🇸 Spanish

---

## Troubleshooting

**"Authentication failed" during setup**  
→ Double-check Client ID, Client Secret, username and password. The integration tests credentials live — if it fails here, the API rejected them.

**State always `unknown`**  
→ Verify the Device ID. Enable debug logs to inspect raw API responses:
```yaml
logger:
  logs:
    custom_components.ha_cameconnect: debug
```

**Commands not working**  
→ The integration tries three endpoint variants per command automatically. Check logs for details.

**Token expired / auth error after days**  
→ The integration re-authenticates automatically on 401. If it keeps failing, re-enter credentials via **Settings → Devices & Services → CAME Connect → Configure**.

---

## Migrating from the proxy add-on

If you were using the `hassio-cameconnect` add-on + REST sensor/template cover:

1. Install this integration and complete setup
2. Remove the old `sensor`, `cover` template and `rest_command` entries from `configuration.yaml`
3. Stop and uninstall the `came_connect` add-on
4. Restart HA

---

## Credits

Based on the original CAME Connect proxy by [@jasonmadigan](https://github.com/jasonmadigan/came-connect).  
CAME Connect cloud API — © CAME S.p.A., Dosson di Conegliano (TV), Italy.
