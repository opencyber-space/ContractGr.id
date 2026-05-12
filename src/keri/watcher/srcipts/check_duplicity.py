#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime


def parse_args():
    p = argparse.ArgumentParser(description="Check duplicity events from the KERI Watcher")
    p.add_argument("--aid", help="Filter by specific AID")
    p.add_argument("--all", action="store_true", help="Fetch all duplicity events")
    p.add_argument("--unresolved", action="store_true", help="Show only unresolved duplicity")
    p.add_argument("--resolve", metavar="ID", help="Resolve a duplicity event by ID")
    p.add_argument("--notes", help="Resolution notes (used with --resolve)")
    p.add_argument("--watcher-url", default="http://localhost:5632")
    return p.parse_args()


def fetch_json(url: str) -> dict:
    try:
        with urllib.request.urlopen(url) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"Error {e.code}: {e.read().decode()}", file=sys.stderr)
        sys.exit(1)


def resolve_duplicity(base_url: str, dup_id: str, notes: str = None) -> dict:
    payload = json.dumps({"action": "resolve", "notes": notes}).encode()
    url = f"{base_url}/duplicity/event/{dup_id}"
    req = urllib.request.Request(url, data=payload, method="PUT", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"Error {e.code}: {e.read().decode()}", file=sys.stderr)
        sys.exit(1)


def main():
    args = parse_args()
    base = args.watcher_url.rstrip("/")

    if args.resolve:
        result = resolve_duplicity(base, args.resolve, args.notes)
        print(f"Resolved: {json.dumps(result, indent=2)}")
        return

    params = {}
    if args.unresolved:
        params["resolved"] = "false"

    if args.aid:
        qs = urllib.parse.urlencode(params)
        url = f"{base}/duplicity/{args.aid}{'?' + qs if qs else ''}"
        data = fetch_json(url)
        events = data["data"]["duplicity"]
    else:
        qs = urllib.parse.urlencode(params)
        url = f"{base}/duplicity{'?' + qs if qs else ''}"
        data = fetch_json(url)
        events = data["data"]["duplicity"]

    if not events:
        print("No duplicity events found.")
        return

    print(f"\nFound {len(events)} duplicity event(s):\n")
    for ev in events:
        resolved_str = "RESOLVED" if ev["resolved"] else "UNRESOLVED"
        print(f"  [{resolved_str}] ID: {ev['id']}")
        print(f"    AID: {ev['aid']}")
        print(f"    SN:  {ev['sn']}")
        print(f"    Detected: {ev['detected_at']}")
        print(f"    First:    {ev['first_said']}")
        print(f"    Conflict: {ev['conflict_said']}")
        if ev.get("source_witness"):
            print(f"    Witness:  {ev['source_witness']}")
        print()


if __name__ == "__main__":
    main()