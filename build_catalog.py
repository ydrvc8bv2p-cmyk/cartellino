#!/usr/bin/env python3
"""Build Cartellino's catalog from the embedded/base dataset plus public product pages.

Design goals:
- keep the existing catalog as a reliable fallback;
- prefer official brand stores over retailers;
- do not re-host third-party images: only store their public image URLs and source pages;
- keep multiple image candidates so the app can fall back when one URL breaks;
- be polite: robots.txt, rate limiting, small per-source/page caps;
- tolerate failures: one blocked retailer must not break the build.

This is intentionally generic. It understands Shopify JSON endpoints and JSON-LD Product
markup, which covers many official brand stores and retailers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import requests
from bs4 import BeautifulSoup

try:
    from ddgs import DDGS  # optional discovery
except Exception:
    DDGS = None

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
UA = "CartellinoCatalogBot/1.0 (+personal wardrobe catalog; respectful public metadata fetcher)"
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": UA,
    "Accept-Language": "en-GB,en;q=0.9,it;q=0.8,fr;q=0.7",
})
ROBOTS: dict[str, urllib.robotparser.RobotFileParser] = {}
LAST_FETCH: dict[str, float] = {}


def clean(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def norm(s: str) -> str:
    s = clean(s).lower()
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s


def canon_brand(s: str) -> str:
    n = norm(s)
    aliases = {"berwick": "berwick1707", "berwick1707": "berwick1707", "moorer": "moorer"}
    return aliases.get(n, n)

def same_brand(a: str, b: str) -> bool:
    aa, bb = canon_brand(a), canon_brand(b)
    return bool(aa and bb and (aa == bb or aa in bb or bb in aa))


def uniq(seq: Iterable[str]) -> list[str]:
    seen = set(); out = []
    for x in seq:
        x = clean(x)
        if not x or x in seen:
            continue
        seen.add(x); out.append(x)
    return out


def absolute(base: str, href: str) -> str:
    return urllib.parse.urljoin(base, href or "")


def can_fetch(url: str) -> bool:
    p = urllib.parse.urlparse(url)
    root = f"{p.scheme}://{p.netloc}"
    if root not in ROBOTS:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(root + "/robots.txt")
        ok = False
        try:
            rp.read(); ok = True
        except Exception:
            ok = False
        rp._cartellino_loaded = ok
        ROBOTS[root] = rp
    rp = ROBOTS[root]
    if not getattr(rp, "_cartellino_loaded", False):
        return True
    try:
        return rp.can_fetch(UA, url)
    except Exception:
        return True


def get(url: str, timeout: int = 25) -> requests.Response | None:
    if not url.startswith(("http://", "https://")):
        return None
    if not can_fetch(url):
        print(f"SKIP robots: {url}")
        return None
    host = urllib.parse.urlparse(url).netloc
    wait = 0.8 - (time.time() - LAST_FETCH.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    try:
        r = SESSION.get(url, timeout=timeout, allow_redirects=True)
        LAST_FETCH[host] = time.time()
        if r.status_code >= 400:
            print(f"HTTP {r.status_code}: {url}")
            return None
        return r
    except requests.RequestException as e:
        print(f"ERR {url}: {e}")
        return None


def first_price(offers: Any) -> tuple[float | int, str]:
    if isinstance(offers, list):
        for x in offers:
            p, c = first_price(x)
            if p:
                return p, c
        return 0, ""
    if not isinstance(offers, dict):
        return 0, ""
    price = offers.get("price") or offers.get("lowPrice") or offers.get("highPrice") or 0
    cur = clean(offers.get("priceCurrency"))
    try:
        return float(str(price).replace(",", ".")), cur
    except Exception:
        return 0, cur


def image_list(v: Any, base: str = "") -> list[str]:
    vals: list[str] = []
    if isinstance(v, str):
        vals = [v]
    elif isinstance(v, list):
        for x in v:
            if isinstance(x, str): vals.append(x)
            elif isinstance(x, dict): vals.append(x.get("url") or x.get("contentUrl") or "")
    elif isinstance(v, dict):
        vals = [v.get("url") or v.get("contentUrl") or ""]
    return uniq(absolute(base, x) for x in vals if x)


def recursive_products(node: Any) -> Iterable[dict[str, Any]]:
    if isinstance(node, dict):
        typ = node.get("@type")
        types = typ if isinstance(typ, list) else [typ]
        if any(str(t).lower() == "product" for t in types if t):
            yield node
        for v in node.values():
            yield from recursive_products(v)
    elif isinstance(node, list):
        for x in node:
            yield from recursive_products(x)


def parse_jsonld(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for s in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        txt = s.string or s.get_text(" ", strip=True)
        if not txt: continue
        try:
            obj = json.loads(txt)
        except Exception:
            continue
        out.extend(recursive_products(obj))
    return out


def infer_style(name: str, category: str = "", desc: str = "") -> str:
    t = f"{name} {category} {desc}".lower()
    rules = [
        (r"tassel|nappa", "Tassel loafer"), (r"penny|loafer|mocass", "Loafer"),
        (r"oxford|richelieu", "Oxford"), (r"derby|blucher", "Derby"),
        (r"double monk|doppia fibbia", "Double monk"), (r"monk", "Monk strap"),
        (r"chelsea", "Chelsea boot"), (r"chukka|desert", "Chukka"),
        (r"boot|stival", "Boot"), (r"sneaker|trainer", "Sneaker"),
        (r"polo", "Polo"), (r"t-?shirt|tee", "T-shirt"),
        (r"overshirt", "Overshirt"), (r"shirt|camicia", "Shirt"),
        (r"trouser|pantal|chino", "Trousers"), (r"blazer|giacca|jacket", "Jacket"),
        (r"cardigan", "Cardigan"), (r"sweater|knit|maglia|pullover", "Knitwear"),
        (r"belt|cintura", "Belt"), (r"wallet|portafogl", "Wallet"), (r"backpack|zaino|messenger|duffle|bag|borsa", "Bag"), (r"card.?holder|portacarte", "Card holder"), (r"key.?ring|keycase|portachiavi", "Key holder"), (r"pouch|pochette", "Pouch"), (r"coat|cappotto|outerwear", "Outerwear"), (r"short|bermuda", "Shorts"),
    ]
    for pat, label in rules:
        if re.search(pat, t): return label
    return clean(category) or "Altro"


def product_from_ld(node: dict[str, Any], page_url: str, target_brand: str, source_name: str, rank: int) -> dict[str, Any] | None:
    brand = node.get("brand")
    if isinstance(brand, dict): brand = brand.get("name")
    brand = clean(brand) or target_brand
    if target_brand and brand and not same_brand(brand, target_brand):
        return None
    name = clean(node.get("name"))
    if not name: return None
    # Strip a leading brand from display model, but keep full names if useful.
    model = re.sub(r"^" + re.escape(brand) + r"\s*[-–—:]?\s*", "", name, flags=re.I).strip() or name
    desc = clean(node.get("description"))
    category = clean(node.get("category"))
    material = clean(node.get("material"))
    color = clean(node.get("color"))
    images = image_list(node.get("image"), page_url)
    price, cur = first_price(node.get("offers"))
    sku = clean(node.get("sku") or node.get("mpn") or node.get("productID"))
    return {
        "k": "crawl|" + hashlib.sha1((brand+"|"+model+"|"+color+"|"+page_url).encode()).hexdigest()[:16],
        "brand": brand, "model": model, "color": color, "style": infer_style(model, category, desc),
        "last": "", "material": material, "sole": "", "price": price, "cur": cur or "EUR",
        "img": images[0] if images else "", "images": images, "url": page_url, "sku": sku,
        "sources": [{"name": source_name, "url": page_url}], "source_rank": rank,
    }


def parse_product_page(url: str, target_brand: str, source_name: str, rank: int) -> list[dict[str, Any]]:
    r = get(url)
    if not r: return []
    html = r.text
    out = []
    for node in parse_jsonld(html):
        item = product_from_ld(node, r.url, target_brand, source_name, rank)
        if item: out.append(item)
    if out:
        return out
    # Fallback to OpenGraph + title. Good enough to recover a photo candidate even if JSON-LD is absent.
    soup = BeautifulSoup(html, "html.parser")
    title = clean((soup.find("meta", property="og:title") or {}).get("content") if soup.find("meta", property="og:title") else "")
    image = clean((soup.find("meta", property="og:image") or {}).get("content") if soup.find("meta", property="og:image") else "")
    if target_brand and title and target_brand.lower() in title.lower():
        model = re.sub(re.escape(target_brand), "", title, flags=re.I).strip(" -|–—")
        return [{
            "k": "crawl|" + hashlib.sha1((target_brand+"|"+model+"|"+r.url).encode()).hexdigest()[:16],
            "brand": target_brand, "model": model, "color": "", "style": infer_style(model), "last": "", "material": "", "sole": "",
            "price": 0, "cur": "EUR", "img": image, "images": [image] if image else [], "url": r.url,
            "sources": [{"name": source_name, "url": r.url}], "source_rank": rank,
        }]
    return []


def product_links(html: str, base: str, target_brand: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    brand_norm = norm(target_brand)
    patterns = ("/products/", "item-", "/item", "/product/", "/p/", "/shopping/")
    for a in soup.find_all("a", href=True):
        href = absolute(base, a.get("href"))
        txt = clean(a.get_text(" ", strip=True))
        p = urllib.parse.urlparse(href).path.lower()
        if not any(x in p for x in patterns):
            continue
        # For multi-brand pages, prefer links/text that mention the target brand, but don't over-filter official sites.
        if brand_norm and brand_norm not in norm(txt + " " + href) and urllib.parse.urlparse(base).netloc not in urllib.parse.urlparse(href).netloc:
            continue
        out.append(href.split("#")[0])
    return uniq(out)


def shopify_collection_json(url: str) -> str:
    p = urllib.parse.urlparse(url)
    path = p.path.rstrip("/")
    if "/collections/" in path:
        return f"{p.scheme}://{p.netloc}{path}/products.json"
    return f"{p.scheme}://{p.netloc}/products.json"


def crawl_shopify(source: dict[str, Any]) -> list[dict[str, Any]]:
    brand = clean(source.get("brand")); name = source["name"]; rank = int(source.get("priority", 90)); maxp = int(source.get("max_products", 350))
    endpoint = shopify_collection_json(source["url"])
    out=[]
    for page in range(1, 8):
        sep = "&" if "?" in endpoint else "?"
        r = get(endpoint + f"{sep}limit=250&page={page}")
        if not r: break
        try: data = r.json()
        except Exception: break
        products = data.get("products") or []
        if not products: break
        for p in products:
            vendor = clean(p.get("vendor"))
            if brand and vendor and not same_brand(vendor, brand):
                # Multi-brand official stores (e.g. Slowear) may use vendor labels.
                continue
            title = clean(p.get("title")); handle = clean(p.get("handle"))
            if not title: continue
            images = uniq(i.get("src") for i in (p.get("images") or []) if isinstance(i, dict))
            variants = p.get("variants") or []
            price = 0
            if variants:
                try: price = float(variants[0].get("price") or 0)
                except Exception: pass
            tags = p.get("tags") or []
            if isinstance(tags, str): tags=[tags]
            category = clean(p.get("product_type"))
            body = BeautifulSoup(p.get("body_html") or "", "html.parser").get_text(" ", strip=True)
            page_url = urllib.parse.urljoin(source["url"], "/products/"+handle) if handle else source["url"]
            out.append({
                "k":"shopify|"+hashlib.sha1((brand+"|"+handle).encode()).hexdigest()[:16], "brand": brand or vendor,
                "model": title, "color":"", "style":infer_style(title,category,body), "last":"", "material":"", "sole":"",
                "price":price, "cur":"EUR", "img":images[0] if images else "", "images":images, "url":page_url,
                "sku":clean(variants[0].get("sku") if variants else ""), "sources":[{"name":name,"url":page_url}], "source_rank":rank,
            })
            if len(out)>=maxp: return out
        if len(products)<250: break
    return out


def crawl_listing(source: dict[str, Any]) -> list[dict[str, Any]]:
    brand = clean(source.get("brand")); brands = source.get("brands") or ([brand] if brand else [])
    name=source["name"]; rank=int(source.get("priority",70)); maxp=int(source.get("max_products",100))
    r=get(source["url"])
    if not r: return []
    out=[]
    # First harvest any JSON-LD products already present in the listing.
    for b in brands or [""]:
        for node in parse_jsonld(r.text):
            item=product_from_ld(node,r.url,b,name,rank)
            if item: out.append(item)
    # Then follow product links; cap aggressively.
    links=product_links(r.text,r.url,brand)
    for u in links[:maxp]:
        target_brand=brand
        if not target_brand and brands:
            # Guess brand from link/text later; parse against each configured brand until one matches.
            found=[]
            for b in brands:
                found=parse_product_page(u,b,name,rank)
                if found: break
            out.extend(found)
        else:
            out.extend(parse_product_page(u,target_brand,name,rank))
        if len(out)>=maxp: break
    return out[:maxp]


def discover_for_brand(brand: str, discovery: dict[str, Any]) -> list[dict[str, Any]]:
    if not discovery.get("enabled") or DDGS is None:
        return []
    out=[]; seen=set()
    maxres=int(discovery.get("max_search_results_per_domain",2)); maxpages=int(discovery.get("max_product_pages_per_brand",15))
    domains=discovery.get("domains") or []
    try:
        ddgs=DDGS()
        for domain in domains:
            q=f'site:{domain} "{brand}" men product'
            try: results=list(ddgs.text(q,max_results=maxres))
            except Exception as e:
                print(f"DDGS {brand} {domain}: {e}"); continue
            for rr in results:
                u=clean(rr.get("href"))
                if not u or u in seen: continue
                seen.add(u)
                source_name=f"discovery:{domain}"
                # If result itself is a product page, parse it; otherwise follow a few product links.
                fetched=parse_product_page(u,brand,source_name,55)
                if fetched:
                    out.extend(fetched)
                else:
                    r=get(u)
                    if r:
                        for link in product_links(r.text,r.url,brand)[:4]:
                            out.extend(parse_product_page(link,brand,source_name,55))
                if len(out)>=maxpages: return out[:maxpages]
    except Exception as e:
        print(f"Discovery failed for {brand}: {e}")
    return out[:maxpages]


def item_key(x: dict[str, Any]) -> str:
    brand=norm(x.get("brand","")); model=norm(x.get("model","")); color=norm(x.get("color",""))
    # SKU is stronger when present and stable.
    sku=norm(x.get("sku",""))
    return f"{brand}|{sku or model}|{color}"


def merge_item(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    # Prefer the higher ranked record for textual fields, but merge image/source candidates from both.
    if int(b.get("source_rank",0)) > int(a.get("source_rank",0)):
        a,b=b,a
    out=dict(a)
    out["images"]=uniq((a.get("images") or ([a.get("img")] if a.get("img") else [])) + (b.get("images") or ([b.get("img")] if b.get("img") else [])))[:12]
    out["img"]=out["images"][0] if out["images"] else clean(a.get("img") or b.get("img"))
    src=[]; seen=set()
    for s in (a.get("sources") or [])+(b.get("sources") or []):
        if not isinstance(s,dict): continue
        k=clean(s.get("url"))
        if k in seen: continue
        seen.add(k); src.append(s)
    out["sources"]=src[:8]
    for field in ("color","style","last","material","sole","url","sku","cur"):
        if not clean(out.get(field)) and clean(b.get(field)):
            out[field]=b[field]
    if not out.get("price") and b.get("price"):
        out["price"]=b["price"]
    return out


def build(discover: bool = True) -> list[dict[str, Any]]:
    base=json.loads((DATA/"catalog.base.json").read_text())
    cfg=json.loads((DATA/"sources.json").read_text())
    merged={item_key(x):x for x in base}
    for i,s in enumerate(cfg["sources"],1):
        print(f"[{i}/{len(cfg['sources'])}] {s['name']}")
        try:
            if s["kind"] in ("shopify_all","shopify_collection"):
                found=crawl_shopify(s)
            else:
                found=crawl_listing(s)
        except Exception as e:
            print(f"SOURCE FAIL {s['name']}: {e}")
            found=[]
        print("  +",len(found))
        for x in found:
            k=item_key(x)
            merged[k]=merge_item(merged[k],x) if k in merged else x
    if discover:
        counts={}
        for x in merged.values():
            b=clean(x.get("brand",""))
            if b: counts[b]=counts.get(b,0)+1
        registry=cfg.get("brand_registry") or sorted(counts)
        target=int(cfg.get("min_products_per_brand",20))
        brands=sorted(registry,key=lambda b:(counts.get(b,0),b.lower()))
        for brand in brands:
            if counts.get(brand,0) >= target:
                continue
            found=discover_for_brand(brand,cfg.get("discovery") or {})
            if found: print(f"DISCOVERY {brand}: +{len(found)} (had {counts.get(brand,0)})")
            for x in found:
                k=item_key(x); merged[k]=merge_item(merged[k],x) if k in merged else x
            counts[brand]=sum(1 for x in merged.values() if same_brand(clean(x.get("brand","")),brand))
    out=list(merged.values())
    out.sort(key=lambda x:(clean(x.get("brand")).lower(),clean(x.get("model")).lower(),clean(x.get("color")).lower()))
    return out


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--no-discovery",action="store_true",help="skip DuckDuckGo retailer discovery")
    ap.add_argument("--out",default=str(ROOT/"catalog.generated.json"))
    args=ap.parse_args()
    out=build(discover=not args.no_discovery)
    Path(args.out).write_text(json.dumps(out,ensure_ascii=False,separators=(",",":")))
    cfg=json.loads((DATA/"sources.json").read_text())
    counts={}
    for x in out:
        b=clean(x.get("brand",""))
        if b: counts[b]=counts.get(b,0)+1
    target=int(cfg.get("min_products_per_brand",20))
    stats={
        "version":"V8.1",
        "products":len(out),
        "brands":len(counts),
        "registry_brands":len(cfg.get("brand_registry") or []),
        "brands_under_20":{k:v for k,v in sorted(counts.items(),key=lambda kv:kv[1]) if v<target},
        "target_min_per_brand_after_online_refresh":target,
    }
    (DATA/"catalog-stats.json").write_text(json.dumps(stats,ensure_ascii=False,indent=2))
    print(f"WROTE {len(out)} products / {len(counts)} brands -> {args.out}")

if __name__=="__main__": main()
