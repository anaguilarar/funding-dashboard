"""Merge `monitor_sources` from research batches (research/raw/*.json) into data/sources.yaml.

Existing entries (matched by canonical URL) are kept as-is so manual edits survive.
    python scripts/build_sources.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fundintel.models import slugify  # noqa: E402
from fundintel.store import canonical_url, dump_yaml  # noqa: E402

DEFAULT_API_QUERIES = {
    "grants_gov": ["agriculture climate international", "remote sensing agriculture",
                   "food security climate adaptation", "earth observation applications",
                   "artificial intelligence agriculture", "crop model"],
    "eu_funding_tenders": ["earth observation agriculture", "digital agriculture Africa",
                           "climate adaptation food systems", "artificial intelligence agriculture",
                           "agroecology landscapes biodiversity", "Latin America agriculture climate",
                           "crop yield forecasting", "climate services"],
}


def main() -> None:
    path = ROOT / "data" / "sources.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    sources = data.get("sources", [])
    known = {canonical_url(s["url"]) for s in sources}
    ids = {s["id"] for s in sources}
    added = 0
    for f in sorted((ROOT / "research" / "raw").glob("*.json")):
        batch = json.loads(f.read_text(encoding="utf-8"))
        for m in batch.get("monitor_sources", []):
            url = m.get("url", "")
            if not url.startswith("http") or canonical_url(url) in known:
                continue
            sid = slugify(f"{m.get('funder', '')}-{m.get('name', '')}", 50)
            while sid in ids:
                sid += "-x"
            ids.add(sid)
            known.add(canonical_url(url))
            sources.append({"id": sid, "funder": m.get("funder", ""), "name": m.get("name", ""),
                            "url": url, "type": m.get("type", "html") if m.get("type") in ("html", "rss") else "html",
                            "category": batch.get("group", f.stem), "why": m.get("why", ""),
                            "enabled": True})
            added += 1
    data["sources"] = sources
    data.setdefault("api_queries", DEFAULT_API_QUERIES)
    dump_yaml(data, path)
    print(f"{len(sources)} sources ({added} added) -> {path}")


if __name__ == "__main__":
    main()
