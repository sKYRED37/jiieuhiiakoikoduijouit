#!/usr/bin/env python3
"""Download the public Transfermarkt players dataset into the bot folder.

Run from the project root: python data/download_transfermarkt.py
The upstream snapshot is community-maintained and currently may lag behind live squads.
"""
from __future__ import annotations
import gzip
import shutil
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = "https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/players.csv.gz"
DEST = ROOT / "transfermarkt_players.csv"
TMP = ROOT / "data" / "players.csv.gz.part"


def main() -> None:
    req = urllib.request.Request(URL, headers={"User-Agent": "FootballManagerBot/1.0 (dataset import)"})
    print("Downloading Transfermarkt player snapshot...")
    try:
        with urllib.request.urlopen(req, timeout=90) as response, TMP.open("wb") as out:
            shutil.copyfileobj(response, out)
        with gzip.open(TMP, "rb") as src, DEST.open("wb") as out:
            shutil.copyfileobj(src, out)
        if DEST.stat().st_size < 1000:
            DEST.unlink(missing_ok=True)
            raise RuntimeError("Downloaded CSV looks unexpectedly small; refusing to keep it.")
        print(f"Saved {DEST} ({DEST.stat().st_size:,} bytes)")
        print("Restart the bot; main.py imports players whose clubs match the game's clubs.")
    finally:
        TMP.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
