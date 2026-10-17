# SPDX-License-Identifier: GPL-2.0-or-later
"""Full external MCU records for original Z9 menu navigation.

Offsets and consumer masks are bound by check_z9_navigation_decoder.py;
native UI selection must still be verified from the resulting LCD.
No setting RAM edits or native instruction changes are used.
"""
import struct

BINDINGS = {
    'right': (0x22, 0x80, 0),
    'left': (0x23, 0x40, 0),
    'up': (0x24, 0x20, 0),
    'down': (0x25, 0x10, 0),
    'menu': (0x43, 0, 0x8000),
    'ok': (0x4a, 0, 1),
    'playback': (0x44, 0, 2),
    'release-mode': (0x10, 0, 0x08000000),
    'zoom': (0x4b, 0, 8),
    'thumbnail': (0x4c, 0, 4),
}


def parse_actions(text):
    if not text:
        return []
    actions = text.lower().split(',')
    if not 1 <= len(actions) <= 32 or any(x not in BINDINGS for x in actions):
        raise ValueError('1..32 comma-separated actions required: ' + '/'.join(BINDINGS))
    return actions


def key_body(action=None):
    """A complete released contact state, optionally with one navigation key."""
    body = bytearray(124)
    body[0] = body[4] = 1
    if action is not None:
        byte, _, _ = BINDINGS[action]
        body[byte] = 1
    return bytes(body)


def states(actions):
    def record(label, action=None):
        body = key_body(action)
        sw0, sw1 = 0x200, 0
        if action is not None:
            _, mask0, mask1 = BINDINGS[action]
            sw0 |= mask0
            sw1 |= mask1
        return dict(label=label, body_hex=body.hex(),
                    expected_hex=struct.pack('<11I', sw0, sw1, *([0]*9)).hex())
    output = [record('navigation-initial-release')]
    for action in actions:
        output.append(record('navigation-'+action+'-press', action))
        output.append(record('navigation-'+action+'-release'))
    return output
