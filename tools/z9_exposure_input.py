# SPDX-License-Identifier: GPL-2.0-or-later
"""External ISO/MODE/main-dial inputs for the Z9 C5.32 decoder.

Original decoder: MODE byte0e -> SW0 bit11; signed dial byte0b -> word4.
ISO byte16 -> SW1 bit29, matching the original ID_SW1_ISO name table.
Only input delivery is specified here. Read the native LCD to verify exposure.
"""
import struct


def state(label, mode=False, dial=0, hold_ns=500_000_000, *, iso=False):
    if (type(mode) is not bool or type(iso) is not bool or
            type(dial) is not int or not -64 <= dial <= 64):
        raise ValueError('boolean MODE/ISO and bounded signed dial required')
    body = bytearray(124)
    body[0] = body[4] = 1
    body[0x0e] = int(mode)
    body[0x16] = int(iso)
    body[0x0b] = dial & 255
    expected = struct.pack('<11I', 0x200 | (0x800 if mode else 0),
                           0x20000000 if iso else 0, 0, 0,
                           dial & 0xffffffff, 0, 0, 0, 0, 0, 0)
    return dict(label=label, body_hex=body.hex(), expected_hex=expected.hex(),
                hold_ns=hold_ns, workflow_phase='native-exposure-selection')


def adjustment_states(control, direction):
    """One dial detent, with a separately retired modifier press and release."""
    if control not in ('iso', 'shutter', 'mode') or type(direction) is not int or direction not in (-1, 1):
        raise ValueError('ISO/shutter/mode and one signed detent required')
    modifier = dict(iso=control == 'iso', mode=control == 'mode')
    rows = []
    if control != 'shutter':
        rows.append(state(control+'-press', hold_ns=500_000_000, **modifier))
    rows.append(state(control+'-dial', dial=direction, hold_ns=500_000_000, **modifier))
    if control != 'shutter':
        rows.append(state(control+'-dial-stop', hold_ns=500_000_000, **modifier))
    rows.append(state(control+'-release', hold_ns=2_000_000_000))
    if control != 'shutter':
        # A second press also ends the native release-button-to-use-dial latch.
        rows.append(state(control+'-finish-press', hold_ns=500_000_000, **modifier))
        rows.append(state(control+'-finish-release', hold_ns=2_000_000_000))
    return rows


def states(mode_steps=0, shutter_steps=0):
    if type(mode_steps) is not int or not -3 <= mode_steps <= 3:
        raise ValueError('bounded mode steps required')
    if type(shutter_steps) is not int or not -64 <= shutter_steps <= 64:
        raise ValueError('bounded shutter steps required')
    rows = []
    if mode_steps:
        rows += [state('exposure-mode-press', True),
                 state('exposure-mode-dial', True, mode_steps),
                 state('exposure-mode-release', hold_ns=2_000_000_000)]
    if shutter_steps:
        rows += [state('exposure-shutter-dial', dial=shutter_steps),
                 state('exposure-shutter-release', hold_ns=2_000_000_000)]
    return rows
