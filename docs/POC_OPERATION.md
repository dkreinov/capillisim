# How the POC Works (Operation)

This is the physical and software walkthrough of the Milestone 3 proof of
concept: how the projector, the phone camera, and the PC connect and cooperate
to guide an interactive cap-by-cap build.

## The one-line model

**The PC is the hub. The projector is just a second monitor. The phone is just
a wireless webcam.** Nothing custom runs on the projector or the phone for the
POC.

## Physical setup

```
   ┌─────────┐   HDMI               ┌──────────┐
   │   PC    │─────────────────────▶│ projector│──▶ projects onto the table 1:1
   │  (hub)  │  (2nd monitor,                          ▲  glowing target ring
   │         │   fullscreen window)                    │
   │         │                                         │  place the cap here
   │         │   Wi-Fi (same LAN)   ┌──────────┐       │
   │         │◀─────────────────────│  phone   │   hold a cap up to it
   └─────────┘   MJPEG video        └──────────┘
```

- **PC ↔ projector — HDMI cable.** The projector is a second display. The PC
  shows the projection frame as a fullscreen window on it. The projector hangs
  above the table pointing straight down.
- **PC ↔ phone — Wi-Fi, same network.** The phone runs an off-the-shelf
  IP-webcam app that serves its camera as a stream at a URL like
  `http://192.168.1.42:8080/video`. The PC reads that URL. No app to build.
- **Phone position.** It only needs to see the cap you hold up, in a small
  "reading zone" just outside the projector beam (so projection light doesn't
  tint the cap's color). It does **not** need to see the table.

## Two coordinate frames, one calibration

The only spatial calibration the POC needs is **projector → table** (Milestone
2): four markers, aligned to a taped rectangle of known size, give the
homography so the PC can light up any cell at its true position and size.

The phone camera is **not** registered to the table for the POC. Its only job is
"what color is this cap," so it needs no spatial calibration. (Registering the
camera to the table is a later feature, only needed to auto-verify that a cap
actually landed in the right cell.)

## The loop (what the PC does, ~once or twice per second)

1. Grab a frame from the phone stream.
2. Find the cap and read its dominant color (masking metallic glare).
3. Ask the matcher for the best empty cell whose target color matches — or a
   rejection if nothing is close enough.
4. Push an updated frame to the projector: faint rings for the whole plan,
   brighter rings for caps already placed, and a bright green **glow** on the
   target cell. On a rejection, no glow — that means "set this cap aside."
5. You drop the cap onto the glowing spot and press a key to confirm.
6. Mark the cell filled, save the project file, and loop to the next cap.

## A real session, start to finish

1. Mount the projector over the table; HDMI to the laptop; set the laptop
   display to "extend"; drag the projection window onto the projector.
2. Run calibration once (project 4 markers, align to a taped rectangle / enter
   the measured size).
3. Open the IP-webcam app on the phone; type its URL into the PC tool; aim the
   phone at the reading zone.
4. Pick up any cap, hold it in the reading zone → within a second or two a green
   ring lights up on the table → place the cap there → press space → next cap.
   Caps that don't help flash no target → drop them in a "later" box.
5. Stop whenever; the project file holds the state; resume next session by
   re-calibrating and loading the project.

## Minimum kit for the POC

One laptop, one projector (HDMI), one smartphone (on the same Wi-Fi as the
laptop), and the table. That's the whole rig.

## Practical notes

- **Same LAN.** Phone and laptop must share a network. Guest/isolated Wi-Fi
  blocks the stream; a phone hotspot is a fine fallback.
- **Latency.** MJPEG adds ~100–300 ms — invisible for this use.
- **Color reads.** Read the cap outside the projector beam, or briefly blank the
  projection while reading, so projected light doesn't shift the measured color.
- **Confirmation is manual** for the POC (a keypress). Auto-verify via the
  camera comes later.

## Why PC-first, phone-only later

The PC-as-hub setup is the easiest thing to get working. In the phone-only
version (Milestone 5) the phone becomes camera + brains and casts the projection
itself, collapsing the three boxes into one — but the loop above is unchanged,
which is why the matching/geometry logic lives in the device-independent core.
