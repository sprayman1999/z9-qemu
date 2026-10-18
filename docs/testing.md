# Validation status

## Browser single-photo capture (2026-10-18)

The independent **📷 拍照** button now reuses the complete lossless14 capture
profile in the same guest as menu, ISO and shutter controls. Startup performs
the original RAW setup and waits for actual video before enabling controls.
Each request runs the existing full shutter/GPIO and processing sequence,
both native post-shot menu returns and fresh-frame gates. Only a new,
initialized photo entry read from the actual persistent card is exported and
reported saved. Half-up remains a separate release-only contact.

The browser took two released single photos in one C5.32 guest and the default
`playback-card.raw`; an ISO-up command ran between them. The bounded run ended
normally with 4,391 passing protocol checks, 72 automatic contacts, nine manual
contacts, two completed recovery cycles, no recorded error and the owned QEMU
stopped. The card retained both files after shutdown, and read-only extraction
from the stopped backing image matched each session export exactly:

| Native card file | Bytes | SHA-256 |
| --- | --- | --- |
| `DCIM/100NCZ_9/DSC_0001.NEF` | 35,109,505 | `362fe89dcfb5843f806428f22d1d242c6a591abb1f5ab920e43f2adfbeb1ab45` |
| `DCIM/100NCZ_9/DSC_0002.NEF` | 35,109,505 | `3016e21f8f0ccf0f376f66a05d2e2f6257dc12cd51ad97e05a00eeddada392d5` |

Independent rawpy 0.27.1/LibRaw decoding produced 8280×5520 samples per file.
All 91,411,200 samples matched the respective original acknowledged packed
RAW producer buffers. Each embedded 8256×5504, 1620×1080 and 160×120 JPEG
decoded with Pillow. These are decode/sample comparisons, not a new MakerNote
codec-profile audit; ExifTool was unavailable for that separate check. The
browser's download API returned the first file byte-for-byte with the above
hash. The generic browser download event timed out; it is not counted as a
passed download-event check. The final HTTP endpoint adds an explicit
attachment filename, covered by the exact-byte response regression.

All 51 firmware-free Python checks passed, including readiness/busy/S-mode
admission, duplicate-click reservation, bounded queue failure, original half-up
semantics, partition-offset extraction, refusal to reuse an old photo and
download byte/filename restrictions. Browser-script syntax was also checked.
No QEMU C code, guest instructions or application setting RAM were changed.
The UI limit is eight photos per session; this update's native acceptance is
two sequential single photos. Burst, movie capture, arbitrary quality changes
and saved-photo LCD playback retain their separate verification limits.

## Default persistent preview card (2026-10-18)

`tools/run.py` now defaults to `.local/cards/playback-card.raw` and uses
`snapshot=off`, preserving guest writes across launches. `--card` selects
another existing image, `--no-card` explicitly omits storage, and
`--card-snapshot` restores the earlier ephemeral behavior. The image is never
created or formatted by the launcher. Its resolved path and persistence policy
are displayed in the browser.

All 45 firmware-free Python checks passed, including default/override/no-card
argument handling and persistent versus ephemeral NVMe attachment. A bounded
native boot recorded 679 passing protocol checks, no error and a stopped owned
QEMU, with the expected 8 GiB card and `temporary_snapshot=false`. A subsequent
browser check verified the actual default card status, a complete half-release
and re-press, original PHOTO menu entry and half-shutter return to fresh video.
That run ended with 1,529 passing protocol checks, six consumed key contacts,
1,952 RAW frames and 1,356 LCD video frames, no error and the owned QEMU stopped.
The short first boot's lack of video before its deadline is not counted as
live-view acceptance. Browser-script syntax and publication hashes were checked.

The old **Release** button is now **Release half / 松开半按**. It sends only
the existing half-up contact; no full press, capture processing or photo-cache
export is implied. The standalone [full RAW workflow](capture.md) remains the
supported complete capture/write-card path. This update does not establish
browser photo capture at that earlier stage, saved-photo playback or physical card behavior.

## ISO and shutter controls (2026-10-18)

The browser now supplies ISO +/−, shutter faster/slower and MODE dial inputs.
The original C5.32 key task was observed consuming the decoded contact states,
in addition to the existing MCU frame/ACK checks. The bounded local run ended
with all 6,232 recorded protocol checks passing, 92 of 92 external key contacts
observed by the native key scan, no recorded error and the owned QEMU stopped.
The local QA proxy reloaded authored controller source between requests and
kept per-request source hashes; read-only native call witnesses were used to
distinguish command handling from LCD repaint. No setting RAM or instructions
were rewritten. Temporary tracing code is excluded from the shipped controls.

Original LCD observations verified A/M selection and selected ISO
`100 -> 125 -> 100`. Auto ISO was enabled, so the shooting overlay could show
a different metered sensitivity after selection. In M mode, signed main-dial
counts reached the original shutter handler at `0x40d4fc28`, with its original
permission check returning 1. Original batch transactions at `0x410dbc98`
included:

| Direction | ShutterSpeedType `0x06000305` | ShutterSpeed `0x07000301` | FineTune `0x06000307` |
| --- | --- | --- | --- |
| Slower | 0 | 336 | 1344 |
| Faster | 0 | 344 | 1376 |
| Faster | 0 | 352 | 1408 |

These are native encoded values, not host-selected replacements. The original
LCD showed shutter values including `1/26000`, `1/13000` and `1/16000` during
the checks. Small numeric regions sometimes retained an older value after a
later setting transaction. Immediate numeric repaint remains a display-model
limitation; a successful input must not be inferred solely from a cached frame.
The native runtime shutter acceptance above is M-mode scope; custom dial
assignment and direction remain under original firmware control.

The change passed 43 firmware-free Python checks and browser-script syntax
validation. The checks cover HTTP readiness/origin/queue handling, modifier
release even with a full queue, half-shutter wake/release order, preservation
of the S/CL/CH selector, native key-scan acknowledgement and bounded failure
when transport or guest progress stalls. Firmware and tested QEMU identities
are the same as the playback section below. Native result SHA-256:
`068d1b00898442d32d7b2ef30fc0d93a4fc903f0318e3d5ace0e96632e27cd82`.

## Native playback input update (2026-10-17)

The public `tools/run.py` launcher was built locally with pinned QEMU 10.2.4
and started with the original fingerprinted C5.32 MAIN and authored color bars.
After actual live view appeared (RAW1811/LCD-video328), the browser sent PLAY.
The complete family2 frame reached the original MCU receiver and the original
LCD changed to "No memory card." No host viewer or replacement LCD raster was
used. The bounded run exited normally, with all 2,032 recorded checks passing
and no RAW destination rejection. Runtime memory and UI images remain private.

This establishes the no-card playback entry only. Reading a photograph card,
thumbnail browsing, decoded photo pixels, fresh live-view recovery after
playback, release-mode selection and actual continuous burst remain separate
acceptance tasks. The half-shutter return input was delivered, but fresh video
did not return before that run's deadline; no recovery success is inferred.

The change also passed 34 firmware-free Python tests, the C pixel contracts,
default-off board realization and all 13 service-core event checks. A separate
QEMU block-node inspection confirmed a writable temporary qcow2 overlay over
a read-only raw backing file for the new `--card` attachment.

Local tested executable SHA-256:
`95f5d97da1da1ace5ac82d46f6a0e53484a7ee44b571d1a70cae342f0dfc3940`.
Native result SHA-256:
`b2ea7a5dabc7ae5f626d61f005c9dbcdbedb95f9865ef1da3c3da9a5cd3a4946`.

A subsequent cold boot of the final persistent-dial controller verified the
original LCD's S indicator, then the stacked-frame/20 display after selecting
CH and stacked-frame/5 after selecting CL. CL remained on the original LCD
after a LEFT press/release. PLAY while CL was selected again reached the
original no-card playback message. The displayed 20/5 are configured camera
indicators, not measured emulated or physical burst throughput. These checks
establish release-mode selection and persistence; continuous photo writing
and photograph-card playback remain unaccepted.

That final controller run completed all 12 explicit contact frames, carrying
selector values `0,2,1,1,1,1,1,1,1,1,1,0`, and exited normally with all 5,542
recorded protocol checks passing. Both initial half-shutter return and a later
release/half-shutter pair left the LCD black without fresh RAW/LCD video;
this is a reproducible unresolved recovery failure, not a successful return.
Final-run result SHA-256:
`e3b1e277140cd84e2a0944d78c298f76378399398d6a78e27ed2f063e87727cd`.

## Full RAW capture update (2026-10-11)

The current shared Z9 board passed a full shutter/capture/recovery workflow
in run563: all 57 original input states consumed, one initialized native NEF,
fresh post-shot RAW/LCD, two actual PHOTO-menu returns and no observed native
fault. This is a bounded single-shot test; movie recording and RAW pre-capture
remain unaccepted. The standalone public capture command is checked separately
below; shared research evidence is not silently counted as package acceptance.

| Check | Result in run563 |
| --- | --- |
| Card file | `DCIM/100NCZ_9/DSC_0001.NEF`, 81,222,656 bytes |
| RAW | 8280×5520, 14-bit; all 45,705,600 independently decoded samples equal guest producer RAM |
| Embedded JPEG previews | 8256×5504, 1620×1080, 160×120; each byte-identical to its completed codec stream |
| Post-shot recovery | New RAW and visible LCD frames after image work; two actual menus followed by fresh live view |
| Original control flow | Request-bound CCOMP reply, GPIO request/feedback/ack and original wait returns observed |
| Unsupported acceptance | Movie recording, playable video, RAW pre-capture, repeated burst and physical sensor/codec behavior |

Result SHA-256:
`de87b5f06e4e89913ee4594e7c4368aa62d59d09222f6dc3664dad76823b4c64`.
Native NEF SHA-256:
`87fbeba50825a34f513d9215ebe5c9c64b92d8ee246a024504c55e89a63f3a34`.
Shared tested binary SHA-256:
`682926d5502d5c24eaa9a52be07e8f388201c17bf076f05e84efdf1495c948b6`.
The native run took about 309 host seconds plus about 5 seconds for file
auditing in that environment. This is evidence provenance, not a performance
guarantee or measured physical camera rate. Artifact sizes/hashes depend on
the user's input and metadata. Original firmware bytes were unchanged.

The accepted host source was **8256×5504 RGGB/u16 at 14-bit range**, resampled
by the functional sensor model into the firmware's 8280×5520 RAW request.
This does not recover physical border pixels or sensor packing. The output
RAW/file oracle compares the actual producer, not an assumption that the
input and capture geometries are identical. See [capture.md](capture.md).

The public build passes 13 Python tests (including request-bound CCOMP ACK,
14-bit range, fresh-frame/all-preview gating and existing-card preservation),
synthetic C pixel tests, default-off realization and 13 WFE/SEV/IRQ execution
checks. CI uses only authored/synthetic inputs and cannot establish native
camera acceptance without the user's firmware.

## Standalone public package acceptance (run564)

The repository's own `tools/capture.py` command, rebuilt from this source
overlay without the private shared-build launcher or lifecycle plugin,
passed the same 57-contact complete workflow. It resumed fresh visible
RAW-derived live view after the photo, recognized two actual PHOTO menus,
returned to fresh frames, stopped normally and extracted the actual NEF.
The standalone auditor then independently decoded all 45,705,600 samples
and matched all three embedded JPEG streams. Final counters were RAW765
and LCD-video851; counters alone were not the acceptance criterion.

| Artifact | SHA-256 |
| --- | --- |
| Public tested executable | `18ca5bb07cb514f9c57f78d31f43b9beb1e3566e65d354245961facdf52f9006` |
| Native result | `f3a3e2d13980c620730f269fd1a1771cf7c70c1b5884a3f25e61da0dc08d1b9b` |
| Actual 81,222,656-byte NEF | `c138a2a90b0020891f3b9513c6dfef561641472865e57ff6eb4b4dc21831f702` |

Capture and filesystem extraction ran in the authorized Nikon Linux/WSL
environment. Independent decoding used rawpy0.25.1 / LibRaw0.21.4 in the
existing Windows Python environment. The tools require no private fixture
paths; the user supplies firmware and their own local source. Runtime evidence,
the source photograph, NEF, UI images and memory snapshots are not published.
After adding the JPEG source license marker, the rebuilt binary hash remained
identical to the tested executable; no functional code changed.

The repository's full-size synthetic generator also produced the documented
90,882,080-byte 8256×5504/14-bit source. This generated scene is not the scene
used for run564; input-generation validation and native image acceptance are
recorded separately. Small synthetic sources cover range/CFA tests in CI.

## Historical preview-only acceptance (2026-10-10)

The standalone launcher passed three native MENU returns on 2026-10-10,
with fresh RAW/LCD video and four independent pixel checks. Three preceding
cold boots of the same functional profile also passed, including a run with
detailed tracing removed. These are bounded functional tests, not physical
camera qualification or indefinite stability coverage.

| Run | Configuration | Initial RAW/video | Return 1 | Return 2 | Return 3 |
| --- | --- | --- | --- | --- | --- |
|405|Candidate, sparse submission trace|1403/69|1517/293|1628/511|1734/724|
|406|Candidate, no detailed trace|1406/72|1521/296|1634/518|1746/738|
|407|Candidate, CPU3 wait-site counts|1401/66|1512/284|1624/505|1735/722|
|408|Standalone source launcher, no private wrapper/plugin|1403/68|1512/286|1621/503|1732/721|

Every menu in these runs was reached with one press. Run408 compares610,199
clear-alpha pixels at each live-view stage. Mean absolute RGB error is
0.1508–0.1521/255, maximum0.624; luminance standard deviation exceeds60.
The owned emulator stopped normally, without a recorded error. The test
input was synthetic640×480 RGGB12/u16 color bars, not a Nikon sensor dump.

Run408 result SHA-256:
`498601b76356c82c2fa8ee49a04a1e0fe508176f57a1a491c38eaad23d53dbcf`.
Tested executable SHA-256:
`72e2b48214af7477e7bdee4afd86a320afc71f4b71ac570c7ffa4fc062aa26b9`.
The original firmware fingerprint is in [firmware input](firmware.md).
Full runtime evidence stays private because it includes firmware-derived
memory planes and UI captures. These hashes identify local evidence; the
source repository does not distribute those artifacts.

The public build also passes13 firmware-free WFE/SEV/IRQ execution checks,
9 Python tests, pixel tests, default-off board realization and rejection of
unsupported CPU/clock settings. These test the
[documented service event contract](service-events.md), not complete ARM
event architecture. Patch application and repeated preparation were checked.

The private Z9 C5.32 baseline has independently demonstrated 915 RAW-derived
frames, 5,174,830,080 pixel bytes, zero rejected destinations and 1,144 video
scanouts. For 610,199 clear-alpha LCD pixels, an independent NV12 decode had
mean RGB absolute error 0.243/255 and maximum error 0.524. This establishes the
functional pixel path for that recorded run, not physical sensor accuracy.

Source drain tests execute original driver and ISR routines with explicitly
prepared diagnostic state. Masked pending, unmask, unrelated W1C, reset and
restart are checked. The RAW DMA regression checks destination guards,
backpressure and complete-bank replacement. These tests are local because
they require the user's proprietary firmware and are not public CI inputs.

Public CI will run only synthetic source/RAW/protocol tests, publication audit
and a verified upstream build. It cannot boot the camera UI without firmware.
Do not interpret a green CI badge as camera acceptance.

Remaining physical limits include real CMOS programming, sensor timing,
calibration, AE/AF/PDAF, recording, physical card behavior and complete GPU
behavior. Functional virtual-card writing is now supported by the separate
capture profile; the historical preview profile still has no card attached.

The current display correction isolates directly enabled NV12 video from the
two optional layer controls. Ten fixed-pixel checks cover layer combinations,
direct stop/restart, source preservation and strict MMIO. Fourteen existing
display/alpha/IRQ/bounds checks also pass on the corrected standalone build.
QOM `last_frame_has_video` describes the last composed frame; the video frame
counter remains historical. MENU acceptance requires both new RAW and new LCD
video after returning, followed by independent pixel validation.

Earlier native menu-return diagnostics exposed premature frame release during
submission. MVD interrupt delivery and acknowledgement lifetime were
corrected in separate original-ISR checks, but this does not establish restart
acceptance. A further unsupported two-byte plane clear was captured and its
functional support now passes 184 local clear checks, including full-buffer
comparison and invalid-request boundaries. Diagnostic MVD scheduling changes
are excluded from this launcher. The current combined service-event,
instruction-clock, virtual-input and synthetic-timing profile passes the
three-return acceptance above. The historical failing observations remain
valid evidence for the earlier profiles; no single component is claimed as
an independently proved cure for every lifetime failure.

Current development scope and corrected algorithm/movie claims: [2026-10-13 shared136 snapshot](development-snapshot.md). Earlier test results retain their original revision scope.
