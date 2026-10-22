#!/usr/bin/env python3
"""Fase 4: indexação, extração e otimização de mídia do backup.

Uso:
    python src/scripts/media.py scan
    python src/scripts/media.py resolve
    python src/scripts/media.py extract
    python src/scripts/media.py wayback [--year 2014]
    python src/scripts/media.py process
    python src/scripts/media.py report

O diretório `dados/midia/` é privado e não deve ser commitado.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import tarfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "src" / "data"
PRIVATE = ROOT / "dados" / "midia"
RAW = PRIVATE / "raw"
PROCESSED = PRIVATE / "processed"
ARCHIVE = ROOT.parent / "CMM" / "backup-cinemaemuitomais.com-10-20-2026.tar.gz"
REF_CSV = ROOT / "dados" / "analise-2026" / "midia-referenciada.csv"
INDEX_CSV = PRIVATE / "uploads-index.csv"
RESOLVED_CSV = PRIVATE / "resolved.csv"
MISSING_CSV = PRIVATE / "missing.csv"
WAYBACK_DIR = PRIVATE / "wayback-cdx"
WAYBACK_CSV = PRIVATE / "wayback-download.csv"
MANIFEST = DATA / "media-manifest.json"

TAR_PREFIX = "./public_html/wp-content/uploads/"
UPLOAD_PREFIXES = (
    "wp-content/uploads/",
    "public_html/wp-content/uploads/",
    "./public_html/wp-content/uploads/",
)
SIZE_RX = re.compile(r"-\d+x\d+(?=\.[^./]+$)")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp"}
WIDTHS = (400, 800, 1200, 1600)


def winpath(path) -> str:
    text = str(Path(path).resolve())
    if os.name == "nt" and not text.startswith("\\\\?\\"):
        return "\\\\?\\" + text
    return text


def copy_file(src, dest) -> None:
    os.makedirs(winpath(Path(dest).parent), exist_ok=True)
    with open(winpath(src), "rb") as fin, open(winpath(dest), "wb") as fout:
        shutil.copyfileobj(fin, fout, length=1024 * 1024)


def clean_rel(value: str) -> str:
    value = urllib.parse.unquote((value or "").strip()).replace("\\", "/")
    value = value.split("?", 1)[0].split("#", 1)[0].lstrip("/")
    low = value.casefold()
    for prefix in UPLOAD_PREFIXES:
        if low.startswith(prefix.casefold()):
            value = value[len(prefix):]
            break
    return value


def mojibake_variants(value: str) -> set[str]:
    out = {value}
    try:
        if all(ord(ch) < 256 for ch in value):
            fixed = value.encode("latin-1").decode("utf-8")
            if fixed != value:
                out.add(fixed)
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return out


def keys(value: str) -> set[str]:
    base = clean_rel(value)
    out: set[str] = set()
    for item in mojibake_variants(base):
        out.add(unicodedata.normalize("NFC", item).casefold())
        out.add(unicodedata.normalize("NFD", item).casefold())
    return out


def stem_rel(value: str) -> str:
    return SIZE_RX.sub("", clean_rel(value))


def load_media() -> dict:
    with open(DATA / "media.json", encoding="utf-8") as fh:
        return json.load(fh)


def load_refs() -> list[dict]:
    with open(REF_CSV, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def build_sets(refs: list[dict], media: dict):
    path_to_mid: dict[str, str] = {}
    mid_files: dict[str, str] = {}
    for mid, item in media.items():
        original = clean_rel(item.get("file") or "")
        if not original:
            continue
        mid_files[mid] = original
        directory = original.rsplit("/", 1)[0] if "/" in original else ""
        for key in keys(original):
            path_to_mid[key] = mid
        for size in (item.get("sizes") or {}).values():
            name = clean_rel(size.get("file") or "")
            if not name:
                continue
            if directory and "/" not in name:
                name = f"{directory}/{name}"
            for key in keys(name):
                path_to_mid[key] = mid

    used_mids: set[str] = set()
    exact_keys: set[str] = set()
    unresolved_rows: list[dict] = []
    for row in refs:
        rel = clean_rel(row.get("arquivo_local") or "")
        if not rel:
            continue
        row_keys = keys(rel)
        exact_keys |= row_keys
        mid = next((path_to_mid.get(k) for k in row_keys if path_to_mid.get(k)), None)
        if mid is None:
            mid = next((path_to_mid.get(k) for k in keys(stem_rel(rel)) if path_to_mid.get(k)), None)
        if mid:
            used_mids.add(mid)
        else:
            unresolved_rows.append(row)

    for mid in used_mids:
        original = mid_files.get(mid)
        if original:
            exact_keys |= keys(original)

    missing_rows = [r for r in refs if r.get("status") != "exato"]
    stem_keys: set[str] = set()
    basename_keys: set[str] = set()
    for row in missing_rows + unresolved_rows:
        rel = clean_rel(row.get("arquivo_local") or "")
        if not rel:
            continue
        stem_keys |= keys(stem_rel(rel))
        base = rel.rsplit("/", 1)[-1]
        basename_keys |= keys(base)
        basename_keys |= keys(stem_rel(base))

    return {
        "path_to_mid": path_to_mid,
        "mid_files": mid_files,
        "used_mids": used_mids,
        "exact_keys": exact_keys,
        "stem_keys": stem_keys,
        "basename_keys": basename_keys,
        "unresolved_rows": unresolved_rows,
    }


def should_extract(rel: str, sets: dict) -> bool:
    rkeys = keys(rel)
    if rkeys & sets["exact_keys"]:
        return True
    if rkeys & sets["stem_keys"]:
        return True
    base = rel.rsplit("/", 1)[-1]
    return bool(keys(base) & sets["basename_keys"])


def scan(args) -> None:
    PRIVATE.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    refs = load_refs()
    media = load_media()
    sets = build_sets(refs, media)
    print(
        f"refs={len(refs)} used_mids={len(sets['used_mids'])} "
        f"exact_keys={len(sets['exact_keys'])} missing_stems={len(sets['stem_keys'])}"
    )
    t0 = time.time()
    members = 0
    uploads = 0
    extracted = 0
    extracted_bytes = 0
    seen: set[str] = set()
    with open(INDEX_CSV, "w", encoding="utf-8", newline="") as idx:
        writer = csv.writer(idx)
        writer.writerow(["rel", "bytes", "mtime"])
        with tarfile.open(ARCHIVE, "r|gz") as tf:
            for member in tf:
                members += 1
                if not member.isfile():
                    continue
                name = member.name.replace("\\", "/")
                if not name.startswith(TAR_PREFIX):
                    continue
                rel = name[len(TAR_PREFIX):]
                if not rel or rel.startswith("."):
                    continue
                uploads += 1
                writer.writerow([rel, member.size, int(member.mtime)])
                if rel in seen:
                    continue
                seen.add(rel)
                if not should_extract(rel, sets):
                    continue
                dest = RAW / rel
                dest_long = winpath(dest)
                if os.path.exists(dest_long) and os.path.getsize(dest_long) == member.size:
                    extracted += 1
                    extracted_bytes += member.size
                    continue
                os.makedirs(winpath(dest.parent), exist_ok=True)
                src = tf.extractfile(member)
                if src is None:
                    continue
                tmp_dir = PRIVATE / ".tmp"
                os.makedirs(winpath(tmp_dir), exist_ok=True)
                tmp = tmp_dir / (hashlib.sha1(rel.encode("utf-8", "surrogatepass")).hexdigest() + ".part")
                with open(winpath(tmp), "wb") as out:
                    shutil.copyfileobj(src, out, length=1024 * 1024)
                os.replace(winpath(tmp), winpath(dest))
                extracted += 1
                extracted_bytes += member.size
                if extracted % 100 == 0:
                    print(
                        f"  extraídos={extracted} bytes={extracted_bytes/1e6:.1f}MB "
                        f"uploads_vistos={uploads} t={time.time()-t0:.1f}s",
                        flush=True,
                    )
                if args.max_extract and extracted >= args.max_extract:
                    print("limite --max-extract atingido", flush=True)
                    break
    report = {
        "archive": str(ARCHIVE),
        "members": members,
        "uploads": uploads,
        "extracted": extracted,
        "extracted_bytes": extracted_bytes,
        "used_mids": len(sets["used_mids"]),
        "refs": len(refs),
        "unresolved_rows": len(sets["unresolved_rows"]),
        "elapsed_s": round(time.time() - t0, 1),
    }
    (PRIVATE / "scan-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


def extract(args) -> None:
    if not RESOLVED_CSV.exists():
        raise SystemExit("resolved.csv ausente. Rode 'resolve' primeiro.")
    with open(RESOLVED_CSV, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    desired = {row["source_rel"] for row in rows if row.get("source_rel")}
    missing = {rel for rel in desired if not os.path.exists(winpath(RAW / rel))}
    print(f"extract: {len(missing)} fontes ausentes", flush=True)
    extracted = 0
    extracted_bytes = 0
    with tarfile.open(ARCHIVE, "r|gz") as tf:
        for member in tf:
            if not member.isfile():
                continue
            name = member.name.replace("\\", "/")
            if not name.startswith(TAR_PREFIX):
                continue
            rel = name[len(TAR_PREFIX):]
            if rel not in missing:
                continue
            dest = RAW / rel
            os.makedirs(winpath(dest.parent), exist_ok=True)
            src = tf.extractfile(member)
            if src is None:
                continue
            tmp_dir = PRIVATE / ".tmp"
            os.makedirs(winpath(tmp_dir), exist_ok=True)
            tmp = tmp_dir / (hashlib.sha1(rel.encode("utf-8", "surrogatepass")).hexdigest() + ".part")
            with open(winpath(tmp), "wb") as out:
                shutil.copyfileobj(src, out, length=1024 * 1024)
            os.replace(winpath(tmp), winpath(dest))
            extracted += 1
            extracted_bytes += member.size
            if extracted % 20 == 0:
                print(f"  extraídos={extracted}/{len(missing)} {extracted_bytes/1e6:.1f}MB", flush=True)
    remaining = {rel for rel in missing if not os.path.exists(winpath(RAW / rel))}
    print(json.dumps({"desired": len(desired), "missing": len(missing), "extracted": extracted,
                      "extracted_bytes": extracted_bytes, "remaining": len(remaining),
                      "remaining_sample": sorted(remaining)[:20]}, ensure_ascii=False, indent=2))


def load_index() -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not INDEX_CSV.exists():
        return out
    with open(INDEX_CSV, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            rel = row["rel"]
            for key in keys(rel):
                out.setdefault(key, {"rel": rel, "bytes": int(row["bytes"] or 0), "mtime": int(row["mtime"] or 0)})
    if RAW.exists():
        root_long = winpath(RAW)
        for base, _, names in os.walk(root_long):
            for name in names:
                path = Path(base) / name
                rel = os.path.relpath(str(path), root_long).replace("\\", "/")
                item = {"rel": rel, "bytes": os.path.getsize(winpath(path)), "mtime": int(os.path.getmtime(winpath(path)))}
                for key in keys(rel):
                    out.setdefault(key, item)
    return out


def resolve(args) -> None:
    refs = load_refs()
    media = load_media()
    sets = build_sets(refs, media)
    index = load_index()
    if not index:
        raise SystemExit("Índice ausente. Rode 'scan' primeiro.")

    by_base: dict[str, list[dict]] = defaultdict(list)
    for item in index.values():
        for base_key in keys(item["rel"].rsplit("/", 1)[-1]):
            by_base[base_key].append(item)

    def stem_key(value: str) -> str:
        rel = value.replace("\\", "/")
        parent, _, name = rel.rpartition("/")
        stem = Path(name).stem
        stem = re.sub(r"-(?:scaled|rotated)$", "", stem, flags=re.I)
        return f"{parent}/{stem.casefold()}"

    raw_by_stem: dict[str, dict] = {}
    if RAW.exists():
        for base, _, names in os.walk(winpath(RAW)):
            for name in names:
                path = Path(base) / name
                rel = os.path.relpath(str(path), winpath(RAW)).replace("\\", "/")
                raw_by_stem.setdefault(stem_key(rel), {
                    "rel": rel,
                    "bytes": os.path.getsize(winpath(path)),
                })

    def stem_identity(value: str) -> str:
        rel = value.replace("\\", "/")
        parent, _, name = rel.rpartition("/")
        stem = Path(name).stem
        stem = re.sub(r"-(?:scaled|rotated)$", "", stem, flags=re.I)
        return f"{parent}/{stem.casefold()}"

    manifest_stems: set[str] = set()
    if MANIFEST.exists():
        try:
            manifest_stems = {stem_identity(key) for key in json.loads(MANIFEST.read_text(encoding="utf-8"))}
        except Exception:
            manifest_stems = set()

    featured_ids: set[int] = set()
    for name in ("posts.json", "pages.json"):
        path = DATA / name
        if not path.exists():
            continue
        try:
            for item in json.loads(path.read_text(encoding="utf-8")):
                if item.get("featured"):
                    featured_ids.add(int(item["featured"]))
        except Exception:
            pass

    resolved: list[dict] = []
    for row in refs:
        rel = clean_rel(row.get("arquivo_local") or "")
        row_keys = keys(rel)
        hit = next((index[k] for k in row_keys if k in index), None)
        via = "exact"
        if hit is None:
            stem = stem_rel(rel)
            hit = next((index[k] for k in keys(stem) if k in index), None)
            via = "stem" if hit else ""
        if hit is None:
            base_key = next(iter(keys(rel.rsplit("/", 1)[-1])), "")
            candidates = by_base.get(base_key, [])
            if candidates:
                year = rel.split("/", 1)[0] if "/" in rel else ""
                candidates = sorted(
                    candidates,
                    key=lambda x: (
                        0 if x["rel"].startswith(year + "/") else 1,
                        x["rel"],
                    ),
                )
                hit = candidates[0]
                via = "basename"
        if hit is None:
            mid = next((sets["path_to_mid"].get(k) for k in row_keys if sets["path_to_mid"].get(k)), None)
            original = sets["mid_files"].get(mid or "")
            if original:
                hit = next((index[k] for k in keys(original) if k in index), None)
                via = "media-original" if hit else ""
        if hit is None:
            hit = raw_by_stem.get(stem_key(rel))
            via = "raw-stem" if hit else ""
        resolved.append({
            **row,
            "rel": rel,
            "source_rel": hit["rel"] if hit else "",
            "source_bytes": hit["bytes"] if hit else 0,
            "resolution": via if hit else "unresolved",
        })

    known_rel = {r["rel"] for r in resolved}

    def add_media_extra(mid, preferred: str, origin: str) -> None:
        item = media.get(str(mid)) or {}
        size = (item.get("sizes") or {}).get(preferred) or {}
        rel = clean_rel(size.get("file") or item.get("file") or "")
        original = item.get("file") or ""
        directory = original.rsplit("/", 1)[0] if "/" in original else ""
        if directory and rel and "/" not in rel:
            rel = f"{directory}/{rel}"
        if not rel or rel in known_rel or stem_identity(rel) in manifest_stems:
            return
        hit = next((index[k] for k in keys(rel) if k in index), None)
        if hit is None:
            hit = raw_by_stem.get(stem_key(rel))
        known_rel.add(rel)
        resolved.append({
            "url_original": f"https://www.cinemaemuitomais.com/wp-content/uploads/{rel}",
            "arquivo_local": f"wp-content/uploads/{rel}",
            "tamanho_bytes": str(hit["bytes"]) if hit else "0",
            "status": "anexo" if hit else "faltante",
            "usado_em": f"anexo ({origin})",
            "total_usos": "0",
            "rel": rel,
            "source_rel": hit["rel"] if hit else "",
            "source_bytes": hit["bytes"] if hit else 0,
            "resolution": "media-anexo" if hit else "unresolved",
        })

    for mid in sorted(featured_ids):
        add_media_extra(mid, "full", "featured")

    gallery_ids: set[int] = set()
    for name in ("posts.json", "pages.json"):
        path = DATA / name
        if not path.exists():
            continue
        try:
            for item in json.loads(path.read_text(encoding="utf-8")):
                for match in re.finditer(r"\[gallery[^\]]*ids\s*=\s*[\"']([^\"']+)", item.get("content") or "", re.I):
                    for value in re.split(r"[, ]+", match.group(1)):
                        if value.isdigit():
                            gallery_ids.add(int(value))
        except Exception:
            pass
    for mid in sorted(gallery_ids):
        add_media_extra(mid, "medium_large", "galeria")

    PRIVATE.mkdir(parents=True, exist_ok=True)
    with open(RESOLVED_CSV, "w", encoding="utf-8", newline="") as fh:
        fields = list(refs[0].keys()) + ["rel", "source_rel", "source_bytes", "resolution"]
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(resolved)
    missing = [r for r in resolved if not r["source_rel"]]
    with open(MISSING_CSV, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(missing[0].keys()) if missing else fields)
        writer.writeheader()
        writer.writerows(missing)
    print(json.dumps({
        "refs": len(resolved),
        "resolved": len(resolved) - len(missing),
        "unresolved": len(missing),
        "by_resolution": Counter(r["resolution"] for r in resolved),
    }, ensure_ascii=False, indent=2, default=dict))


def placeholder_file(rel: str) -> tuple[Path, str, int, int, str]:
    suffix = Path(rel).suffix.lower()
    fmt = {
        ".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP",
        ".gif": "GIF", ".avif": "AVIF", ".pdf": "PDF",
    }.get(suffix, "JPEG")
    base = PRIVATE / ".placeholder"
    os.makedirs(winpath(base), exist_ok=True)
    target = base / f"placeholder.{fmt.lower()}"
    width, height = 1600, 900
    if not os.path.exists(winpath(target)):
        image = Image.new("RGB", (width, height), "#111111")
        draw = ImageDraw.Draw(image)
        for y in range(height):
            ratio = y / max(1, height - 1)
            color = (int(17 + 25 * ratio), int(17 + 18 * ratio), int(17 + 12 * ratio))
            draw.line((0, y, width, y), fill=color)
        try:
            font_big = ImageFont.truetype("arialbd.ttf", 104)
            font_small = ImageFont.truetype("arial.ttf", 34)
        except Exception:
            font_big = ImageFont.load_default(size=104)
            font_small = ImageFont.load_default(size=34)
        title = "Cinema e Muito +"
        subtitle = "Imagem original indisponível"
        box = draw.textbbox((0, 0), title, font=font_big)
        draw.text(((width - (box[2] - box[0])) / 2, 340), title, font=font_big, fill="#f4c542")
        box = draw.textbbox((0, 0), subtitle, font=font_small)
        draw.text(((width - (box[2] - box[0])) / 2, 500), subtitle, font=font_small, fill="#d8d8d8")
        image.save(winpath(target), format=fmt, quality=88)
    mime = {
        "JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp",
        "GIF": "image/gif", "AVIF": "image/avif", "PDF": "application/pdf",
    }.get(fmt, "image/jpeg")
    return target, fmt, width, height, mime


def process(args) -> None:
    if not RESOLVED_CSV.exists():
        raise SystemExit("resolved.csv ausente. Rode 'resolve' primeiro.")
    PROCESSED.mkdir(parents=True, exist_ok=True)
    with open(RESOLVED_CSV, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))

    manifest: dict[str, dict] = {}
    sources: dict[str, dict] = {}
    copied: set[str] = set()
    generated = 0
    generated_bytes = 0
    failed: list[dict] = []

    for row in rows:
        source_rel = row.get("source_rel") or ""
        rel = row.get("rel") or ""
        if not source_rel:
            continue
        src = RAW / source_rel
        if not os.path.exists(winpath(src)):
            failed.append({"rel": rel, "source_rel": source_rel, "error": "raw ausente"})
            continue
        source_rel = source_rel.replace("\\", "/")
        entry = sources.setdefault(source_rel, {
            "source": source_rel,
            "bytes": os.path.getsize(winpath(src)),
            "refs": [],
            "width": 0,
            "height": 0,
            "mime": "",
            "webp": {},
        })
        entry["refs"].append(rel)
        suffix = src.suffix.lower()
        if suffix not in IMAGE_EXTS:
            target = PROCESSED / rel
            if rel not in copied:
                copy_file(src, target)
                copied.add(rel)
            entry.setdefault("non_image", True)
            manifest[rel] = {
                "source": source_rel,
                "fallback": rel,
                "webp": {},
                "width": 0,
                "height": 0,
                "bytes": os.path.getsize(winpath(src)),
                "mime": "application/pdf" if suffix == ".pdf" else "",
            }
            continue

        try:
            with Image.open(winpath(src)) as im:
                im = ImageOps.exif_transpose(im)
                width, height = im.size
                entry["width"], entry["height"] = width, height
                entry["mime"] = Image.MIME.get(im.format or "", "")
                # fallback no caminho exato referenciado
                fallback = PROCESSED / rel
                if rel not in copied:
                    if rel == source_rel or suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
                        copy_file(src, fallback)
                    else:
                        os.makedirs(winpath(fallback.parent), exist_ok=True)
                        target_size = parse_size_suffix(rel)
                        copy = im.copy()
                        if target_size and (target_size[0] < width or target_size[1] < height):
                            copy.thumbnail(target_size, Image.Resampling.LANCZOS)
                        if copy.mode not in ("RGB", "RGBA"):
                            copy = copy.convert("RGBA" if "A" in copy.getbands() else "RGB")
                        fmt = "PNG" if suffix == ".png" else "WEBP" if suffix == ".webp" else "JPEG"
                        copy.save(winpath(fallback), format=fmt, quality=88, optimize=True)
                    copied.add(rel)

                webp_paths = {}
                for target_w in WIDTHS:
                    if width and target_w > width and target_w != WIDTHS[0]:
                        continue
                    ratio = (target_w / width) if width else 1
                    target_h = max(1, round(height * ratio))
                    out_rel = f"{source_rel}.w{target_w}.webp"
                    out = PROCESSED / out_rel
                    if not os.path.exists(winpath(out)):
                        os.makedirs(winpath(out.parent), exist_ok=True)
                        frame = im.copy()
                        if target_w != width:
                            frame = frame.resize((target_w, target_h), Image.Resampling.LANCZOS)
                        if frame.mode not in ("RGB", "RGBA"):
                            frame = frame.convert("RGBA" if "A" in frame.getbands() else "RGB")
                        frame.save(winpath(out), "WEBP", quality=78, method=3)
                        generated += 1
                        generated_bytes += os.path.getsize(winpath(out))
                    webp_paths[str(target_w)] = {"path": out_rel, "width": target_w, "height": target_h}
                entry["webp"] = webp_paths
                fallback_path = PROCESSED / rel
                manifest[rel] = {
                    "source": source_rel,
                    "fallback": rel,
                    "webp": webp_paths,
                    "width": width,
                    "height": height,
                    "bytes": os.path.getsize(winpath(fallback_path)) if os.path.exists(winpath(fallback_path)) else 0,
                    "mime": entry["mime"],
                }
        except Exception as exc:
            failed.append({"rel": rel, "source_rel": source_rel, "error": str(exc)})
            continue
        if len(manifest) % 200 == 0:
            print(f"  manifest={len(manifest)} gerados={generated} {generated_bytes/1e6:.1f}MB", flush=True)

    placeholders = 0
    placeholder_bytes = 0
    for row in rows:
        if row.get("source_rel"):
            continue
        rel = row.get("rel") or ""
        if not rel or rel in manifest:
            continue
        try:
            src, _, width, height, mime = placeholder_file(rel)
            dest = PROCESSED / rel
            copy_file(src, dest)
            size = os.path.getsize(winpath(dest))
            placeholders += 1
            placeholder_bytes += size
            manifest[rel] = {
                "source": "__placeholder__",
                "fallback": rel,
                "webp": {},
                "width": width,
                "height": height,
                "bytes": size,
                "mime": mime,
                "placeholder": True,
            }
        except Exception as exc:
            failed.append({"rel": rel, "source_rel": "", "error": f"placeholder: {exc}"})
    print(f"  placeholders={placeholders} {placeholder_bytes/1e6:.1f}MB", flush=True)

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, separators=(",", ":"))
    report = {
        "refs": len(rows),
        "manifest": len(manifest),
        "sources": len(sources),
        "generated_webp": generated,
        "generated_bytes": generated_bytes,
        "placeholders": placeholders,
        "placeholder_bytes": placeholder_bytes,
        "processed_files": len(list(iter_processed())),
        "processed_bytes": sum(os.path.getsize(winpath(p)) for p in iter_processed()),
        "failed": failed[:50],
        "failed_count": len(failed),
    }
    (PRIVATE / "process-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


def parse_size_suffix(rel: str):
    m = re.search(r"-(\d+)x(\d+)(?=\.[^./]+$)", rel)
    return (int(m.group(1)), int(m.group(2))) if m else None


def iter_processed():
    if not PROCESSED.exists():
        return
    for base, _, names in os.walk(winpath(PROCESSED)):
        for name in names:
            yield Path(base) / name


def wayback(args) -> None:
    if not MISSING_CSV.exists():
        raise SystemExit("missing.csv ausente. Rode 'resolve' primeiro.")
    with open(MISSING_CSV, encoding="utf-8", newline="") as fh:
        missing = list(csv.DictReader(fh))

    cdx: dict[str, dict] = {}
    for path in sorted(WAYBACK_DIR.glob("*.json")):
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for row in rows[1:]:
            original, timestamp, digest, length = row
            marker = "/wp-content/uploads/"
            if marker not in original:
                continue
            rel = urllib.parse.unquote(original.split(marker, 1)[1].split("?", 1)[0])
            cdx.setdefault(rel, {
                "url": original,
                "timestamp": timestamp,
                "digest": digest,
                "length": int(length or 0),
            })

    done = set()
    if WAYBACK_CSV.exists():
        with open(WAYBACK_CSV, encoding="utf-8", newline="") as fh:
            done = {row["rel"] for row in csv.DictReader(fh) if row.get("status") == "ok"}

    todo = []
    for row in missing:
        rel = row.get("rel") or ""
        if args.year and not rel.startswith(args.year + "/"):
            continue
        if args.featured and "(featured)" not in (row.get("usado_em") or ""):
            continue
        if rel in cdx and rel not in done:
            todo.append((rel, cdx[rel]))
    if args.limit:
        todo = todo[:args.limit]

    print(f"wayback: {len(cdx)} caminhos no CDX; {len(todo)} downloads pendentes", flush=True)
    fields = ["rel", "timestamp", "url", "status", "bytes", "note"]
    new_file = not WAYBACK_CSV.exists()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    with open(WAYBACK_CSV, "a", encoding="utf-8", newline="") as report_fh:
        writer = csv.DictWriter(report_fh, fieldnames=fields)
        if new_file:
            writer.writeheader()
        for index, (rel, info) in enumerate(todo, 1):
            dest = RAW / rel
            if os.path.exists(winpath(dest)) and os.path.getsize(winpath(dest)) > 0:
                writer.writerow({"rel": rel, "timestamp": info["timestamp"], "url": info["url"], "status": "ok", "bytes": os.path.getsize(winpath(dest)), "note": "já existia"})
                continue
            archive_url = f"https://web.archive.org/web/{info['timestamp']}id_/{info['url']}"
            status, size, note = "error", 0, ""
            for attempt in range(3):
                try:
                    req = urllib.request.Request(archive_url, headers=headers)
                    with urllib.request.urlopen(req, timeout=90) as response:
                        data = response.read()
                        ctype = response.headers.get("content-type", "")
                    if not data or data[:20].lstrip().lower().startswith((b"<!doctype", b"<html")):
                        raise ValueError(f"resposta não binária: {ctype}")
                    os.makedirs(winpath(dest.parent), exist_ok=True)
                    tmp = PRIVATE / ".tmp" / (hashlib.sha1(rel.encode("utf-8", "surrogatepass")).hexdigest() + ".wb")
                    os.makedirs(winpath(tmp.parent), exist_ok=True)
                    with open(winpath(tmp), "wb") as out:
                        out.write(data)
                    os.replace(winpath(tmp), winpath(dest))
                    status, size = "ok", len(data)
                    note = ctype
                    break
                except urllib.error.HTTPError as exc:
                    note = f"HTTP {exc.code}"
                    if exc.code == 429:
                        wait = int(exc.headers.get("Retry-After") or 0) or 30 * (attempt + 1)
                        print(f"  429 {rel[-60:]} aguardando {wait}s", flush=True)
                        time.sleep(wait)
                        continue
                    if exc.code in (404, 410):
                        break
                    time.sleep(5 * (attempt + 1))
                except Exception as exc:
                    note = f"{type(exc).__name__}: {str(exc)[:80]}"
                    time.sleep(5 * (attempt + 1))
            writer.writerow({"rel": rel, "timestamp": info["timestamp"], "url": info["url"], "status": status, "bytes": size, "note": note})
            report_fh.flush()
            if index % 10 == 0 or status != "ok":
                print(f"  {index}/{len(todo)} ok={status == 'ok'} {rel[-70:]} {note}", flush=True)
            if status == "ok":
                time.sleep(args.sleep)
    print(f"relatório: {WAYBACK_CSV}", flush=True)


def report(args) -> None:
    def dist():
        if not PROCESSED.exists():
            return {}
        files = list(iter_processed())
        return {
            "files": len(files),
            "bytes": sum(os.path.getsize(winpath(p)) for p in files),
            "by_ext": dict(Counter(Path(p).suffix.lower() for p in files)),
        }

    def manifest_audit():
        if not MANIFEST.exists():
            return {}
        entries = json.loads(MANIFEST.read_text(encoding="utf-8"))
        missing: list[str] = []
        placeholders = 0
        for entry in entries.values():
            if entry.get("placeholder"):
                placeholders += 1
            files = [entry.get("fallback")] if entry.get("fallback") else []
            files += [item["path"] for item in (entry.get("webp") or {}).values()]
            for rel in files:
                if not os.path.isfile(winpath(PROCESSED / rel)):
                    missing.append(rel)
        return {"entries": len(entries), "placeholders": placeholders, "missing_assets": missing}

    data = {
        "scan": json.loads((PRIVATE / "scan-report.json").read_text(encoding="utf-8")) if (PRIVATE / "scan-report.json").exists() else None,
        "process": json.loads((PRIVATE / "process-report.json").read_text(encoding="utf-8")) if (PRIVATE / "process-report.json").exists() else None,
        "processed": dist(),
        "manifest": str(MANIFEST),
        "manifest_bytes": MANIFEST.stat().st_size if MANIFEST.exists() else 0,
        "manifest_check": manifest_audit(),
    }
    print(json.dumps(data, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_scan = sub.add_parser("scan")
    p_scan.add_argument("--max-extract", type=int, default=0)
    sub.add_parser("resolve")
    sub.add_parser("extract")
    p_wayback = sub.add_parser("wayback")
    p_wayback.add_argument("--year")
    p_wayback.add_argument("--featured", action="store_true")
    p_wayback.add_argument("--limit", type=int, default=0)
    p_wayback.add_argument("--sleep", type=float, default=2.5)
    sub.add_parser("process")
    sub.add_parser("report")
    args = parser.parse_args()
    {"scan": scan, "resolve": resolve, "extract": extract, "wayback": wayback, "process": process, "report": report}[args.cmd](args)


if __name__ == "__main__":
    main()
