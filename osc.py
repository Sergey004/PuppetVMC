"""Minimal parser for single (non-bundle) OSC messages, no external dependencies.
VMC sends plain messages shaped like:
    /VMC/Ext/Bone/Pos  ,sfffffff  name px py pz qx qy qz qw
"""

import socket
import struct
import threading
import queue


def _read_osc_string(data, pos):
    end = data.index(b'\x00', pos)
    s = data[pos:end].decode('utf-8', errors='ignore')
    pos = (end + 4) & ~3  # align to 4-byte boundary
    return s, pos


def parse_osc_message(data):
    """Parses a single OSC message. Returns (address, args) or None if this
    isn't a message (e.g. #bundle — intentionally not handled here, VMC
    usually sends messages one at a time)."""
    if not data.startswith(b'/'):
        return None
    address, pos = _read_osc_string(data, 0)
    if pos >= len(data) or data[pos:pos + 1] != b',':
        return address, []
    type_tags, pos = _read_osc_string(data, pos)
    args = []
    for tag in type_tags[1:]:  # skip the leading comma
        if tag == 'f':
            (val,) = struct.unpack_from('>f', data, pos)
            args.append(val)
            pos += 4
        elif tag == 'i':
            (val,) = struct.unpack_from('>i', data, pos)
            args.append(val)
            pos += 4
        elif tag == 's':
            val, pos = _read_osc_string(data, pos)
            args.append(val)
        else:
            break  # unsupported type — stop parsing this message
    return address, args


class OSCReceiver:
    """Network thread. IMPORTANT: it only receives UDP and pushes onto a
    queue — it never touches bpy.data directly (Blender's API isn't safe to
    call from a non-main thread). Applying the data is only done by the
    modal timer (see loop.py)."""

    def __init__(self, port):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", port))
        self.sock.settimeout(0.5)
        self.queue = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while not self._stop.is_set():
            try:
                data, _ = self.sock.recvfrom(65536)
            except socket.timeout:
                continue
            except OSError:
                break
            parsed = parse_osc_message(data)
            if parsed:
                self.queue.put(parsed)

    def stop(self):
        self._stop.set()
        self.sock.close()
