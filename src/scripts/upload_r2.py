#!/usr/bin/env python3
"""Fase 4: envia a mídia processada para o Cloudflare R2.

Uso:
    pip install boto3
    python src/scripts/upload_r2.py --dry-run
    python src/scripts/upload_r2.py --resume
    python src/scripts/upload_r2.py --verify-base https://media.cinemaemuitomais.com

Credenciais (nunca commitar):
    R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET
    R2_ENDPOINT (opcional; padrão https://<account>.r2.cloudflarestorage.com)

As chaves preservam wp-content/uploads/ano/mes/arquivo.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "dados" / "midia" / "processed"
REPORT = ROOT / "dados" / "midia" / "upload-report.json"
DEFAULT_PREFIX = "wp-content/uploads/"
CACHE_CONTROL = "public, max-age=31536000, immutable"

CONTENT_TYPES = {
    ".avif": "image/avif",
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".webp": "image/webp",
}


def env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def winpath(path) -> str:
    text = str(Path(path).resolve())
    if os.name == "nt" and not text.startswith("\\\\?\\"):
        return "\\\\?\\" + text
    return text


def iter_files(source: Path):
    for path in source.rglob("*"):
        try:
            if os.path.isfile(winpath(path)):
                yield path
        except OSError:
            continue


def content_type(path: Path) -> str:
    return CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")


def make_client(args):
    import boto3
    from botocore.config import Config

    endpoint = args.endpoint or env("R2_ENDPOINT")
    account = args.account_id or env("R2_ACCOUNT_ID")
    if not endpoint:
        if not account:
            raise SystemExit("defina R2_ENDPOINT ou R2_ACCOUNT_ID")
        endpoint = f"https://{account}.r2.cloudflarestorage.com"
    access = env("R2_ACCESS_KEY_ID") or env("AWS_ACCESS_KEY_ID")
    secret = env("R2_SECRET_ACCESS_KEY") or env("AWS_SECRET_ACCESS_KEY")
    if not access or not secret:
        raise SystemExit("defina R2_ACCESS_KEY_ID e R2_SECRET_ACCESS_KEY")
    return boto3.session.Session().client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        region_name="auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 5, "mode": "standard"}),
    )


def upload_one(client, bucket: str, prefix: str, path: Path, key: str, resume: bool) -> tuple[str, str]:
    try:
        if resume:
            try:
                client.head_object(Bucket=bucket, Key=key)
                return "skipped", key
            except Exception:
                pass
        with open(winpath(path), "rb") as body:
            client.upload_fileobj(
                body,
                bucket,
                key,
                ExtraArgs={"ContentType": content_type(path), "CacheControl": CACHE_CONTROL},
            )
        return "uploaded", key
    except Exception as exc:
        return "failed", f"{key}: {type(exc).__name__}: {str(exc)[:200]}"


def verify_one(base: str, key: str) -> tuple[str, str]:
    url = base.rstrip("/") + "/" + urllib.parse.quote(key, safe="/")
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "cmm-r2-check/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status == 200:
                return "ok", url
            return "failed", f"{response.status} {url}"
    except urllib.error.HTTPError as exc:
        return "failed", f"{exc.code} {url}"
    except Exception as exc:
        return "failed", f"{type(exc).__name__}: {str(exc)[:120]} {url}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=PROCESSED)
    parser.add_argument("--bucket", default=env("R2_BUCKET"))
    parser.add_argument("--prefix", default=env("R2_PREFIX") or DEFAULT_PREFIX)
    parser.add_argument("--endpoint")
    parser.add_argument("--account-id")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify-base", default=env("R2_PUBLIC_BASE"))
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args()

    source = args.source.resolve()
    if not source.is_dir():
        raise SystemExit(f"diretório não encontrado: {source}")
    prefix = args.prefix.strip("/")
    prefix = prefix + "/" if prefix else ""

    files = list(iter_files(source))
    if args.limit:
        files = files[: args.limit]
    total_bytes = sum(os.path.getsize(winpath(path)) for path in files)
    started = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    print(f"fonte: {source}")
    print(f"destino: r2://{args.bucket or '(bucket ausente)'}/{prefix}")
    print(f"arquivos: {len(files)}; bytes: {total_bytes}")
    print(f"cache: {CACHE_CONTROL}")

    if args.dry_run:
        sample = [prefix + path.relative_to(source).as_posix() for path in files[:5]]
        for key in sample:
            print(f"  {key}")
        print("dry-run: nada enviado")
        return 0
    if not args.bucket:
        raise SystemExit("defina R2_BUCKET ou use --bucket")

    client = make_client(args)
    counts = {"uploaded": 0, "skipped": 0, "failed": 0}
    failures: list[str] = []
    keys = [prefix + path.relative_to(source).as_posix() for path in files]
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {
            pool.submit(
                upload_one,
                client,
                args.bucket,
                prefix,
                path,
                prefix + path.relative_to(source).as_posix(),
                args.resume,
            ): path
            for path in files
        }
        for index, future in enumerate(as_completed(futures), 1):
            status, detail = future.result()
            counts[status] += 1
            if status == "failed":
                failures.append(detail)
            if index % 250 == 0 or status == "failed":
                print(f"  {index}/{len(files)} uploaded={counts['uploaded']} skipped={counts['skipped']} failed={counts['failed']}", flush=True)

    verify = {"ok": 0, "failed": 0, "failures": []}
    if args.verify_base and keys:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = [pool.submit(verify_one, args.verify_base, key) for key in keys]
            for index, future in enumerate(as_completed(futures), 1):
                status, detail = future.result()
                verify[status] += 1
                if status == "failed":
                    verify["failures"].append(detail)
                if index % 250 == 0 or status == "failed":
                    print(f"  verify {index}/{len(keys)} ok={verify['ok']} failed={verify['failed']}", flush=True)

    report = {
        "started": started,
        "finished": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": str(source),
        "bucket": args.bucket,
        "prefix": prefix,
        "files": len(files),
        "bytes": total_bytes,
        "uploaded": counts["uploaded"],
        "skipped": counts["skipped"],
        "failed": counts["failed"],
        "failures": failures[:100],
        "verify": verify,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("files", "bytes", "uploaded", "skipped", "failed")}, indent=2))
    if args.verify_base:
        print(f"verificação: {verify['ok']} ok, {verify['failed']} falhas")
    print(f"relatório: {args.report}")
    return 1 if counts["failed"] or verify["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
