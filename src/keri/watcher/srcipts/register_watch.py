#!/usr/bin/env python3
"""
Usage:
    python scripts/register_watch.py \
        --aid ETestAID \
        --witness EWit1 http://localhost:5631/oobi/EWit1 \
        --watcher-url http://localhost:5632
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
import urllib.error


def parse_args():
    p = argparse.ArgumentParser(description="Register an AID with the KERI Watcher")
    p.add_argument("--aid", required=True, help="AID to watch")
    p.add_argument("--watcher-url", default="http://localhost:5632", help="Watcher base URL")
    p.add_argument(
        "--witness",
        nargs=2,
        metavar=("AID", "OOBI"),
        action="append",
        default=[],
        help="Witness AID and OOBI URL (repeatable)",
    )
    p.add_argument("--force", action="store_true", help="Re-register even if already watched")
    return p.parse_args()


def main():
    args = parse_args()

    witnesses = [w[0] for w in args.witness]
    witness_oobis = {w[0]: w[1] for w in args.witness}

    payload = json.dumps({
        "aid": args.aid,
        "witnesses": witnesses,
        "witness_oobis": witness_oobis,
        "force": args.force,
    }).encode()

    url = f"{args.watcher_url.rstrip('/')}/watch"
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            print(f"Success: {json.dumps(data, indent=2)}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"Error {e.code}: {body}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Connection error: {e.reason}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()