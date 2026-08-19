from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from app.market_data.models import DataManifest, HistoricalBar


def write_dataset_cache(
    root: Path, provider: str, symbol: str, interval: str, bars: tuple[HistoricalBar, ...]
) -> tuple[Path, str]:
    directory = root / provider.lower() / interval
    directory.mkdir(parents=True, exist_ok=True)
    safe_symbol = "".join(character if character.isalnum() else "_" for character in symbol)
    path = directory / f"{safe_symbol}.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["timestamp", "open", "high", "low", "close", "volume", "complete"]
        )
        writer.writeheader()
        for bar in bars:
            writer.writerow(bar.as_dict())
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    return path, checksum


def write_manifest(path: Path, manifest: DataManifest) -> Path:
    manifest_path = path.with_suffix(".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest_path
