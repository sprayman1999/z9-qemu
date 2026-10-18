# SPDX-License-Identifier: GPL-2.0-or-later
"""Boot and control the local experimental Z9. No camera or USB access."""
import argparse
from collections import deque
import io
import json
from pathlib import Path
import queue
import resource
import struct
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import quote
from PIL import Image
from boot import prepare,boot,key_body
from guest import Guest,ROOT
from service_z9_mcu import Peer
from service_serial8 import WritePeer
from z9_global1_boundary_input import Peer as BoundaryPeer
from validate_run import MenuAcceptance
from z9_navigation_input import BINDINGS, key_body as navigation_body
from z9_exposure_input import adjustment_states

DEFAULT_CARD = ROOT / '.local/cards/playback-card.raw'

DRIVE_MODES = {'drive-single': 0, 'drive-cl': 1, 'drive-ch': 2}
DRIVE_LABELS = {0: 'S', 1: 'CL', 2: 'CH'}
EXPOSURE_COMMANDS = {
    'iso-down': ('iso', -1), 'iso-up': ('iso', 1),
    'shutter-slower': ('shutter', -1), 'shutter-faster': ('shutter', 1),
    'mode-previous': ('mode', -1), 'mode-next': ('mode', 1),
}
KEY_COMMANDS = (frozenset(BINDINGS) | frozenset(DRIVE_MODES) |
                frozenset(EXPOSURE_COMMANDS) | {'half-down', 'half-up'})


def decoded_contact(body):
    """Expected native C5.32 key-scan state for this controller's contacts."""
    sw0 = (0x200 if body[4] else 0) | (0x80000000 if body[7] else 0)
    sw0 |= 0x800 if body[0x0e] else 0
    sw1 = 0x20000000 if body[0x16] else 0
    for byte, mask0, mask1 in BINDINGS.values():
        if body[byte]:sw0 |= mask0;sw1 |= mask1
    signed = lambda offset: int.from_bytes(body[offset:offset+1], 'little', signed=True) & 0xffffffff
    return struct.pack('<11I', sw0, sw1, 0, 0, signed(0x0b), signed(0x0c),
                       signed(0x5f), signed(0x60), body[0x0f] | (body[0x11] << 16),
                       body[0x7b] | (body[0x7a] << 8) | (body[0x57] << 16),
                       body[0x36] | (body[0x19] << 16))


class KeyController:
    """Serialize contacts after MCU RX retirement and native key-scan consumption.

    The worker owns this controller and sends each returned body while stopped.
    Holds and debounce gaps use guest virtual time, including when host input
    arrives faster than the guest can process it.
    """
    def __init__(self, peer, *, native_state=None):
        self.peer = peer
        self.half = True  # boot() leaves half-shutter held
        self.release_mode = 0  # complete boot contacts select S
        self.steps = deque()
        self.busy = False
        self.waiting = False
        self.due = 0
        self.native_state = native_state
        self.native_since = None
        self.consumed = []
        self.sent_at = None

    def contact(self, body):
        data = bytearray(body)
        # This is an absolute dial position, not a press/release bit.
        data[0x11] = self.release_mode
        return bytes(data)

    def start(self, command):
        if command not in KEY_COMMANDS:
            raise ValueError('unsupported interactive key')
        if self.busy:
            raise RuntimeError('previous key has not finished')
        self.due = 0
        self.busy = True
        if command in DRIVE_MODES:
            if self.half:
                self.steps.append((self.contact(navigation_body()), 400_000_000))
            self.half = False
            self.release_mode = DRIVE_MODES[command]
            self.steps.append((self.contact(navigation_body()), 2_000_000_000))
        elif command in ('half-down', 'half-up'):
            self.half = command == 'half-down'
            self.steps.append((self.contact(key_body(half=self.half)), 500_000_000))
        elif command in EXPOSURE_COMMANDS:
            control, direction = EXPOSURE_COMMANDS[command]
            if not self.half:
                self.steps.append((self.contact(key_body(half=True)), 500_000_000))
            self.steps.append((self.contact(navigation_body()), 500_000_000))
            for row in adjustment_states(control, direction):
                self.steps.append((self.contact(bytes.fromhex(row['body_hex'])), row['hold_ns']))
            self.steps.append((self.contact(key_body(half=True)), 2_000_000_000))
            self.half = True
        else:
            if self.half:
                self.steps.append((self.contact(navigation_body()), 400_000_000))
            self.half = False
            hold = 400_000_000 if command == 'menu' else 60_000_000
            gap = 2_000_000_000 if command in ('menu', 'ok', 'playback', 'release-mode') else 500_000_000
            self.steps.extend(((self.contact(navigation_body(command)), hold),
                               (self.contact(navigation_body()), gap)))

    def next_body(self, virtual_ns):
        if not self.busy:
            return None
        if self.waiting:
            if time.monotonic() - self.sent_at > 60:
                raise TimeoutError('Interactive contact did not retire within the host transport bound')
            # RX can still be waiting behind a TX ACK or protocol replies.
            # Accepted RX also has to retire through the original flag clear.
            if self.peer.pending or self.peer.rx is not None or self.peer.rx_retiring:
                return None
            if self.native_state is not None:
                if self.native_since is None:self.native_since = virtual_ns
                actual = self.native_state()
                if actual != self.expected_native:
                    if virtual_ns - self.native_since > 10_000_000_000:
                        raise TimeoutError('Original key-scan task did not consume the interactive contact')
                    return None
                self.consumed.append(dict(body_hex=self.delivered_body.hex(),
                    decoded_hex=actual.hex(), virtual_ns=virtual_ns))
            self.waiting = False
            self.due = virtual_ns + self.delay
        if virtual_ns < self.due:
            return None
        if not self.steps:
            self.busy = False
            return None
        body, self.delay = self.steps.popleft()
        self.waiting = True
        self.sent_at = time.monotonic()
        self.native_since = None
        self.delivered_body = body
        self.expected_native = decoded_contact(body)
        return body

class Session:
    def __init__(self):
        self.commands=queue.Queue(maxsize=16)
        self.status={'phase':'Starting','ready':False};self.png=b'';self.stop=threading.Event()
        self.capture_pending=False;self.capture_lock=threading.Lock()
    def progress(self,message):
        self.status=dict(self.status,phase=message);print(message,flush=True)

def state(g,name):return json.loads(g.qmp.command('qom-get',path='/machine',property=name))

def live_view_ready(raw,lcd):
    return (raw.get('frames',0)>=8 and lcd.get('video_frames',0)>=8 and
            lcd.get('last_frame_has_video',False))

def worker(a,s):
    log_guard=None
    try:
        # Standalone capture workers supply their own card-bearing Guest.
        card=getattr(a,'card',None);card_snapshot=getattr(a,'card_snapshot',False)
        binary=a.qemu
        if binary is None:
            manifest=json.loads((ROOT/'.local/build-manifest.json').read_text())
            binary=Path(manifest['binary'])
        card_options=dict(card=card,card_snapshot=card_snapshot) if card is not None else {}
        with Guest(a.firmware,binary,a.raw,a.output,**card_options) as g:
            from native_log_guard import NativeLogGuard
            log_guard=NativeLogGuard(g.log_path)
            card_status=dict(card_attached=card is not None,
                card_path=str(card.resolve()) if card is not None else None,
                card_persistent=card is not None and not card_snapshot)
            s.status.update(card_status)
            # ROM fixtures must be attached before process launch; see main.
            boot(g,s.progress)
            peer=Peer(g,limit_frames=1024,config_reply=True,all_mode_replies=True)
            clock=BoundaryPeer(g,33,auxiliary_masked=True)
            spi8=WritePeer(g);spi9=WritePeer(g,channel=9,wire_bits=9,allow_dummy_rx=True)
            next_capture=0;deadline=time.monotonic()+a.seconds if a.seconds else float('inf')
            # Original key task at 40d28b5c accumulates rotary counts and copies
            # this 44-byte state at 40d28f30. RX retirement alone precedes it.
            keys=KeyController(peer,native_state=lambda:g.read_bytes(0xa03222034,44))
            g.data['interactive_key_consumers']=keys.consumed
            initial_frames=0;explicit_stop=False;auto_contact_index=-1
            acceptance=MenuAcceptance(g,peer,s.progress,virtual_clock=True) if a.menu_test else None
            g.qmp.command('cont')
            while not s.stop.is_set() and time.monotonic()<deadline:
                if log_guard.poll():raise RuntimeError('Unmodeled MMIO: inspect the local stderr.log')
                if not g.qmp.command('query-status')['running']:
                    handled=peer.handle()
                    if not handled and not explicit_stop:raise RuntimeError('Guest stopped outside the modeled peer')
                    explicit_stop=False;g.qmp.command('cont');continue
                clock.tick()
                now=time.monotonic()
                if now>=next_capture:
                    g.qmp.command('stop')
                    # Handle a simultaneously reached peer breakpoint before
                    # continuing from our requested capture stop.
                    peer.handle()
                    raw=state(g,'raw-pipeline-state');lcd=state(g,'engine1548-scanout-state')
                    screen=g.out/'display.ppm';g.qmp.command('screendump',filename=str(screen))
                    with Image.open(screen) as im:
                        buf=io.BytesIO();im.save(buf,format='PNG');s.png=buf.getvalue()
                    ready=live_view_ready(raw,lcd)
                    available=ready or bool(initial_frames)
                    capture_status=(peer.browser_status() if hasattr(peer,'browser_status') else
                        dict(capture_supported=False,capture_ready=False,manual_ready=True,
                             capture_unavailable=getattr(a,'capture_unavailable','Preview-only session')))
                    s.status=dict(phase='Running' if available else 'Waiting for live view',ready=available,
                        live_view=ready,
                        raw_frames=raw['frames'],raw_bytes=raw['bytes'],lcd_video_frames=lcd.get('video_frames',0),
                        output=str(g.out),half_held=keys.half,queued_keys=s.commands.qsize(),key_busy=keys.busy,
                        **card_status,
                        **capture_status,
                        drive_mode=DRIVE_LABELS[keys.release_mode])
                    if ready and not initial_frames:
                        initial_frames=raw['frames'];s.progress('Original LCD is receiving RAW-derived video')
                    if acceptance:acceptance.tick(now,raw,lcd,screen)
                    g.data['latest_pipeline']=dict(raw=raw,lcd=lcd)
                    next_capture=now+.5;g.qmp.command('cont')
                    if acceptance and acceptance.done:break
                manual_ready=not hasattr(peer,'browser_status') or peer.browser_status().get('manual_ready',True)
                if hasattr(peer,'browser_status') and peer.browser_status() and manual_ready and peer.index!=auto_contact_index:
                    auto_contact_index=peer.index
                    last=bytes.fromhex(peer.states[peer.index-1]['body_hex'])
                    keys.half=bool(last[7]);keys.release_mode=last[0x11]
                if manual_ready and (keys.busy or not s.commands.empty()):
                    key_now=state(g,'runtime-clock-state')['virtual_ns']
                    body=keys.next_body(key_now)
                    if not keys.busy and not s.commands.empty():
                        cmd=s.commands.get_nowait()
                        if cmd=='capture':
                            peer.request_capture();keys.half=False
                        else:keys.start(cmd)
                        g.data.setdefault('keys',[]).append(dict(command=cmd,host_time=now,virtual_time=key_now/1e9))
                        body=keys.next_body(key_now)
                    if body is not None:
                        g.qmp.command('stop');peer.handle()
                        if hasattr(peer,'manual_contact'):peer.manual_contact(body)
                        peer.enqueue_external(body,2)
                        g.qmp.command('cont')
                channels=state(g,'serial-state')
                if peer.clock_if_ready(channels):explicit_stop=True;continue
                spi8.clock_if_ready(channels[8]);spi9.clock_if_ready(channels[9])
                time.sleep(.002)
            g.qmp.command('stop');peer.close()
            if hasattr(peer,'browser_status') and (s.capture_pending or peer.browser_status().get('capture_busy')):
                raise TimeoutError('Run ended before the photograph completed and was saved')
            if acceptance and not acceptance.done:raise AssertionError('Run ended before three MENU round trips passed')
            g.data['final_pipeline']=dict(raw=state(g,'raw-pipeline-state'),lcd=state(g,'engine1548-scanout-state'))
            g.qmp.command('screendump',filename=str(g.out/'final.ppm'))
            s.progress('Stopped')
    except Exception as exc:
        traceback.print_exc()
        s.progress('Error: '+str(exc))
        s.status['error']=repr(exc)
    finally:
        if log_guard is not None:log_guard.close()
        s.capture_pending=False
        s.stop.set()

class PreparedGuest(Guest):
    def __init__(self,*args,card=None,card_snapshot=False):
        super().__init__(*args)
        try:
            if card is not None:
                from virtual_recording_card import attach_existing
                attach_existing(self,card,snapshot=card_snapshot)
        except BaseException as exc:
            self.__exit__(type(exc),exc,None)
            raise

    def __enter__(self):
        try:prepare(self)
        except BaseException as exc:
            self.__exit__(type(exc),exc,None)
            raise
        return super().__enter__()

Guest=PreparedGuest

def make_handler(s,port,*,menu_test=False):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            filename=None
            route=self.path.split('?',1)[0]
            if route=='/':data=(ROOT/'tools/interactive.html').read_bytes();kind='text/html; charset=utf-8'
            elif route=='/status':data=json.dumps(dict(s.status,capture_pending=s.capture_pending)).encode();kind='application/json'
            elif route=='/frame':data=s.png;kind='image/png'
            elif route.startswith('/photo/'):
                index=route.removeprefix('/photo/')
                photos=s.status.get('photos',[])
                if not index.isascii() or not index.isdecimal() or len(index)>4 or int(index)>=len(photos):self.send_error(404);return
                path=Path(photos[int(index)]['cache'])
                try:data=path.read_bytes()
                except OSError:self.send_error(404);return
                kind='application/octet-stream';filename=path.name
            else:self.send_error(404);return
            self.send_response(200);self.send_header('Content-Type',kind);self.send_header('Cache-Control','no-store')
            if filename:self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+quote(filename,safe=''))
            self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def do_POST(self):
            # Local UI only; reject cross-origin form submissions.
            if self.headers.get('Origin') not in (f'http://127.0.0.1:{port}',f'http://localhost:{port}'):
                self.send_error(403);return
            if self.path=='/capture':
                with s.capture_lock:
                    if (s.stop.is_set() or menu_test or s.capture_pending or
                            not s.status.get('capture_ready') or s.status.get('capture_busy') or
                            s.status.get('drive_mode')!='S'):
                        self.send_error(409);return
                    try:s.commands.put_nowait('capture')
                    except queue.Full:self.send_error(429);return
                    s.capture_pending=True
                self.send_response(204);self.end_headers();return
            cmd=self.path.removeprefix('/key/')
            if cmd not in KEY_COMMANDS or self.path!='/key/'+cmd:self.send_error(400);return
            if s.stop.is_set() or menu_test:self.send_error(409);return
            if s.capture_pending or s.status.get('capture_busy') or not s.status.get('manual_ready',True):
                self.send_error(409);return
            if cmd in EXPOSURE_COMMANDS and not s.status.get('ready'):
                self.send_error(409);return
            try:s.commands.put_nowait(cmd)
            except queue.Full:self.send_error(429);return
            self.send_response(204);self.end_headers()
    return Handler


def argument_parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--firmware',type=Path,required=True);p.add_argument('--qemu',type=Path)
    p.add_argument('--raw',type=Path,default=ROOT/'.local/z9-14bit.raw')
    p.add_argument('--preview-only',action='store_true',help='omit the full RAW capture profile')
    p.add_argument('--auto-setup-raw',action='store_true',
        help='opt in to automatic RAW quality setup and post-photo menu acceptance checks')
    cards=p.add_mutually_exclusive_group()
    cards.add_argument('--card',type=Path,default=DEFAULT_CARD,
        help='existing MBR exFAT .raw card; default: %(default)s; guest writes persist')
    cards.add_argument('--no-card',action='store_const',const=None,dest='card',
        help='start without a virtual card')
    p.add_argument('--card-snapshot',action='store_true',
        help='discard card writes on exit instead of persisting them')
    p.add_argument('--output',type=Path,default=ROOT/'.local'/time.strftime('run-%Y%m%d-%H%M%S'))
    p.add_argument('--port',type=int,default=8789);p.add_argument('--seconds',type=int,default=0)
    p.add_argument('--menu-test',action='store_true');p.add_argument('--headless',action='store_true')
    return p


def main():
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    p=argument_parser()
    a=p.parse_args()
    if not 1<=a.port<=65535 or not 0<=a.seconds<=3600:p.error('Invalid port or duration')
    if a.card is not None and not a.card.is_file():
        p.error(f'Virtual card does not exist: {a.card}; supply --card PATH or use --no-card')
    if a.card_snapshot and a.card is None:p.error('--card-snapshot requires a card')
    if a.auto_setup_raw and (a.preview_only or a.card is None or a.card_snapshot or a.menu_test or a.headless):
        p.error('--auto-setup-raw requires an interactive capture session with a persistent card')
    if not a.raw.exists() and a.raw==ROOT/'.local/z9-14bit.raw':
        from make_cmos import generate
        print('Generating full-resolution 14-bit sensor input',flush=True)
        a.raw.parent.mkdir(parents=True,exist_ok=True)
        data=generate(8280,5520,bits=14)
        with a.raw.open('xb') as stream:stream.write(data)
        del data
    a.capture_unavailable='Use a persistent card and full-resolution 14-bit input for photo capture'
    if not a.preview_only and a.card is not None and not a.card_snapshot and not a.menu_test and not a.headless:
        from capture_support import full_sensor
        try:full_sensor(a.raw)
        except ValueError as exc:a.capture_unavailable=str(exc)
        else:
            from capture_sequence import interactive
            return interactive(a)
    s=Session()
    return serve(a,s)


def serve(a,s):
    if a.headless:
        worker(a,s)
        if 'error' in s.status:raise SystemExit(1)
        return
    server=ThreadingHTTPServer(('127.0.0.1',a.port),make_handler(s,a.port,menu_test=a.menu_test))
    task=threading.Thread(target=worker,args=(a,s),daemon=True);task.start()
    print(f'http://127.0.0.1:{a.port}/',flush=True)
    try:server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:pass
    finally:s.stop.set();server.server_close();task.join(timeout=40)

if __name__=='__main__':main()
