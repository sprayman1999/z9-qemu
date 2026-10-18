# SPDX-License-Identifier: GPL-2.0-or-later
import struct
import json
import io
import sys
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from make_cmos import generate
from mcu_frames import frames
from boot import key_body
from service_z9_mcu import Peer
from validate_run import MenuAcceptance
from z9_global1_boundary_input import Peer as BoundaryPeer
from z9_navigation_input import key_body as navigation_body, states as navigation_states
from run import DEFAULT_CARD, EXPOSURE_COMMANDS, KEY_COMMANDS, KeyController, Session, argument_parser, decoded_contact, make_handler, live_view_ready
from z9_exposure_input import adjustment_states, state as exposure_state, states as exposure_states


class InteractiveKeys(unittest.TestCase):
    def test_startup_requires_real_video_before_releasing_bootstrap_hold(self):
        self.assertFalse(live_view_ready({'frames':1000},{'video_frames':0,'last_frame_has_video':False}))
        self.assertFalse(live_view_ready({'frames':8},{'video_frames':8,'last_frame_has_video':False}))
        self.assertFalse(live_view_ready({'frames':7},{'video_frames':8,'last_frame_has_video':True}))
        self.assertTrue(live_view_ready({'frames':8},{'video_frames':8,'last_frame_has_video':True}))

    def test_default_card_is_persistent_and_can_be_overridden_or_disabled(self):
        parser = argument_parser()
        base = ['--firmware', '/tmp/firmware.bin']
        args = parser.parse_args(base)
        self.assertEqual(args.card, DEFAULT_CARD)
        self.assertFalse(args.card_snapshot)
        self.assertFalse(args.auto_setup_raw)
        self.assertTrue(parser.parse_args(base+['--auto-setup-raw']).auto_setup_raw)
        self.assertEqual(parser.parse_args(base+['--no-card']).card, None)
        args = parser.parse_args(base+['--card', '/tmp/other.raw', '--card-snapshot'])
        self.assertEqual(args.card, Path('/tmp/other.raw'))
        self.assertTrue(args.card_snapshot)

    def peer(self):
        # Use the actual external-frame encoder without a firmware process.
        peer = Peer.__new__(Peer)
        peer.pending = []
        peer.rx = None
        peer.rx_retiring = False
        peer.start_rx = lambda: None
        return peer

    def send(self, keys, now):
        body = keys.next_body(now)
        self.assertIsNotNone(body)
        keys.peer.enqueue_external(body, 2)
        family, queued, frame = keys.peer.pending.pop(0)
        self.assertEqual((family, queued), (2, body))
        self.assertEqual(len(frame), 256)
        self.assertEqual(sum(frame) & 255, 255)
        self.assertEqual(frame[8:132], body)
        return body

    def test_navigation_contacts_and_existing_decoder_contract(self):
        mappings = {'right': (0x22, 0x280, 0), 'left': (0x23, 0x240, 0),
                    'up': (0x24, 0x220, 0), 'down': (0x25, 0x210, 0),
                    'menu': (0x43, 0x200, 0x8000), 'ok': (0x4a, 0x200, 1),
                    'playback': (0x44, 0x200, 2), 'release-mode': (0x10, 0x200, 0x08000000),
                    'zoom': (0x4b, 0x200, 8), 'thumbnail': (0x4c, 0x200, 4)}
        self.assertEqual(navigation_body(), key_body())
        self.assertEqual(navigation_body('menu'), key_body(menu=True))
        for action, (offset, sw0, sw1) in mappings.items():
            with self.subTest(action=action):
                body = navigation_body(action)
                self.assertEqual(len(body), 124)
                self.assertEqual([i for i in range(124) if body[i] != key_body()[i]], [offset])
                initial, press, release = navigation_states([action])
                self.assertEqual(press['body_hex'], body.hex())
                self.assertEqual(press['expected_hex'], struct.pack('<11I', sw0, sw1, *([0]*9)).hex())
                self.assertEqual(decoded_contact(body).hex(), press['expected_hex'])
                self.assertEqual(initial['body_hex'], release['body_hex'])

    def test_short_pulses_wait_for_receive_retirement_and_release_gap(self):
        for action in ('up', 'down', 'left', 'right', 'ok', 'menu', 'playback', 'release-mode', 'zoom', 'thumbnail'):
            with self.subTest(action=action):
                peer = self.peer();keys = KeyController(peer);keys.half = False
                keys.start(action)
                self.assertEqual(self.send(keys, 0), navigation_body(action))
                peer.pending.append(object())
                self.assertIsNone(keys.next_body(1_000_000_000))
                peer.pending.clear();peer.rx = object()
                self.assertIsNone(keys.next_body(2_000_000_000))
                peer.rx = None;peer.rx_retiring = True
                self.assertIsNone(keys.next_body(3_000_000_000))
                peer.rx_retiring = False
                self.assertIsNone(keys.next_body(4_000_000_000))
                hold = 400_000_000 if action == 'menu' else 60_000_000
                release_at = 4_000_000_000 + hold
                self.assertIsNone(keys.next_body(release_at-1))
                self.assertEqual(self.send(keys, release_at), key_body())
                self.assertIsNone(keys.next_body(release_at))
                gap = 2_000_000_000 if action in ('menu', 'ok', 'playback', 'release-mode') else 500_000_000
                self.assertIsNone(keys.next_body(release_at+gap-1))
                self.assertTrue(keys.busy)
                with self.assertRaises(RuntimeError):keys.start('left')
                self.assertIsNone(keys.next_body(release_at+gap))
                self.assertFalse(keys.busy)

    def test_half_shutter_is_released_before_navigation(self):
        keys = KeyController(self.peer())
        keys.start('right')
        self.assertFalse(keys.half)
        self.assertEqual(self.send(keys, 0), key_body())
        self.assertIsNone(keys.next_body(0))
        self.assertIsNone(keys.next_body(399_999_999))
        self.assertEqual(self.send(keys, 400_000_000), navigation_body('right'))

    def test_half_hold_and_release_remain_complete_inputs(self):
        keys = KeyController(self.peer())
        now = 0
        for command, half in (('half-down', True), ('half-up', False)):
            keys.start(command)
            self.assertEqual(self.send(keys, now), key_body(half=half))
            self.assertEqual(keys.half, half)
            self.assertIsNone(keys.next_body(now))
            now += 500_000_000
            self.assertIsNone(keys.next_body(now))
            self.assertFalse(keys.busy)

    def request(self, session, path, *, origin='http://127.0.0.1:8789', menu_test=False, method='POST', raw=False):
        class Socket:
            def __init__(self):self.output = bytearray()
            def makefile(self, *args):
                headers = '' if origin is None else f'Origin: {origin}\r\n'
                return io.BytesIO(f'{method} {path} HTTP/1.0\r\n{headers}Content-Length: 0\r\n\r\n'.encode())
            def sendall(self, data):self.output.extend(data)
        sock = Socket()
        make_handler(session, 8789, menu_test=menu_test)(sock, ('127.0.0.1', 12345), SimpleNamespace())
        return bytes(sock.output) if raw else int(sock.output.split(b' ', 2)[1])

    def test_http_commands_queue_in_order_and_reject_invalid_requests(self):
        session = Session();session.status['ready'] = True
        commands = ['menu', 'up', 'down', 'left', 'right', 'ok', 'half-down', 'half-up',
                    'playback', 'release-mode', 'zoom', 'thumbnail', 'drive-single', 'drive-cl', 'drive-ch',
                    'iso-down', 'iso-up', 'shutter-slower', 'shutter-faster', 'mode-previous', 'mode-next']
        self.assertEqual(set(commands), KEY_COMMANDS)
        received = []
        for command in commands:
            if session.commands.full():received.append(session.commands.get_nowait())
            self.assertEqual(self.request(session, '/key/'+command), 204)
        while not session.commands.empty():received.append(session.commands.get_nowait())
        self.assertEqual(received, commands)
        for path in ('/key/touch', '/key/up?x=1', '/key/menu-down', '/up', '/key/up/'):
            self.assertEqual(self.request(session, path), 400)
        for origin in (None, 'https://example.com', 'http://127.0.0.1:9999'):
            self.assertEqual(self.request(session, '/key/up', origin=origin), 403)
        self.assertTrue(session.commands.empty())
        self.assertEqual(self.request(session, '/key/ok', origin='http://localhost:8789'), 204)

    def test_full_http_queue_cannot_discard_internal_key_release(self):
        session = Session();keys = KeyController(self.peer());keys.half = False
        keys.start('down')
        self.assertEqual(self.send(keys, 0), navigation_body('down'))
        self.assertIsNone(keys.next_body(0))
        for _ in range(16):self.assertEqual(self.request(session, '/key/up'), 204)
        self.assertEqual(self.request(session, '/key/up'), 429)
        self.assertEqual(self.send(keys, 60_000_000), key_body())
        self.assertEqual(session.commands.qsize(), 16)

    def test_capture_requires_ready_single_mode_and_reserves_one_request(self):
        session=Session()
        self.assertEqual(self.request(session,'/capture'),409)
        session.status.update(capture_ready=True,drive_mode='CH')
        self.assertEqual(self.request(session,'/capture'),409)
        session.status['drive_mode']='S'
        self.assertEqual(self.request(session,'/capture',origin=None),403)
        self.assertEqual(self.request(session,'/capture'),204)
        self.assertEqual(self.request(session,'/capture'),409)
        self.assertEqual(self.request(session,'/key/half-up'),409)
        self.assertEqual(session.commands.get_nowait(),'capture')
        self.assertTrue(session.capture_pending)

    def test_photo_download_serves_only_exported_files_with_exact_bytes(self):
        session=Session()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'DSC_0001.NEF';body=b'II*\0'+bytes(range(255))
            path.write_bytes(body);session.status['photos']=[dict(cache=str(path))]
            response=self.request(session,'/photo/0',method='GET',raw=True)
            headers,payload=response.split(b'\r\n\r\n',1)
            self.assertIn(b'200 OK',headers)
            self.assertIn(b"attachment; filename*=UTF-8''DSC_0001.NEF",headers)
            self.assertEqual(payload,body)
            for route in ['/photo/1','/photo/-1','/photo/../../etc/passwd','/photo/'+'1'*5000]:
                self.assertEqual(self.request(session,route,method='GET'),404)

    def test_full_queue_does_not_reserve_a_failed_capture_request(self):
        session=Session();session.status.update(capture_ready=True,drive_mode='S')
        for _ in range(16):session.commands.put_nowait('up')
        self.assertEqual(self.request(session,'/capture'),429)
        self.assertFalse(session.capture_pending)
        session.commands.get_nowait()
        self.assertEqual(self.request(session,'/capture'),204)

    def test_manual_inputs_wait_for_raw_preparation_and_capture_recovery(self):
        session=Session();session.status['manual_ready']=False
        self.assertEqual(self.request(session,'/key/menu'),409)
        session.status.update(manual_ready=True,capture_busy=True)
        self.assertEqual(self.request(session,'/key/half-up'),409)
        session.status['capture_busy']=False
        self.assertEqual(self.request(session,'/key/half-up'),204)
        self.assertEqual(session.commands.get_nowait(),'half-up')

    def test_stopped_and_automatic_test_sessions_reject_manual_input(self):
        session = Session()
        self.assertEqual(self.request(session, '/key/up', menu_test=True), 409)
        session.stop.set()
        self.assertEqual(self.request(session, '/key/up'), 409)
        self.assertTrue(session.commands.empty())

    def test_drive_selector_persists_across_all_later_contacts(self):
        keys = KeyController(self.peer());keys.half = False
        now = 0
        for command, selector in (('drive-ch', 2), ('playback', 2), ('left', 2),
                                  ('half-down', 2), ('half-up', 2),
                                  ('drive-cl', 1), ('menu', 1), ('drive-single', 0)):
            keys.start(command)
            bodies = []
            for _ in range(12):
                body = keys.next_body(now)
                if body is not None:
                    bodies.append(body)
                    keys.peer.enqueue_external(body, 2)
                    _, actual, frame = keys.peer.pending.pop(0)
                    self.assertEqual(actual, body)
                    self.assertEqual(sum(frame) & 255, 255)
                if not keys.busy:break
                now += 2_000_000_000
            self.assertFalse(keys.busy)
            self.assertTrue(bodies)
            self.assertTrue(all(body[0x11] == selector for body in bodies))
            if command in ('drive-single', 'drive-cl', 'drive-ch'):
                self.assertEqual(len(bodies), 1)  # a dial position stays selected
                self.assertTrue(all(value == 0 for i, value in enumerate(bodies[0]) if i not in (0, 4, 0x11)))

    def test_drive_change_releases_half_with_previous_selector_first(self):
        keys = KeyController(self.peer());keys.release_mode = 2
        keys.start('drive-cl')
        before = self.send(keys, 0)
        self.assertEqual((before[7], before[0x11]), (0, 2))
        self.assertIsNone(keys.next_body(0))
        after = self.send(keys, 400_000_000)
        self.assertEqual((after[7], after[0x11]), (0, 1))

    def test_exposure_contacts_preserve_drive_and_release_modifier_and_delta(self):
        for command, (control, direction) in EXPOSURE_COMMANDS.items():
            with self.subTest(command=command):
                keys = KeyController(self.peer());keys.release_mode = 2
                keys.start(command)
                now = 0
                bodies = []
                for _ in range(24):
                    body = keys.next_body(now)
                    if body is not None:
                        bodies.append(body)
                        keys.peer.enqueue_external(body, 2)
                        _, _, frame = keys.peer.pending.pop(0)
                        self.assertEqual(sum(frame) & 255, 255)
                    if not keys.busy:break
                    now += 2_000_000_000
                self.assertFalse(keys.busy)
                self.assertTrue(keys.half)
                self.assertTrue(all(body[0x11] == 2 for body in bodies))
                dial_bodies = [body for body in bodies if body[0xb] or body[0xc]]
                self.assertEqual(len(dial_bodies), 1)
                dial = dial_bodies[0]
                self.assertFalse(dial[7])
                self.assertEqual(dial[0xb], direction & 255)
                self.assertEqual(dial[0xc], 0)
                self.assertEqual((dial[0x16], dial[0xe]), (int(control == 'iso'), int(control == 'mode')))
                self.assertEqual((bodies[-1][0xb], bodies[-1][0x16], bodies[-1][0xe]), (0, 0, 0))
                if control != 'shutter':
                    self.assertEqual((bodies[0][7], bodies[0][0xb]), (0, 0))
                    self.assertEqual((bodies[1][0x16], bodies[1][0xe]), (dial[0x16], dial[0xe]))
                    self.assertTrue(all(not body[7] for body in bodies[:-1]))
                    self.assertEqual((bodies[3][0xb], bodies[3][0x16], bodies[3][0xe]),
                                     (0, dial[0x16], dial[0xe]))
                    self.assertFalse(bodies[-1][0x16] or bodies[-1][0xe])
                    self.assertEqual((bodies[-3][0x16], bodies[-3][0xe], bodies[-3][0xb]),
                                     (dial[0x16], dial[0xe], 0))
                else:
                    self.assertTrue(all(not body[7] for body in bodies[:-1]))
                self.assertEqual(bodies[-1][7], 1)

    def test_iso_release_survives_full_queue_and_receive_retirement(self):
        session = Session();session.status['ready'] = True
        keys = KeyController(self.peer())
        keys.start('iso-up')
        self.assertEqual(self.send(keys, 0), key_body())
        self.assertIsNone(keys.next_body(0))
        self.assertEqual(self.send(keys, 500_000_000)[0x16], 1)
        keys.peer.rx_retiring = True
        self.assertIsNone(keys.next_body(1_000_000_000))
        keys.peer.rx_retiring = False
        self.assertIsNone(keys.next_body(1_000_000_000))
        dial = self.send(keys, 1_500_000_000)
        self.assertEqual((dial[0x16], dial[0xb]), (1, 1))
        self.assertIsNone(keys.next_body(1_500_000_000))
        for _ in range(16):self.assertEqual(self.request(session, '/key/iso-down'), 204)
        self.assertEqual(self.request(session, '/key/iso-down'), 429)
        stopped_dial = self.send(keys, 2_000_000_000)
        self.assertEqual((stopped_dial[0x16], stopped_dial[0xb]), (1, 0))
        self.assertIsNone(keys.next_body(2_000_000_000))
        self.assertEqual(self.send(keys, 2_500_000_000), key_body())
        self.assertIsNone(keys.next_body(2_500_000_000))
        finish = self.send(keys, 4_500_000_000)
        self.assertEqual((finish[0x16], finish[0xb]), (1, 0))
        self.assertIsNone(keys.next_body(4_500_000_000))
        self.assertEqual(self.send(keys, 5_000_000_000), key_body())
        self.assertIsNone(keys.next_body(5_000_000_000))
        self.assertEqual(self.send(keys, 7_000_000_000), key_body(half=True))
        self.assertIsNone(keys.next_body(7_000_000_000))
        self.assertIsNone(keys.next_body(9_000_000_000))
        self.assertFalse(keys.busy)
        self.assertTrue(keys.half)
        self.assertEqual(session.commands.qsize(), 16)

    def test_exposure_decoder_contract_and_existing_capture_inputs(self):
        row = exposure_state('iso', iso=True, dial=-1)
        self.assertEqual(decoded_contact(bytes.fromhex(row['body_hex'])), bytes.fromhex(row['expected_hex']))
        self.assertEqual(struct.unpack('<11I', bytes.fromhex(row['expected_hex'])),
                         (0x200, 0x20000000, 0, 0, 0xffffffff, 0, 0, 0, 0, 0, 0))
        self.assertEqual(len(exposure_states(mode_steps=1, shutter_steps=-1)), 5)
        for control, direction in (('iso', 0), ('iso', True), ('iso', 2), ('unknown', 1)):
            with self.assertRaises(ValueError):adjustment_states(control, direction)

    def test_exposure_waits_for_initial_live_view(self):
        session = Session()
        for command in EXPOSURE_COMMANDS:
            self.assertEqual(self.request(session, '/key/'+command), 409)
        self.assertTrue(session.commands.empty())
        session.status['ready'] = True
        self.assertEqual(self.request(session, '/key/iso-up'), 204)

    def test_shutter_releases_half_before_turning(self):
        keys = KeyController(self.peer())
        keys.start('shutter-slower')
        self.assertEqual(self.send(keys, 0), key_body())
        self.assertIsNone(keys.next_body(0))
        dial = self.send(keys, 500_000_000)
        self.assertEqual((dial[7], dial[0xb]), (0, 255))
        self.assertIsNone(keys.next_body(500_000_000))
        self.assertEqual(self.send(keys, 1_000_000_000), key_body())

    def test_exposure_wakes_a_released_camera_before_using_the_dial(self):
        keys = KeyController(self.peer());keys.half = False
        keys.start('iso-up')
        self.assertEqual(self.send(keys, 0), key_body(half=True))
        self.assertIsNone(keys.next_body(0))
        self.assertEqual(self.send(keys, 500_000_000), key_body())
        self.assertIsNone(keys.next_body(500_000_000))
        iso = self.send(keys, 1_000_000_000)
        self.assertEqual((iso[7], iso[0x16], iso[0xb]), (0, 1, 0))

    def test_next_contact_waits_for_original_keyscan_after_rx_retirement(self):
        observed = [decoded_contact(key_body())]
        keys = KeyController(self.peer(), native_state=lambda:observed[0])
        keys.start('shutter-slower')
        self.assertEqual(self.send(keys, 0), key_body())
        self.assertIsNone(keys.next_body(0))
        dial = self.send(keys, 500_000_000)
        self.assertIsNone(keys.next_body(1_000_000_000))
        self.assertEqual(len(keys.consumed), 1)
        observed[0] = decoded_contact(dial)
        self.assertIsNone(keys.next_body(2_000_000_000))
        self.assertIsNone(keys.next_body(2_499_999_999))
        self.assertEqual(self.send(keys, 2_500_000_000), key_body())
        self.assertEqual(keys.consumed[-1]['decoded_hex'], observed[0].hex())

    def test_missing_original_keyscan_is_a_bounded_failure(self):
        keys = KeyController(self.peer(), native_state=lambda:decoded_contact(key_body()))
        keys.half = False;keys.start('iso-up');self.send(keys, 0)
        self.assertIsNone(keys.next_body(1_000_000_000))
        with self.assertRaisesRegex(TimeoutError, 'key-scan'):
            keys.next_body(11_000_000_001)

    def test_stalled_transport_has_a_host_bound_even_without_virtual_progress(self):
        keys = KeyController(self.peer());keys.start('iso-up');self.send(keys, 0)
        keys.peer.rx_retiring = True
        with patch('run.time.monotonic', return_value=keys.sent_at+61):
            with self.assertRaisesRegex(TimeoutError, 'host transport'):
                keys.next_body(0)

class BoundaryClockTests(unittest.TestCase):
    def test_pause_dropped_periods_and_record_cap_do_not_change_delivery(self):
        class QMP:
            def __init__(self):self.ns=0;self.running=True;self.sent=[]
            def command(self,op,**args):
                if op=='qom-get':return json.dumps(dict(virtual_ns=self.ns,running=self.running))
                self.sent.append(args)
        class Guest:
            def __init__(self,path):self.qmp=QMP();self.out=path;self.data={}
        with tempfile.TemporaryDirectory() as directory:
            g=Guest(Path(directory));peer=BoundaryPeer(g,33)
            peer.record['limit']=1
            peer.tick();self.assertEqual(len(g.qmp.sent),1)
            g.qmp.ns=1_000_000_000;g.qmp.running=False;peer.tick()
            self.assertEqual(len(g.qmp.sent),1)
            g.qmp.running=True;peer.tick();peer.tick()
            self.assertEqual(len(g.qmp.sent),2)  # no catch-up burst
            g.qmp.ns+=34_000_000;peer.tick()
            self.assertEqual(len(g.qmp.sent),3)  # recording cap is not a device stop
            self.assertEqual(peer.record['total_deliveries'],3)
            self.assertEqual(len(peer.record['deliveries']),1)
            self.assertTrue(peer.record['record_limit_reached'])

class Inputs(unittest.TestCase):
    def test_raw_header_size_range(self):
        raw=generate(32,24)
        self.assertEqual(struct.unpack_from('<8s6I',raw),(b'NZ9RAW1\0',32,24,12,0,0,4095))
        samples=np.frombuffer(raw[32:],dtype='<u2')
        self.assertEqual(len(samples),32*24)
        self.assertLessEqual(int(samples.max()),4095)
        self.assertGreater(int(samples.max()),3000)

    def test_user_red_image_is_rggb(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'red.png';Image.new('RGB',(4,4),(255,0,0)).save(path)
            raw=np.frombuffer(generate(4,4,path)[32:],dtype='<u2').reshape(4,4)
            self.assertTrue(np.all(raw[::2,::2]==4095))
            self.assertTrue(np.all(raw[1::2]==0))
            self.assertTrue(np.all(raw[:,1::2]==0))

    def test_fragmented_transport_reconstructs_body(self):
        body=bytes(range(251))*3
        packets=frames(body,family=3,channel=3)
        self.assertEqual(len(packets),4)
        self.assertEqual(b''.join(p[8:248] for p in packets)[:len(body)],body)
        for i,p in enumerate(packets):
            self.assertEqual(len(p),256);self.assertEqual(sum(p)&255,255)
            self.assertEqual(p[252:254],bytes((4,i+1)))
            self.assertEqual(struct.unpack_from('<H',p,2)[0],len(body))

    def test_keys_are_separate_complete_inputs(self):
        menu,half,up=key_body(menu=True),key_body(half=True),key_body()
        self.assertEqual(len(menu),124)
        self.assertEqual([i for i in range(124) if menu[i]!=up[i]],[0x43])
        self.assertEqual([i for i in range(124) if half[i]!=up[i]],[7])
        for raw in (menu,half,up):self.assertEqual(sum(frames(raw,family=2)[0])&255,255)

    def test_invalid_input_rejected(self):
        for w,h in ((3,4),(0,4),(16386,4),(16384,16384)):
            with self.assertRaises(ValueError):generate(w,h)
        with self.assertRaises(ValueError):frames(bytes(241),channel=1)
        with self.assertRaises(ValueError):frames(b'')

class ServicePeer(unittest.TestCase):
    def test_smp_snapshot_services_global_breakpoint_once(self):
        pc=0x40c160d8
        class QMP:
            def hmp(self,command,cpu):
                return f'PC={pc:016x} X00=0000000000000000' if cpu in (0,1) else 'PC=0000000040000000 X00=0000000000000000'
        class Guest:
            def __init__(self):self.qmp=QMP();self.rsp_commands=[];self.qt_commands=[]
            def rsp(self,command):self.rsp_commands.append(command)
            def qt_command(self,command):self.qt_commands.append(command)
        guest=Guest();peer=Peer.__new__(Peer)
        peer.g=guest;peer.points={pc:'tx_gpio_isr'};peer.record={'events':[]}
        peer.asserted={25};peer.gic='/machine/gic'
        self.assertTrue(peer.handle())
        self.assertEqual(guest.rsp_commands,[f'z1,{pc:x},4'])
        self.assertEqual(guest.qt_commands,['set_irq_in /machine/gic unnamed-gpio-in 25 0'])
        self.assertEqual(peer.record['events'][0]['simultaneous_cpu_hits'],[0,1])
        self.assertEqual(peer.record['events'][1],{'irq':57,'level':0})

    def test_e22_is_ignored_only_when_qemu_confirms_breakpoint_absent(self):
        pc=0x40c93c48
        class QMP:
            def __init__(self,table):self.table=table
            def hmp(self,command):self.asserted_command=command;return self.table
        class Guest:
            def __init__(self,table):self.qmp=QMP(table)
            def rsp(self,command):raise RuntimeError(f'{command}: bytearray(b\'E22\')')
        peer=Peer.__new__(Peer);peer.record={}
        peer.g=Guest('No breakpoints or watchpoints.')
        self.assertFalse(peer.disarm(pc,'tx_request',[0]))
        diagnostic=peer.record['breakpoint_remove_diagnostics'][0]
        self.assertFalse(diagnostic['address_still_present'])
        self.assertEqual(peer.g.qmp.asserted_command,'info breakpoints')
        peer.record={};peer.g=Guest(f'1 hw breakpoint keep y 0x{pc:x}')
        with self.assertRaisesRegex(RuntimeError,'E22'):
            peer.disarm(pc,'tx_request',[0])
        self.assertTrue(peer.record['breakpoint_remove_diagnostics'][0]['address_still_present'])
        peer.record={};peer.g=Guest("unknown command: 'info breakpoints'")
        with self.assertRaisesRegex(RuntimeError,'E22'):
            peer.disarm(pc,'tx_request',[0])
        self.assertIsNone(peer.record['breakpoint_remove_diagnostics'][0]['address_still_present'])

class MenuAcceptanceTests(unittest.TestCase):
    def test_half_shutter_queues_while_camera_transport_is_busy(self):
        class Peer:
            tx=object();rx=object();rx_retiring=True;pending=[object()]
            def __init__(self):self.sent=[]
            def enqueue_external(self,body,family):self.sent.append((body,family))
        class Guest:
            def __init__(self):self.data={}
        peer=Peer();acceptance=MenuAcceptance(Guest(),peer,lambda _:None)
        acceptance.stage='release-in-menu';acceptance.since=0
        acceptance.tick(3,{}, {},None)
        self.assertEqual(acceptance.stage,'video')
        self.assertEqual(len(peer.sent),1)
        self.assertEqual(peer.sent[0][1],2)

if __name__=='__main__':unittest.main()
