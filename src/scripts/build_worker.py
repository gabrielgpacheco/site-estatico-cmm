import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "src" / "data" / "redirects.json"
OUT = ROOT / "deploy" / "cloudflare" / "worker.js"

def main():
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    rules = {}
    for rule in payload["rules"]:
        rules[rule["from"]] = rule.get("to") if rule["status"] == 301 else None

    query = {
        "post": {str(k): v for k, v in payload["post_id_map"].items()},
        "page": {str(k): v for k, v in payload["page_id_map"].items()},
        "attachment": {str(k): v for k, v in payload["attachment_id_map"].items()},
    }

    template = """const ORIGIN = "https://gabrielgpacheco.github.io";
const BASE = "https://www.cinemaemuitomais.com";
const RULES = __RULES__;
const POST_IDS = __POST_IDS__;
const PAGE_IDS = __PAGE_IDS__;
const ATTACHMENT_IDS = __ATTACHMENT_IDS__;

function redirect(location) {
  return new Response(null, {
    status: 301,
    headers: { Location: location },
  });
}

function gone() {
  return new Response("<!doctype html><html lang=\\"pt-BR\\"><meta charset=\\"utf-8\\"><title>Conteudo removido</title><h1>410 - Conteudo removido</h1>", {
    status: 410,
    headers: { "Content-Type": "text/html; charset=utf-8" },
  });
}

function target(path, search) {
  const url = new URL(path, BASE);
  if (!url.search) url.search = search;
  return url.toString();
}

export default {
  async fetch(request) {
    const url = new URL(request.url);

    if (url.hostname === "cinemaemuitomais.com") {
      return redirect("https://www.cinemaemuitomais.com" + url.pathname + url.search);
    }

    const params = url.searchParams;
    const postId = params.get("p");
    if (postId && POST_IDS[postId]) return redirect(target(POST_IDS[postId], ""));
    const pageId = params.get("page_id");
    if (pageId && PAGE_IDS[pageId]) return redirect(target(PAGE_IDS[pageId], ""));
    const attachmentId = params.get("attachment_id");
    if (attachmentId && ATTACHMENT_IDS[attachmentId]) return redirect(target(ATTACHMENT_IDS[attachmentId], ""));
    if (params.has("rest_route") || params.has("preview")) return gone();
    if (params.has("s")) {
      const q = params.get("s") || "";
      return redirect(BASE + "/busca/" + (q ? "?q=" + encodeURIComponent(q) : ""));
    }

    const rule = Object.prototype.hasOwnProperty.call(RULES, url.pathname)
      ? RULES[url.pathname]
      : null;

    if (rule === null && Object.prototype.hasOwnProperty.call(RULES, url.pathname)) return gone();
    if (typeof rule === "string") return redirect(target(rule, url.search));

    const origin = new URL(url.pathname + url.search, ORIGIN);
    return fetch(origin, {
      method: request.method,
      headers: request.headers,
      body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
      redirect: "manual",
    });
  },
};
"""
    replacements = {
        "__RULES__": json.dumps(rules, ensure_ascii=False, separators=(",", ":")),
        "__POST_IDS__": json.dumps(query["post"], ensure_ascii=False, separators=(",", ":")),
        "__PAGE_IDS__": json.dumps(query["page"], ensure_ascii=False, separators=(",", ":")),
        "__ATTACHMENT_IDS__": json.dumps(query["attachment"], ensure_ascii=False, separators=(",", ":")),
    }
    text = template
    for key, value in replacements.items():
        text = text.replace(key, value)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"worker: {len(rules)} regras, {len(query['post'])} posts, {len(query['page'])} paginas, {len(query['attachment'])} anexos")
    print(f"arquivo: {OUT} ({OUT.stat().st_size / 1024:.1f} KB)")

if __name__ == "__main__":
    main()
