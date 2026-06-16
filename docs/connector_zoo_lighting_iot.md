# Lighting, IoT, and Automation Connector Expansion

This bundle adds ten new optional Connector Zoo entries for common lighting, IoT, and automation
systems. The selection is intentionally biased toward the kinds of consumer smart-home platforms
that recur across IFTTT's public service catalog.

They are modeled as operator-installable connector plugins so they show up in the Connector Zoo and
generic connector registry without expanding the built-in connector set.

## Added systems

1. `lifx`
   - system: LIFX Cloud
   - category: lighting
   - primary use: cloud light selection, scenes, color, brightness, and transition control
   - core fields: `api_token`, `selector`, `power_state`, `color`, `brightness`

2. `kasa`
   - system: TP-Link Kasa
   - category: lighting
   - primary use: smart-plug, bulb, and strip device actions through a bridge or local API proxy
   - core fields: `base_url`, `username`, `password`, `device_alias`, `command`

3. `smartlife`
   - system: Smart Life
   - category: automation
   - primary use: scene and device execution for Tuya and Smart Life ecosystems
   - core fields: `base_url`, `access_token`, `device_id`, `scene_id`, `command`

4. `smartthings`
   - system: Samsung SmartThings
   - category: automation
   - primary use: device command routing through the SmartThings API
   - core fields: `base_url`, `personal_access_token`, `device_id`, `component`, `command`

5. `switchbot`
   - system: SwitchBot
   - category: iot
   - primary use: scenes, curtain control, bot actions, and device-state commands
   - core fields: `base_url`, `token`, `secret`, `device_id`, `command`, `scene_name`

6. `wiz`
   - system: WiZ
   - category: lighting
   - primary use: cloud room, light, scene, and brightness automation
   - core fields: `base_url`, `access_token`, `room_id`, `light_id`, `scene_id`, `brightness`

7. `tplink_tapo`
   - system: TP-Link Tapo
   - category: iot
   - primary use: cameras, plugs, bulbs, and smart-device actions across Tapo deployments
   - core fields: `base_url`, `access_token`, `device_id`, `command`, `parameters`

8. `lutron_caseta`
   - system: Lutron Caseta and RA2 Select
   - category: lighting
   - primary use: lighting scene, dimmer, and shade automation through the Lutron cloud stack
   - core fields: `base_url`, `access_token`, `device_id`, `scene_id`, `level`

9. `ewelink`
   - system: eWeLink Smart Home
   - category: iot
   - primary use: switch, light, and scene control across eWeLink-managed devices
   - core fields: `base_url`, `access_token`, `device_id`, `scene_id`, `command`

10. `homeseer`
    - system: HomeSeer
    - category: automation
    - primary use: event, device, and scene execution across HomeSeer automations
    - core fields: `base_url`, `access_token`, `device_ref`, `event_name`, `command`

## Runtime scope

- These additions are Connector Zoo and plugin-catalog entries, not new vendor-specific transport drivers.
- They are immediately available to operators as installable/configurable connector definitions.
- Provider-specific runtime send logic can be layered on later without changing the Connector Zoo
  contract or the persisted connector endpoint shape.
