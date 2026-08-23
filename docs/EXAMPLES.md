# Examples

Worked examples for the use cases listed in the
[README](../README.md#use-cases). Each one states the goal, what it needs, and
the YAML to paste.

Entity IDs below assume the default device name, `Divoom Times Gate`. Check your
own IDs under **Settings > Devices & services > Divoom Times Gate**.

## Flash a doorbell alert on the middle screen

**Goal.** Notice a doorbell press from across the room without picking up your
phone.

Screen 2 (index 2) flashes red text for 15 seconds, then goes back to whatever it
was showing.

```yaml
automation:
  - alias: Doorbell on the Times Gate
    triggers:
      - trigger: state
        entity_id: binary_sensor.front_door_bell
        to: "on"
    actions:
      - action: divoom_times_gate.show_message
        data:
          screen: 2
          text: DOORBELL
          color: "#FF0000"
          duration: 15
```

`show_message` reverts the screen on its own when `duration` runs out. You do not
need a second automation to clean up.

## Show the camera at the front door for 30 seconds

**Goal.** See who is there, not only that someone is there.

This snapshots a camera to a file, then puts that file on screen 2 for 30
seconds.

```yaml
automation:
  - alias: Front door camera on the Times Gate
    triggers:
      - trigger: state
        entity_id: binary_sensor.front_door_bell
        to: "on"
    actions:
      - action: camera.snapshot
        target:
          entity_id: camera.front_door
        data:
          filename: /config/www/doorbell.jpg
      - action: divoom_times_gate.show_image
        data:
          screen: 2
          image_path: /config/www/doorbell.jpg
          fit: cover
          duration: 30
```

`fit: cover` centre-crops the frame to the square screen. Use `fit: contain` to
letterbox the full frame on black instead.

## Warn when the washing machine finishes

**Goal.** Get a message on the clock instead of another phone notification.

```yaml
automation:
  - alias: Washing machine done
    triggers:
      - trigger: numeric_state
        entity_id: sensor.washing_machine_power
        below: 5
        for: "00:05:00"
    conditions:
      - condition: state
        entity_id: binary_sensor.washing_machine_running
        state: "on"
    actions:
      - action: divoom_times_gate.show_message
        data:
          screen: 4
          text: WASH DONE
          duration: 60
```

## Watch solar and battery at a glance

**Goal.** See production, house load, and battery charge without opening the
dashboard.

Put this on one screen through **Configure**. It is a `card` page, so the
integration picks icons, lays the values out, and polls them for you.

```yaml
- page_type: card
  card: sensor_grid
  theme: navy
  slots:
    - entity_id: sensor.solar_power
      color: "#FFB300"
    - entity_id: sensor.home_battery_soc
    - entity_id: sensor.grid_power
      value_template: "{{ (states('sensor.grid_power')|float * 1000)|round }} W"
```

For a hand-drawn version with the bundled solar icons, see the PV card in the
[README](../README.md#bundled-icons--the-pv-solar-card). For every card option,
see [docs/CARDS.md](CARDS.md).

## Keep native faces most of the time, and one Home Assistant screen

**Goal.** Leave the device looking like the clock you bought, and give up one
screen to Home Assistant.

Set the **Display source** select to `HA Dashboard`, then in **Configure** set
four screens to a native face and one to your own page:

```yaml
# Screen 1, a native device face
- page_type: clock
  clock_id: 61
```

```yaml
# Screen 3, your data
- page_type: card
  card: sensor_grid
  theme: terminal
  slots:
    - entity_id: sensor.living_room_temperature
    - entity_id: sensor.outdoor_temperature
```

The coordinator sends pixels only to screens whose **Screen N** select is set to
`Custom`. A screen set to a face is written once when it changes and then left
alone.

## Switch the whole device back to its own faces at night

**Goal.** Stop Home Assistant redrawing screens overnight, and dim the display.

```yaml
automation:
  - alias: Times Gate night mode
    triggers:
      - trigger: time
        at: "23:00:00"
    actions:
      - action: select.select_option
        target:
          entity_id: select.divoom_times_gate_display_source
        data:
          option: "Overall Display: Clock"
      - action: light.turn_on
        target:
          entity_id: light.divoom_times_gate_display
        data:
          brightness_pct: 10

  - alias: Times Gate day mode
    triggers:
      - trigger: time
        at: "07:00:00"
    actions:
      - action: select.select_option
        target:
          entity_id: select.divoom_times_gate_display_source
        data:
          option: HA Dashboard
      - action: light.turn_on
        target:
          entity_id: light.divoom_times_gate_display
        data:
          brightness_pct: 80
```

Check the exact option names in your own **Display source** select before you
copy this. The options are `HA Dashboard`, `Off`, one `Overall Display: <name>`
per whole-device face, and one `Independent Display: <name>` per preset you
saved in the Divoom app, so the face names are yours, not these.

## Show a live sensor value without repainting the screen

**Goal.** Keep one number always current, without Home Assistant pushing a new
image every refresh interval.

A `dispdata_text` page is set up once. After that the device polls Home Assistant
for the value on its own, on the schedule you give it.

```yaml
- page_type: dispdata_text
  update_time: 15
  sensors:
    - entity_id: sensor.living_room_temperature
      name: Inside
      color: "#00FF00"
```

The integration appends the entity's `unit_of_measurement` to the value for you,
so this row reads `Inside: 21.4°C`.

`update_time: 15` means the device asks Home Assistant for a new value every 15
seconds. The screen is never repainted from Home Assistant in between.

Two rules to respect:

- the device must be able to reach Home Assistant on port 8123 over the local
  network, and a custom `background_gif:` must be a GIF file,
- do not put this page in a rotation with a `gif` or `visualizer` page. See
  [docs/TROUBLESHOOTING.md, a screen is stuck on "Loading"](TROUBLESHOOTING.md#a-screen-is-stuck-on-loading).

Setup details are in [docs/DISPDATA.md](DISPDATA.md).

## Use the RGB lights as a house status indicator

**Goal.** Turn the clock's own lighting into an ambient alarm state.

```yaml
automation:
  - alias: Times Gate alarm colour
    triggers:
      - trigger: state
        entity_id: alarm_control_panel.home
    actions:
      - action: light.turn_on
        target:
          entity_id: light.divoom_times_gate_edgelight
        data:
          rgb_color: >-
            {% set s = states('alarm_control_panel.home') %}
            {{ [255,0,0] if s == 'triggered'
               else [255,160,0] if s == 'armed_away'
               else [0,180,60] }}
          brightness_pct: 60
```

The edge strip and the backlight are separate entities and hold separate colours.
See the [README RGB lighting section](../README.md#rgb-lighting) for the effect
lists.

## Repaint every screen after you change something by hand

**Goal.** Force a full redraw without reloading the integration.

```yaml
      - action: button.press
        target:
          entity_id: button.divoom_times_gate_refresh_screens
```

This clears each screen's change-tracking signature, so the next poll repaints
every screen and re-runs the setup call for any `dispdata_text` page. Use it after
the device has been power-cycled, or when a screen looks wrong.
