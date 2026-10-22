# -*- coding: utf-8 -*-
"""Valida o url-map contra os sitemaps publicos do Yoast."""
import json
import os
import re
import sys
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

PROJ = r"C:\Users\dayan\Downloads\migracao-sites\site-estatico-cmm"
DATA = os.path.join(PROJ, "src", "data")
SITE = "https://www.cinemaemuitomais.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def locs(xml):
    return re.findall(r"<loc>\s*([^<]+?)\s*</loc>", xml)


def path(u):
    return urllib.parse.unquote(urllib.parse.urlparse(u).path or "/")


def ensure_slash(p):
    if p != "/" and not p.endswith("/") and "." not in p.rstrip("/").split("/")[-1]:
        p += "/"
    return p


index = fetch(SITE + "/sitemap_index.xml")
maps = locs(index)
print("sitemaps:", len(maps))

groups = {"post": [], "page": [], "post_tag": [], "category": [], "author": [], "attachment": []}
for m in maps:
    name = m.rsplit("/", 1)[-1]
    for k in groups:
        if name.startswith(k + "-sitemap"):
            groups[k].append(m)
            break

collected = {}
for k, urls in groups.items():
    acc = set()
    for u in urls:
        xml = fetch(u)
        for l in locs(xml):
            acc.add(ensure_slash(path(l)))
    collected[k] = acc
    print(f"  {k}: {len(acc)} URLs em {len(urls)} sitemap(s)")

entries = json.load(open(os.path.join(DATA, "url-map.json"), encoding="utf-8"))["entries"]
ours = {
    "post": {u for u, v in entries.items() if v["type"] == "post"},
    "page": {u for u, v in entries.items() if v["type"] == "page"},
    "post_tag": {u for u, v in entries.items() if v["type"] == "tag"},
    "category": {u for u, v in entries.items() if v["type"] == "category"},
    "author": {u for u, v in entries.items() if v["type"] == "author"},
}

out = ["# Validacao contra sitemaps do Yoast\n"]
for k in ("post", "page", "post_tag", "category", "author"):
    a, b = collected[k], ours[k]
    out.append(f"## {k}\n")
    out.append(f"- Sitemap: {len(a)}\n- url-map: {len(b)}\n")
    out.append(f"- Faltando no url-map: {len(a - b)}\n- Sobrando no url-map: {len(b - a)}\n")
    if a - b:
        out.append("\nExemplos faltando:\n\n")
        for u in list(sorted(a - b))[:15]:
            out.append(f"- `{u}`\n")
    if b - a:
        out.append("\nExemplos sobrando:\n\n")
        for u in list(sorted(b - a))[:15]:
            out.append(f"- `{u}`\n")
    out.append("\n")
    print(f"  {k}: sitemap={len(a)} url-map={len(b)} falta={len(a-b)} sobra={len(b-a)}")

# grava copia dos sitemaps para auditoria
raw_dir = os.path.join(PROJ, "dados", "brutos", "sitemaps")
os.makedirs(raw_dir, exist_ok=True)
for k, urls in groups.items():
    for u in urls:
        name = u.rsplit("/", 1)[-1]
        with open(os.path.join(raw_dir, name), "w", encoding="utf-8") as f:
            f.write(fetch(u))

with open(os.path.join(PROJ, "dados", "analise-2026", "fase-2-validacao-sitemaps.md"), "w", encoding="utf-8") as f:
    f.writelines(out)
print("[ok] relatorio em dados/analise-2026/fase-2-validacao-sitemaps.md")
