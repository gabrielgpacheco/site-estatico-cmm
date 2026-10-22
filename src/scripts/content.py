"""Renderização de conteúdo WordPress para HTML estático.

Converte blocos Gutenberg, shortcodes antigos, URLs de upload e incorporações
para uma saída limpa, sem scripts de terceiros e pronta para o tema novo.
"""
from __future__ import annotations

import html as htmlmod
import re
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

MESES = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]

WP_COMMENT_RX = re.compile(r"<!--.*?-->", re.S)
SCRIPT_RX = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.S | re.I)
SCRIPT_SELF_RX = re.compile(r"<script\b[^>]*/?>", re.I)
ADSENSE_INS_RX = re.compile(
    r"<ins\b[^>]*class\s*=\s*[\"'][^\"']*adsbygoogle[^\"']*[\"'][^>]*>.*?</ins\s*>",
    re.S | re.I,
)
ADSENSE_INS_SELF_RX = re.compile(
    r"<ins\b[^>]*class\s*=\s*[\"'][^\"']*adsbygoogle[^\"']*[\"'][^>]*/?>", re.I
)
LINK_RX = re.compile(r"<link\b[^>]*>", re.I)
META_RX = re.compile(r"<meta\b[^>]*>", re.I)

CAPTION_RX = re.compile(r"\[caption\b([^\]]*)\](.*?)\[/caption\]", re.S | re.I)
GALLERY_RX = re.compile(r"\[gallery\b([^\]]*)\]", re.I)
INFOBOX_RX = re.compile(r"\[infobox\b([^\]]*)\](.*?)\[/infobox\]", re.S | re.I)
BOX_RX = re.compile(r"\[box\b([^\]]*)\](.*?)\[/box\]", re.S | re.I)
YOUTUBE_RX = re.compile(r"\[youtube\b([^\]]*)\]", re.I)
EMBED_RX = re.compile(r"\[embed\b[^\]]*\](.*?)\[/embed\]", re.S | re.I)
BFABINDER_RX = re.compile(r"\[bfabinder\b[^\]]*\]", re.I)

IFRAME_RX = re.compile(r"<iframe\b([^>]*)>.*?</iframe\s*>", re.S | re.I)
IMG_RX = re.compile(r"<img\b([^>]*)>", re.I)
ANCHOR_RX = re.compile(
    r"<a\b([^>]*?)\bhref\s*=\s*([\"'])(.*?)\2([^>]*)>(.*?)</a\s*>", re.S | re.I
)
TABLE_RX = re.compile(r"(<table\b.*?</table\s*>)", re.S | re.I)
STYLE_ATTR_RX = re.compile(r"\sstyle\s*=\s*([\"'])(.*?)\1", re.S | re.I)
EVENT_ATTR_RX = re.compile(
    r"\s(?:on[a-z]+)\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+)", re.I
)
FONT_RX = re.compile(r"</?font\b[^>]*>", re.I)
EMPTY_P_RX = re.compile(r"<p>\s*(?:&nbsp;|<br\s*/?>|\s)*</p>", re.I)

SITE_UPLOAD_RX = re.compile(
    r"(?:https?:)?//(?:i0\.wp\.com/)?(?:www\.)?cinemaemuitomais\.com"
    r"/wp-content/uploads/([^\s\"'<>)]+)",
    re.I,
)
JETPACK_UPLOAD_RX = re.compile(
    r"(?:https?:)?//i0\.wp\.com/(?:www\.)?cinemaemuitomais\.com"
    r"/wp-content/uploads/([^\s\"'<>)]+)",
    re.I,
)
EXTERNAL_UPLOAD_RX = re.compile(
    r"(?:https?:)?//[^/\s\"'<>]+/wp-content/uploads/([^\s\"'<>)]+)", re.I
)
RELATIVE_UPLOAD_RX = re.compile(r"(?<![A-Za-z0-9_.-])/wp-content/uploads/([^\s\"'<>)]+)", re.I)
SITE_HOST_RX = re.compile(
    r"(?:https?:)?//(?:www\.)?cinemaemuitomais\.com(/[^\s\"'<>)]*)", re.I
)
YOUTUBE_ID_RX = re.compile(
    r"(?:youtube(?:-nocookie)?\.com/(?:embed/|watch\?[^#]*v=)|youtu\.be/)"
    r"([A-Za-z0-9_-]{11})",
    re.I,
)

STYLE_DROP = {
    "color", "background", "background-color", "font-family", "font-size",
    "line-height", "text-shadow", "letter-spacing",
}


def br_date(iso: str) -> str:
    from datetime import datetime

    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return ""
    return f"{dt.day} de {MESES[dt.month - 1]} de {dt.year}"


def iso_date(iso: str) -> str:
    return iso[:10]


def strip_tags(value: str) -> str:
    value = re.sub(r"<(script|style)\b.*?</\1\s*>", " ", value, flags=re.S | re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", htmlmod.unescape(value)).strip()


def truncate(value: str, limit: int = 180) -> str:
    value = strip_tags(value)
    if len(value) <= limit:
        return value
    cut = value[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:-")
    return cut + "…"


def parse_attrs(raw: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for m in re.finditer(r"([a-zA-Z0-9_-]+)\s*=\s*([\"'])(.*?)\2", raw, re.S):
        attrs[m.group(1).lower()] = m.group(3)
    for m in re.finditer(r"(?<![a-zA-Z0-9_-])([a-zA-Z0-9_-]+)(?=\s|$)", raw):
        attrs.setdefault(m.group(1).lower(), "")
    return attrs


class ContentRenderer:
    def __init__(self, site: dict, media: dict, media_base: str,
                 redirects: dict[str, str] | None = None,
                 gone: set[str] | None = None,
                 manifest: dict | None = None,
                 resolvable: set[str] | None = None,
                 fallbacks: dict[str, str] | None = None):
        self.site = site
        self.media = {str(k): v for k, v in media.items()}
        self.media_base = media_base.rstrip("/")
        self.redirects = redirects or {}
        self.gone = gone or set()
        self.manifest = manifest or {}
        self.resolvable = resolvable or set()
        self.fallbacks = fallbacks or {}
        self.manifest_by_stem: dict[str, dict] = {}
        for key, entry in self.manifest.items():
            self.manifest_by_stem.setdefault(self._stem_key(key), entry)

    # ------------------------------------------------------------------ mídia
    @staticmethod
    def _stem_key(file: str) -> str:
        rel = file.replace("\\", "/").lstrip("/")
        parent, _, name = rel.rpartition("/")
        stem = re.sub(r"-\d+x\d+$", "", Path(name).stem)
        stem = re.sub(r"-(?:scaled|rotated)$", "", stem, flags=re.I)
        return f"{parent}/{stem.casefold()}"

    def _manifest_entry(self, file: str) -> dict:
        rel = file.replace("\\", "/").lstrip("/")
        for prefix in ("wp-content/uploads/", "public_html/wp-content/uploads/"):
            if rel.startswith(prefix):
                rel = rel[len(prefix):]
                break
        candidates = [rel]
        original = re.sub(r"-\d+x\d+(?=\.[^./]+$)", "", rel)
        if original != rel:
            candidates.append(original)
        for candidate in candidates:
            entry = self.manifest.get(candidate)
            if entry:
                return entry
        return self.manifest_by_stem.get(self._stem_key(rel), {})

    def media_info(self, media_id, preferred: str = "medium_large") -> dict:
        item = self.media.get(str(media_id))
        if not item:
            return {}
        size = (item.get("sizes") or {}).get(preferred) or {}
        file = size.get("file") or item.get("file")
        if not file:
            return {}
        original = item.get("file") or ""
        directory = original.rsplit("/", 1)[0] if "/" in original else ""
        if directory and "/" not in file:
            file = f"{directory}/{file}"
        entry = self._manifest_entry(file)
        fallback = entry.get("fallback") or file
        webps = entry.get("webp") or {}
        target = {"thumbnail": 400, "medium": 800, "medium_large": 800,
                  "large": 1200, "full": 1600}.get(preferred, 800)
        selected = None
        if webps:
            selected = min(webps.items(), key=lambda pair: abs(int(pair[0]) - target))[1]
        srcset = ""
        if webps:
            srcset = ", ".join(
                f"{self.media_base}/{value['path']} {value['width']}w"
                for _, value in sorted(webps.items(), key=lambda pair: int(pair[0]))
            )
        return {
            "url": f"{self.media_base}/{fallback}",
            "webp": f"{self.media_base}/{selected['path']}" if selected else "",
            "srcset": srcset,
            "width": (selected or {}).get("width") or size.get("width") or item.get("width") or 0,
            "height": (selected or {}).get("height") or size.get("height") or item.get("height") or 0,
            "alt": item.get("alt") or item.get("caption") or "",
            "caption": item.get("caption") or "",
            "placeholder": bool(entry.get("placeholder")),
        }

    def media_url(self, media_id, preferred: str = "medium_large") -> str:
        return self.media_info(media_id, preferred).get("url", "")

    # ---------------------------------------------------------------- URLs
    def _lookup(self, table, path: str):
        candidates = (path, path.rstrip("/") + "/", path.rstrip("/"))
        for candidate in candidates:
            if candidate in table:
                return table[candidate]
        return None

    def _media_fallback(self, url: str) -> str:
        path = url.split("?", 1)[0]
        prefixes = (self.media_base + "/", "/wp-content/uploads/")
        for prefix in prefixes:
            if path.startswith(prefix):
                return self.fallbacks.get(path[len(prefix):], "")
        return ""

    def _fix_internal_links(self, value: str) -> str:
        def sub(m: re.Match) -> str:
            before, quote, url, after, inner = m.groups()
            if url.strip().lower() in ("about:blank", "#"):
                return inner
            fallback = self._media_fallback(url)
            if fallback:
                return f'<a{before}href="{fallback}"{after}>{inner}</a>'
            if re.match(r"^www\.[^/]+", url, re.I):
                return f'<a{before}href="https://{url}"{after}>{inner}</a>'
            path, _, fragment = url.partition("#")
            path = path.split("?", 1)[0]
            if not path.startswith("/"):
                return m.group(0)
            if path.startswith(("/wp-content/uploads/", "/assets/", "/pagefind/")):
                return m.group(0)
            target = self._lookup(self.redirects, path)
            if target:
                suffix = f"#{fragment}" if fragment else ""
                return f'<a{before}href="{target}{suffix}"{after}>{inner}</a>'
            if any(c in self.gone for c in (path, path.rstrip("/") + "/", path.rstrip("/"))):
                return inner
            normalized = path.rstrip("/") + "/"
            if self.resolvable and normalized in self.resolvable:
                suffix = f"#{fragment}" if fragment else ""
                if path != normalized:
                    return f'<a{before}href="{normalized}{suffix}"{after}>{inner}</a>'
                return m.group(0)
            if path in ("/", "/404.html"):
                return m.group(0)
            if Path(path).suffix:
                return m.group(0)
            return inner

        return ANCHOR_RX.sub(sub, value)

    def rewrite_urls(self, value: str) -> str:
        if not value:
            return value
        value = SITE_HOST_RX.sub(lambda m: m.group(1), value)
        value = self._fix_internal_links(value)
        value = JETPACK_UPLOAD_RX.sub(
            lambda m: f"{self.media_base}/{m.group(1).split('?')[0]}", value
        )
        value = SITE_UPLOAD_RX.sub(
            lambda m: f"{self.media_base}/{m.group(1).split('?')[0]}", value
        )
        value = EXTERNAL_UPLOAD_RX.sub(
            lambda m: f"{self.media_base}/{m.group(1).split('?')[0]}", value
        )
        value = RELATIVE_UPLOAD_RX.sub(
            lambda m: f"{self.media_base}/{m.group(1).split('?')[0]}", value
        )
        return value

    def rewrite_media_url(self, url: str) -> str:
        """Reescreve uma URL absoluta de upload/og:image para a base de mídia."""
        if not url:
            return ""
        return self.rewrite_urls(url)

    # -------------------------------------------------------------- shortcodes
    def _youtube_facade(self, video_id: str, title: str = "") -> str:
        label = htmlmod.escape(title or "Assistir vídeo no YouTube")
        return (
            f'<div class="video-facade" data-video="{htmlmod.escape(video_id)}" '
            f'data-title="{label}">'
            f'<button type="button" class="video-facade__btn" '
            f'aria-label="{label}">'
            f'<span class="video-facade__icon" aria-hidden="true"></span>'
            f'<span class="video-facade__label">Assistir no YouTube</span>'
            f"</button></div>"
        )

    def _link_embed(self, url: str, label: str = "Conteúdo externo") -> str:
        safe = htmlmod.escape(url, quote=True)
        return (
            f'<p class="embed-link"><a href="{safe}" rel="nofollow noopener" '
            f'target="_blank">{htmlmod.escape(label)}</a></p>'
        )

    def _caption(self, m: re.Match) -> str:
        attrs = parse_attrs(m.group(1))
        inner = m.group(2).strip()
        align = attrs.get("align", "alignnone")
        width = attrs.get("width", "")
        img_match = IMG_RX.search(inner)
        img = img_match.group(0) if img_match else ""
        text = inner.replace(img, "", 1) if img else inner
        text = strip_tags(text)
        style = f' style="max-width:{int(width)}px"' if width.isdigit() else ""
        cap = (
            f'<figcaption class="wp-caption-text">{htmlmod.escape(text)}</figcaption>'
            if text
            else ""
        )
        return (
            f'<figure class="wp-caption {htmlmod.escape(align)}"{style}>'
            f"{img}{cap}</figure>"
        )

    def _gallery(self, m: re.Match) -> str:
        attrs = parse_attrs(m.group(1))
        ids = [x.strip() for x in attrs.get("ids", "").split(",") if x.strip()]
        if not ids:
            return ""
        items = []
        for media_id in ids:
            info = self.media_info(media_id, "medium_large")
            if not info.get("url"):
                continue
            w = info["width"] or 768
            h = info["height"] or 512
            alt = htmlmod.escape(info["alt"], quote=True)
            items.append(
                f'<figure class="gallery-item"><img src="{info["url"]}" '
                f'alt="{alt}" width="{w}" height="{h}" loading="lazy" '
                f'decoding="async"></figure>'
            )
        if not items:
            return ""
        return f'<div class="gallery gallery-columns-3">{"".join(items)}</div>'

    def _callout(self, style: str, body: str, kind: str) -> str:
        tone = "info" if kind == "info" else "warning"
        if "success" in style:
            tone = "success"
        elif "danger" in style or "error" in style:
            tone = "danger"
        elif "block" in style or "note" in style:
            tone = "neutral"
        return f'<aside class="callout callout--{tone}">{body.strip()}</aside>'

    def _iframe(self, m: re.Match) -> str:
        attrs = parse_attrs(m.group(1))
        src = attrs.get("src", "").strip()
        if not src:
            return ""
        yt = YOUTUBE_ID_RX.search(src)
        if yt:
            return self._youtube_facade(yt.group(1))
        title = attrs.get("title", "").strip()
        return self._link_embed(src, title or "Ver conteúdo incorporado")

    def _shortcodes(self, value: str) -> str:
        value = CAPTION_RX.sub(self._caption, value)
        value = GALLERY_RX.sub(self._gallery, value)
        value = INFOBOX_RX.sub(
            lambda m: self._callout(
                parse_attrs(m.group(1)).get("style", ""), m.group(2), "info"
            ),
            value,
        )
        value = BOX_RX.sub(
            lambda m: self._callout(
                parse_attrs(m.group(1)).get("type", ""), m.group(2), "box"
            ),
            value,
        )

        def youtube_sub(m: re.Match) -> str:
            raw = m.group(1).strip()
            attrs = parse_attrs(raw)
            candidate = attrs.get("url") or attrs.get("id") or raw
            yt = YOUTUBE_ID_RX.search(candidate)
            if not yt and re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
                return self._youtube_facade(candidate)
            if yt:
                return self._youtube_facade(yt.group(1))
            return ""

        value = YOUTUBE_RX.sub(youtube_sub, value)

        def embed_sub(m: re.Match) -> str:
            url = m.group(1).strip()
            yt = YOUTUBE_ID_RX.search(url)
            if yt:
                return self._youtube_facade(yt.group(1))
            return self._link_embed(url)

        value = EMBED_RX.sub(embed_sub, value)
        value = BFABINDER_RX.sub("", value)
        return value

    # --------------------------------------------------------------- limpeza
    def _clean_style(self, m: re.Match) -> str:
        decls = []
        for part in m.group(2).split(";"):
            if ":" not in part:
                continue
            prop, val = part.split(":", 1)
            prop = prop.strip().lower()
            val = val.strip()
            if not val or prop in STYLE_DROP:
                continue
            if "expression(" in val.lower() or "url(" in val.lower():
                continue
            decls.append(f"{prop}: {val}")
        return f' style="{"; ".join(decls)}"' if decls else ""

    def _lazy_images(self, value: str) -> str:
        def sub(m: re.Match) -> str:
            attrs = m.group(1).rstrip()
            if attrs.endswith("/"):
                attrs = attrs[:-1].rstrip()
            src_match = re.search(r'\bsrc\s*=\s*(["\'])(.*?)\1', attrs, re.I | re.S)
            if src_match:
                src = src_match.group(2).strip()
                prefix = self.media_base + "/"
                rel = src.split(prefix, 1)[1] if prefix and src.startswith(prefix) else ""
                if not rel and "/wp-content/uploads/" in src:
                    rel = src.split("/wp-content/uploads/", 1)[1]
                entry = self._manifest_entry(rel) if rel else {}
                override = self.fallbacks.get(rel) if rel else None
                fallback = entry.get("fallback") or ""
                fallback_url = override or (f"{self.media_base}/{fallback}" if fallback and fallback != rel else "")
                if fallback_url:
                    attrs = re.sub(
                        r'(\bsrc\s*=\s*["\'])(.*?)(["\'])',
                        lambda match: f"{match.group(1)}{fallback_url}{match.group(3)}",
                        attrs,
                        count=1,
                        flags=re.I | re.S,
                    )
                    if override:
                        attrs = re.sub(r"\s(?:srcset|sizes)\s*=\s*([\"']).*?\1", '', attrs, flags=re.I | re.S)
                webps = entry.get("webp") or {}
                srcset_match = re.search(r"\bsrcset\s*=\s*([\"'])(.*?)\1", attrs, re.I | re.S)
                if srcset_match:
                    candidates = []
                    for part in srcset_match.group(2).split(","):
                        bits = part.strip().split()
                        if not bits:
                            continue
                        cand = bits[0]
                        if not re.match(r"^(?:https?:)?//", cand, re.I):
                            parsed_src = urlparse(src) if src else None
                            if parsed_src and parsed_src.scheme and parsed_src.netloc:
                                cand = urljoin(f"{parsed_src.scheme}://{parsed_src.netloc}/", cand)
                            elif src:
                                cand = urljoin(src, cand)
                        candidates.append(" ".join([cand] + bits[1:]))
                    attrs = attrs[:srcset_match.start()] + f'srcset="{", ".join(candidates)}"' + attrs[srcset_match.end():]
                if webps and not re.search(r"\bsrcset\s*=", attrs, re.I):
                    srcset = ", ".join(
                        f"{self.media_base}/{item['path']} {item['width']}w"
                        for _, item in sorted(webps.items(), key=lambda pair: int(pair[0]))
                    )
                    attrs += f' srcset="{srcset}" sizes="(max-width: 900px) 100vw, 800px"'
            if not re.search(r"\bloading\s*=", attrs, re.I):
                attrs += ' loading="lazy"'
            if not re.search(r"\bdecoding\s*=", attrs, re.I):
                attrs += ' decoding="async"'
            return f"<img{attrs}>"

        return IMG_RX.sub(sub, value)

    def _wrap_tables(self, value: str) -> str:
        if "<table" not in value.lower():
            return value
        return TABLE_RX.sub(lambda m: f'<div class="table-wrap">{m.group(1)}</div>', value)

    def _sanitize(self, value: str) -> str:
        value = SCRIPT_RX.sub("", value)
        value = SCRIPT_SELF_RX.sub("", value)
        value = ADSENSE_INS_RX.sub("", value)
        value = ADSENSE_INS_SELF_RX.sub("", value)
        value = LINK_RX.sub("", value)
        value = META_RX.sub("", value)
        value = FONT_RX.sub("", value)
        value = EVENT_ATTR_RX.sub("", value)
        value = re.sub(
            r"href\s*=\s*([\"'])\s*javascript:[^\"']*\1", 'href="#"', value, flags=re.I
        )
        value = STYLE_ATTR_RX.sub(self._clean_style, value)
        return value

    # ------------------------------------------------------------------ API
    def render(self, raw: str) -> str:
        if not raw:
            return ""
        value = raw.replace("\r\n", "\n")
        value = WP_COMMENT_RX.sub("", value)
        value = self._sanitize(value)
        value = re.sub(r"<h1(\b[^>]*)>(.*?)</h1>", r"<h2\1>\2</h2>", value, flags=re.I | re.S)
        value = self._shortcodes(value)
        value = self.rewrite_urls(value)
        value = IFRAME_RX.sub(self._iframe, value)
        value = self._lazy_images(value)
        value = self._wrap_tables(value)
        value = EMPTY_P_RX.sub("", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        return value.strip()

    def render_comment(self, raw: str) -> str:
        value = self.render(raw)
        value = re.sub(
            r'<a\b([^>]*)href="(https?://[^"]+)"',
            r'<a\1href="\2" rel="nofollow ugc noopener"',
            value,
            flags=re.I,
        )
        return value

    def ad_slot(self, ad_slot: str = "7431298507", label: str = "Publicidade") -> str:
        client = htmlmod.escape(self.site.get("adsense", ""), quote=True)
        return (
            f'<aside class="ad-slot" aria-label="{label}">'
            f'<span class="ad-slot__label">{label}</span>'
            f'<ins class="adsbygoogle" style="display:block" '
            f'data-ad-client="{client}" data-ad-slot="{ad_slot}" '
            f'data-ad-format="auto" data-full-width-responsive="true"></ins></aside>'
        )

    def insert_ad_after_paragraphs(self, content: str, count: int = 2) -> str:
        """Insere um espaço de anúncio após N parágrafos, se houver conteúdo."""
        if not content:
            return content
        idx = 0
        for _ in range(count):
            nxt = content.find("</p>", idx)
            if nxt == -1:
                return content + self.ad_slot()
            idx = nxt + 4
        return content[:idx] + self.ad_slot() + content[idx:]
