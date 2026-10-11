import sys
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

import mdr
from sonybuds import BudsMonitor

CSS = """
window { }
.card {
    background-color: alpha(currentColor, 0.07);
    border-radius: 14px;
    padding: 14px;
    margin: 4px;
}
.title { font-weight: 800; font-size: 16px; }
.big { font-size: 28px; font-weight: 700; }
.small { font-size: 11px; opacity: 0.75; }
.dot {
    min-width: 10px; min-height: 10px;
    border-radius: 5px;
    background-color: rgba(127,127,127,0.45);
}
.dot-ok { background-color: #2ecc71; }
.dot-bad { background-color: #e74c3c; }
.label { font-weight: 700; }
"""


class BudCard(Gtk.Box):
    def __init__(self, label):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.set_halign(Gtk.Align.FILL)
        self.set_hexpand(True)
        self.set_css_classes(["card"])

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        lbl = Gtk.Label(label=label)
        lbl.set_css_classes(["label"])
        top.append(lbl)
        self._state = Gtk.Label(label="")
        self._state.set_css_classes(["small"])
        top.append(self._state)

        self._bar = Gtk.LevelBar(orientation=Gtk.Orientation.HORIZONTAL)
        self._bar.set_min_value(0)
        self._bar.set_max_value(100)
        self._bar.set_valign(Gtk.Align.CENTER)
        self._bar.set_hexpand(True)

        self._pct = Gtk.Label(label="--%")
        self._pct.set_css_classes(["big"])

        self.append(top)
        self.append(self._bar)
        self.append(self._pct)

    def set_level(self, pct, charging):
        if pct is None:
            self._pct.set_label("--%")
            self._state.set_label("")
            self._bar.set_value(0)
            self._bar.set_sensitive(False)
            return
        self._bar.set_sensitive(True)
        self._bar.set_value(max(0, min(100, pct)))
        self._pct.set_label(f"{pct}%")
        self._state.set_label(mdr.charging_text(charging))


class BatteryApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="local.wfc700n.battery",
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self._snap = {}
        self._monitor = None
        self._status = None
        self._dot = None
        self._updated = None
        self._cards = {}

    def do_startup(self):
        Gtk.Application.do_startup(self)
        display = Gdk.Display.get_default()
        if display is None:
            return
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self):
        if self.props.active_window:
            self.props.active_window.present()
            return
        win = Gtk.ApplicationWindow(application=self)
        win.set_title("WF-C700N Battery")
        win.set_default_size(420, 240)
        win.set_resizable(False)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        root.set_margin_top(16)
        root.set_margin_bottom(16)
        root.set_margin_start(18)
        root.set_margin_end(18)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(label="WF-C700N")
        title.set_css_classes(["title"])
        self._dot = Gtk.Box()
        self._dot.set_size_request(10, 10)
        self._dot.set_css_classes(["dot"])
        header.append(title)
        header.append(self._dot)
        header.append(Gtk.Label(label=""))

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for key, text in (("left", "LEFT"), ("right", "RIGHT"), ("case", "CASE")):
            card = BudCard(text)
            self._cards[key] = card
            row.append(card)

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._status = Gtk.Label(label="starting…")
        self._status.set_css_classes(["small"])
        self._updated = Gtk.Label(label="")
        self._updated.set_css_classes(["small"])
        refresh = Gtk.Button(label="Refresh")
        refresh.connect("clicked", lambda *_: self._monitor and self._monitor.refresh_now())
        footer.append(self._status)
        footer.append(Gtk.Label(label=""))
        footer.append(self._updated)
        footer.append(refresh)

        root.append(header)
        root.append(row)
        root.append(footer)
        win.set_child(root)
        self._window = win
        win.present()

        self._monitor = BudsMonitor(
            on_update=lambda snap: GLib.idle_add(self._handle_update, snap),
            on_state=lambda st: GLib.idle_add(self._handle_state, st),
            interval=60,
        )
        self._monitor.start()

    def _handle_update(self, snap):
        for key, value in snap.items():
            if key in self._cards:
                self._cards[key].set_level(*value)
        self._snap.update(snap)
        self._updated.set_label(time.strftime("updated %H:%M:%S"))
        return GLib.SOURCE_REMOVE

    def _handle_state(self, state):
        connected = state == BudsMonitor.STATE_CONNECTED
        self._status.set_label(state if connected else "disconnected")
        self._dot.set_css_classes(["dot", "dot-ok" if connected else "dot-bad"])
        if not connected:
            self._updated.set_label("")
        return GLib.SOURCE_REMOVE

    def do_shutdown(self):
        if self._monitor:
            self._monitor.stop()
        Gtk.Application.do_shutdown(self)


def main():
    if "--cli" in sys.argv:
        run_cli()
        return 0

    smoke = "--smoke" in sys.argv
    app = BatteryApp()
    if smoke:
        GLib.timeout_add(2500, app.quit)
    return app.run(None)


def run_cli():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--mac", default=None)
    args, _ = ap.parse_known_args()

    mac = args.mac or mdr.discover_device("WF-C700N")
    if not mac:
        print("WF-C700N: not detected (not connected)")
        sys.exit(1)
    print(f"WF-C700N @ {mac}")
    link = mdr.MdrLink(mac)
    try:
        link.connect()
        link.handshake(timeout=3.0)
        lr = link.command(0x01)
        ca = link.command(0x02)
        sn = link.command(0x00) if not lr else None
    except mdr.MdrError as e:
        print(f"error: {e}")
        sys.exit(1)
    finally:
        link.close()

    def show(kind, val):
        if val:
            pct, charging = val
            print(f"{kind:>7}: {pct}% ({mdr.charging_text(charging)})")
        else:
            print(f"{kind:>7}: --")

    left = right = ca_val = None
    if lr:
        left, right = mdr.parse_battery(lr[1], lr[2:]).values()
    if ca:
        ca_val = mdr.parse_battery(ca[1], ca[2:]).get("case")
    show("left", left)
    show("right", right)
    show("case", ca_val)
    if sn and not lr:
        single = mdr.parse_battery(sn[1], sn[2:]).get("single")
        show("buds", single)


if __name__ == "__main__":
    sys.exit(main())