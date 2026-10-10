#!/usr/bin/env python3
"""Sync arr.club curated lists -> johntian.me Watching section.

Pulls 4 lists from Supabase (tags + company_tags + companies),
downloads logos, and writes watch-data.js consumed by index.html.
Run daily via cron; safe to re-run (only new logos are downloaded).
"""
import json, os, re, urllib.request, hashlib

SITE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_DIR = os.path.join(SITE_DIR, "watch", "list")
os.makedirs(LOGO_DIR, exist_ok=True)

def logo_path(slug, ext):
    """Content-hashed logo URL: changes only when the file changes (cache-safe)."""
    p = os.path.join(LOGO_DIR, slug + ext)
    h = hashlib.md5(open(p, "rb").read()).hexdigest()[:8]
    return "watch/list/%s%s?v=%s" % (slug, ext, h)

# tag slug -> (max companies shown, 0 = all)
LISTS = [
    ("rl-env-vendors", 8),
    ("frontier-post-training", 0),
    ("frontier-ai-data", 0),
    ("frontier-robotics-data", 0),
]

env = open(os.path.expanduser("~/workspace/arrclub-cf/repo/.env.local"), encoding="utf-8").read()
SB_URL = re.search(r'NEXT_PUBLIC_SUPABASE_URL="([^"]+)"', env).group(1)
SRK = re.search(r'SUPABASE_SERVICE_ROLE_KEY="([^"]+)"', env).group(1)

def sb(path):
    req = urllib.request.Request(SB_URL + path,
        headers={"apikey": SRK, "Authorization": "Bearer " + SRK})
    return json.load(urllib.request.urlopen(req, timeout=30))

def parse_arr(s):
    if not s: return 0
    m = re.match(r"\$?\s*([\d.]+)\s*([KMB])?", s.strip().upper())
    if not m: return 0
    return float(m.group(1)) * {"K": 1e3, "M": 1e6, "B": 1e9}.get(m.group(2) or "M", 1)

def download_logo(logo_url, slug):
    """Download company logo to watch/list/{slug}.*; return local path or ''."""
    # reuse an already-downloaded file (any extension), e.g. manually placed
    for e in (".png", ".svg", ".jpg", ".jpeg", ".webp"):
        p = os.path.join(LOGO_DIR, slug + e)
        if os.path.exists(p) and os.path.getsize(p) > 0:
            return logo_path(slug, e)
    if not logo_url:
        return ""
    if logo_url.startswith("/"):
        logo_url = "https://www.arr.club" + logo_url
    try:
        req = urllib.request.Request(logo_url, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=20).read()
        # sanity: content must look like an image (magic bytes or <svg)
        head = data[:64].lstrip()
        is_img = (head.startswith(b"<svg") or head.startswith(b"\x89PNG")
                  or head.startswith(b"\xff\xd8\xff") or head.startswith(b"RIFF"))
        if not is_img or len(data) < 100:
            return ""
        # strip query string before sniffing extension
        clean = logo_url.lower().split("?")[0]
        ext = ".png"
        if clean.endswith(".svg"): ext = ".svg"
        elif clean.endswith((".jpg", ".jpeg")): ext = ".jpg"
        elif clean.endswith(".webp"): ext = ".webp"
        dest = os.path.join(LOGO_DIR, slug + ext)
        open(dest, "wb").write(data)
        return logo_path(slug, ext)
    except Exception as e:
        print("  logo failed for %s: %s" % (slug, e))
        return ""

out = []
for tag_slug, limit in LISTS:
    tags = sb("/rest/v1/tags?slug=eq.%s&select=id,name,thesis" % tag_slug)
    if not tags:
        print("tag not found:", tag_slug); continue
    tag = tags[0]
    rows = sb("/rest/v1/company_tags?tag_id=eq.%s&select=company_id,sort_order" % tag["id"])
    total = len(rows)
    order = {r["company_id"]: (r.get("sort_order") or 0) for r in rows}
    companies = []
    for cid in order:
        cs = sb("/rest/v1/companies?id=eq.%s&select=id,name,slug,logo_url,current_arr" % cid)
        if cs:
            c = cs[0]; c["_oid"] = cid
            companies.append(c)
    if any(v > 0 for v in order.values()):
        companies.sort(key=lambda c: order.get(c["_oid"], 0))
    else:
        companies.sort(key=lambda c: (-parse_arr(c.get("current_arr") or ""), c["name"]))
    for c in companies:
        c.pop("_oid", None)
        c.pop("id", None)
    shown = companies[:limit] if limit else companies
    items = []
    for c in shown:
        cslug = c["slug"]
        logo = download_logo(c.get("logo_url") or "", cslug)
        items.append({"slug": cslug, "name": c["name"], "logo": logo,
                      "arr": (c.get("current_arr") or "").strip()})
    out.append({"slug": tag_slug, "name": tag["name"], "thesis": tag.get("thesis") or "",
                "total": total, "companies": items})
    print("%s: %d companies (%d shown)" % (tag["name"], total, len(items)))

js = "const WATCH_DATA = %s;\n" % json.dumps(out, ensure_ascii=False)
open(os.path.join(SITE_DIR, "watch-data.js"), "w", encoding="utf-8").write(js)
print("wrote watch-data.js")
