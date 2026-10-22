# -*- coding: utf-8 -*-
"""
Fase 2 - Exportacao do dump WordPress para JSON sanitizado e mapa de URLs.

Gera em src/data/:
  site.json, posts.json, pages.json, tags.json, categories.json,
  authors.json, media.json, url-map.json, redirects.json

E o relatorio em dados/analise-2026/fase-2-relatorio.md

Uso:
  python src/scripts/export-db.py
"""
import collections
import csv
import html
import json
import math
import os
import re
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wpdb  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

ROOT = r"C:\Users\dayan\Downloads\migracao-sites"
CMM = os.path.join(ROOT, "CMM")
PROJ = os.path.join(ROOT, "site-estatico-cmm")
DATA = os.path.join(PROJ, "src", "data")
ANA = os.path.join(PROJ, "dados", "analise-2026")
SQL = os.path.join(CMM, "gabriel_cinemaemuitoma.sql.gz")
OLD_SQL = os.path.join(CMM, "gabriel_cinemaemuitoma01.sql.gz")
SITE = "https://www.cinemaemuitomais.com"
SITE_HOSTS = {"www.cinemaemuitomais.com", "cinemaemuitomais.com"}
MEDIA_BASE = "https://media.cinemaemuitomais.com"
POSTS_PER_PAGE = 50
GENERATED = "2026-10-20"

os.makedirs(DATA, exist_ok=True)
os.makedirs(ANA, exist_ok=True)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def norm_title(s):
    s = html.unescape(s or "")
    s = s.replace("\u00a0", " ")
    s = s.replace("\u2019", "'").replace("\u2018", "'")
    s = s.replace("\u201c", '"').replace("\u201d", '"')
    return re.sub(r"\s+", " ", s).strip()


def nn(v):
    """mysqldump grava NULL sem aspas; nosso parser devolve a string 'NULL'."""
    return "" if v is None or v == "NULL" else v


def path_of(u):
    u = nn(u)
    if not u:
        return "/"
    if u.startswith("http://") or u.startswith("https://"):
        p = urllib.parse.urlparse(u)
        return urllib.parse.unquote(p.path or "/")
    return urllib.parse.unquote(urllib.parse.urlparse(u).path or "/")


def ensure_slash(p):
    if not p:
        return "/"
    if not p.startswith("/"):
        p = "/" + p
    if p != "/" and not p.endswith("/") and "." not in p.rstrip("/").split("/")[-1]:
        p += "/"
    return p


def canon_path(u):
    return ensure_slash(path_of(u))


def abs_url(p):
    return SITE + p


def slugify(s):
    s = norm_title(s).lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def clean_html(s):
    if not s:
        return ""
    s = re.sub(r"<script\b[^>]*>.*?</script\s*>", "", s, flags=re.S | re.I)
    s = re.sub(r"\son[a-z]+\s*=\s*\"[^\"]*\"", "", s, flags=re.I)
    s = re.sub(r"\son[a-z]+\s*=\s*'[^']*'", "", s, flags=re.I)
    s = re.sub(r"\son[a-z]+\s*=\s*[^\s>]+", "", s, flags=re.I)
    s = re.sub(r"javascript:", "", s, flags=re.I)
    return s


def plain(s, limit=None):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit] if limit else s


def iso(dt):
    if not dt or dt.startswith("0000"):
        return None
    return dt.replace(" ", "T") + "-03:00"


def jdump(path, obj, indent=None):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":") if not indent else None,
                  indent=indent)


# ---------------------------------------------------------------------------
# Load current dump
# ---------------------------------------------------------------------------
print("[1/6] lendo dump atual...")
T = wpdb.load_tables(SQL, [
    "options", "users", "usermeta", "terms", "term_taxonomy", "term_relationships",
    "posts", "postmeta", "comments", "yoast_indexable",
])

opts = {}
for r in T["options"]:
    if len(r) >= 3:
        opts[r[1]] = nn(r[2])

users = {}
for r in T["users"]:
    if len(r) >= 10:
        users[int(r[0])] = {"nicename": nn(r[3]), "display": nn(r[9]), "login": nn(r[1])}

user_bio = {}
for r in T["usermeta"]:
    if len(r) >= 4 and r[2] == "description" and r[3]:
        user_bio[int(r[1])] = plain(nn(r[3]))

terms = {}
for r in T["terms"]:
    if len(r) >= 3:
        terms[int(r[0])] = {"name": nn(r[1]), "slug": nn(r[2])}

taxonomy = {}
for r in T["term_taxonomy"]:
    if len(r) >= 6:
        taxonomy[int(r[0])] = {"term_id": int(r[1]), "taxonomy": r[2],
                               "parent": int(r[4] or 0), "count": int(r[5] or 0)}

rel = collections.defaultdict(set)   # ttid -> set(object_id)
for r in T["term_relationships"]:
    if len(r) >= 2:
        try:
            rel[int(r[1])].add(int(r[0]))
        except ValueError:
            pass

posts_by_id = {}
for r in T["posts"]:
    if len(r) < 23:
        continue
    pid = int(r[0])
    posts_by_id[pid] = {
        "id": pid, "author": int(r[1] or 0), "date": r[2], "modified": r[14],
        "content": r[4], "title": r[5], "excerpt": r[6], "status": r[7],
        "slug": r[11], "parent": int(r[17] or 0), "guid": r[18],
        "menu_order": int(r[19] or 0), "type": r[20], "mime": r[21],
        "comment_count": int(r[22] or 0),
    }

meta = collections.defaultdict(dict)
for r in T["postmeta"]:
    if len(r) >= 4:
        meta[int(r[1])][r[2]] = r[3]

attachments = {}
for pid, p in posts_by_id.items():
    if p["type"] != "attachment":
        continue
    f = meta.get(pid, {}).get("_wp_attached_file", "")
    md = wpdb.php_unserialize(meta.get(pid, {}).get("_wp_attachment_metadata", "")) or {}
    alt = meta.get(pid, {}).get("_wp_attachment_image_alt", "")
    sizes = {}
    for name, v in (md.get("sizes") or {}).items():
        if isinstance(v, dict):
            sizes[name] = {"file": v.get("file"), "width": v.get("width"), "height": v.get("height")}
    attachments[pid] = {
        "id": pid,
        "file": f,
        "url": MEDIA_BASE + "/" + f if f else "",
        "width": md.get("width"),
        "height": md.get("height"),
        "mime": p["mime"],
        "alt": html.unescape(alt or ""),
        "caption": plain(p["excerpt"]),
        "description": plain(p["content"]),
        "sizes": sizes,
    }

comments = collections.defaultdict(list)
for r in T["comments"]:
    if len(r) < 15:
        continue
    if r[10] != "1":
        continue
    cid = int(r[1])
    comments[cid].append({
        "id": int(r[0]),
        "author": html.unescape(plain(r[2], 120)),
        "date": iso(r[6]),
        "content": plain(r[8]),
        "reply_to": int(r[13] or 0),
    })

yoast_post = {}
yoast_term = {}
yoast_home_rows = []
for r in T["yoast_indexable"]:
    if len(r) < 22:
        continue
    oid = r[3]
    otype = r[4]
    rec = {
        "permalink": nn(r[1]),
        "object_type": otype,
        "object_sub_type": nn(r[5]) if len(r) > 5 else "",
        "title": nn(r[8]),
        "description": nn(r[9]),
        "breadcrumb": nn(r[10]) if len(r) > 10 else "",
        "number_of_pages": nn(r[15]) if len(r) > 15 else "",
        "canonical": nn(r[16]) or "",
        "noindex": r[21] == "1" if len(r) > 21 else False,
        "og_image": nn(r[33]) if len(r) > 33 else "",
        "twitter_image": nn(r[27]) if len(r) > 27 else "",
    }
    if otype == "post" and oid and oid != "NULL":
        yoast_post[int(oid)] = rec
    elif otype == "term" and oid and oid != "NULL":
        yoast_term[int(oid)] = rec
    elif otype == "home-page":
        yoast_home_rows.append(rec)

yoast_home = yoast_home_rows[0] if yoast_home_rows else {}

print(f"  posts={len(posts_by_id)} users={len(users)} terms={len(terms)} "
      f"attachments={len(attachments)} comments={sum(len(v) for v in comments.values())}")

# ---------------------------------------------------------------------------
# Posts and pages
# ---------------------------------------------------------------------------
published = {pid: p for pid, p in posts_by_id.items()
             if p["type"] in ("post", "page") and p["status"] == "publish"}
pages = {pid: p for pid, p in published.items() if p["type"] == "page"}
home_id = int(opts.get("page_on_front") or 0)

page_paths = {}


def page_path(pid):
    if pid in page_paths:
        return page_paths[pid]
    if pid == home_id:
        page_paths[pid] = "/"
        return "/"
    parts = []
    cur = pid
    seen = set()
    while cur and cur in pages and cur not in seen:
        seen.add(cur)
        parts.append(pages[cur]["slug"])
        cur = pages[cur]["parent"]
    page_paths[pid] = ensure_slash("/" + "/".join(reversed(parts)))
    return page_paths[pid]


content_url = {}
for pid, p in published.items():
    y = yoast_post.get(pid, {})
    path = canon_path(y.get("permalink")) if y.get("permalink") else None
    if pid == home_id:
        path = "/"
    if not path or path == "/" and pid != home_id:
        path = page_path(pid) if p["type"] == "page" else ensure_slash("/" + p["slug"])
    content_url[pid] = path


def seo_of(pid):
    y = yoast_post.get(pid, {})
    canonical = canon_path(y.get("canonical")) if y.get("canonical") else content_url.get(pid, "")
    return {
        "title": y.get("title", ""),
        "description": y.get("description", ""),
        "canonical": abs_url(canonical),
        "noindex": bool(y.get("noindex")),
        "og_image": y.get("og_image", "") or y.get("twitter_image", ""),
    }


def term_path(ttid):
    tx = taxonomy[ttid]
    t = terms[tx["term_id"]]
    y = yoast_term.get(tx["term_id"], {})
    if y.get("permalink"):
        return canon_path(y["permalink"])
    base = "/tag/" if tx["taxonomy"] == "post_tag" else "/category/"
    return ensure_slash(base + t["slug"])


# count only relationships to published posts/pages
pub_ids = set(published)

tags = []
cats = []
for ttid, tx in taxonomy.items():
    if tx["taxonomy"] not in ("post_tag", "category"):
        continue
    t = terms.get(tx["term_id"])
    if not t:
        continue
    count = len(rel.get(ttid, set()) & pub_ids)
    row = {
        "id": tx["term_id"],
        "ttid": ttid,
        "name": html.unescape(t["name"]),
        "slug": t["slug"],
        "url": term_path(ttid),
        "count": count,
        "noindex": bool(yoast_term.get(tx["term_id"], {}).get("noindex")),
        "description": plain(yoast_term.get(tx["term_id"], {}).get("description", "")),
    }
    (tags if tx["taxonomy"] == "post_tag" else cats).append(row)

tags_by_ttid = {t["ttid"]: t for t in tags}
cats_by_ttid = {c["ttid"]: c for c in cats}

# marca o que esta de fato no sitemap do Yoast (se baixado em dados/brutos/sitemaps)
SITEMAP_DIR = os.path.join(PROJ, "dados", "brutos", "sitemaps")


def sitemap_paths(prefix):
    acc = set()
    if not os.path.isdir(SITEMAP_DIR):
        return acc
    for name in os.listdir(SITEMAP_DIR):
        if not (name.startswith(prefix + "-sitemap") and name.endswith(".xml")):
            continue
        with open(os.path.join(SITEMAP_DIR, name), encoding="utf-8", errors="replace") as f:
            xml = f.read()
        for loc in re.findall(r"<loc>\s*([^<]+?)\s*</loc>", xml):
            acc.add(ensure_slash(path_of(loc)))
    return acc


sitemap_tags = sitemap_paths("post_tag")
sitemap_cats = sitemap_paths("category")
sitemap_authors = sitemap_paths("author")
for t in tags:
    t["in_sitemap"] = (t["url"] in sitemap_tags) if sitemap_tags else (t["count"] > 0)
for c in cats:
    c["in_sitemap"] = (c["url"] in sitemap_cats) if sitemap_cats else (c["count"] > 0)

# post -> terms
post_tags = collections.defaultdict(list)
post_cats = collections.defaultdict(list)
for ttid, ids in rel.items():
    tx = taxonomy.get(ttid)
    if not tx:
        continue
    for oid in ids & pub_ids:
        if tx["taxonomy"] == "post_tag":
            post_tags[oid].append(ttid)
        elif tx["taxonomy"] == "category":
            post_cats[oid].append(ttid)


def record(pid):
    p = published[pid]
    thumb = meta.get(pid, {}).get("_thumbnail_id")
    try:
        thumb = int(thumb) if thumb else None
    except ValueError:
        thumb = None
    if thumb not in attachments:
        thumb = None
    body = clean_html(p["content"])
    excerpt = plain(p["excerpt"]) or plain(body, 180)
    return {
        "id": pid,
        "type": p["type"],
        "slug": p["slug"],
        "url": content_url[pid],
        "canonical": abs_url(content_url[pid]),
        "title": html.unescape(norm_title(p["title"])),
        "date": iso(p["date"]),
        "modified": iso(p["modified"]),
        "author": p["author"],
        "excerpt": excerpt,
        "content": body,
        "categories": [cats_by_ttid[t]["id"] for t in post_cats.get(pid, []) if t in cats_by_ttid],
        "tags": [tags_by_ttid[t]["id"] for t in post_tags.get(pid, []) if t in tags_by_ttid],
        "featured": thumb,
        "comment_count": len(comments.get(pid, [])),
        "comments": comments.get(pid, []),
        "seo": seo_of(pid),
    }


post_records = [record(pid) for pid in published if published[pid]["type"] == "post"]
page_records = [record(pid) for pid in published if published[pid]["type"] == "page"]
post_records.sort(key=lambda r: r["date"] or "", reverse=True)
page_records.sort(key=lambda r: (r["url"].count("/"), r["url"]))

# authors with published posts
author_posts = collections.Counter(p["author"] for pid, p in published.items() if p["type"] == "post")
author_records = []
for uid in sorted(author_posts):
    u = users.get(uid)
    if not u or author_posts[uid] == 0:
        continue
    author_records.append({
        "id": uid,
        "nicename": u["nicename"],
        "name": html.unescape(u["display"]),
        "url": ensure_slash("/author/" + u["nicename"]),
        "description": user_bio.get(uid, ""),
        "posts": author_posts[uid],
    })

for a in author_records:
    a["in_sitemap"] = (a["url"] in sitemap_authors) if sitemap_authors else True

# ---------------------------------------------------------------------------
# URL map + pagination
# ---------------------------------------------------------------------------
print("[2/6] montando mapa de URLs...")
entries = {}
duplicates = []


def add(url, meta):
    if url in entries:
        duplicates.append((url, entries[url].get("type"), meta.get("type")))
        return
    entries[url] = meta


add("/", {"type": "home", "id": home_id})
add("/busca/", {"type": "search"})

for r in post_records:
    add(r["url"], {"type": "post", "id": r["id"]})
for r in page_records:
    if r["url"] != "/":
        add(r["url"], {"type": "page", "id": r["id"]})

# pagination overrides from fase 1 (GA/GSC observed)
fase1_pages = {}
fase1_csv = os.path.join(ANA, "arquivos-2026.csv")
if os.path.exists(fase1_csv):
    with open(fase1_csv, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("url"):
                try:
                    fase1_pages[row["url"]] = max(fase1_pages.get(row["url"], 1),
                                                  int(row.get("paginas_total") or 1))
                except ValueError:
                    pass

pag_count = 0
for rows, typ in ((tags, "tag"), (cats, "category")):
    for t in rows:
        url = t["url"]
        add(url, {"type": typ, "id": t["id"]})
        total = max(1, math.ceil(t["count"] / POSTS_PER_PAGE)) if t["count"] else 1
        total = max(total, fase1_pages.get(url, 1))
        t["pages"] = total
        for page in range(2, total + 1):
            add(ensure_slash(url.rstrip("/") + "/page/%d" % page),
                {"type": typ + "-page", "id": t["id"], "page": page})
            pag_count += 1

for a in author_records:
    add(a["url"], {"type": "author", "id": a["id"]})
    total = max(1, math.ceil(a["posts"] / POSTS_PER_PAGE))
    a["pages"] = total
    for page in range(2, total + 1):
        add(ensure_slash(a["url"].rstrip("/") + "/page/%d" % page),
            {"type": "author-page", "id": a["id"], "page": page})
        pag_count += 1

print(f"  entradas={len(entries)} paginas_extra={pag_count} duplicatas={len(duplicates)}")

# ---------------------------------------------------------------------------
# Redirects
# ---------------------------------------------------------------------------
print("[3/6] gerando redirects (dump 2010-2014 + anexos + WordPress)...")
current_urls = set(entries)
rules = []
seen_from = set()


def add_rule(frm, to, status, reason):
    if frm in seen_from or frm in current_urls:
        return
    seen_from.add(frm)
    rules.append({"from": frm, "to": to, "status": status, "reason": reason})


# attachments -> parent post
att_parent = {}
for pid, a in attachments.items():
    p = posts_by_id.get(pid)
    parent = p["parent"] if p else 0
    target = content_url.get(parent) if parent in published else None
    att_parent[pid] = target
    slug = p["slug"] if p else ""
    if slug:
        add_rule(ensure_slash("/" + slug), target, 301 if target else 410,
                 "anexo-para-post")

# old dump
print("  lendo dump antigo...")
O = wpdb.load_tables(OLD_SQL, ["posts", "terms", "term_taxonomy", "options"], prefix="wp_")
old_opts = {}
for r in O["options"]:
    if len(r) >= 3:
        old_opts[r[1]] = r[2]

old_posts = {}
for r in O["posts"]:
    if len(r) < 23:
        continue
    old_posts[int(r[0])] = {"id": int(r[0]), "type": nn(r[20]), "status": nn(r[7]), "slug": nn(r[11]),
                            "parent": int(r[17] or 0), "title": nn(r[5])}

old_pages = {pid: p for pid, p in old_posts.items()
             if p["type"] == "page" and p["status"] == "publish"}
old_page_paths = {}


def old_page_path(pid):
    if pid in old_page_paths:
        return old_page_paths[pid]
    parts = []
    cur = pid
    seen = set()
    while cur and cur in old_pages and cur not in seen:
        seen.add(cur)
        parts.append(old_pages[cur]["slug"])
        cur = old_pages[cur]["parent"]
    old_page_paths[pid] = ensure_slash("/" + "/".join(reversed(parts)))
    return old_page_paths[pid]


legacy_301 = 0
legacy_410 = 0
att_id_map = {str(pid): tgt for pid, tgt in att_parent.items() if tgt}
for pid, p in old_posts.items():
    if p["type"] in ("post", "page") and p["status"] != "publish":
        continue
    if p["type"] == "attachment" and p["status"] not in ("inherit", "publish"):
        continue
    if p["type"] not in ("post", "page", "attachment"):
        continue
    if p["type"] == "page":
        old_path = old_page_path(pid)
    else:
        old_path = ensure_slash("/" + p["slug"])
    if old_path in current_urls:
        continue
    if p["type"] in ("post", "page") and pid in content_url:
        add_rule(old_path, content_url[pid], 301, "slug-antigo")
        legacy_301 += 1
    elif p["type"] == "attachment" and pid in attachments and att_parent.get(pid):
        add_rule(old_path, att_parent[pid], 301, "anexo-antigo")
        legacy_301 += 1
    else:
        add_rule(old_path, None, 410, "conteudo-removido")
        legacy_410 += 1

# old terms
current_term_paths = {t["url"] for t in tags} | {c["url"] for c in cats}
old_terms = {}
for r in O["terms"]:
    if len(r) >= 3:
        old_terms[int(r[0])] = {"name": r[1], "slug": r[2]}
for r in O["term_taxonomy"]:
    if len(r) < 6:
        continue
    tid, tax = int(r[1]), r[2]
    if tax not in ("post_tag", "category") or tid not in old_terms:
        continue
    base = "/tag/" if tax == "post_tag" else "/category/"
    old_path = ensure_slash(base + old_terms[tid]["slug"])
    if old_path not in current_urls and old_path not in current_term_paths:
        add_rule(old_path, None, 410, "termo-removido")
        legacy_410 += 1

# caso especifico conhecido
special = "/tarantino-fala-sobre-star-trek/colunacliche"
target = "/tarantino-fala-sobre-star-trek/" if "/tarantino-fala-sobre-star-trek/" in current_urls else None
if not target and "/colunas/cliche/" in current_urls:
    target = "/colunas/cliche/"
add_rule(special, target, 301 if target else 410, "url-malformada")

# WordPress endpoints
for pat, reason in [
    ("/wp-admin/*", "wordpress"), ("/wp-login.php", "wordpress"),
    ("/xmlrpc.php", "wordpress"), ("/wp-json/*", "wordpress"),
    ("/feed/*", "feed"), ("/comments/feed/*", "feed"),
    ("/wp-content/*", "wordpress"), ("/wp-includes/*", "wordpress"),
    ("/readme.html", "wordpress"), ("/license.txt", "wordpress"),
    ("/wp-trackback.php", "wordpress"), ("/wp-cron.php", "wordpress"),
]:
    add_rule(pat, None, 410, reason)

query_rules = [
    {"param": "p", "action": "post-id", "status": 301},
    {"param": "page_id", "action": "page-id", "status": 301},
    {"param": "attachment_id", "action": "attachment", "status": 301},
    {"param": "s", "to": "/busca/", "status": 301},
    {"param": "rest_route", "to": None, "status": 410},
    {"param": "preview", "to": None, "status": 410},
]

r301 = sum(1 for r in rules if r["status"] == 301)
r410 = sum(1 for r in rules if r["status"] == 410)

# ---------------------------------------------------------------------------
# Counts / validation
# ---------------------------------------------------------------------------
print("[4/6] validando contagens...")
pub_post_ids = {pid for pid, p in published.items() if p["type"] == "post"}
pub_page_ids = {pid for pid, p in published.items() if p["type"] == "page"}
tag_com_post = set()
for ttid, ids in rel.items():
    tx = taxonomy.get(ttid)
    if tx and tx["taxonomy"] == "post_tag" and (ids & pub_post_ids):
        tag_com_post.add(ttid)
tag_pub = [t for t in tags if t["count"] > 0]
tag_noindex = [t for t in tags if t["noindex"]]
tag_sitemap = [t for t in tags if t["in_sitemap"]]
tag_so_pagina = [t for t in tag_pub if t["ttid"] not in tag_com_post]
cat_pub = [c for c in cats if c["count"] > 0]
author_posts = collections.Counter(p["author"] for pid, p in published.items() if p["type"] == "post")

yoast_posts = sum(1 for v in yoast_post.values() if v["object_type"] == "post"
                  and v["object_sub_type"] in ("post", "page"))
yoast_terms = sum(1 for v in yoast_term.values() if v["object_type"] == "term")

report = {
    "posts": len(post_records),
    "pages": len(page_records),
    "tags_total": len(tags),
    "tags_com_posts": len(tag_pub),
    "tags_com_post": len(tag_com_post),
    "tags_so_em_paginas": len(tag_so_pagina),
    "tags_noindex": len(tag_noindex),
    "tags_sitemap": len(tag_sitemap),
    "sitemap_data_disponivel": bool(sitemap_tags),
    "categories": len(cats),
    "categories_com_posts": len(cat_pub),
    "authors": len(author_records),
    "authors_com_posts": sum(1 for a in author_records if author_posts.get(a["id"], 0) > 0),
    "media": len(attachments),
    "comments": sum(len(v) for v in comments.values()),
    "url_entries": len(entries),
    "url_duplicates": len(duplicates),
    "pagination_pages": pag_count,
    "redirects_301": r301,
    "redirects_410": r410,
    "redirects_total": len(rules),
    "yoast_posts": yoast_posts,
    "yoast_terms": yoast_terms,
    "home_pages_yoast": yoast_home.get("number_of_pages"),
    "home_rows_yoast": len(yoast_home_rows),
    "legacy_301": legacy_301,
    "legacy_410": legacy_410,
}
report["media_com_dimensoes"] = sum(1 for a in attachments.values()
                                   if a.get("width") and a.get("height"))
reasons = collections.Counter(r["reason"] for r in rules)

print("  ", report)

# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------
print("[5/6] escrevendo JSON...")
site = {
    "name": opts.get("blogname", "Cinema e Muito +"),
    "description": opts.get("blogdescription", ""),
    "url": SITE,
    "media_base": MEDIA_BASE,
    "language": "pt-BR",
    "timezone": opts.get("timezone_string", "America/Sao_Paulo"),
    "date_format": opts.get("date_format", "d/m/Y"),
    "permalink_structure": opts.get("permalink_structure", "/%postname%/"),
    "posts_per_page": POSTS_PER_PAGE,
    "page_on_front": home_id,
    "page_for_posts": int(opts.get("page_for_posts") or 0),
    "adsense": "ca-pub-6725457701341059",
    "ga4": "G-7JK7M6939D",
    "gtm": "GTM-WTDZX43",
    "generated_at": GENERATED,
}

jdump(os.path.join(DATA, "site.json"), site, indent=2)
jdump(os.path.join(DATA, "posts.json"), post_records)
jdump(os.path.join(DATA, "pages.json"), page_records)
jdump(os.path.join(DATA, "tags.json"), tags)
jdump(os.path.join(DATA, "categories.json"), cats)
jdump(os.path.join(DATA, "authors.json"), author_records, indent=2)
jdump(os.path.join(DATA, "media.json"), {str(k): v for k, v in attachments.items()})
jdump(os.path.join(DATA, "url-map.json"), {
    "site": SITE,
    "generated_at": GENERATED,
    "entries": entries,
})
jdump(os.path.join(DATA, "redirects.json"), {
    "generated_at": GENERATED,
    "total": len(rules),
    "by_status": {"301": r301, "410": r410},
    "rules": rules,
    "query": query_rules,
    "post_id_map": {str(r["id"]): r["url"] for r in post_records},
    "page_id_map": {str(r["id"]): r["url"] for r in page_records},
    "attachment_id_map": att_id_map,
})

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
print("[6/6] escrevendo relatorio...")
with open(os.path.join(ANA, "fase-2-relatorio.md"), "w", encoding="utf-8") as f:
    f.write("# Fase 2 - Exportacao e mapa de URLs\n\n")
    f.write(f"Gerado em {GENERATED} por `src/scripts/export-db.py`.\n\n")
    f.write("## Contagens\n\n")
    f.write("| Item | Valor |\n|---|---:|\n")
    for k, v in report.items():
        f.write(f"| {k} | {v} |\n")
    f.write("\n## Validacao\n\n")
    f.write(f"- Posts esperados 4.596: **{len(post_records)}**\n")
    f.write(f"- Paginas esperadas 191: **{len(page_records)}**\n")
    f.write(f"- Tags no sitemap do Yoast: **{len(tag_sitemap)}**\n")
    f.write(f"- Tags geradas (todas, inclui P3): **{len(tags)}**\n")
    f.write(f"- URLs duplicadas: **{len(duplicates)}**\n")
    if duplicates:
        f.write("\nDuplicatas:\n\n")
        for u, a, b in duplicates[:100]:
            f.write(f"- `{u}` ({a} x {b})\n")
    f.write("\n## Redirects\n\n")
    f.write(f"- 301: {r301}\n- 410: {r410}\n- Total: {len(rules)}\n\n")
    f.write("Por motivo:\n\n| Motivo | Regras |\n|---|---:|\n")
    for reason, n in reasons.most_common():
        f.write(f"| {reason} | {n} |\n")
    f.write("\n## Observacoes\n\n")
    f.write("- A home (`/`) consta no page-sitemap como pagina, mas no url-map tem tipo `home`.\n")
    f.write(f"- Tags no sitemap: {len(tag_sitemap)}; geradas: {len(tags)} "
            f"(+{len(tags) - len(tag_sitemap)} tags P3 fora do sitemap, marcadas `in_sitemap=false`).\n")
    f.write(f"- Midia com dimensoes: {report['media_com_dimensoes']}/{len(attachments)}.\n")
    f.write("\n## Arquivos gerados\n\n")
    for name in ["site.json", "posts.json", "pages.json", "tags.json", "categories.json",
                 "authors.json", "media.json", "url-map.json", "redirects.json"]:
        p = os.path.join(DATA, name)
        f.write(f"- `{name}` ({os.path.getsize(p) / 1024:.1f} KB)\n")

print("[ok] arquivos em", DATA)
