from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple
from urllib.parse import urlparse
import re

# Optional dependencies (URL + HTML extraction)
try:
    import requests
    _REQ_OK = True
except Exception:
    _REQ_OK = False

try:
    from bs4 import BeautifulSoup  # pip install beautifulsoup4
    _BS4_OK = True
except Exception:
    _BS4_OK = False

# Optional: readability-lxml for cleaner extraction on messy pages
try:
    from readability import Document  # pip install readability-lxml
    _READABILITY_OK = True
except Exception:
    _READABILITY_OK = False


# ----------------------------
# Output structure
# ----------------------------

@dataclass
class LoadedPolicy:
    text: str
    meta: Dict[str, Any]


# ----------------------------
# Normalisation helpers
# ----------------------------

_BOM = "\ufeff"

def normalize_text(text: str) -> str:
    """Standardise policy text for downstream NLP."""
    if text is None:
        return ""
    t = text.replace(_BOM, "")
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _guess_decode_bytes(raw: bytes) -> Tuple[str, str]:
    """
    Decode bytes robustly. Returns (decoded_text, encoding_used).
    """
    raw = raw or b""
    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc), enc
        except Exception:
            pass
    return raw.decode("utf-8", errors="ignore"), "utf-8(ignore)"


def sniff_content_type(headers: Dict[str, str]) -> str:
    ct = (headers.get("content-type") or headers.get("Content-Type") or "").lower()
    return ct.split(";")[0].strip()


def is_probably_html(content_type: str, body: str) -> bool:
    if "text/html" in (content_type or ""):
        return True
    head = (body or "")[:800].lower()
    return "<html" in head or "<body" in head or "<head" in head or "<!doctype html" in head


def _github_blob_to_raw(url: str) -> str:
    """
    Convert GitHub blob URLs to raw URLs.
    Useful for Open Terms Archive snapshots hosted on GitHub.
    """
    m = re.match(r"^https?://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.*)$", url.strip())
    if not m:
        return url
    user, repo, branch, path = m.group(1), m.group(2), m.group(3), m.group(4)
    return f"https://raw.githubusercontent.com/{user}/{repo}/{branch}/{path}"


def html_to_text(html: str) -> Tuple[str, Dict[str, Any]]:
    """
    Extract readable text from HTML.
    Returns (text, meta_extraction_info).
    """
    meta: Dict[str, Any] = {"extraction": "none"}

    if not html:
        return "", meta

    # Best effort: readability (if installed)
    if _READABILITY_OK:
        try:
            doc = Document(html)
            title = doc.short_title()
            cleaned_html = doc.summary(html_partial=True)
            meta.update({"extraction": "readability", "title": title})
            if _BS4_OK:
                soup = BeautifulSoup(cleaned_html, "lxml")
                text = soup.get_text("\n")
                return normalize_text(text), meta
            else:
                # fallback: strip tags from readability output
                text = re.sub(r"<[^>]+>", "\n", cleaned_html)
                return normalize_text(text), meta
        except Exception:
            pass

    # Next best: BeautifulSoup (if installed)
    if _BS4_OK:
        soup = BeautifulSoup(html, "html.parser")

        for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "svg"]):
            tag.decompose()

        text = soup.get_text("\n")
        meta.update({"extraction": "bs4"})
        return normalize_text(text), meta

    # Last resort: naive tag strip
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "\n", text)
    meta.update({"extraction": "regex"})
    return normalize_text(text), meta


# ----------------------------
# Loaders
# ----------------------------

def load_from_text(text: str, *, source: str = "pasted") -> LoadedPolicy:
    cleaned = normalize_text(text)
    return LoadedPolicy(
        text=cleaned,
        meta={
            "source_type": "text",
            "source": source,
            "length_chars": len(cleaned),
        },
    )


def load_from_file_bytes(file_bytes: bytes, filename: str = "upload.txt") -> LoadedPolicy:
    decoded, encoding = _guess_decode_bytes(file_bytes)
    ext = (filename.split(".")[-1] if "." in filename else "").lower()

    # If it looks like HTML, extract readable text
    looks_html = ext in ("html", "htm") or ("<html" in decoded[:1200].lower()) or ("<!doctype html" in decoded[:1200].lower())
    if looks_html:
        text, ex_meta = html_to_text(decoded)
    else:
        text, ex_meta = normalize_text(decoded), {"extraction": "plain"}

    return LoadedPolicy(
        text=text,
        meta={
            "source_type": "file",
            "filename": filename,
            "encoding": encoding,
            "length_chars": len(text),
            **ex_meta,
        },
    )


def load_from_url(url: str, *, timeout: float = 25.0) -> LoadedPolicy:
    if not _REQ_OK:
        raise ImportError("requests is not installed. Run: pip install requests")

    url = (url or "").strip()
    if not url:
        raise ValueError("URL is empty")

    url = _github_blob_to_raw(url)

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must start with http:// or https://")

    headers = {
        "User-Agent": "ConsentCompanion/1.0 (policy change analysis; academic project)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.7",
    }

    r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    r.raise_for_status()

    content_type = sniff_content_type(dict(r.headers))
    body = r.text or ""

    if ("text/plain" in content_type) or url.endswith((".txt", ".md")):
        text = normalize_text(body)
        ex_meta = {"extraction": "plain"}
    else:
        if is_probably_html(content_type, body):
            text, ex_meta = html_to_text(body)
        else:
            text, ex_meta = normalize_text(body), {"extraction": "plain"}

    return LoadedPolicy(
        text=text,
        meta={
            "source_type": "url",
            "url": url,
            "final_url": str(r.url),
            "status_code": r.status_code,
            "content_type": content_type,
            "length_chars": len(text),
            **ex_meta,
        },
    )


# ----------------------------
# Convenience: load two versions
# ----------------------------

def load_pair(
    *,
    old_text: Optional[str] = None,
    new_text: Optional[str] = None,
    old_url: Optional[str] = None,
    new_url: Optional[str] = None,
    old_file: Optional[Tuple[bytes, str]] = None,  # (bytes, filename)
    new_file: Optional[Tuple[bytes, str]] = None,
) -> Tuple[LoadedPolicy, LoadedPolicy]:
    """
    Exactly one source per side:
      - text OR url OR file
    """

    def _chosen_count(*vals) -> int:
        c = 0
        for v in vals:
            if v is None:
                continue
            if isinstance(v, str) and v.strip() == "":
                continue
            c += 1
        return c

    def pick(side: str, text: Optional[str], url: Optional[str], file_obj: Optional[Tuple[bytes, str]]) -> LoadedPolicy:
        if _chosen_count(text, url, file_obj) != 1:
            raise ValueError(f"{side}: provide exactly one of text, url, or file.")

        if text is not None and text.strip() != "":
            return load_from_text(text, source=f"{side}_text")
        if url is not None and url.strip() != "":
            return load_from_url(url)
        if file_obj is not None:
            b, name = file_obj
            return load_from_file_bytes(b, name)

        # should never happen
        return load_from_text("", source=f"{side}_empty")

    old_loaded = pick("old", old_text, old_url, old_file)
    new_loaded = pick("new", new_text, new_url, new_file)
    return old_loaded, new_loaded
