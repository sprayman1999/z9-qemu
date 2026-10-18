# SPDX-License-Identifier: GPL-2.0-or-later
"""Firmware-free input, completion and storage ownership regressions."""
import json
import importlib
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from make_cmos import generate
from mcu_frames import frames
from ccomp_command_peer import reply_for
from capture_workflow_ready import evaluate
from virtual_recording_card import create, attach_existing
from capture_support import card_photos, export_new_photos, full_sensor
from inspect_virtual_exfat import catalog
from types import SimpleNamespace


class CaptureContracts(unittest.TestCase):
    def photo_card(self, directory):
        """Tiny synthetic filesystem fixture, not a camera-photo acceptance test."""
        path=Path(directory)/'photo-card.raw'
        data=bytearray(14*512);base=4*512
        data[450]=7;struct.pack_into('<II',data,454,4,10);data[510:512]=b'\x55\xaa'
        data[base+3:base+11]=b'EXFAT   ';data[base+108]=9
        struct.pack_into('<IIIII',data,base+80,1,1,2,8,2)
        struct.pack_into('<I',data,base+512+8,0xffffffff)
        group=bytearray(96);group[0]=0x85;group[1]=2;group[32]=0xc0
        group[33]=2;group[35]=8;group[64]=0xc1
        group[66:82]='TEST.NEF'.encode('utf-16le')
        struct.pack_into('<Q',group,40,32);struct.pack_into('<I',group,52,3)
        struct.pack_into('<Q',group,56,32)
        checksum=0
        for i,value in enumerate(group):
            if i not in (2,3):checksum=(((checksum>>1)|((checksum&1)<<15))+value)&0xffff
        struct.pack_into('<H',group,2,checksum)
        data[base+1024:base+1120]=group
        data[base+1536:base+1568]=b'II*\0'+bytes(range(28))
        path.write_bytes(data)
        return path

    def test_extracts_only_new_initialized_photos_from_partition_offset(self):
        with tempfile.TemporaryDirectory() as directory:
            card=self.photo_card(directory);before=card.read_bytes()
            rows,offset,length=card_photos(card)
            self.assertEqual((offset,length),(2048,5120))
            self.assertEqual(list(rows),['TEST.NEF'])
            exported=export_new_photos(card,{},Path(directory)/'photos'/'shot-1')
            self.assertEqual(exported[0]['name'],'TEST.NEF')
            self.assertEqual(Path(exported[0]['cache']).read_bytes(),before[3584:3616])
            self.assertEqual(card.read_bytes(),before)
            with self.assertRaisesRegex(ValueError,'no new photograph'):
                export_new_photos(card,rows,Path(directory)/'shot-2')
            self.assertFalse((Path(directory)/'shot-2').exists())
            with self.assertRaises(ValueError):catalog(card,offset=2048,length=1024)
            with self.assertRaises(ValueError):catalog(card,offset=card.stat().st_size)

    def test_full_sensor_checks_header_and_exact_file_length(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'sensor.raw'
            with path.open('wb') as stream:
                stream.write(struct.pack('<8s6I',b'NZ9RAW1\0',8280,5520,14,0,0,16383))
                stream.truncate(32+8280*5520*2)
            self.assertEqual(full_sensor(path),(8280,5520))
            with path.open('ab') as stream:stream.write(b'!')
            with self.assertRaisesRegex(ValueError,'trailing'):full_sensor(path)
            path.write_bytes(generate(32,16,bits=12))
            with self.assertRaisesRegex(ValueError,'14-bit'):full_sensor(path)

    def playback_card(self, directory):
        path = Path(directory)/'existing-card.raw'
        mbr = bytearray(512)
        mbr[450] = 7
        struct.pack_into('<II', mbr, 454, 2, 128)
        mbr[510:] = b'\x55\xaa'
        boot = bytearray(512)
        boot[3:11] = b'EXFAT   '
        boot[510:] = b'\x55\xaa'
        with path.open('xb') as stream:
            stream.write(mbr)
            stream.seek(1024)
            stream.write(boot)
            stream.truncate(130*512)
        return path

    def test_playback_card_uses_native_nvme_with_temporary_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.playback_card(directory)
            before = path.read_bytes()
            guest = SimpleNamespace(command=['qemu', '-M', 'nikon-z9-lab'], proc=None, data={})
            attach_existing(guest, path)
            self.assertEqual(path.read_bytes(), before)
            self.assertIn('pcie-intx-model=on', guest.command[2])
            drive = guest.command[guest.command.index('-drive')+1]
            self.assertIn('snapshot=on', drive)
            self.assertIn('format=raw', drive)
            self.assertIn(str(path), drive)
            self.assertIn('nvme,drive=card,serial=WL-Z9-PLAYBACK,bus=dw-pcie,addr=0', guest.command)
            self.assertTrue(guest.data['playback_card']['source_read_only'])
            self.assertFalse(guest.data['playback_card']['native_playback_verified'])

    def test_playback_rejects_truncated_or_non_exfat_cards_before_attach(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.playback_card(directory)
            valid = path.read_bytes()
            invalid = [valid[:511], valid[:1024], bytes(130*512),
                       valid[:1027]+b'BADFS   '+valid[1035:]]
            for body in invalid:
                with self.subTest(bytes=len(body)):
                    path.write_bytes(body)
                    guest = SimpleNamespace(command=['qemu', '-M', 'nikon-z9-lab'], proc=None, data={})
                    with self.assertRaises(ValueError):attach_existing(guest, path)
                    self.assertEqual(guest.command, ['qemu', '-M', 'nikon-z9-lab'])
                    self.assertEqual(guest.data, {})

    def test_persistent_card_disables_ephemeral_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.playback_card(directory)
            guest = SimpleNamespace(command=['qemu', '-M', 'nikon-z9-lab'], proc=None, data={})
            attach_existing(guest, path, snapshot=False)
            drive = guest.command[guest.command.index('-drive')+1]
            self.assertIn('snapshot=off', drive)
            self.assertFalse(guest.data['playback_card']['temporary_snapshot'])
            self.assertFalse(guest.data['playback_card']['source_read_only'])

    def test_playback_cannot_attach_after_emulator_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.playback_card(directory)
            guest = SimpleNamespace(command=['qemu', '-M', 'nikon-z9-lab'], proc=object(), data={})
            with self.assertRaisesRegex(ValueError, 'before launching'):
                attach_existing(guest, path)

    def test_full_capture_helpers_import_without_research_checkout(self):
        tools=Path(__file__).resolve().parents[1]/'tools'
        for path in sorted(tools.glob('capture_*.py')):
            with self.subTest(module=path.stem):
                importlib.import_module(path.stem)

    def test_14bit_samples_keep_full_range(self):
        data = generate(32, 16, bits=14)
        self.assertEqual(struct.unpack('<8s6I', data[:32]), (b'NZ9RAW1\0',32,16,14,0,0,16383))
        samples = np.frombuffer(data[32:], dtype='<u2')
        self.assertEqual(samples.max(), 16383)
        self.assertEqual(samples.min(), 0)
        with self.assertRaises(ValueError):
            generate(8, 8, bits=16)

    def test_ccomp_ack_requires_exact_complete_request(self):
        body = struct.pack('<3I', 2, 0xf3, 1) + bytes(228)
        valid = frames(body, family=9)[0]
        self.assertIsNotNone(reply_for(valid))
        for bad in (valid[:-1], valid[:20] + bytes((valid[20] ^ 1,)) + valid[21:],
                    frames(struct.pack('<3I', 2, 0xf3, 2)+bytes(228), family=9)[0],
                    frames(body, family=8)[0]):
            self.assertIsNone(reply_for(bad))

    def test_menu_gate_requires_all_image_work_and_fresh_frames(self):
        released = dict(raw=dict(frames=10), lcd=dict(video_frames=10))
        raw, lcd = dict(frames=20), dict(video_frames=20, last_frame_has_video=True)
        jpeg = dict(jobs=3, requested=False, pending=0, core=0, acks=3, core_acks=3)
        side = dict(jobs=1, pending=False, acks=1)
        streams = [dict(observation=dict(jpeg=dict(width=w,height=h)), files=[dict(label='encoded')])
                   for w,h in ((8256,5504),(1620,1080),(160,120))]
        self.assertTrue(evaluate(released,raw,lcd,jpeg,side,streams)['ready'])
        self.assertFalse(evaluate(released,raw,lcd,jpeg,side,streams[:-1])['ready'])
        self.assertFalse(evaluate(released,raw,lcd,dict(jpeg,pending=1),side,streams)['ready'])
        self.assertFalse(evaluate(released,dict(frames=10),lcd,jpeg,side,streams)['ready'])
        self.assertFalse(evaluate(released,raw,dict(lcd,last_frame_has_video=False),jpeg,side,streams)['ready'])

    def test_card_creation_never_overwrites_existing_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'capture-card.raw'
            path.write_bytes(b'existing user data')
            expected=ValueError if os.name=='nt' or os.environ.get('WSL_DISTRO_NAME')=='ubuntu-noble' else FileExistsError
            with self.assertRaises(expected):
                create(path, 'blank')
            self.assertEqual(path.read_bytes(), b'existing user data')


if __name__ == '__main__':
    unittest.main()
