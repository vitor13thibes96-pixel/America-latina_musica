#!/usr/bin/env python3
"""Find missing artist-card images through public APIs and update HTML src only."""
from __future__ import annotations
import argparse, csv, html, json, mimetypes, os, re, sys, time, unicodedata
from pathlib import Path
from urllib.parse import quote, urlparse
import requests
from bs4 import BeautifulSoup

UA = "AmericaLatinaMusicaImageHelper/1.0 (educational website; contact: repository owner)"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA})
MAX_BYTES = 8 * 1024 * 1024
COMMONS_API = "https://commons.wikimedia.org/w/api.php"


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return value[:90] or "artista"


def norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()).strip()


def clean_artist(img, soup):
    alt = (img.get("alt") or "").strip()
    # Common patterns: "Imagen de Artist", "Foto de Artist", "Artista: Artist".
    for pat in [r"^(?:imagen|foto|fotografia|retrato|imagem|photo|picture)\s+(?:de|do|da|of)\s+", r"^artista\s*:\s*"]:
        alt = re.sub(pat, "", alt, flags=re.I).strip()
    if alt and norm(alt) not in {"artista", "imagen", "imagem", "foto", "placeholder", "image"}:
        return alt
    # Fallback: card's headings/text, avoiding long descriptive strings.
    node = img
    for _ in range(4):
        node = node.parent if node else None
        if not node: break
        heading = node.find(re.compile(r"^h[1-6]$"))
        if heading and 2 <= len(heading.get_text(" ", strip=True)) <= 90:
            return heading.get_text(" ", strip=True)
    return ""


def get_json(url, params=None, headers=None):
    r = SESSION.get(url, params=params, headers=headers, timeout=25)
    r.raise_for_status()
    return r.json()


def commons_search(artist: str):
    # Search title + content. Return candidates with full image and license metadata.
    queries = [f'filetype:bitmap "{artist}"', artist]
    seen = set()
    for query in queries:
        try:
            data = get_json(COMMONS_API, {
                "action":"query", "format":"json", "generator":"search",
                "gsrsearch":query, "gsrnamespace":6, "gsrlimit":10,
                "prop":"imageinfo", "iiprop":"url|extmetadata", "iiurlwidth":1000
            })
        except Exception as e:
            print(f"Commons search failed for {artist}: {e}", file=sys.stderr)
            continue
        pages = (data.get("query") or {}).get("pages") or {}
        candidates = []
        for page in pages.values():
            title = page.get("title", "")
            if title in seen: continue
            seen.add(title)
            infos = page.get("imageinfo") or []
            if not infos: continue
            info = infos[0]
            meta = info.get("extmetadata") or {}
            title_n, artist_n = norm(title), norm(artist)
            # Exact name in filename is a minimum confidence gate.
            tokens = [t for t in artist_n.split() if len(t) > 2]
            hits = sum(1 for t in tokens if t in title_n)
            score = hits / max(len(tokens), 1)
            if artist_n and artist_n in title_n: score = 1.0
            if score < 0.6: continue
            mime = info.get("mime", "")
            if not mime.startswith("image/") or mime == "image/svg+xml": continue
            license_name = strip_html(meta.get("LicenseShortName", {}).get("value", "Unknown"))
            license_url = meta.get("LicenseUrl", {}).get("value", "")
            author = strip_html(meta.get("Artist", {}).get("value", "Unknown"))
            desc = strip_html(meta.get("ImageDescription", {}).get("value", ""))
            page_url = "https://commons.wikimedia.org/wiki/" + quote(title.replace(" ", "_"), safe="_:()")
            candidates.append({"score":score,"title":title,"url":info.get("thumburl") or info.get("url"),
                "mime":mime,"page":page_url,"author":author or "Unknown","license":license_name,
                "license_url":license_url,"description":desc,"source":"Wikimedia Commons"})
        if candidates:
            candidates.sort(key=lambda c:c["score"], reverse=True)
            return candidates
    return []


def strip_html(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(str(s or "")))).strip()


def flickr_search(artist: str):
    key = os.getenv("FLICKR_API_KEY", "").strip()
    if not key: return []
    try:
        data = get_json("https://www.flickr.com/services/rest/", {
            "method":"flickr.photos.search", "api_key":key, "text":artist,
            "license":"4,5,6,9,10", "content_type":1, "media":"photos",
            "sort":"relevance", "per_page":10, "format":"json", "nojsoncallback":1,
            "extras":"owner_name,license,url_o,url_l,url_c"
        })
        photos = (data.get("photos") or {}).get("photo") or []
        out=[]
        for p in photos:
            title=p.get("title", "")
            tokens=[t for t in norm(artist).split() if len(t)>2]
            hits=sum(1 for t in tokens if t in norm(title))
            score=hits/max(len(tokens),1)
            if score < 0.6: continue
            url=p.get("url_o") or p.get("url_l") or p.get("url_c")
            if not url: continue
            page=f"https://www.flickr.com/photos/{p.get('owner')}/{p.get('id')}"
            out.append({"score":score,"title":title,"url":url,"mime":"image/jpeg","page":page,
              "author":p.get("ownername", "Unknown"),"license":f"Flickr license ID {p.get('license','unknown')} (verify on photo page)",
              "license_url":"https://www.flickr.com/services/api/","description":"","source":"Flickr"})
        return sorted(out,key=lambda c:c["score"],reverse=True)
    except Exception as e:
        print(f"Flickr search failed for {artist}: {e}", file=sys.stderr)
        return []


def download(candidate, dest: Path):
    url=candidate["url"]
    if not url or urlparse(url).scheme != "https": return False
    with SESSION.get(url, timeout=30, stream=True) as r:
        r.raise_for_status()
        ctype=r.headers.get("Content-Type", "").split(";")[0].lower()
        if not ctype.startswith("image/") or ctype in {"image/svg+xml", "image/gif"}: return False
        data=bytearray()
        for chunk in r.iter_content(65536):
            data.extend(chunk)
            if len(data)>MAX_BYTES: return False
        if len(data)<4096: return False
        # Basic magic-byte validation to avoid HTML/error pages.
        b=bytes(data[:16])
        if not (b.startswith(b"\xff\xd8\xff") or b.startswith(b"\x89PNG\r\n\x1a\n") or b.startswith(b"RIFF") and b[8:12]==b"WEBP"):
            return False
        ext = ".jpg" if b.startswith(b"\xff\xd8\xff") else ".png" if b.startswith(b"\x89PNG") else ".webp"
        dest=dest.with_suffix(ext)
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_bytes(data)
        return dest


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root", default=".", help="Raiz do site")
    ap.add_argument("--replace-existing", action="store_true", help="Substitui também imagens que já existem")
    args=ap.parse_args()
    root=Path(args.root).resolve()
    imgroot=root/"img"
    imgroot.mkdir(exist_ok=True)
    attribution_path=imgroot/"attributions.csv"
    review_path=imgroot/"review-needed.csv"
    attrib=[]; review=[]; changed=0; skipped=0
    html_files=[p for p in root.rglob("*.html") if not any(part.startswith(".") for part in p.relative_to(root).parts) and "node_modules" not in p.parts]
    for path in html_files:
        try: original=path.read_text(encoding="utf-8")
        except UnicodeDecodeError: continue
        soup=BeautifulSoup(original,"html.parser")
        modified=False
        for img in soup.find_all("img"):
            artist=clean_artist(img,soup)
            if not artist:
                continue
            src=(img.get("src") or "").strip()
            existing=True
            if not src or src.startswith(("data:","http://","https://")):
                existing=False if not src or "placeholder" in src.lower() else True
            else:
                local=(path.parent/src).resolve()
                existing=local.exists() and local.is_file()
            if existing and not args.replace_existing:
                skipped+=1; continue
            candidates=commons_search(artist)
            # Prefer high-confidence Commons candidate; use Flickr only if no Commons match.
            if not candidates:
                candidates=flickr_search(artist)
            if not candidates:
                review.append([str(path.relative_to(root)),artist,src,"Nenhuma correspondência com confiança suficiente"])
                continue
            best=candidates[0]
            if best["score"] < 0.8:
                review.append([str(path.relative_to(root)),artist,src,f"Correspondência incerta: {best['title']} ({best['score']:.0%})"])
                continue
            filename=slugify(artist)+"-"+str(abs(hash(best["page"]))%100000)+".jpg"
            target=imgroot/filename
            try: downloaded=download(best,target)
            except Exception as e:
                review.append([str(path.relative_to(root)),artist,src,f"Falha no download: {e}"]); continue
            if not downloaded:
                review.append([str(path.relative_to(root)),artist,src,"Arquivo não passou na validação de imagem"]); continue
            rel=os.path.relpath(downloaded,path.parent).replace(os.sep,"/")
            img["src"]=rel
            if not img.get("alt"): img["alt"]=artist
            modified=True; changed+=1
            attrib.append([artist,str(downloaded.relative_to(root)),best["source"],best["title"],best["author"],best["license"],best["license_url"],best["page"]])
            time.sleep(0.4)
        if modified:
            path.write_text(str(soup),encoding="utf-8")
    with attribution_path.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.writer(f); w.writerow(["artista","arquivo","fonte","título do arquivo","autor","licença","URL da licença","página da imagem"]); w.writerows(attrib)
    with review_path.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.writer(f); w.writerow(["arquivo HTML","artista","src atual","motivo da revisão"]); w.writerows(review)
    print(f"HTMLs examinados: {len(html_files)} | imagens atualizadas: {changed} | imagens mantidas: {skipped} | para revisar: {len(review)}")
    print(f"Relatórios: {attribution_path} e {review_path}")

if __name__=="__main__": main()
