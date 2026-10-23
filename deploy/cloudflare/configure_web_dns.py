import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ZONE_NAME = "cinemaemuitomais.com"
ORIGIN_HOST = "gabrielgpacheco.github.io"
GITHUB_IPS = [
    "185.199.108.153",
    "185.199.109.153",
    "185.199.110.153",
    "185.199.111.153",
]
API = "https://api.cloudflare.com/client/v4"


def load_env():
    env = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] in "'\"" and value[-1] == value[0]:
            value = value[1:-1]
        env[key.strip()] = value
    return env


def api(token, method, path, data=None):
    body = None if data is None else json.dumps(data).encode("utf-8")
    request = urllib.request.Request(
        API + path,
        data=body,
        method=method,
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        payload = json.load(error)
        raise RuntimeError(f"{method} {path}: {payload.get('errors')}") from error
    if not payload.get("success"):
        raise RuntimeError(f"{method} {path}: {payload.get('errors')}")
    return payload.get("result")


def zone_id(token):
    zones = api(token, "GET", f"/zones?name={ZONE_NAME}")
    if not zones:
        raise RuntimeError("zona nao encontrada")
    return zones[0]["id"]


def records(token, zid):
    return api(token, "GET", f"/zones/{zid}/dns_records?per_page=100")


def snapshot(token, zid, items):
    path = ROOT / "dados" / "fase7-dns-antes.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"snapshot: {path} ({len(items)} registros)")


def apply_www(token, zid, items):
    record = next(
        (item for item in items if item["name"] == f"www.{ZONE_NAME}" and item["type"] == "CNAME"),
        None,
    )
    payload = {"content": ORIGIN_HOST, "proxied": True, "ttl": 1}
    if record:
        result = api(token, "PATCH", f"/zones/{zid}/dns_records/{record['id']}", payload)
    else:
        result = api(
            token,
            "POST",
            f"/zones/{zid}/dns_records",
            {"type": "CNAME", "name": f"www.{ZONE_NAME}", **payload},
        )
    print(f"www: {result['name']} {result['type']} -> {result['content']} proxied={result['proxied']}")


def apply_apex(token, zid, items):
    old = [
        item
        for item in items
        if item["name"] == ZONE_NAME and item["type"] in ("A", "AAAA")
    ]
    for item in old:
        api(token, "DELETE", f"/zones/{zid}/dns_records/{item['id']}")
        print(f"removido: {item['type']} {item['name']} {item['content']}")
    for ip in GITHUB_IPS:
        result = api(
            token,
            "POST",
            f"/zones/{zid}/dns_records",
            {"type": "A", "name": ZONE_NAME, "content": ip, "ttl": 1, "proxied": True},
        )
        print(f"apex: {result['name']} A {result['content']} proxied={result['proxied']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--www", action="store_true")
    parser.add_argument("--apex", action="store_true")
    args = parser.parse_args()
    if not args.www and not args.apex:
        parser.error("use --www e/ou --apex")

    env = load_env()
    token = env["CLOUDFLARE_API_TOKEN"]
    zid = zone_id(token)
    items = records(token, zid)
    snapshot(token, zid, items)
    if args.www:
        apply_www(token, zid, items)
    if args.apex:
        apply_apex(token, zid, items)


if __name__ == "__main__":
    main()
