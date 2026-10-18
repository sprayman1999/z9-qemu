# Running and controls

Run with the default full-resolution 14-bit input (generated on first launch):

```sh
python tools/run.py --firmware /path/to/main.bin \
    --output /your/linux/path/z9-run-001 --port 8789
```

The output directory must be new. Keep it local. The default is a timestamped
directory beneath `.local/`. Open `http://127.0.0.1:8789/`.

With a persistent card and full-resolution input, the browser prepares the
verified lossless14 RAW configuration in the original camera menu, then enables
**📷 拍照**. Each click runs one full shutter press/release, native processing,
write-card completion and live-view/menu recovery in the same guest. ISO and
shutter adjustments made after preparation stay in that guest. Select **S**
single drive mode first. Manual controls wait while preparation or a photo is
in progress. Up to eight released single photos are allowed per session;
continuous burst is not enabled by this button.

Success requires a new, fully initialized NEF/JPEG entry on the actual card,
not just an input acknowledgement or a changed frame. After recovery, the
runner pauses the guest, reads the card without modifying it, and exports
the newly saved files to `OUTPUT/photos/shot-N/`. The page then shows download
links. It never assembles a substitute camera file. `POST /capture` reserves
one ordered request and rejects unavailable/busy/non-S sessions with 409;
`GET /photo/N` downloads only files exported by this session. A missing new
file or interrupted capture is an error, not a saved photo.

The default sensor file is `.local/z9-14bit.raw`, generated as authored
8280×5520 color bars when absent. To use a scene image, generate the full input
before launch:

```sh
python tools/make_cmos.py --width 8280 --height 5520 --bits 14 \
    --image /path/to/scene.jpg --output .local/z9-14bit.raw
```

`--preview-only`, `--no-card`, `--card-snapshot`, `--headless` and `--menu-test`
retain the preview workflow. Explicit small/12-bit `--raw` inputs also run
preview only; the photo button stays disabled. A full input may use either
8256×5504 or 8280×5520 14-bit RGGB, with an exact NZ9RAW1 file length. Initial
preparation and full photo processing can take minutes. A 600 s host bound
detects a stalled preparation/photo; original firmware timers are unchanged.

The preview-only controller starts with half-shutter held to keep the active capture path
running. MENU releases half-shutter and sends one MENU press/release pair.
The current firmware path can consume a first press without opening a menu;
if the shooting overlay remains, wait before pressing MENU again. Half shutter
hold returns from menus through the original firmware's key path. Release
releases half-shutter. This is not a full shutter press: it does not request a
photo or create a photo cache. Use the separate **📷 拍照** button, or the
standalone [full RAW capture workflow](capture.md). Both use the complete
sensor, processing, shutter GPIO and write-card models. All inputs are synthetic MCU messages; they do not
alter application state directly.

Use the direction pad to navigate and OK to confirm. Keyboard shortcuts are
the arrow keys, Enter for OK and M for MENU. A click or key press sends one
complete press/release pair; keyboard auto-repeat is ignored. Navigation also
releases a held half-shutter first. Inputs run in order, with pulse and release
gaps measured in guest virtual time after MCU receive retirement. Directions
use a 60 ms pulse and a 500 ms release gap; OK uses a 60 ms pulse and a 2 s
gap, and MENU a 400 ms pulse and a 2 s gap. These reuse the existing synthetic
contact mappings; actual menu selection still needs firmware/LCD validation.

The local POST routes are `/key/up`, `/key/down`, `/key/left`, `/key/right`,
`/key/ok`, `/key/menu`, `/key/half-down` and `/key/half-up`. They require an
Origin matching this server's `http://127.0.0.1:PORT` or `http://localhost:PORT`.
A successful enqueue returns 204, a full queue 429, and stopped sessions or
automatic `--menu-test` runs reject manual input with 409. Internal releases
do not use the bounded HTTP queue, so a full queue cannot discard a release.

Playback sends the original camera's PLAY key, rather than opening a host
image viewer. Use **Playback** (P), then the existing direction pad and OK.
**Thumbnails / −** (minus) and **Zoom / +** (plus or equals) send the original
THUMBNAIL and ZOOM keys. **Half shutter hold** returns to shooting through
the existing half-shutter input; however, fresh live view did not recover
after the tested no-card playback path and the LCD remained black. This
recovery path is unresolved. **Release mode** (R) sends the physical
RELEASE_MODE key. Use the **Drive** selector for S (single), CL (continuous
low) or CH (continuous high). It changes the absolute MCU dial position and
preserves that position in later navigation, release and half-shutter frames.
The input selection does not claim continuous shooting acceptance.

The additional POST routes are `/key/playback`, `/key/thumbnail`, `/key/zoom`,
`/key/release-mode`, `/key/drive-single`, `/key/drive-cl` and `/key/drive-ch`.

The **Exposure / 曝光参数** controls become available after the first verified
live-view frames. Exposure POSTs before initial readiness return 409. Use them
in the shooting view:

- **ISO − / ISO +** hold the original ISO key and turn the main dial one detent.
- **Slower / Faster** turn the main dial one detent. Select S or M with
  **Mode ◀ / Mode ▶** first; the native firmware determines the dial's meaning
  in P/A and custom control configurations.
- **Mode ◀ / Mode ▶** hold MODE and turn the main dial to cycle exposure modes.

Read the selected values from the original LCD. Auto ISO remains under camera
control: changing the selected ISO does not disable Auto ISO or fix its actual
metered sensitivity. Use the original camera menu to disable Auto ISO when a
fixed ISO is needed. The controller does not render or assume numeric values.

Each modifier press lasts 500 ms, followed by a signed dial input for 500 ms,
a separate 500 ms zero-dial state with the modifier still pressed, and a released
modifier state for 2 s, timed after MCU receive retirement. ISO/MODE operations
finish with another 500 ms press and 2 s release of the same button. This uses
the documented [f6 exit action](https://onlinemanual.nikonimglib.com/z9/en/15_menu_guide_04_f06.html)
to end a retained parameter selection before a later dial action. Shutter
operations use a 500 ms dial input and 2 s zero-dial state. A held half-shutter
is released before any exposure action; if it was released, a 500 ms half-press
wakes the camera first. Every exposure action finishes with half-shutter held
for at least 2 s and leaves it held to keep the preview active. **Release**
releases it. All
contacts retain the selected S/CL/CH drive position. Pending modifier releases
and finishing contacts remain internal even when the HTTP queue is full.

The worker waits for both MCU RX retirement and the original key-scan task's
decoded contact state before starting each hold/gap. It reads the 44-byte state
at `0xa03222034`, copied by the original task at `0x40d28f30` after rotary-count
accumulation at `0x40d28f20`. This prevents a following zero-dial frame from
overtaking the native key scan. These reads only observe firmware RAM. A missing
match fails after 10 s of guest virtual time instead of reporting a completed
input. A 60 s host transport bound also catches a stalled virtual clock or RX.
These are controller diagnostics; original firmware deadlines are unchanged.
Consumed states are retained in the local run's `interactive_key_consumers`.

Native M-mode ISO selection and shutter setting transactions have been checked.
The LCD's small numeric regions can retain an older value after a setting
transaction; immediate repaint is not guaranteed by the current display model.
No host numeric overlay replaces those fields. See [validation status](testing.md).

The routes are `/key/iso-down`, `/key/iso-up`, `/key/shutter-slower`,
`/key/shutter-faster`, `/key/mode-previous` and `/key/mode-next`. On the pinned
default controls, ISO up and faster shutter use signed main-dial delta +1;
ISO down and slower shutter use −1. MODE uses −1 / +1 for previous / next.
The original decoder at `0x41024e90` maps ISO body byte `0x16` to SW1
`0x20000000`, MODE byte `0x0e` to SW0 `0x800`, and signed main dial byte
`0x0b` to decoded word 4. The original `ID_SW1_ISO` name table corroborates
the ISO mask. These are external input records; settings RAM is not edited.

Every normal `tools/run.py` launch attaches
`.local/cards/playback-card.raw` beneath the repository root. Guest writes
persist to this regular image across runs. The image must already exist;
the runner never creates or formats it, and a missing default fails with an
actionable error. Use `--no-card` explicitly for card-free experiments.

To select another card, supply an actual raw virtual card, for example from
a completed capture run:

```sh
python tools/run.py --firmware /path/to/main.bin \
    --card /path/to/completed-capture/capture-card.raw
```

The file must be a regular `.raw` disk image with an MBR exFAT partition.
It is attached to the modeled NVMe controller before boot with
`snapshot=off`. Add `--card-snapshot` to use a temporary overlay and discard
all this run's card writes on exit. The status reports `card_path` and
`card_persistent` so the selected image and write policy are visible. The
launcher selects the full capture profile only with a valid full input and
persistent card; releasing half-shutter still cannot create a photograph. Native file reading,
JPEG decoding and the resulting LCD
must be checked in a firmware-dependent run; successful key delivery alone
does not establish working photograph playback.

The original-firmware run on 2026-10-17 verified that PLAY leaves live view
and displays the camera's own "No memory card." message. That run had no
card attached, so it does not validate file browsing, thumbnails or decoded
photographs. See [validation status](testing.md).

The new contact mappings are pinned to the documented Z9 C5.32 firmware:

| Key | MCU body byte | Decoded SW1 mask | Native UI key |
| --- | --- | --- | --- |
| PLAY | `0x44` | `0x00000002` | `0x2e` |
| THUMBNAIL | `0x4c` | `0x00000004` | `0x1a` |
| ZOOM | `0x4b` | `0x00000008` | `0x19` |
| RELEASE_MODE | `0x10` | `0x08000000` | `0x26` |

The original decoder at `0x41024e90`, key-name masks and the translation
table at `0x41fb0fac` corroborate these fields. The original handler at
`0x4045e594` dispatches thumbnail and zoom keys. These are static
interoperability observations, not physical timing or LCD acceptance.

The drive selector is MCU body byte `0x11`: 0 for S, 1 for CL and 2 for CH.
It becomes the decoder's ushort at `+0x22`, then original key status `+0x6e`.
The consumer at `0x40d32aa4` submits the observed value to setting `0x02000006`;
the original setter chain through `0x410e83d8` derives release mode and speed.
The low/high distinction is corroborated by the original named
`ReleaseSpeedContLow` / `ReleaseSpeedContHigh` consumers. No application RAM
or setting value is directly written by the controller.

The browser receives PNG snapshots of QEMU's actual LCD surface. It does not
render its own ISO, shutter, menu, icons, no-card mark or video background.
The displayed RAW/LCD counters are diagnostic host state. Initial startup
takes time; the service waits for actual video production before showing ready.

The HTTP server binds only to loopback. It has no upload, shell execution,
firmware writing or remote-control endpoint. Do not expose it to a network.
The selected QEMU process and local Unix sockets are owned by this run;
Ctrl+C closes that run without attaching to another emulator.

For bounded acceptance use `--menu-test --headless --seconds 360`.
Startup and all three returns can take several minutes. `--seconds` measures
host time after boot; native key and acceptance delays use virtual time.
`--qemu /path/to/binary`
overrides the build manifest. `--raw /path/to/input.raw` selects a local RAW
input. `--menu-test` observes the native menu after a press and allows one
further press after ten seconds if it has not appeared. It requires three
returns with new RAW and LCD video frames and independent pixel comparison.
The supplied runtime profile has passed this acceptance; see
[recorded results](testing.md). Recovery uses a new process rather than QMP
warm reset. The MCU peer is still a bounded experimental implementation,
not an indefinitely validated camera service.

Input format: 32-byte header, `NZ9RAW1\0`, then six little-endian u32 values
for width, height, bits, CFA=0, black and white; remaining pixels are linear
RGGB unsigned 16-bit little-endian samples. Even dimensions are required.
12-bit or 14-bit values are stored in 16-bit words, not packed RAW12/RAW14. The sample generator
undoes sRGB transfer before Bayer sampling and uses a simple stretch to the
selected dimensions. This is a test fixture, not a physical sensor protocol.

For shutter release, a full NEF on a virtual card, fresh post-shot live view
and two post-shot menu returns, use the separate [capture workflow](capture.md).
The preview-only profile omits the full shutter/REC processing graph. Normal
browser sessions attach the default card and enable single-photo capture when
the full-resolution input and RAW preparation are ready; REC remains separate.
The capture profile uses full-size 8256×5504/14-bit host input (or 8280×5520), opt-in image/storage
models and a request-bound CCOMP MCU/GPIO peer. Do not combine it with another
running preview process or count LCD video as a movie recording.
