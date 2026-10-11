import threading
import time

import mdr


class BudsMonitor(threading.Thread):
    """Polls earbud + case battery over the Sony MDR v2 link.

    Runs the (blocking) protocol I/O on this thread; results are handed back to
    the GUI thread through callbacks marshalled by the caller (GLib.idle_add).
    """

    STATE_DISCONNECTED = "disconnected"
    STATE_CONNECTING = "connecting"
    STATE_CONNECTED = "connected"

    def __init__(self, on_update, on_state, interval=60, retry=15, name_hint="WF-C700N", mac=None):
        super().__init__(daemon=True, name="buds-monitor")
        self.on_update = on_update
        self.on_state = on_state
        self.interval = interval
        self.retry = retry
        self.name_hint = name_hint
        self.fixed_mac = mac
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._link = None

    def stop(self):
        self._stop.set()
        self._wake.set()

    def refresh_now(self):
        self._wake.set()

    def run(self):
        while not self._stop.is_set():
            try:
                mac = self.fixed_mac or mdr.discover_device(self.name_hint)
                if not mac:
                    raise mdr.MdrError("no connected WF-C700N found")
                self._set_state(self.STATE_CONNECTING)
                link = mdr.MdrLink(mac)
                link.notify = self._on_notify
                link.connect()
                link.handshake(timeout=3.0)
                self._link = link
                self._set_state(self.STATE_CONNECTED)
                while not self._stop.is_set():
                    snap = self._query(link)
                    if snap is not None:
                        self.on_update(snap)
                    self._wake.clear()
                    self._wait_idle()
                break
            except Exception as e:
                self._disconnect()
                self._set_state(self.STATE_DISCONNECTED)
                self._set_error(str(e))
                if self._stop.wait(self.retry if not self._wake.is_set() else 0.1):
                    break
                self._wake.clear()

    def _query(self, link):
        lr = link.command(0x01)
        snap = {}
        if lr:
            snap.update(mdr.parse_battery(lr[1], lr[2:]))
        ca = link.command(0x02)
        if ca:
            snap.update(mdr.parse_battery(ca[1], ca[2:]))
        if not lr:
            sn = link.command(0x00)
            if sn:
                snap.update(mdr.parse_battery(sn[1], sn[2:]))
        return snap if snap else None

    def _wait_idle(self):
        step = 0.5
        waited = 0.0
        while waited < self.interval and not self._stop.is_set():
            self._stop.wait(step)
            waited += step
            if self._wake.is_set():
                return

    def _on_notify(self, kind, pct, charging):
        self.on_update({kind: (pct, charging)})

    def _set_state(self, state):
        try:
            self.on_state(state)
        except Exception:
            pass

    def _set_error(self, msg):
        try:
            self.on_state(f"{self.STATE_DISCONNECTED}: {msg}")
        except Exception:
            pass

    def _disconnect(self):
        if self._link:
            self._link.close()
            self._link = None