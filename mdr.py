import re
import select
import socket
import subprocess
import time

V2_UUID = bytes.fromhex("956c7b26d49a4ba8b03fb17d393cb6e2")
V1_UUID = bytes.fromhex("96cc203e506846adb32de316f5e069ba")

SDP_PSM = 1
BTPROTO_RFCOMM = socket.BTPROTO_RFCOMM
SOL_RFCOMM = 18
RFCOMM_LM = 3
LM_AUTH_ENCRYPT = 0x0006  # RFCOMM_LM_AUTH | RFCOMM_LM_ENCRYPT


class MdrError(Exception):
    pass


def adapter_mac():
    out = subprocess.run(["bluetoothctl", "show"], capture_output=True, text=True, timeout=5).stdout
    m = re.search(r"Controller ([0-9A-F:]{17})", out)
    return m.group(1) if m else None


def discover_device(name_hint="WF-C700N"):
    out = subprocess.run(["bluetoothctl", "devices", "Connected"],
                         capture_output=True, text=True, timeout=5).stdout
    for line in out.splitlines():
        m = re.match(r"Device\s+([0-9A-F:]{17})\s+(.*)", line.strip())
        if m:
            mac, name = m.groups()
            if name_hint and (name_hint in name or name.startswith("WF-")):
                return mac
            if not name_hint:
                return mac
    return None


def de_len(data, pos):
    t = data[pos]
    if 0x08 <= t <= 0x0C:
        return 1 << (t - 0x08)
    if t == 0x19:
        return 2
    if t == 0x1A:
        return 4
    if t == 0x1B:
        return 8
    if t == 0x1C:
        return 16
    return 0


def de_content(data, pos):
    t = data[pos]
    if t in (0x35, 0x36):
        ln = data[pos + 1]
        return data[pos + 2:pos + 2 + ln], pos + 2 + ln
    if t in (0x37, 0x38):
        ln = int.from_bytes(data[pos + 1:pos + 3], "big")
        return data[pos + 3:pos + 3 + ln], pos + 3 + ln
    if t in (0x39, 0x3A):
        ln = int.from_bytes(data[pos + 1:pos + 5], "big")
        return data[pos + 5:pos + 5 + ln], pos + 5 + ln
    ln = de_len(data, pos)
    return data[pos + 1:pos + 1 + ln], pos + 1 + ln


def find_channel(val):
    v, _ = de_content(val, 0)
    j = 0
    while j < len(v):
        t = v[j]
        if t in (0x35, 0x36, 0x37, 0x38):
            sub, n2 = de_content(v, j)
            if len(sub) >= 3 and sub[0] == 0x19:
                u = int.from_bytes(sub[1:3], "big")
                if u == 0x0003 and len(sub) >= 4 and sub[3] in (0x08, 0x09):
                    return int.from_bytes(sub[4:4 + de_len(sub, 3)], "big")
            j = n2
        elif t == 0x19:
            j += 3
        else:
            j += 1
    return None


def parse_protocols(attrlist):
    i = 0
    while i + 3 <= len(attrlist):
        if attrlist[i] == 0x09 and attrlist[i + 1] == 0x00 and attrlist[i + 2] == 0x04:
            return find_channel(attrlist[i + 3:])
        if attrlist[i] in (0x35, 0x36, 0x37, 0x38, 0x39, 0x3A):
            _, nxt = de_content(attrlist, i)
            i = nxt
        else:
            i += 1
    return None


def sdp_channel(mac):
    local = adapter_mac()
    if not local:
        return None
    for uuid in (V2_UUID, V1_UUID):
        try:
            s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, socket.BTPROTO_L2CAP)
            s.settimeout(5)
            s.bind((local, 0))
            s.connect((mac, SDP_PSM))
            pattern = b"\x35\x11\x1c" + uuid
            attr_ids = b"\x35\x06\x09\x00\x01\x09\x00\x04"
            body = pattern + bytes.fromhex("ffff") + attr_ids + b"\x00"
            pdu = b"\x06\x00\x01" + len(body).to_bytes(2, "big") + body
            s.sendall(pdu)
            data = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
                if len(data) < 5:
                    continue
                plen = int.from_bytes(data[3:5], "big")
                if len(data) >= 5 + plen:
                    break
            s.close()
            if len(data) < 5 or data[0] != 0x07:
                continue
            params = data[5:5 + plen]
            listlen = int.from_bytes(params[:2], "big")
            attrlist = params[2:2 + listlen]
            ch = parse_protocols(attrlist)
            if ch:
                return ch
        except OSError:
            continue
    return None


def build_frame(payload, seq, dtype=0x0C):
    body = bytes([dtype, seq]) + len(payload).to_bytes(4, "big") + payload
    checksum = sum(body) & 0xFF
    frame = bytes([0x3E]) + body + bytes([checksum, 0x3C])
    out = bytearray()
    for i, b in enumerate(frame):
        if b in (0x3C, 0x3D, 0x3E) and 0 < i < len(frame) - 1:
            out.append(0x3D)
            out.append(b & ~0x10)
        else:
            out.append(b)
    return bytes(out)


def unstuff(data):
    out = bytearray()
    i = 0
    while i < len(data):
        b = data[i]
        if b == 0x3D and i + 1 < len(data):
            out.append(data[i + 1] | 0x10)
            i += 2
        else:
            out.append(b)
            i += 1
    return bytes(out)


def parse_frame(unstuffed):
    if len(unstuffed) < 8 or unstuffed[0] != 0x3E or unstuffed[-1] != 0x3C:
        return None
    body = unstuffed[1:-2]
    chk = unstuffed[-2]
    if (sum(body) & 0xFF) != chk:
        return None
    dtype = body[0]
    seq = body[1]
    ln = int.from_bytes(body[2:6], "big")
    return dtype, seq, body[6:6 + ln]


class MdrLink:
    def __init__(self, mac):
        self.mac = mac
        self.sock = None
        self.buf = b""
        self.tx = 0
        self.notify = None  # optional callable(battery_kind, pct, charging)

    def connect(self):
        ch = sdp_channel(self.mac)
        if not ch:
            raise MdrError("SDP: no RFCOMM channel found")
        s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, BTPROTO_RFCOMM)
        s.settimeout(10)
        try:
            s.setsockopt(SOL_RFCOMM, RFCOMM_LM, LM_AUTH_ENCRYPT)
        except OSError:
            pass
        s.connect((self.mac, ch))
        self.sock = s
        self.buf = b""
        self.tx = 0

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None

    def send_frame(self, payload, dtype=0x0C):
        if not self.sock:
            raise MdrError("not connected")
        self.sock.sendall(build_frame(payload, self.tx, dtype))

    def send_ack(self, seq):
        self.sock.sendall(build_frame(b"", 1 - seq, dtype=0x01))

    def handshake(self, timeout=3.0):
        self.send_frame(b"\x00\x00")
        deadline = time.time() + timeout
        while time.time() < deadline:
            f = self.read_frame(timeout)
            if not f:
                break
            dtype, seq, pl = f
            if dtype == 0x01:
                if seq == 1 - self.tx:
                    self.tx = 1 - self.tx
                continue
            self.send_ack(seq)
            return pl
        return None

    def read_frame(self, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            idx = self.buf.find(b"\x3e")
            if idx < 0:
                self.buf = b""
            else:
                self.buf = self.buf[idx:]
            end = self.buf.find(b"\x3c")
            if end > 0:
                frame = unstuff(self.buf[:end + 1])
                self.buf = self.buf[end + 1:]
                if frame and frame[0] == 0x3E:
                    return parse_frame(frame)
            if not self.sock:
                return None
            ready, _, _ = select.select([self.sock], [], [], 0.5)
            if not ready:
                continue
            chunk = self.sock.recv(4096)
            if not chunk:
                self.close()
                return None
            self.buf += chunk
        return None

    def command(self, subtype, timeout=5.0):
        payload = bytes([0x22, subtype])
        self._expect = subtype
        self.send_frame(payload)
        deadline = time.time() + timeout
        while time.time() < deadline:
            f = self.read_frame(timeout)
            if not f:
                break
            dtype, seq, pl = f
            if dtype == 0x01:
                if seq == 1 - self.tx:
                    self.tx = 1 - self.tx
                continue
            self.send_ack(seq)
            if not pl:
                continue
            op = pl[0]
            if op in (0x23, 0x25) and len(pl) >= 2 and pl[1] == subtype:
                self._emit(pl)
                if op == 0x23:
                    return pl
        return None

    def _emit(self, pl):
        if not self.notify:
            return
        built = parse_battery(pl[1], pl[2:])
        if built:
            for kind, (pct, charging) in built.items():
                try:
                    self.notify(kind, pct, charging)
                except Exception:
                    pass


def parse_battery(kind, data):
    result = {}
    if kind == 0 and len(data) >= 2:
        result["single"] = (data[0], data[1])
    elif kind == 1 and len(data) >= 4:
        result["left"] = (data[0], data[1])
        result["right"] = (data[2], data[3])
    elif kind == 2 and len(data) >= 2:
        result["case"] = (data[0], data[1])
    return result


CHARGING_TEXT = {
    0: "not charging",
    1: "charging",
    2: "unknown",
    3: "charged",
    0xFF: "unknown",
}


def charging_text(v):
    return CHARGING_TEXT.get(v, "unknown")