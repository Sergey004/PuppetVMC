"""OSC receiver using vendored pythonosc (same as VMC4B).

This gives us full OSC spec compliance (bundles, arrays, blobs, timetags, MIDI,
etc.) without external dependencies — the pythonosc source is vendored in
vendor/pythonosc/."""

import threading
import queue
import time

# Vendored pythonosc (copied from VMC4B core/pythonosc/)
from .vendor.pythonosc.dispatcher import Dispatcher
from .vendor.pythonosc.osc_server import BlockingOSCUDPServer


class _PacketQueueHandler:
    """Forwards flattened OSC messages to the receiver's thread-safe handler."""

    def __init__(self, receiver):
        self.receiver = receiver

    def __call__(self, address, *args):
        self.receiver._handle_packet(address, args)


class OSCReceiver:
    """Network thread running a pythonosc BlockingOSCUDPServer.

    The server runs in a daemon thread and only pushes parsed (address, args)
    tuples onto a queue — it never touches bpy.data directly (Blender's API
    isn't safe to call from a non-main thread). Applying the data is only done
    by the modal timer (see loop.py)."""

    def __init__(self, host, port, face_tracking=False):
        self.queue = queue.Queue()
        self._latest = {}
        self._latest_lock = threading.Lock()
        self.recording = False
        self._face_tracking = face_tracking
        self._stop = threading.Event()

        dispatcher = Dispatcher()
        handler = _PacketQueueHandler(self)
        dispatcher.set_default_handler(handler)

        self.server = BlockingOSCUDPServer((host, port), dispatcher)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _handle_packet(self, address, args):
        timestamp = time.time()
        if self._face_tracking:
            prefix = "/avatar/parameters/"
            if address.startswith(prefix) and args:
                value = args[0]
                if isinstance(value, (int, float, bool)):
                    with self._latest_lock:
                        self._latest[address[len(prefix):]] = (timestamp, value)
            elif address == "/tracking/eye/EyesClosedAmount" and args:
                value = args[0]
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    with self._latest_lock:
                        self._latest["tracking/eye/EyesClosedAmount"] = (
                            timestamp, value,
                        )
            elif (address == "/tracking/eye/LeftRightPitchYaw"
                  and len(args) >= 4
                  and all(
                      isinstance(value, (int, float))
                      and not isinstance(value, bool)
                      for value in args[:4]
                  )):
                with self._latest_lock:
                    self._latest["tracking/eye/LeftRightPitchYaw"] = (
                        timestamp, tuple(args[:4]),
                    )
            return

        if (address == "/VMC/Ext/Bone/Pos" and len(args) >= 8
                and isinstance(args[0], str)):
            with self._latest_lock:
                self._latest[("bone", args[0])] = (timestamp, args)
            if self.recording:
                self.queue.put(
                    {"timestamp": timestamp, "address": address, "args": args}
                )
            return
        if (address == "/PuppetVMC/Anim/LocalBone/Pos" and len(args) >= 5
                and isinstance(args[0], str)):
            with self._latest_lock:
                self._latest[("local_bone", args[0])] = (timestamp, args)
            if self.recording:
                self.queue.put(
                    {"timestamp": timestamp, "address": address, "args": args}
                )
            return

        item = {"timestamp": timestamp, "address": address, "args": args}
        if self.recording and address.startswith("/VMC/Ext/"):
            self.queue.put(item)
        elif address in {
            "/PuppetVMC/Record/Start",
            "/PuppetVMC/Record/Stop",
            "/PuppetVMC/Anim/Muscle",
            "/PuppetVMC/Anim/Finger",
        }:
            self.queue.put(item)

    def take_latest(self):
        """Return and clear coalesced samples, keeping Blender work off this lock."""
        with self._latest_lock:
            latest = self._latest
            self._latest = {}
        return latest

    def _loop(self):
        # serve_forever blocks; shutdown() from stop() will break it
        try:
            self.server.serve_forever()
        except Exception:
            pass

    def stop(self):
        if self.server is not None:
            self.server.shutdown()
        self._thread.join(timeout=1.0)
        self.server = None
