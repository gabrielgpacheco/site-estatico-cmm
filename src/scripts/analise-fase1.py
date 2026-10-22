# -*- coding: utf-8 -*-
"""
Fase 1 - Analise GA4/GSC e lista de URLs do CMM.

Gera em dados/analise-2026/:
  - paginas-posts-2026.csv
  - arquivos-2026.csv
  - midia-referenciada.csv
  - resumo-analise.md
  - urls-para-verificacao.txt

Uso:
  python src/scripts/analise-fase1.py
"""
import collections
import csv
import gzip
import glob
import html
import math
import os
import re
import subprocess
import sys
import urllib.parse

sys.stdout.reconfigure(encoding="utf-8")

ROOT = r"C:\Users\dayan\Downloads\migracao-sites"
CMM = os.path.join(ROOT, "CMM")
PROJ = os.path.join(ROOT, "site-estatico-cmm")
OUT = os.path.join(PROJ, "dados", "analise-2026")
SQL = os.path.join(CMM, "gabriel_cinemaemuitoma.sql.gz")
TAR = os.path.join(CMM, "backup-cinemaemuitomais.com-10-20-2026.tar.gz")
SITE = "https://www.cinemaemuitomais.com"
BLOGNAME = "Cinema e Muito +"
POSTS_PER_PAGE = 50

os.makedirs(OUT, exist_ok=True)


# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------
def parse_values(s):
    """Le tuplas (v1,v2,...) de um trecho VALUES do mysqldump."""
    rows = []
    i = 0
    n = len(s)
    while i < n:
        while i < n and s[i] in " ,\r\n\t":
            i += 1
        if i >= n or s[i] != "(":
            break
        i += 1
        vals = []
        cur = []
        isstr = False
        while i < n:
            c = s[i]
            if isstr:
                if c == "\\":
                    nxt = s[i + 1] if i + 1 < n else ""
                    mp = {"n": "\n", "r": "\r", "t": "\t", "0": "\0", "Z": "\x1a", "b": "\b"}
                    cur.append(mp.get(nxt, nxt))
                    i += 2
                    continue
                if c == "'":
                    if i + 1 < n and s[i + 1] == "'":
                        cur.append("'")
                        i += 2
                        continue
                    isstr = False
                    i += 1
                    continue
                cur.append(c)
                i += 1
                continue
            if c == "'":
                isstr = True
                i += 1
                continue
            if c == ",":
                vals.append("".join(cur))
                cur = []
                i += 1
                continue
            if c == ")":
                vals.append("".join(cur))
                i += 1
                break
            cur.append(c)
            i += 1
        rows.append(vals)
    return rows


def insert_rows(line):
    k = line.find(" VALUES ")
    if k < 0:
        return []
    return parse_values(line[k + 8:])


# ---------------------------------------------------------------------------
# Text normalization
# ---------------------------------------------------------------------------
def norm_title(s):
    s = html.unescape(s or "")
    s = s.replace("\u00a0", " ")
    s = s.replace("\u2019", "'").replace("\u2018", "'")
    s = s.replace("\u201c", '"').replace("\u201d", '"')
    s = re.sub(r"\s+", " ", s).strip()
    return s


def strip_suffix(s):
    s = norm_title(s)
    s = re.sub(r"\s*[-\u2013\u2014|]\s*Cinema e Muito\s*\+$", "", s, flags=re.I)
    return s.strip()


def strip_archives(s):
    s = strip_suffix(s)
    s = re.sub(r"\s+Archives$", "", s, flags=re.I).strip()
    return s


def slugify(s):
    s = norm_title(s).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def rel_path_from_url(u):
    """Devolve caminho relativo comecando com / (sem query/fragmento)."""
    if not u:
        return "/"
    if u.startswith("http://") or u.startswith("https://"):
        path = urllib.parse.urlparse(u).path
    else:
        path = urllib.parse.urlparse(u).path
    path = urllib.parse.unquote(path or "/")
    return path or "/"


def abs_url(path):
    if not path:
        return ""
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return SITE + ("" if path.startswith("/") else "/") + path


def norm_key(path):
    p = rel_path_from_url(path)
    return p[:-1] if len(p) > 1 and p.endswith("/") else p


def is_pretty(path):
    last = rel_path_from_url(path).rstrip("/").split("/")[-1]
    return "." not in last


def ensure_slash(u):
    if not u:
        return u
    if not u.endswith("/") and is_pretty(u):
        return u + "/"
    return u


# ---------------------------------------------------------------------------
# CSV section reader
# ---------------------------------------------------------------------------
def read_section(path, header_prefix, ncols, numeric_index, only_first=True):
    rows = []
    insec = False
    started = False
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            if not row:
                if insec:
                    insec = False
                continue
            first = row[0]
            if first.startswith("#"):
                if insec:
                    insec = False
                continue
            if first.startswith(header_prefix):
                if only_first and started:
                    insec = False
                    continue
                started = True
                insec = True
                continue
            if insec:
                if len(row) <= numeric_index:
                    insec = False
                    continue
                try:
                    int(row[numeric_index])
                except ValueError:
                    insec = False
                    continue
                rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Load GA4 / GSC
# ---------------------------------------------------------------------------
engagement_csv = glob.glob(os.path.join(CMM, "*engajamento*.csv"))[0]
resumo_csv = glob.glob(os.path.join(CMM, "Resumo*.csv"))[0]
aquisicao_csv = glob.glob(os.path.join(CMM, "*aquisi*.csv"))[0]
monetizacao_csv = glob.glob(os.path.join(CMM, "*monetiza*.csv"))[0]

print("[ga] lendo engajamento YTD...")
ytd_rows = read_section(engagement_csv, "T\u00edtulo da p\u00e1gina", 2, 1)
print("[ga] lendo resumo 28 dias...")
res_rows = read_section(resumo_csv, "T\u00edtulo da p\u00e1gina", 5, 1)
print("[gsc] lendo paginas de destino...")
gsc_rows = read_section(aquisicao_csv, "P\u00e1gina de destino", 2, 1)

ytd = {}
for r in ytd_rows:
    t = r[0]
    v = int(r[1])
    ytd[t] = ytd.get(t, 0) + v

res28 = {}
for r in res_rows:
    t = r[0]
    res28[t] = (int(r[1]), int(r[2]))

gsc = {}
for r in gsc_rows:
    path = r[0]
    imp = int(r[1])
    u = ensure_slash(abs_url(path))
    gsc[u] = max(gsc.get(u, 0), imp)
    k = norm_key(u)
    gsc.setdefault(k, 0)
    gsc[k] = max(gsc[k], imp)

gsc_archives = {}
for u, imp in list(gsc.items()):
    p = rel_path_from_url(u)
    if p.startswith("/tag/") or p.startswith("/category/") or p.startswith("/author/"):
        gsc_archives[ensure_slash(u)] = imp


def ga_lookup(table, title):
    for key in (norm_title(title), strip_suffix(title), slugify(strip_suffix(title))):
        if key in table:
            return table[key]
    return None


ytd_by_norm = {}
for t, v in ytd.items():
    ytd_by_norm.setdefault(norm_title(t), v)
    ytd_by_norm.setdefault(strip_suffix(t), v)
    ytd_by_norm.setdefault(slugify(strip_suffix(t)), v)

res_by_norm = {}
for t, vu in res28.items():
    res_by_norm.setdefault(norm_title(t), vu)
    res_by_norm.setdefault(strip_suffix(t), vu)
    res_by_norm.setdefault(slugify(strip_suffix(t)), vu)

print(f"[ga] títulos YTD={len(ytd)} | 28d={len(res28)} | GSC URLs={len(gsc)}")


# ---------------------------------------------------------------------------
# Parse SQL dump
# ---------------------------------------------------------------------------
content = {}          # pid -> dict
pages = {}            # pid -> (title, slug, parent)
attachments = {}      # att id -> dict
thumbs = {}           # post id -> thumb id
attached_file = {}    # att id -> file
terms = {}            # term_id -> dict
taxonomy = {}         # ttid -> dict
rel_count = collections.Counter()
media_refs = collections.defaultdict(set)   # rel -> set of (pid, origem)
yoast_post = {}       # object_id -> dict (object_type == post)
yoast_term = {}       # object_id -> dict (object_type == term)
users = {}            # user id -> dict

print("[sql] lendo dump (pode demorar)...")
with gzip.open(SQL, "rt", encoding="utf-8", errors="replace") as f:
    for line in f:
        if line.startswith("INSERT INTO `wp4LG7q9Gf_posts`"):
            for r in insert_rows(line):
                if len(r) < 23:
                    continue
                pid = int(r[0])
                typ = r[20]
                st = r[7]
                title = r[5]
                slug = r[11]
                if typ in ("post", "page") and st == "publish":
                    c = {
                        "id": pid,
                        "type": typ,
                        "title": title,
                        "slug": slug,
                        "date": r[2],
                        "parent": int(r[17] or 0),
                        "content_len": len(r[4] or ""),
                        "gutenberg": "<!-- wp:" in (r[4] or ""),
                    }
                    content[pid] = c
                    if typ == "page":
                        pages[pid] = (title, slug, int(r[17] or 0))
                    for m in re.finditer(r"/wp-content/uploads/([^\s\"'<>)]+)", r[4] or ""):
                        media_refs[urllib.parse.unquote(m.group(1).split("?")[0])].add((pid, "conteudo"))
                elif typ == "attachment":
                    attachments[pid] = {"guid": r[18], "title": title, "parent": int(r[17] or 0)}
        elif line.startswith("INSERT INTO `wp4LG7q9Gf_postmeta`"):
            for r in insert_rows(line):
                if len(r) < 4:
                    continue
                key = r[2]
                if key == "_thumbnail_id":
                    thumbs[r[1]] = r[3]
                elif key == "_wp_attached_file":
                    attached_file[r[1]] = r[3]
        elif line.startswith("INSERT INTO `wp4LG7q9Gf_terms`"):
            for r in insert_rows(line):
                if len(r) >= 3:
                    terms[int(r[0])] = {"name": r[1], "slug": r[2]}
        elif line.startswith("INSERT INTO `wp4LG7q9Gf_term_taxonomy`"):
            for r in insert_rows(line):
                if len(r) >= 6:
                    taxonomy[int(r[0])] = {
                        "term_id": int(r[1]),
                        "taxonomy": r[2],
                        "parent": int(r[4] or 0),
                        "count": int(r[5] or 0),
                    }
        elif line.startswith("INSERT INTO `wp4LG7q9Gf_term_relationships`"):
            for r in insert_rows(line):
                if len(r) >= 2:
                    try:
                        rel_count[int(r[1])] += 1
                    except ValueError:
                        pass
        elif line.startswith("INSERT INTO `wp4LG7q9Gf_users`"):
            for r in insert_rows(line):
                if len(r) >= 10:
                    users[int(r[0])] = {"nicename": r[3], "display": r[9]}
        elif line.startswith("INSERT INTO `wp4LG7q9Gf_yoast_indexable`"):
            for r in insert_rows(line):
                if len(r) < 5:
                    continue
                try:
                    oid = int(r[3])
                except (TypeError, ValueError):
                    continue
                otype = r[4]
                if otype not in ("post", "term"):
                    continue
                rec = {
                    "object_type": otype,
                    "permalink": r[1],
                    "title": r[8],
                    "description": r[9],
                    "number_of_pages": r[15],
                    "canonical": r[16],
                    "noindex": r[21] if len(r) > 21 else None,
                    "og_image": r[33] if len(r) > 33 else None,
                    "twitter_image": r[27] if len(r) > 27 else None,
                    "published": r[51] if len(r) > 51 else None,
                }
                if otype == "post":
                    yoast_post[oid] = rec
                else:
                    yoast_term[oid] = rec

print(f"[sql] posts/pages={len(content)} pages={len(pages)} attachments={len(attachments)} terms={len(terms)}")

# featured images
for pid, c in content.items():
    tid = thumbs.get(str(pid))
    if tid:
        f = attached_file.get(str(tid))
        if f:
            media_refs[f].add((pid, "featured"))

# ---------------------------------------------------------------------------
# Build URLs
# ---------------------------------------------------------------------------
page_path = {}


def page_url(pid):
    if pid in page_path:
        return page_path[pid]
    if pid == 39:
        page_path[pid] = SITE + "/"
        return page_path[pid]
    parts = []
    cur = pid
    seen = set()
    while cur and cur in pages and cur not in seen:
        seen.add(cur)
        t, s, p = pages[cur]
        parts.append(s)
        cur = p
    page_path[pid] = SITE + "/" + "/".join(reversed(parts)) + "/"
    return page_path[pid]


content_url = {}
for pid, c in content.items():
    y = yoast_post.get(pid) or {}
    u = y.get("permalink") or ""
    if not u or "?" in u:
        u = page_url(pid) if c["type"] == "page" else SITE + "/" + c["slug"] + "/"
    u = ensure_slash(u if u.startswith("http") else abs_url(u))
    content_url[pid] = u

term_url = {}
for ttid, tx in taxonomy.items():
    if tx["taxonomy"] not in ("post_tag", "category"):
        continue
    t = terms.get(tx["term_id"])
    if not t:
        continue
    y = yoast_term.get(tx["term_id"]) or {}
    u = y.get("permalink") or ""
    if not u:
        base = "/tag/" if tx["taxonomy"] == "post_tag" else "/category/"
        u = SITE + base + t["slug"] + "/"
    term_url[ttid] = ensure_slash(u if u.startswith("http") else abs_url(u))

author_url = {}
for uid, u in users.items():
    author_url[uid] = SITE + "/author/" + u["nicename"] + "/"


# ---------------------------------------------------------------------------
# Match GA/GSC to content
# ---------------------------------------------------------------------------
home_id = 39
title_lookup = collections.defaultdict(list)
for pid, c in content.items():
    for k in {norm_title(c["title"]), strip_suffix(c["title"]), slugify(strip_suffix(c["title"]))}:
        title_lookup[k].append(pid)

ambiguous = 0
matched_ga = 0
for title, views in ytd.items():
    keys = [norm_title(title), strip_suffix(title), slugify(strip_suffix(title))]
    cands = []
    for k in keys:
        for pid in title_lookup.get(k, []):
            if pid not in cands:
                cands.append(pid)
    if norm_title(title) == norm_title(BLOGNAME):
        cands = [home_id]
    if not cands:
        continue
    if len(cands) > 1:
        ambiguous += 1
    pid = cands[0]
    content[pid]["views_ga"] = max(content[pid].get("views_ga", 0), views)
    matched_ga += 1

for title, (views, us) in res28.items():
    for k in (norm_title(title), strip_suffix(title), slugify(strip_suffix(title))):
        for pid in title_lookup.get(k, []):
            content[pid]["users_28"] = max(content[pid].get("users_28", 0), us)
            break

for pid, c in content.items():
    u = content_url[pid]
    c["gsc"] = max(gsc.get(u, 0), gsc.get(norm_key(u), 0))
    c["views_ga"] = c.get("views_ga", 0)
    c["users_28"] = c.get("users_28", 0)

print(f"[match] conteudo com GA={matched_ga} ambiguos={ambiguous}")


# ---------------------------------------------------------------------------
# Prioridade
# ---------------------------------------------------------------------------
top100 = [pid for pid, _ in sorted(content.items(), key=lambda kv: -kv[1]["views_ga"])[:100]]

for pid, c in content.items():
    p0 = False
    if pid == home_id or c["type"] == "page":
        p0 = True
    if c["gsc"] > 0:
        p0 = True
    if c["views_ga"] == 0 and c["gsc"] == 0:
        p0 = False
    c["prioridade"] = "P0" if p0 else "P1"
for pid in top100:
    if content[pid]["prioridade"] == "P1":
        content[pid]["prioridade"] = "P0"


# ---------------------------------------------------------------------------
# Media
# ---------------------------------------------------------------------------
print("[midia] indexando uploads no tar...")
sizes = {}
pat = re.compile(r"^\S+\s+\d+\s+\S+\s+\S+\s+(\d+)\s+\S+\s+\S+\s+\S+\s+(.*)$")
proc = subprocess.Popen(["tar", "-tvzf", TAR], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                        text=True, encoding="utf-8", errors="replace")
for line in proc.stdout:
    m = pat.match(line.rstrip("\n"))
    if not m:
        continue
    p = m.group(2)
    if "/wp-content/uploads/" in p and not p.endswith("/"):
        rel = urllib.parse.unquote(p.split("/wp-content/uploads/", 1)[1])
        sizes[rel] = int(m.group(1))
proc.wait()
print(f"[midia] {len(sizes)} arquivos indexados")


def media_candidates(rel):
    yield rel
    base, ext = os.path.splitext(rel)
    m = re.match(r"^(.*)-\d+x\d+$", base)
    if m:
        yield m.group(1) + ext
    if base.endswith("-scaled"):
        yield base[: -len("-scaled")] + ext
    else:
        yield base + "-scaled" + ext


def resolve_media(rel):
    for cand in media_candidates(rel):
        if cand in sizes:
            return cand, sizes[cand], ("exato" if cand == rel else "original")
    bn = os.path.basename(rel)
    bn_base, bn_ext = os.path.splitext(bn)
    m = re.match(r"^(.*)-\d+x\d+$", bn_base)
    orig_bn = (m.group(1) if m else bn_base) + bn_ext
    cands = [k for k in sizes if os.path.basename(k) == orig_bn]
    if cands:
        best = max(cands, key=lambda k: sizes[k])
        return best, sizes[best], "original"
    return None, 0, "faltante"


title_by_id = {pid: c["title"] for pid, c in content.items()}
media_rows = []
found = original = missing = 0
for rel, uses in media_refs.items():
    local, size, status = resolve_media(rel)
    if status == "exato":
        found += 1
    elif status == "original":
        original += 1
    else:
        missing += 1
    usados = []
    for pid, origem in sorted(uses, key=lambda x: x[0])[:3]:
        usados.append(f"{pid}:{title_by_id.get(pid, '?')[:60]} ({origem})")
    media_rows.append({
        "url_original": SITE + "/wp-content/uploads/" + rel,
        "arquivo_local": local or ("wp-content/uploads/" + rel),
        "tamanho_bytes": size,
        "status": status,
        "usado_em": " | ".join(usados),
        "total_usos": len(uses),
    })
media_rows.sort(key=lambda r: (-r["tamanho_bytes"], r["url_original"]))
print(f"[midia] referenciadas={len(media_rows)} exatas={found} originais={original} faltantes={missing}")


# ---------------------------------------------------------------------------
# Archives
# ---------------------------------------------------------------------------
term_lookup = {}
for ttid, tx in taxonomy.items():
    if tx["taxonomy"] not in ("post_tag", "category"):
        continue
    t = terms.get(tx["term_id"])
    if not t:
        continue
    for k in {norm_title(t["name"]), slugify(t["name"])}:
        term_lookup.setdefault(k, []).append(ttid)

archive_views = collections.Counter()
archive_pages = collections.defaultdict(set)
archive_raw_pages = collections.defaultdict(set)
unknown_archives = collections.Counter()

for title, views in ytd.items():
    if "Archives" not in title:
        continue
    s = strip_suffix(title)
    m = re.match(r"^(.*?)\s*-\s*P\u00e1gina\s+(\d+)\s+de\s+(\d+)$", s)
    page_no = 1
    total_pages = 1
    if m:
        s = m.group(1).strip()
        page_no = int(m.group(2))
        total_pages = int(m.group(3))
    s = re.sub(r"\s+Archives$", "", s, flags=re.I).strip()
    key = norm_title(s)
    cands = term_lookup.get(key) or term_lookup.get(slugify(s))
    if cands:
        ttid = cands[0]
        archive_views[ttid] += views
        archive_pages[ttid].add(page_no)
        archive_raw_pages[ttid].add(total_pages)
    else:
        unknown_archives[s] += views

# categorias/autores/arquivos de data sem a palavra Archives
for title, views in ytd.items():
    if "Archives" in title:
        continue
    base = strip_suffix(title)
    if base.startswith("Voc\u00ea pesquisou") or "P\u00e1gina n\u00e3o encontrada" in base:
        continue
    page = 1
    m = re.match(r"^(.*?)\s*-\s*P\u00e1gina\s+(\d+)\s+de\s+(\d+)$", base)
    if m:
        base = m.group(1).strip()
        page = int(m.group(2))
    norm = norm_title(base)
    if norm == norm_title(BLOGNAME) or norm in title_lookup:
        continue
    cands = term_lookup.get(norm) or term_lookup.get(slugify(base))
    if cands:
        ttid = cands[0]
        archive_views[ttid] += views
        archive_pages[ttid].add(page)
    else:
        unknown_archives[base] += views

archive_rows = []
for ttid, u in term_url.items():
    tx = taxonomy[ttid]
    t = terms[tx["term_id"]]
    count = rel_count.get(ttid, tx["count"])
    pages_total = max(1, math.ceil(count / POSTS_PER_PAGE)) if count else 1
    ga_max = max(archive_raw_pages.get(ttid, {1}))
    pages_total = max(pages_total, ga_max)
    pag_trafego = sorted(archive_pages.get(ttid, {1}))
    gsc_imp = max(gsc_archives.get(u, 0), gsc_archives.get(ensure_slash(u), 0))
    views = archive_views.get(ttid, 0)
    prioridade = "P2" if (gsc_imp > 0 or views >= 10) else "P3"
    archive_rows.append({
        "prioridade": prioridade,
        "url": u,
        "tipo": tx["taxonomy"],
        "base": t["name"],
        "slug": t["slug"],
        "posts": count,
        "views_ga_2026": views,
        "impressoes_gsc": gsc_imp,
        "paginas_total": pages_total,
        "paginas_com_trafego": ",".join(str(p) for p in pag_trafego),
        "paginas_gerar_total": max(1, len(pag_trafego)),
    })

# autores
for uid, u in author_url.items():
    gsc_imp = max(gsc_archives.get(u, 0), gsc_archives.get(ensure_slash(u), 0))
    views = 0
    for title, v in ytd.items():
        if strip_suffix(title).strip() == users[uid]["display"]:
            views += v
    prioridade = "P2" if (gsc_imp > 0 or views >= 10) else "P3"
    archive_rows.append({
        "prioridade": prioridade,
        "url": u,
        "tipo": "author",
        "base": users[uid]["display"],
        "slug": users[uid]["nicename"],
        "posts": 0,
        "views_ga_2026": views,
        "impressoes_gsc": gsc_imp,
        "paginas_total": 1,
        "paginas_com_trafego": "1" if views else "",
        "paginas_gerar_total": 1 if views else 0,
    })

# desconhecidos (inclui datas)
MESES = {"janeiro": 1, "fevereiro": 2, "marco": 3, "mar\u00e7o": 3, "abril": 4, "maio": 5,
         "junho": 6, "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10,
         "novembro": 11, "dezembro": 12}


def date_archive_url(base):
    m = re.match(r"^([A-Za-z\u00c0-\u00ff]+)\s+(\d{4})$", base.strip())
    if m and m.group(1).lower() in MESES:
        mm = MESES[m.group(1).lower()]
        return SITE + "/%s/%02d/" % (m.group(2), mm)
    m = re.match(r"^(\d{4})$", base.strip())
    if m:
        return SITE + "/%s/" % m.group(1)
    return None


for base, views in unknown_archives.most_common():
    gsc_imp = 0
    url = date_archive_url(base) or ""
    if url:
        gsc_imp = max(gsc_archives.get(url, 0), gsc_archives.get(ensure_slash(url), 0))
    prioridade = "P2" if (views >= 10 or gsc_imp > 0) else "P3"
    archive_rows.append({
        "prioridade": prioridade,
        "url": url if url else "",
        "tipo": "arquivo-data" if url else "arquivo-desconhecido",
        "base": base,
        "slug": slugify(base),
        "posts": 0,
        "views_ga_2026": views,
        "impressoes_gsc": gsc_imp,
        "paginas_total": 1,
        "paginas_com_trafego": "1" if views else "",
        "paginas_gerar_total": 1 if views else 0,
    })

archive_rows.sort(key=lambda r: (-r["impressoes_gsc"], -r["views_ga_2026"]))


# ---------------------------------------------------------------------------
# Write CSVs
# ---------------------------------------------------------------------------
content_rows = []
for pid, c in content.items():
    acao = "preservar"
    if c["views_ga"] == 0 and c["gsc"] == 0:
        acao = "preservar + revisar titulo"
    content_rows.append({
        "prioridade": c["prioridade"],
        "url": content_url[pid],
        "titulo": c["title"],
        "tipo": c["type"],
        "status": "publish",
        "publicado_em": c["date"],
        "views_ga_2026": c["views_ga"],
        "usuarios_ga_28d": c["users_28"],
        "impressoes_gsc": c["gsc"],
        "paginas_total": 1,
        "acao": acao,
    })
content_rows.sort(key=lambda r: (r["prioridade"], -r["impressoes_gsc"], -r["views_ga_2026"]))

with open(os.path.join(OUT, "paginas-posts-2026.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["prioridade", "url", "titulo", "tipo", "status",
                                      "publicado_em", "views_ga_2026", "usuarios_ga_28d",
                                      "impressoes_gsc", "paginas_total", "acao"])
    w.writeheader()
    w.writerows(content_rows)

with open(os.path.join(OUT, "arquivos-2026.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["prioridade", "url", "tipo", "base", "slug", "posts",
                                      "views_ga_2026", "impressoes_gsc", "paginas_total",
                                      "paginas_com_trafego", "paginas_gerar_total"])
    w.writeheader()
    w.writerows(archive_rows)

with open(os.path.join(OUT, "midia-referenciada.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["url_original", "arquivo_local", "tamanho_bytes",
                                      "status", "usado_em", "total_usos"])
    w.writeheader()
    w.writerows(media_rows)

# URLs para verificacao
urls = set()
urls.add("/")
for r in content_rows:
    urls.add(rel_path_from_url(r["url"]))
for r in archive_rows:
    if r["url"]:
        p = rel_path_from_url(r["url"])
        urls.add(p)
        for pg in r["paginas_com_trafego"].split(","):
            if pg and pg != "1":
                urls.add(p.rstrip("/") + "/page/" + pg + "/")
with open(os.path.join(OUT, "urls-para-verificacao.txt"), "w", encoding="utf-8", newline="") as f:
    for u in sorted(urls):
        f.write(u + "\n")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
n_p0 = sum(1 for r in content_rows if r["prioridade"] == "P0")
n_p1 = sum(1 for r in content_rows if r["prioridade"] == "P1")
n_p2 = sum(1 for r in archive_rows if r["prioridade"] == "P2")
n_p3 = sum(1 for r in archive_rows if r["prioridade"] == "P3")
views_content = sum(r["views_ga_2026"] for r in content_rows)
views_arch = sum(r["views_ga_2026"] for r in archive_rows)
gsc_content = sum(r["impressoes_gsc"] for r in content_rows)
gsc_arch = sum(r["impressoes_gsc"] for r in archive_rows)

with open(os.path.join(OUT, "resumo-analise.md"), "w", encoding="utf-8") as f:
    f.write("# Fase 1 - Resumo da analise GA4/GSC\n\n")
    f.write("Gerado por `src/scripts/analise-fase1.py` em 2026-10-20.\n\n")
    f.write("## Totais\n\n")
    f.write(f"- Posts/paginas: {len(content_rows)} (P0={n_p0}, P1={n_p1})\n")
    f.write(f"- Arquivos (tags/categorias/autores/desconhecidos): {len(archive_rows)} (P2={n_p2}, P3={n_p3})\n")
    f.write(f"- Views GA 2026 em conteudo: {views_content}\n")
    f.write(f"- Views GA 2026 em arquivos: {views_arch}\n")
    f.write(f"- Impressoes GSC em conteudo: {gsc_content}\n")
    f.write(f"- Impressoes GSC em arquivos: {gsc_arch}\n")
    f.write(f"- Midia referenciada: {len(media_rows)} (exata={found}, original={original}, faltante={missing})\n")
    f.write(f"- URLs para verificacao: {len(urls)}\n\n")
    f.write("## Qualidade dos dados\n\n")
    f.write("- O GA4 esta contaminado por trafego Direct/Singapore (~97%).\n")
    f.write("- Prioridade P0 usa GSC + paginas + home + top 100 GA.\n")
    f.write(f"- Titulos de conteudo ambiguos: {ambiguous}.\n\n")
    f.write("## Top 30 P0 por impressoes GSC\n\n")
    f.write("| Impressoes | Views GA | Tipo | URL |\n|---:|---:|---|---|\n")
    for r in [x for x in content_rows if x["prioridade"] == "P0"][:30]:
        f.write(f"| {r['impressoes_gsc']} | {r['views_ga_2026']} | {r['tipo']} | {r['url']} |\n")
    f.write("\n## Top 30 posts/paginas por views GA 2026\n\n")
    f.write("| Views GA | Impressoes | Tipo | URL |\n|---:|---:|---|---|\n")
    for r in sorted(content_rows, key=lambda x: -x["views_ga_2026"])[:30]:
        f.write(f"| {r['views_ga_2026']} | {r['impressoes_gsc']} | {r['tipo']} | {r['url']} |\n")
    f.write("\n## Top 30 arquivos\n\n")
    f.write("| Views GA | Impressoes | Tipo | Base | URL |\n|---:|---:|---|---|---|\n")
    for r in archive_rows[:30]:
        f.write(f"| {r['views_ga_2026']} | {r['impressoes_gsc']} | {r['tipo']} | {r['base']} | {r['url']} |\n")
    f.write("\n## Midia\n\n")
    f.write(f"- Arquivos referenciados encontrados exatamente: {found}\n")
    f.write(f"- Encontrados na versao original (sem sufixo de tamanho): {original}\n")
    f.write(f"- Faltantes no backup: {missing}\n")
    f.write("\nLista completa em `midia-referenciada.csv`.\n")

print("[ok] arquivos gerados em", OUT)
print(f"[ok] conteudo={len(content_rows)} P0={n_p0} P1={n_p1}")
print(f"[ok] arquivos={len(archive_rows)} P2={n_p2} P3={n_p3}")
print(f"[ok] midia={len(media_rows)} faltantes={missing}")
print(f"[ok] urls={len(urls)}")
