"""Gera sitemaps e arquivos estaticos de publicacao da Fase 5."""
from __future__ import annotations

import json
import os
import shutil
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "src" / "data"
NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
XMLNS = f'xmlns="{NS}"'
NSMAP = {"sm": NS}


def load_json(name: str):
    with (DATA / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def winpath(path: Path | str) -> str:
    value = os.path.abspath(str(path))
    if os.name == "nt" and not value.startswith("\\\\?\\"):
        return "\\\\?\\" + value
    return value


def ensure_url(url: str) -> str:
    if not url:
        return "/"
    if not url.startswith("/"):
        url = "/" + url
    if not url.endswith("/") and not url.endswith(".html"):
        url += "/"
    return url


def write_text(path: Path, content: str) -> None:
    os.makedirs(winpath(path.parent), exist_ok=True)
    with open(winpath(path), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


def lastmod(value: str | None, fallback: str) -> str:
    if value and len(value) >= 10 and value[4] == "-" and value[7] == "-":
        return value[:10]
    return fallback


def absolute(site_url: str, url: str) -> str:
    url = ensure_url(url)
    return site_url + urllib.parse.quote(urllib.parse.unquote(url), safe="/%:@&=+$,;~!*'()")


def write_urlset(path: Path, entries: list[tuple[str, str]]) -> int:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<urlset {XMLNS}>',
    ]
    for loc, modified in entries:
        item = f"  <url><loc>{escape(loc)}</loc>"
        if modified:
            item += f"<lastmod>{escape(modified)}</lastmod>"
        lines.append(item + "</url>")
    lines.append("</urlset>")
    write_text(path, "\n".join(lines) + "\n")
    return len(entries)


def public_pages(pages: list[dict]) -> list[dict]:
    result = []
    seen = set()
    for page in pages:
        url = ensure_url(page.get("url", ""))
        if url in seen or page.get("seo", {}).get("noindex"):
            continue
        seen.add(url)
        result.append(page)
    if "/" not in seen:
        result.insert(0, {"url": "/", "modified": ""})
    return result


def write_sitemaps(out: Path, site: dict, posts: list[dict], pages: list[dict],
                   tags: list[dict], categories: list[dict], authors: list[dict]) -> dict:
    site_url = site["url"].rstrip("/")
    fallback = lastmod(site.get("generated_at"), "2026-10-20")
    groups: dict[str, list[tuple[str, str]]] = {}

    groups["post-sitemap.xml"] = [
        (absolute(site_url, post["url"]), lastmod(post.get("modified") or post.get("date"), fallback))
        for post in posts
        if not post.get("seo", {}).get("noindex")
    ]
    groups["page-sitemap.xml"] = [
        (absolute(site_url, page["url"]), lastmod(page.get("modified") or page.get("date"), fallback))
        for page in public_pages(pages)
    ]
    groups["post_tag-sitemap.xml"] = [
        (absolute(site_url, tag["url"]), fallback)
        for tag in tags
        if tag.get("in_sitemap", True) and not tag.get("noindex")
    ]
    groups["category-sitemap.xml"] = [
        (absolute(site_url, category["url"]), fallback)
        for category in categories
        if category.get("in_sitemap", True) and not category.get("noindex")
    ]
    groups["author-sitemap.xml"] = [
        (absolute(site_url, author["url"]), fallback)
        for author in authors
        if author.get("in_sitemap", True)
    ]

    counts = {}
    for name, entries in groups.items():
        counts[name] = write_urlset(out / name, entries)

    index_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<sitemapindex {XMLNS}>',
    ]
    for name in groups:
        loc = site_url + "/" + name
        index_lines.append(
            f"  <sitemap><loc>{escape(loc)}</loc><lastmod>{escape(fallback)}</lastmod></sitemap>"
        )
    index_lines.append("</sitemapindex>")
    index_xml = "\n".join(index_lines) + "\n"
    write_text(out / "sitemap_index.xml", index_xml)
    write_text(out / "sitemap.xml", index_xml)
    return counts


def write_extras(out: Path, site: dict) -> dict:
    site_url = site["url"].rstrip("/")
    host = urllib.parse.urlparse(site_url).hostname or "www.cinemaemuitomais.com"
    publisher = (site.get("adsense") or "").replace("ca-", "")
    ads = (
        f"google.com, {publisher}, DIRECT, f08c47fec0942fa0\n"
        if publisher.startswith("pub-") else ""
    )
    robots = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /busca/\n"
        "Disallow: /404.html\n"
        "Disallow: /pagefind/\n"
        "\n"
        f"Sitemap: {site_url}/sitemap_index.xml\n"
    )
    llms = (
        f"# {site['name']}\n\n"
        f"> {site['description']}\n\n"
        "## Sobre\n\n"
        "Site brasileiro de cinema, séries, teatro, literatura, entrevistas e cultura pop, "
        "publicado desde 2008.\n\n"
        "## Seções\n\n"
        f"- [Início]({site_url}/)\n"
        f"- [Programação de cinema]({site_url}/programacao/cinema/)\n"
        f"- [Cultura]({site_url}/category/cultura/)\n"
        f"- [Teatro]({site_url}/category/teatro-4/)\n"
        f"- [Literatura]({site_url}/category/literatura/)\n"
        f"- [Entrevistas]({site_url}/category/entrevistas-2/)\n"
        f"- [Quem somos]({site_url}/quemsomos/)\n"
        f"- [Contato]({site_url}/contato/)\n\n"
        "## Recursos\n\n"
        f"- [Sitemap]({site_url}/sitemap_index.xml)\n"
        f"- [Busca]({site_url}/busca/)\n"
    )
    write_text(out / "robots.txt", robots)
    write_text(out / "ads.txt", ads)
    write_text(out / "llms.txt", llms)
    write_text(out / "CNAME", host + "\n")
    write_text(out / ".nojekyll", "")
    for source, name in (
        (ROOT / "src" / "assets" / "img" / "favicon.ico", "favicon.ico"),
        (ROOT / "src" / "assets" / "img" / "apple-touch-icon.png", "apple-touch-icon.png"),
        (ROOT / "src" / "assets" / "site.webmanifest", "site.webmanifest"),
    ):
        if source.exists():
            shutil.copyfile(winpath(source), winpath(out / name))
    return {"publisher": publisher, "host": host}


def sitemap_files(out: Path) -> list[Path]:
    return sorted(out.glob("*-sitemap.xml"))


def validate(out: Path, counts: dict) -> dict:
    index = ET.parse(winpath(out / "sitemap_index.xml")).getroot()
    children = [loc.text for loc in index.findall("sm:sitemap/sm:loc", NSMAP)]
    seen: set[str] = set()
    total = 0
    for child in children:
        name = urllib.parse.urlparse(child or "").path.rsplit("/", 1)[-1]
        path = out / name
        if not path.is_file():
            raise ValueError(f"sitemap ausente: {name}")
        root = ET.parse(winpath(path)).getroot()
        locs = [loc.text for loc in root.findall("sm:url/sm:loc", NSMAP)]
        if len(locs) != counts.get(name):
            raise ValueError(f"contagem divergente em {name}: {len(locs)} != {counts.get(name)}")
        for loc in locs:
            if not loc or not loc.startswith("https://"):
                raise ValueError(f"URL invalida em {name}: {loc}")
            if loc in seen:
                raise ValueError(f"URL duplicada: {loc}")
            seen.add(loc)
            url_path = urllib.parse.unquote(urllib.parse.urlparse(loc).path)
            if url_path.endswith(".html"):
                target = out / url_path.lstrip("/")
            elif url_path == "/":
                target = out / "index.html"
            else:
                target = out / url_path.strip("/") / "index.html"
            if not os.path.isfile(winpath(target)):
                raise ValueError(f"arquivo ausente para {loc}")
        total += len(locs)
    return {"children": len(children), "urls": total}


def generate(out: Path, site: dict | None = None) -> dict:
    site = site or load_json("site.json")
    posts = load_json("posts.json")
    pages = load_json("pages.json")
    tags = load_json("tags.json")
    categories = load_json("categories.json")
    authors = load_json("authors.json")
    extras = write_extras(out, site)
    counts = write_sitemaps(out, site, posts, pages, tags, categories, authors)
    checked = validate(out, counts)
    return {"sitemaps": counts, "validation": checked, "extras": extras}
