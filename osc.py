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
    """Flattens bundles into individual messages and pushes (address, args) to a queue."""

    def __init__(self, q: queue.Queue):
        self.q = q

    def __call__(self, address, *args):
        self.q.put((address, list(args)))


class OSCReceiver:
    """Network thread running a pythonosc BlockingOSCUDPServer.

    The server runs in a daemon thread and only pushes parsed (address, args)
    tuples onto a queue — it never touches bpy.data directly (Blender's API
    isn't safe to call from a non-main thread). Applying the data is only done
    by the modal timer (see loop.py)."""

    def __init__(self, host, port):
        self.queue = queue.Queue()
        self._stop = threading.Event()

        dispatcher = Dispatcher()
        handler = _PacketQueueHandler(self.queue)
        dispatcher.set_default_handler(handler)

        self.server = BlockingOSCUDPServer((host, port), dispatcher)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

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
