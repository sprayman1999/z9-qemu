# SPDX-License-Identifier: GPL-2.0-or-later
"""Boot and control the local experimental Z9. No camera or USB access."""
import argparse
from collections import deque
import io
import json
from pathlib import Path
import queue
import resource
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from PIL import Image
from boot import prepare,boot,key_body
from guest import Guest,ROOT
from service_z9_mcu import Peer
from service_serial8 import WritePeer
from z9_global1_boundary_input import Peer as BoundaryPeer
from validate_run import MenuAcceptance
from z9_navigation_input import BINDINGS, key_body as navigation_body

KEY_COMMANDS = frozenset(BINDINGS) | {'half-down', 'half-up'}


class KeyController:
    """Serialize complete contacts and time pulses after MCU RX retirement.

    The worker owns this controller and sends each returned body while stopped.
    Holds and debounce gaps use guest virtual time, including when host input
    arrives faster than the guest can process it.
    """
    def __init__(self, peer):
        self.peer = peer
        self.half = True  # boot() leaves half-shutter held
        self.steps = deque()
        self.busy = False
        self.waiting = False
        self.due = 0

    def start(self, command):
        if command not in KEY_COMMANDS:
            raise ValueError('unsupported interactive key')
        if self.busy:
            raise RuntimeError('previous key has not finished')
        self.due = 0
        self.busy = True
        if command in ('half-down', 'half-up'):
            self.half = command == 'half-down'
            self.steps.append((key_body(half=self.half), 500_000_000))
        else:
            if self.half:
                self.steps.append((navigation_body(), 400_000_000))
            self.half = False
            hold = 400_000_000 if command == 'menu' else 60_000_000
            gap = 2_000_000_000 if command in ('menu', 'ok') else 500_000_000
            self.steps.extend(((navigation_body(command), hold), (navigation_body(), gap)))

    def next_body(self, virtual_ns):
        if not self.busy:
            return None
        if self.waiting:
            # RX can still be waiting behind a TX ACK or protocol replies.
            # Accepted RX also has to retire through the original flag clear.
            if self.peer.pending or self.peer.rx is not None or self.peer.rx_retiring:
                return None
            self.waiting = False
            self.due = virtual_ns + self.delay
        if virtual_ns < self.due:
            return None
        if not self.steps:
            self.busy = False
            return None
        body, self.delay = self.steps.popleft()
        self.waiting = True
        return body

class Session:
    def __init__(self):
        self.commands=queue.Queue(maxsize=16)
        self.status={'phase':'Starting','ready':False};self.png=b'';self.stop=threading.Event()
    def progress(self,message):
        self.status=dict(self.status,phase=message);print(message,flush=True)

def state(g,name):return json.loads(g.qmp.command('qom-get',path='/machine',property=name))

def worker(a,s):
    try:
        binary=a.qemu
        if binary is None:
            manifest=json.loads((ROOT/'.local/build-manifest.json').read_text())
            binary=Path(manifest['binary'])
        with Guest(a.firmware,binary,a.raw,a.output) as g:
            # ROM fixtures must be attached before process launch; see main.
            boot(g,s.progress)
            peer=Peer(g,limit_frames=1024,config_reply=True,all_mode_replies=True)
            clock=BoundaryPeer(g,33,auxiliary_masked=True)
            spi8=WritePeer(g);spi9=WritePeer(g,channel=9,wire_bits=9,allow_dummy_rx=True)
            next_capture=0;deadline=time.monotonic()+a.seconds if a.seconds else float('inf')
            keys=KeyController(peer)
            initial_frames=0;explicit_stop=False
            acceptance=MenuAcceptance(g,peer,s.progress,virtual_clock=True) if a.menu_test else None
            g.qmp.command('cont')
            while not s.stop.is_set() and time.monotonic()<deadline:
                if 'Z9_UNKNOWN' in g.log():raise RuntimeError('Unmodeled MMIO: inspect the local stderr.log')
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
                    ready=(raw['frames']>=8 and lcd.get('video_frames',0)>=8 and
                           lcd.get('last_frame_has_video',False))
                    s.status=dict(phase='Running' if ready else 'Waiting for live view',ready=ready,
                        raw_frames=raw['frames'],raw_bytes=raw['bytes'],lcd_video_frames=lcd.get('video_frames',0),
                        output=str(g.out),half_held=keys.half,queued_keys=s.commands.qsize(),key_busy=keys.busy)
                    if ready and not initial_frames:
                        initial_frames=raw['frames'];s.progress('Original LCD is receiving RAW-derived video')
                    if acceptance:acceptance.tick(now,raw,lcd,screen)
                    g.data['latest_pipeline']=dict(raw=raw,lcd=lcd)
                    next_capture=now+.5;g.qmp.command('cont')
                    if acceptance and acceptance.done:break
                if keys.busy or not s.commands.empty():
                    key_now=state(g,'runtime-clock-state')['virtual_ns']
                    body=keys.next_body(key_now)
                    if not keys.busy and not s.commands.empty():
                        cmd=s.commands.get_nowait();keys.start(cmd)
                        g.data.setdefault('keys',[]).append(dict(command=cmd,host_time=now,virtual_time=key_now/1e9))
                        body=keys.next_body(key_now)
                    if body is not None:
                        g.qmp.command('stop');peer.handle()
                        peer.enqueue_external(body,2)
                        g.qmp.command('cont')
                channels=state(g,'serial-state')
                if peer.clock_if_ready(channels):explicit_stop=True;continue
                spi8.clock_if_ready(channels[8]);spi9.clock_if_ready(channels[9])
                time.sleep(.002)
            g.qmp.command('stop');peer.close()
            if acceptance and not acceptance.done:raise AssertionError('Run ended before three MENU round trips passed')
            g.data['final_pipeline']=dict(raw=state(g,'raw-pipeline-state'),lcd=state(g,'engine1548-scanout-state'))
            g.qmp.command('screendump',filename=str(g.out/'final.ppm'))
            s.progress('Stopped')
    except Exception as exc:
        traceback.print_exc()
        s.progress('Error: '+str(exc))
        s.status['error']=repr(exc)
    finally:s.stop.set()

class PreparedGuest(Guest):
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
            route=self.path.split('?',1)[0]
            if route=='/':data=(ROOT/'tools/interactive.html').read_bytes();kind='text/html; charset=utf-8'
            elif route=='/status':data=json.dumps(s.status).encode();kind='application/json'
            elif route=='/frame':data=s.png;kind='image/png'
            else:self.send_error(404);return
            self.send_response(200);self.send_header('Content-Type',kind);self.send_header('Cache-Control','no-store')
            self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def do_POST(self):
            # Local UI only; reject cross-origin form submissions.
            if self.headers.get('Origin') not in (f'http://127.0.0.1:{port}',f'http://localhost:{port}'):
                self.send_error(403);return
            cmd=self.path.removeprefix('/key/')
            if cmd not in KEY_COMMANDS or self.path!='/key/'+cmd:self.send_error(400);return
            if s.stop.is_set() or menu_test:self.send_error(409);return
            try:s.commands.put_nowait(cmd)
            except queue.Full:self.send_error(429);return
            self.send_response(204);self.end_headers()
    return Handler


def main():
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--firmware',type=Path,required=True);p.add_argument('--qemu',type=Path)
    p.add_argument('--raw',type=Path,default=ROOT/'.local/input.raw')
    p.add_argument('--output',type=Path,default=ROOT/'.local'/time.strftime('run-%Y%m%d-%H%M%S'))
    p.add_argument('--port',type=int,default=8789);p.add_argument('--seconds',type=int,default=0)
    p.add_argument('--menu-test',action='store_true');p.add_argument('--headless',action='store_true')
    a=p.parse_args()
    if not 1<=a.port<=65535 or not 0<=a.seconds<=3600:p.error('Invalid port or duration')
    s=Session()
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
