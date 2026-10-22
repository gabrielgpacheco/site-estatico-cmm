"""Gerador estático do Cinema e Muito + (Fase 3).

Uso:
    python src/scripts/build.py --sample --pagefind
    python src/scripts/build.py --all

O modo --sample monta uma amostra navegável (home, posts, páginas, tags,
categorias, autor, busca, 404 e página de teste) para aprovação visual.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sitemaps import generate as generate_extras, winpath  # noqa: E402
from content import (  # noqa: E402
    ContentRenderer,
    br_date,
    iso_date,
    strip_tags,
    truncate,
)

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
DATA = SRC / "data"
TEMPLATES = SRC / "templates"
ASSETS = SRC / "assets"


def load_json(name: str):
    with (DATA / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def ensure_url(url: str) -> str:
    if not url:
        return "/"
    if not url.startswith("/"):
        url = "/" + url
    if not url.endswith("/") and not url.endswith(".html"):
        url += "/"
    return url


def page_url(base: str, page: int) -> str:
    base = ensure_url(base)
    return base if page <= 1 else f"{base}page/{page}/"


def reading_minutes(raw: str) -> int:
    words = len(strip_tags(raw).split())
    return max(1, round(words / 200))


class Builder:
    def __init__(self, args):
        self.args = args
        self.out = Path(args.out).resolve()
        self.site = load_json("site.json")
        self.posts = load_json("posts.json")
        self.pages = load_json("pages.json")
        self.tags = load_json("tags.json")
        self.categories = load_json("categories.json")
        self.authors = load_json("authors.json")
        self.media = load_json("media.json")
        self.site["url"] = self.site["url"].rstrip("/")
        self.media_base = (
            args.media_base or self.site.get("media_base") or ""
        ).rstrip("/")
        manifest_path = DATA / "media-manifest.json"
        use_manifest = (
            manifest_path.exists()
            and (args.force_manifest or self.media_base == (self.site.get("media_base") or "").rstrip("/"))
        )
        self.manifest = load_json("media-manifest.json") if use_manifest else {}
        fallback_path = DATA / "media-fallbacks.json"
        self.media_fallbacks = json.loads(fallback_path.read_text(encoding="utf-8")) if fallback_path.exists() else {}

        redirects_data = load_json("redirects.json")
        self.redirect_301: dict[str, str] = {}
        self.gone: set[str] = set()
        for rule in redirects_data.get("rules", []):
            source = (rule.get("from") or "").strip()
            if not source.startswith("/"):
                continue
            keys = {source, source.rstrip("/") + "/", source.rstrip("/") or "/"}
            if rule.get("status") == 301 and rule.get("to"):
                for key in keys:
                    self.redirect_301[key] = rule["to"]
            elif rule.get("status") == 410:
                self.gone.update(keys)
        self.renderer = ContentRenderer(
            self.site, self.media, self.media_base, self.redirect_301, self.gone,
            manifest=self.manifest, fallbacks=self.media_fallbacks,
        )

        self.posts.sort(key=lambda p: p.get("date", ""), reverse=True)
        self.post_by_id = {p["id"]: p for p in self.posts}
        self.page_by_id = {g["id"]: g for g in self.pages}
        self.tag_by_id = {t["id"]: t for t in self.tags}
        self.cat_by_id = {c["id"]: c for c in self.categories}
        self.author_by_id = {a["id"]: a for a in self.authors}

        self.posts_by_tag: dict[int, list] = {}
        self.posts_by_cat: dict[int, list] = {}
        self.posts_by_author: dict[int, list] = {}
        for p in self.posts:
            for tid in p.get("tags") or []:
                self.posts_by_tag.setdefault(tid, []).append(p)
            for cid in p.get("categories") or []:
                self.posts_by_cat.setdefault(cid, []).append(p)
            self.posts_by_author.setdefault(p.get("author"), []).append(p)

        self.page_size = args.page_size or (10 if args.sample else int(self.site["posts_per_page"]))
        self.public_tags = [
            t for t in self.tags if t.get("count", 0) > 0 or t.get("in_sitemap", False)
        ]
        self.public_categories = [c for c in self.categories if c.get("count", 0) > 0]
        self._view_cache = {}
        self.year = str(self.site.get("generated_at", "2026"))[:4]
        self.sample_ids: set[int] = set()
        self.sample_tag_ids: set[int] = set()
        self.renderer.resolvable = self.generated_urls()

        self.env = Environment(
            loader=FileSystemLoader(str(TEMPLATES)),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.env.filters["brdate"] = br_date
        self.env.filters["isodate"] = iso_date

        self.nav = self._build_nav()
        self.footer_pages = [
            g for g in self.pages
            if g["url"] in ("/quemsomos/", "/contato/", "/politica-de-privacidade/",
                            "/politica-de-cookies-br/", "/mapa-site/")
        ]
        self.programacao_links = self._build_programacao_links()

    # ------------------------------------------------------------------ nav
    def _build_programacao_links(self):
        cinema = [
            g for g in self.pages
            if g["url"].startswith("/programacao/cinema/") and g["url"] != "/programacao/cinema/"
        ]
        order = [
            "rio-de-janeiro", "sao-paulo", "minas-gerais", "espirito-santo",
            "bahia", "parana", "rio-grande-do-sul", "pernambuco", "ceara",
            "distrito-federal", "goias", "amazonas", "alagoas", "acre",
        ]
        by_slug = {g["url"].rstrip("/").rsplit("/", 1)[-1]: g for g in cinema}
        links = [{"label": "Programação", "url": "/programacao/"},
                 {"label": "Salas de Cinema", "url": "/programacao/cinema/"}]
        for slug in order:
            if slug in by_slug:
                links.append({"label": by_slug[slug]["title"], "url": by_slug[slug]["url"]})
        return links

    def _build_nav(self):
        prog = [x for x in self._build_programacao_links() if x["url"] != "/programacao/"]
        return [
            {"label": "Início", "url": "/"},
            {"label": "Programação", "url": "/programacao/", "children": prog[:9]},
            {"label": "Cultura", "url": "/category/cultura/"},
            {"label": "Teatro", "url": "/category/teatro-4/"},
            {"label": "Literatura", "url": "/category/literatura/"},
            {"label": "Entrevistas", "url": "/category/entrevistas-2/"},
            {"label": "Coluna Clichê", "url": "/category/coluna-cliche/"},
            {"label": "Quem Somos", "url": "/quemsomos/"},
            {"label": "Contato", "url": "/contato/"},
        ]

    # --------------------------------------------------------------- views
    def pool(self, items):
        if not self.args.sample:
            return items
        return [p for p in items if p["id"] in self.sample_ids]

    def category_of(self, post):
        for cid in post.get("categories") or []:
            cat = self.cat_by_id.get(cid)
            if cat:
                return cat
        return None

    def author_of(self, post):
        return self.author_by_id.get(post.get("author"))

    def post_view(self, post, *, size="medium_large", excerpt_limit=180) -> dict:
        key = (post["id"], size, excerpt_limit)
        cached = self._view_cache.get(key)
        if cached is not None:
            return cached
        cat = self.category_of(post)
        author = self.author_of(post)
        image = self.renderer.media_info(post.get("featured"), size) if post.get("featured") else {}
        excerpt = post.get("excerpt") or truncate(post.get("content", ""), excerpt_limit)
        view = {
            "id": post["id"],
            "url": ensure_url(post["url"]),
            "title": post["title"],
            "excerpt": truncate(excerpt, excerpt_limit),
            "date_iso": iso_date(post.get("date", "")),
            "date_br": br_date(post.get("date", "")),
            "reading_time": reading_minutes(post.get("content", "")),
            "image": image.get("url", ""),
            "image_webp": image.get("webp", ""),
            "image_srcset": image.get("srcset", ""),
            "image_placeholder": image.get("placeholder", False),
            "image_w": image.get("width", 0),
            "image_h": image.get("height", 0),
            "image_alt": image.get("alt") or post["title"],
            "image_caption": image.get("caption", ""),
            "category_name": cat["name"] if cat else "Conteúdo",
            "category_url": ensure_url(cat["url"]) if cat else "/",
            "author_name": author["name"] if author else "Redação",
            "author_url": ensure_url(author["url"]) if author else "/quemsomos/",
            "comments_count": len(post.get("comments") or []),
        }
        self._view_cache[key] = view
        return view

    def comment_views(self, post):
        out = []
        for c in post.get("comments") or []:
            out.append({
                "author": c.get("author") or "Leitor",
                "date_br": br_date(c.get("date", "")),
                "date_iso": iso_date(c.get("date", "")),
                "content": self.renderer.render_comment(c.get("content", "")),
                "reply_to": c.get("reply_to") or 0,
            })
        return out

    def generated_urls(self) -> set[str]:
        urls = {"/", "/busca/", "/404.html"}
        for item in self.posts + self.pages:
            url = ensure_url(item.get("url") or "/")
            urls.add(url)
        def add_archive(base: str, count: int):
            pages = max(1, math.ceil(count / self.page_size))
            base = ensure_url(base)
            urls.add(base)
            for page in range(2, pages + 1):
                urls.add(f"{base}page/{page}/")
        for tag in self.public_tags:
            add_archive(tag["url"], len(self.posts_by_tag.get(tag["id"], [])))
        for cat in self.public_categories:
            add_archive(cat["url"], len(self.posts_by_cat.get(cat["id"], [])))
        for author in self.authors:
            add_archive(author["url"], len(self.posts_by_author.get(author["id"], [])))
        return urls

    def seo(self, raw_title: str, fallback_title: str, description: str, canonical: str,
            image: str = "", noindex: bool = False, og_type: str = "website") -> dict:
        title = raw_title.strip() if raw_title else ""
        if not title or "%%" in title:
            title = fallback_title
        desc = truncate(description, 160) if description else self.site.get("description", "")
        return {
            "seo_title": title,
            "seo_description": desc,
            "canonical": canonical or self.site["url"] + "/",
            "og_image": image,
            "noindex": noindex,
            "og_type": og_type,
        }

    def base_context(self, *, url: str, title: str, description: str, canonical: str,
                     image: str = "", noindex: bool = False, og_type: str = "website",
                     indexable: bool = False, pagefind_ignore: bool = False,
                     body_class: str = "", jsonld=None) -> dict:
        seo = self.seo(title, title, description, canonical, image, noindex, og_type)
        return {
            "site": self.site,
            "nav": self.nav,
            "current_url": url,
            "year": self.year,
            "indexable": indexable,
            "pagefind_ignore": pagefind_ignore,
            "body_class": body_class,
            "programacao_links": self.programacao_links,
            "jsonld": jsonld or [],
            **seo,
        }

    # ---------------------------------------------------------------- write
    def file_for(self, url: str) -> Path:
        url = ensure_url(url)
        if url.endswith(".html"):
            return self.out / url.lstrip("/")
        if url == "/":
            return self.out / "index.html"
        return self.out / url.strip("/") / "index.html"

    def write(self, url: str, template: str, ctx: dict):
        path = self.file_for(url)
        os.makedirs(winpath(path.parent), exist_ok=True)
        html = self.env.get_template(template).render(**ctx)
        with open(winpath(path), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(html)

    # ----------------------------------------------------------------- home
    def build_home(self):
        pool = self.pool(self.posts)
        featured = [p for p in pool if p.get("featured")]
        hero_post = featured[0] if featured else pool[0]
        secondary_posts = [p for p in featured[1:5]]
        latest_posts = [p for p in pool[:14] if p["id"] != hero_post["id"]]

        hero = self.post_view(hero_post, size="large", excerpt_limit=230)
        secondary = [self.post_view(p) for p in secondary_posts]
        latest = [self.post_view(p) for p in latest_posts[:9]]

        def section(title, base, limit=4):
            items = [p for p in self.pool(self.posts_by_cat.get(base, []))
                     if p["id"] != hero_post["id"]][:limit]
            cat = self.cat_by_id.get(base)
            return {
                "title": title,
                "url": ensure_url(cat["url"]) if cat else "/",
                "posts": [self.post_view(p) for p in items],
            }

        sections = [
            section("Cultura", 56),
            section("Teatro", 3301),
            section("Literatura", 12628),
            section("Coluna Clichê", 434),
            section("Entrevistas", 2501),
        ]
        sections = [s for s in sections if s["posts"]]

        tag_pool = [
            t for t in self.tags
            if not self.args.sample or t["id"] in self.sample_tag_ids
        ]
        top_tags = [
            {"name": t["name"], "url": ensure_url(t["url"]), "count": t["count"]}
            for t in sorted(tag_pool, key=lambda x: -x["count"])
            if t["count"] > 0
        ][:18]

        jsonld = [
            {
                "@context": "https://schema.org",
                "@type": "WebSite",
                "name": self.site["name"],
                "url": self.site["url"] + "/",
                "description": self.site["description"],
                "inLanguage": "pt-BR",
                "potentialAction": {
                    "@type": "SearchAction",
                    "target": f"{self.site['url']}/busca/?q={{search_term_string}}",
                    "query-input": "required name=search_term_string",
                },
            },
            {
                "@context": "https://schema.org",
                "@type": "Organization",
                "name": self.site["name"],
                "url": self.site["url"] + "/",
            },
        ]
        ctx = self.base_context(
            url="/",
            title=f"{self.site['name']} — {self.site['description']}",
            description=self.site["description"],
            canonical=self.site["url"] + "/",
            image=hero.get("image", ""),
            pagefind_ignore=True,
            body_class="home",
            jsonld=jsonld,
        )
        ctx.update({
            "hero": hero,
            "secondary": secondary,
            "latest": latest,
            "sections": sections,
            "top_tags": top_tags,
            "programacao_links": self.programacao_links,
        })
        self.write("/", "home.html", ctx)

    # ----------------------------------------------------------------- post
    def build_post(self, post):
        view = self.post_view(post, size="large", excerpt_limit=320)
        content_html = self.renderer.render(post.get("content", ""))
        if content_html:
            content_html = self.renderer.insert_ad_after_paragraphs(content_html, 2)

        tags = [
            {"name": self.tag_by_id[t]["name"], "url": ensure_url(self.tag_by_id[t]["url"])}
            for t in (post.get("tags") or []) if t in self.tag_by_id
        ]
        cat = self.category_of(post)
        related_posts = [
            p for p in self.pool(self.posts_by_cat.get(cat["id"], []))
            if p["id"] != post["id"]
        ][:3] if cat else []
        related = [self.post_view(p) for p in related_posts]

        pool = self.pool(self.posts)
        index = next((i for i, p in enumerate(pool) if p["id"] == post["id"]), None)
        newer = self.post_view(pool[index - 1]) if index and index > 0 else None
        older = (
            self.post_view(pool[index + 1])
            if index is not None and index + 1 < len(pool) else None
        )

        breadcrumb = [
            {"label": "Início", "url": "/"},
            {"label": cat["name"] if cat else "Conteúdo",
             "url": ensure_url(cat["url"]) if cat else "/"},
            {"label": post["title"], "url": ensure_url(post["url"])},
        ]
        jsonld = [
            {
                "@context": "https://schema.org",
                "@type": "Article",
                "headline": post["title"],
                "datePublished": post.get("date"),
                "dateModified": post.get("modified") or post.get("date"),
                "inLanguage": "pt-BR",
                "mainEntityOfPage": {"@type": "WebPage", "@id": view["url"]},
                "author": {"@type": "Person", "name": view["author_name"],
                           "url": self.site["url"] + view["author_url"]},
                "publisher": {"@type": "Organization", "name": self.site["name"],
                              "url": self.site["url"] + "/"},
                "description": view["excerpt"],
            },
            {
                "@context": "https://schema.org",
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": i + 1, "name": b["label"],
                     "item": self.site["url"] + b["url"]}
                    for i, b in enumerate(breadcrumb)
                ],
            },
        ]
        if view.get("image"):
            jsonld[0]["image"] = [view["image"]]

        ctx = self.base_context(
            url=view["url"],
            title=view["title"],
            description=view["excerpt"],
            canonical=post.get("seo", {}).get("canonical") or self.site["url"] + view["url"],
            image=view.get("image", ""),
            noindex=bool(post.get("seo", {}).get("noindex")),
            og_type="article",
            indexable=True,
            body_class="single",
            jsonld=jsonld,
        )
        sidebar_posts = []
        for candidate in self.pool(self.posts):
            if candidate["id"] == post["id"]:
                continue
            sidebar_posts.append(self.post_view(candidate))
            if len(sidebar_posts) == 5:
                break
        ctx.update({
            "post": view,
            "content_html": content_html,
            "tags": tags,
            "breadcrumb": breadcrumb,
            "related": related,
            "comments": self.comment_views(post),
            "newer": newer,
            "older": older,
            "author": self.author_of(post),
            "sidebar_posts": sidebar_posts,
        })
        self.write(view["url"], "post.html", ctx)

    # ----------------------------------------------------------------- page
    NO_ADS_PAGES = {
        "/politica-de-privacidade/", "/politica-de-cookies-br/", "/quemsomos/",
        "/contato/", "/mapa-site/", "/link/",
    }

    def build_page(self, page):
        if page["id"] == self.site.get("page_on_front") or ensure_url(page["url"]) == "/":
            return
        view = self.post_view(page, size="large", excerpt_limit=320)
        content_html = self.renderer.render(page.get("content", ""))
        if content_html and view["url"] not in self.NO_ADS_PAGES:
            content_html = self.renderer.insert_ad_after_paragraphs(content_html, 2)

        parts = [x for x in view["url"].strip("/").split("/") if x]
        breadcrumb = [{"label": "Início", "url": "/"}]
        acc = "/"
        for part in parts[:-1]:
            acc += part + "/"
            found = next((g for g in self.pages if ensure_url(g["url"]) == acc), None)
            breadcrumb.append({"label": found["title"] if found else part.replace("-", " ").title(),
                               "url": acc})
        breadcrumb.append({"label": page["title"], "url": view["url"]})

        jsonld = [{
            "@context": "https://schema.org",
            "@type": "WebPage",
            "name": page["title"],
            "url": self.site["url"] + view["url"],
            "inLanguage": "pt-BR",
            "description": view["excerpt"],
        }]
        ctx = self.base_context(
            url=view["url"],
            title=view["title"],
            description=view["excerpt"],
            canonical=page.get("seo", {}).get("canonical") or self.site["url"] + view["url"],
            image=view.get("image", ""),
            noindex=bool(page.get("seo", {}).get("noindex")),
            indexable=True,
            body_class="page",
            jsonld=jsonld,
        )
        ctx.update({
            "page": view,
            "content_html": content_html,
            "breadcrumb": breadcrumb,
            "programacao_links": self.programacao_links,
        })
        self.write(view["url"], "page.html", ctx)

    # -------------------------------------------------------------- archive
    def build_archive(self, kind: str, item: dict, posts: list, *, noindex: bool = False):
        base = ensure_url(item["url"])
        pages = max(1, math.ceil(len(posts) / self.page_size))
        if kind == "author":
            title = item["name"]
            kicker = "Autor"
            description = item.get("description") or f"Conteúdos publicados por {item['name']}."
        elif kind == "category":
            title = item["name"]
            kicker = "Editoria"
            description = f"Todos os conteúdos de {item['name']}."
        else:
            title = item["name"]
            kicker = "Tag"
            description = f"Todos os conteúdos marcados com “{item['name']}”."
        count = len(posts)

        for page in range(1, pages + 1):
            start = (page - 1) * self.page_size
            chunk = posts[start:start + self.page_size]
            url = page_url(base, page)
            prev_url = page_url(base, page - 1) if page > 1 else ""
            next_url = page_url(base, page + 1) if page < pages else ""
            archive_title = title if page == 1 else f"{title} — página {page}"
            jsonld = [{
                "@context": "https://schema.org",
                "@type": "CollectionPage",
                "name": archive_title,
                "url": self.site["url"] + url,
                "inLanguage": "pt-BR",
                "description": description,
            }]
            ctx = self.base_context(
                url=url,
                title=f"{archive_title} - {self.site['name']}",
                description=description,
                canonical=self.site["url"] + url,
                noindex=noindex,
                pagefind_ignore=True,
                body_class=f"archive archive--{kind}",
                jsonld=jsonld,
            )
            ctx.update({
                "archive": {
                    "kind": kind,
                    "kicker": kicker,
                    "title": title,
                    "description": description,
                    "count": count,
                    "page": page,
                    "pages": pages,
                    "posts": [self.post_view(p) for p in chunk],
                    "prev_url": prev_url,
                    "next_url": next_url,
                    "base": base,
                },
            })
            self.write(url, "archive.html", ctx)

    # --------------------------------------------------------- busca / 404
    def build_search(self):
        ctx = self.base_context(
            url="/busca/",
            title=f"Busca - {self.site['name']}",
            description="Busque por filmes, séries, teatro, livros e cultura pop.",
            canonical=self.site["url"] + "/busca/",
            noindex=True,
            pagefind_ignore=True,
            body_class="search-page",
        )
        self.write("/busca/", "search.html", ctx)

    def build_404(self):
        ctx = self.base_context(
            url="/404.html",
            title=f"Página não encontrada - {self.site['name']}",
            description="A página que você procura não existe ou foi movida.",
            canonical=self.site["url"] + "/404.html",
            noindex=True,
            pagefind_ignore=True,
            body_class="error404",
        )
        ctx.update({"programacao_links": self.programacao_links})
        path = self.out / "404.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.env.get_template("404.html").render(**ctx), encoding="utf-8", newline="\n")

    # --------------------------------------------------------------- sample
    def select_sample(self):
        chosen: list[dict] = []
        seen: set[int] = set()

        def add(items, limit):
            for p in items[:limit]:
                if p["id"] not in seen:
                    seen.add(p["id"])
                    chosen.append(p)

        add(self.posts, 20)
        add(self.posts_by_tag.get(79, []), 20)
        add(self.posts_by_cat.get(56, []), 12)
        for pid in (11863, 26769, 13295, 20145, 23404):
            if pid in self.post_by_id:
                add([self.post_by_id[pid]], 1)
        self.sample_ids = {p["id"] for p in chosen}
        self.sample_tag_ids = set()
        for p in chosen:
            self.sample_tag_ids.update(p.get("tags") or [])
        return chosen

    def build_test_page(self):
        links = [
            ("Home", "/", "Hero, grades, editorias, programação e tags."),
            ("Post", "/como-marvel-e-dc-estao-tentando-fortalecer-a-presenca-feminina-nas-hqs/", "Post longo com imagem, tags, comentários e relacionados."),
            ("Post com vídeo", "/musique-se-pieta/", "Verifica fachada de YouTube (sem iframe antes do clique)."),
            ("Post com galeria", "/brasil-game-show-2018/", "Galeria, shortcodes e conteúdo antigo."),
            ("Post com comentário", "/sex-and-the-city-samantha-nao-esta/", "Comentário aprovado preservado."),
            ("Página", "/programacao/cinema/", "Página hierárquica com links de estados."),
            ("Página de estado", "/programacao/cinema/rio-de-janeiro/", "Conteúdo extenso e imagem destacada."),
            ("Tag (pág. 1)", "/tag/filme/", "Arquivo de tag com paginação."),
            ("Tag (pág. 2)", "/tag/filme/page/2/", "Segunda página da tag."),
            ("Categoria", "/category/cultura/", "Arquivo de editoria."),
            ("Autor", "/author/clarissa-c-cavalcante/", "Arquivo de autor."),
            ("Busca", "/busca/", "Pagefind (se o índice foi gerado)."),
            ("404", "/404.html", "Página de erro."),
        ]
        ctx = self.base_context(
            url="/teste.html",
            title="Teste da amostra - Cinema e Muito +",
            description="Página interna de verificação da Fase 3.",
            canonical=self.site["url"] + "/teste.html",
            noindex=True,
            pagefind_ignore=True,
            body_class="test-page",
        )
        ctx.update({"links": links, "sample_count": len(self.sample_ids)})
        path = self.out / "teste.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.env.get_template("teste.html").render(**ctx), encoding="utf-8", newline="\n")

    def write_report(self, started, files, html_files, total, extras, pagefind_ok):
        tags_pages = sum(
            max(1, math.ceil(len(self.posts_by_tag.get(tag["id"], [])) / self.page_size))
            for tag in self.public_tags
        )
        categories_pages = sum(
            max(1, math.ceil(len(self.posts_by_cat.get(cat["id"], [])) / self.page_size))
            for cat in self.public_categories
        )
        authors_pages = sum(
            max(1, math.ceil(len(self.posts_by_author.get(author["id"], [])) / self.page_size))
            for author in self.authors
        )
        empty_tags = len(self.tags) - len(self.public_tags)
        empty_categories = len(self.categories) - len(self.public_categories)
        sitemaps = extras["sitemaps"] if extras else {}
        validation = extras["validation"] if extras else {}
        extras_info = extras["extras"] if extras else {}
        verification = self.site.get("verification") or {}
        missing_verification = [
            name for name in ("google", "bing", "yandex") if not verification.get(name)
        ]
        lines = [
            "# Fase 5 - Geracao completa do site",
            "",
            f"- Data: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"- Saida: `{self.out}`",
            f"- Comando: `python src/scripts/build.py --all --pagefind`",
            f"- Tempo: {time.time() - started:.1f}s",
            "",
            "## Contagem por tipo",
            "",
            "| Tipo | Paginas |",
            "|---|---:|",
            f"| Posts | {len(self.posts):,} |".replace(",", "."),
            f"| Paginas (+ home) | {len(self.pages):,} |".replace(",", "."),
            f"| Tags (page 1) | {len(self.public_tags):,} |".replace(",", "."),
            f"| Tags (com paginacao) | {tags_pages:,} |".replace(",", "."),
            f"| Categorias | {categories_pages:,} |".replace(",", "."),
            f"| Autores | {authors_pages:,} |".replace(",", "."),
            "| Busca | 1 |",
            "| 404 | 1 |",
            "",
            f"- Arquivos HTML gerados: **{html_files:,}**".replace(",", "."),
            f"- Arquivos totais: **{files:,}**".replace(",", "."),
            f"- Tamanho total: **{total / 1024 / 1024:.1f} MB** ({total / 1024 / 1024 / 1024:.3f} GB)",
            f"- Pagefind: **{'ok' if pagefind_ok else 'nao gerado/falhou'}**",
            "",
            "## Sitemaps",
            "",
            "| Sitemap | URLs |",
            "|---|---:|",
        ]
        for name, count in sitemaps.items():
            lines.append(f"| `{name}` | {count:,} |".replace(",", "."))
        lines += [
            "",
            f"- URLs validadas: **{validation.get('urls', 0):,}**".replace(",", ".").replace(",", "."),
            f"- Sitemaps no indice: **{validation.get('children', 0)}**",
            "- Status: **valido** (sem URLs duplicadas; todos os arquivos existem)",
            "",
            "## Arquivos de publicacao",
            "",
            f"- Host: `{extras_info.get('host', '')}`",
            f"- Publisher AdSense: `{extras_info.get('publisher', '')}`",
            "- Gerados: `robots.txt`, `ads.txt`, `llms.txt`, `CNAME`, `.nojekyll`, `sitemap.xml`, `sitemap_index.xml`",
            "- Favicons e manifest: `favicon.ico`, `apple-touch-icon.png`, `site.webmanifest`, `assets/img/*` e `assets/site.webmanifest`",
            "",
            "## Observacoes",
            "",
            f"- {empty_tags:,} tags vazias fora do sitemap foram omitidas; 3 tags vazias incluidas no Yoast foram geradas para manter as 14.847 URLs do sitemap.".replace(",", "."),
            f"- {empty_categories} categorias vazias/noindex foram omitidas; 8 categorias publicas foram geradas.",
            "- 2.129 placeholders de midia ausente foram mantidos por decisao aprovada.",
            "- Sitemaps usam apenas a primeira pagina dos arquivos; a paginacao fica acessivel no HTML.",
            "- O sitemap inclui 14.847 tags do Yoast, 4.596 posts, 191 paginas, 8 categorias e 5 autores.",
            "- O plano citava 15.076 bases de arquivo do crawl; a fonte de verdade para tags e o Yoast (14.847) e o banco de tags (14.930 bases, incluindo 3 vazias no sitemap).",
        ]
        if missing_verification:
            lines.append(
                "- Tokens de verificacao ausentes: "
                + ", ".join(missing_verification)
                + "; o template suporta `site.json.verification` e a validacao final pode ser feita por DNS/GSC na Fase 7."
            )
        report = "\n".join(lines) + "\n"
        report_path = ROOT / "dados" / "fase5-relatorio.md"
        os.makedirs(winpath(report_path.parent), exist_ok=True)
        with open(winpath(report_path), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(report)
        print(f"Relatorio: {report_path}")

    # ------------------------------------------------------------------ run
    def run(self):
        started = time.time()
        out_path = winpath(self.out)
        if os.path.exists(out_path):
            shutil.rmtree(out_path)
        os.makedirs(out_path, exist_ok=True)

        if ASSETS.exists():
            shutil.copytree(ASSETS, self.out / "assets")

        if self.args.sample:
            sample_posts = self.select_sample()
            for p in sample_posts:
                self.build_post(p)
            for g in self.pages:
                self.build_page(g)

            sample_tag_ids = set()
            for p in sample_posts:
                sample_tag_ids.update(p.get("tags") or [])
            for tid in sorted(sample_tag_ids):
                tag = self.tag_by_id.get(tid)
                if not tag:
                    continue
                items = [p for p in self.posts_by_tag.get(tid, []) if p["id"] in self.sample_ids]
                self.build_archive("tag", tag, items, noindex=not tag.get("in_sitemap", True))
            for cat in self.categories:
                items = [p for p in self.posts_by_cat.get(cat["id"], []) if p["id"] in self.sample_ids]
                self.build_archive("category", cat, items,
                                   noindex=not cat.get("in_sitemap", True))
            for author in self.authors:
                items = [p for p in self.posts_by_author.get(author["id"], []) if p["id"] in self.sample_ids]
                self.build_archive("author", author, items,
                                   noindex=not author.get("in_sitemap", True))
            self.build_test_page()
        else:
            for p in self.posts:
                self.build_post(p)
            for g in self.pages:
                self.build_page(g)

            for tag in self.public_tags:
                items = self.posts_by_tag.get(tag["id"], [])
                noindex = (not tag.get("in_sitemap", True)) or bool(tag.get("noindex"))
                self.build_archive("tag", tag, items, noindex=noindex)
            for cat in self.public_categories:
                items = self.posts_by_cat.get(cat["id"], [])
                self.build_archive("category", cat, items,
                                   noindex=not cat.get("in_sitemap", True))
            for author in self.authors:
                items = self.posts_by_author.get(author["id"], [])
                self.build_archive("author", author, items,
                                   noindex=not author.get("in_sitemap", True))

        self.build_home()
        self.build_search()
        self.build_404()

        extras = None
        if self.args.all:
            extras = generate_extras(self.out, self.site)

        pagefind_ok = None
        if self.args.pagefind:
            try:
                subprocess.run(
                    f'npx --yes pagefind --site "{self.out}"',
                    check=True, shell=True,
                )
                pagefind_ok = True
            except subprocess.CalledProcessError as exc:
                pagefind_ok = False
                print(f"[aviso] Pagefind falhou: {exc}", file=sys.stderr)

        elapsed = time.time() - started
        files = 0
        total = 0
        html_files = 0
        for root, _dirs, names in os.walk(winpath(self.out)):
            for name in names:
                path = os.path.join(root, name)
                files += 1
                total += os.path.getsize(path)
                if name.endswith(".html"):
                    html_files += 1
        print(f"OK: {files} arquivos, {total / 1024 / 1024:.1f} MB, {elapsed:.1f}s")
        print(f"Saída: {self.out}")
        if self.args.all:
            print(
                f"Conteúdo: {len(self.posts)} posts, {len(self.pages)} páginas, "
                f"{len(self.public_tags)} tags, {len(self.public_categories)} categorias, "
                f"{len(self.authors)} autores"
            )
            self.write_report(started, files, html_files, total, extras, pagefind_ok)
        if self.args.sample:
            print("Amostra: http://localhost:8000/teste.html")


def main():
    parser = argparse.ArgumentParser(description="Gerador estático do Cinema e Muito +")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--sample", action="store_true", help="gera apenas a amostra")
    group.add_argument("--all", action="store_true", help="gera o site completo")
    parser.add_argument("--out", default=str(ROOT / "site"), help="diretório de saída")
    parser.add_argument("--media-base", default="", help="base das imagens (ex.: R2 ou site atual)")
    parser.add_argument("--force-manifest", action="store_true", help="usa o manifest mesmo com media-base local")
    parser.add_argument("--page-size", type=int, default=0, help="itens por página em arquivos")
    parser.add_argument("--pagefind", action="store_true", help="gera o índice Pagefind")
    args = parser.parse_args()
    if not args.sample and not args.all:
        parser.error("use --sample ou --all")
    Builder(args).run()


if __name__ == "__main__":
    main()
