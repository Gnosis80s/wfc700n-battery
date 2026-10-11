#!/usr/bin/env python3
"""Waybar-style and structured JSON output for WF-C700N battery.

- default: Waybar JSON (text + tooltip + class)
- --json-full: structured JSON {connected, levels:{left:(pct,ch), right:(pct,ch), case:(pct,ch), single:(pct,ch)}, error?}
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mdr

ICON = "\U000F0309"  # mdi-earbuds
NAME = "WF-C700N"


def emit_waybar(text, tooltip, active=False):
    print(json.dumps({
        "text": text,
        "tooltip": tooltip,
        "class": "active" if active else "",
    }))


def emit_full(obj):
    print(json.dumps(obj))


def read_levels_full():
    mac = mdr.discover_device(NAME)
    if not mac:
        return {"connected": False, "error": "not_connected"}
    link = mdr.MdrLink(mac)
    try:
        
        link.connect()
        link.handshake(timeout=2.0)
        lr = link.command(0x01, timeout=3.5)
        ca = link.command(0x02, timeout=3.5)
        sn = link.command(0x00, timeout=3.5) if not lr else None
    except Exception as e:
        return {"connected": False, "error": str(e)}
    finally:
        try:
            link.close()
        except Exception:
            pass

    levels = {}
    if lr:
        levels.update(mdr.parse_battery(lr[1], lr[2:]))
    if ca:
        levels.update(mdr.parse_battery(ca[1], ca[2:]))
    if sn and not lr:
        levels.update(mdr.parse_battery(sn[1], sn[2:]))
    if not levels:
        return {"connected": False, "error": "no_data"}
    return {"connected": True, "levels": levels}


def read_levels_waybar():
    mac = mdr.discover_device(NAME)
    if not mac:
        emit_waybar(f"{ICON} –", f"{NAME}: not connected")
        return
    link = mdr.MdrLink(mac)
    try:
        
        link.connect()
        link.handshake(timeout=2.0)
        lr = link.command(0x01, timeout=3.5)
        ca = link.command(0x02, timeout=3.5)
        sn = link.command(0x00, timeout=3.5) if not lr else None
    except Exception as e:
        emit_waybar(f"{ICON} –", f"{NAME}: unreachable\n{e}")
        return
    finally:
        try:
            link.close()
        except Exception:
            pass

    levels = {}
    if lr:
        levels.update(mdr.parse_battery(lr[1], lr[2:]))
    if ca:
        levels.update(mdr.parse_battery(ca[1], ca[2:]))
    if sn and not lr:
        levels.update(mdr.parse_battery(sn[1], sn[2:]))
    if not levels:
        emit_waybar(f"{ICON} –", f"{NAME}: not connected")
        return

    left = levels.get("left")
    right = levels.get("right")
    case = levels.get("case")
    single = levels.get("single")

    buds = [v for v in (left, right) if v]
    if buds:
        pct = min(v[0] for v in buds)
        charging = any(v[1] in (1, 3) for v in buds)
    elif single:
        pct = single[0]
        charging = single[1] in (1, 3)
    else:
        pct = None
        charging = False

    label = f"{pct}%" if pct is not None else "–"
    text = f"{ICON} {label}"

    lines = [NAME]
    if left:
        lines.append(f"Left:  {left[0]}%  {mdr.charging_text(left[1])}")
    if right:
        lines.append(f"Right: {right[0]}%  {mdr.charging_text(right[1])}")
    if single and not buds:
        lines.append(f"Buds:  {single[0]}%  {mdr.charging_text(single[1])}")
    if case:
        lines.append(f"Case:  {case[0]}%  {mdr.charging_text(case[1])}")

    emit_waybar(text, "\n".join(lines), active=charging)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--json-full":
        emit_full(read_levels_full())
        return
    read_levels_waybar()


if __name__ == "__main__":
    main()
