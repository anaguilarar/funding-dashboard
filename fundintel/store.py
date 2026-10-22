"""YAML-backed storage for opportunities, archive and candidates, plus de-duplication."""
from __future__ import annotations

import difflib
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from .models import FIELDS, WATCHED_FIELDS, normalize

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: Path | None = None) -> dict:
    with open(path or ROOT / "config.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def p(cfg: dict, key: str) -> Path:
    path = ROOT / cfg["paths"][key]
    if key not in ("sources",):
        path.mkdir(parents=True, exist_ok=True)
    return path


class _Dumper(yaml.SafeDumper):
    pass


def _str_presenter(dumper, data):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _str_presenter)


def dump_yaml(obj, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        yaml.dump(obj, fh, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=100)


def load_dir(folder: Path) -> list[dict]:
    recs = []
    for f in sorted(folder.glob("*.yaml")):
        with open(f, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        rec = normalize(data)
        rec["_file"] = str(f)
        recs.append(rec)
    return recs


def save_record(rec: dict, folder: Path) -> Path:
    out = {k: rec[k] for k in FIELDS if k in rec}
    out.update({k: v for k, v in rec.items() if k not in FIELDS and not k.startswith("_")})
    path = folder / f"{rec['id']}.yaml"
    dump_yaml(out, path)
    return path


def move_record(rec: dict, src: Path, dst: Path) -> Path:
    new = save_record(rec, dst)
    old = src / f"{rec['id']}.yaml"
    if old.exists() and old.resolve() != new.resolve():
        old.unlink()
    return new


# ---------------------------------------------------------------- de-duplication
def canonical_url(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    path = re.sub(r"/+$", "", parts.path.lower())
    return f"{host}{path}"


def _norm_title(t: str) -> str:
    t = re.sub(r"\b(20\d\d|call|for|proposals?|the|and|of|programme|program)\b", " ", t.lower())
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def find_duplicate(rec: dict, existing: list[dict], threshold: float = 0.86) -> dict | None:
    """Same opportunity if canonical URL matches, or same funder + very similar title."""
    cu = canonical_url(rec.get("url", ""))
    srcs = {canonical_url(u) for u in rec.get("source_urls", [])} | {cu}
    for other in existing:
        if other.get("id") == rec.get("id") and (
                difflib.SequenceMatcher(None, _norm_title(other.get("title", "")),
                                        _norm_title(rec.get("title", ""))).ratio() >= threshold
                or canonical_url(other.get("url", "")) == cu):
            return other
        ou = canonical_url(other.get("url", ""))
        if cu and ou and cu == ou:
            return other
        if ou and ou in srcs:
            return other
        fa, fb = other.get("funder", "").lower(), rec.get("funder", "").lower()
        same_funder = (difflib.SequenceMatcher(None, fa, fb).ratio() > 0.8
                       or (min(len(fa), len(fb)) > 3 and (fa in fb or fb in fa)))
        if same_funder:
            r = difflib.SequenceMatcher(None, _norm_title(other.get("title", "")),
                                        _norm_title(rec.get("title", ""))).ratio()
            if r >= threshold:
                return other
    return None


def diff_watched(old: dict, new: dict) -> dict:
    """Return {field: (old, new)} for watched fields that changed."""
    changes = {}
    for f in WATCHED_FIELDS:
        if old.get(f) != new.get(f):
            changes[f] = (old.get(f), new.get(f))
    return changes


def add_history(rec: dict, event: str, detail: str = "") -> None:
    rec.setdefault("history", []).append(
        {"date": datetime.now().strftime("%Y-%m-%d %H:%M"), "event": event, "detail": detail})
    rec["history"] = rec["history"][-50:]


# ---------------------------------------------------------------- change log
def log_event(cfg: dict, kind: str, payload: dict) -> None:
    path = p(cfg, "state") / "changelog.jsonl"
    entry = {"ts": datetime.now().isoformat(timespec="seconds"), "kind": kind, **payload}
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_events(cfg: dict, since: datetime | None = None) -> list[dict]:
    path = p(cfg, "state") / "changelog.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        if since is None or datetime.fromisoformat(e["ts"]) >= since:
            out.append(e)
    return out
