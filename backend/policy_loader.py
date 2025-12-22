from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List
from urllib.parse import urlparse
import json
import re

# ----------------------------
# Optional dependencies
# ----------------------------
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

try:
    from readability import Document  # pip install readability-lxml
    _READABILITY_OK = True
except Exception:
    _READABILITY_OK = False


# ----------------------------
# Public output structure
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
    """Decode bytes robustly. Returns (decoded_text, encoding_used)."""
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
    head = (body or "")[:900].lower()
    return "<!doctype html" in head or "<html" in head or "<body" in head or "<head" in head


def _github_blob_to_raw(url: str) -> str:
    """
    Convert GitHub blob URLs to raw URLs.
    Example:
      https://github.com/OpenTermsArchive/.../blob/main/X/Privacy%20Policy.md
    ->
      https://raw.githubusercontent.com/OpenTermsArchive/.../main/X/Privacy%20Policy.md
    """
    u = (url or "").strip()
    m = re.match(r"^https?://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.*)$", u)
    if not m:
        return u
    user, repo, branch, path = m.group(1), m.group(2), m.group(3), m.group(4)
    return f"https://raw.githubusercontent.com/{user}/{repo}/{branch}/{path}"


def html_to_text(html: str) -> Tuple[str, Dict[str, Any]]:
    """
    Extract readable text from HTML.
    Returns (text, extraction_meta).
    """
    meta: Dict[str, Any] = {"extraction": "none"}
    if not html:
        return "", meta

    # Best effort: readability-lxml
    if _READABILITY_OK:
        try:
            doc = Document(html)
            cleaned_html = doc.summary(html_partial=True)
            meta.update({"extraction": "readability", "title": doc.short_title()})

            if _BS4_OK:
                soup = BeautifulSoup(cleaned_html, "lxml")
                for tag in soup(["script", "style", "noscript", "svg"]):
                    tag.decompose()
                return normalize_text(soup.get_text("\n")), meta

            # fallback: strip tags
            text = re.sub(r"<[^>]+>", "\n", cleaned_html)
            return normalize_text(text), meta
        except Exception:
            pass

    # Next: BeautifulSoup only
    if _BS4_OK:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "svg"]):
            tag.decompose()
        meta.update({"extraction": "bs4"})
        return normalize_text(soup.get_text("\n")), meta

    # Last resort: regex strip
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "\n", text)
    meta.update({"extraction": "regex"})
    return normalize_text(text), meta


# ----------------------------
# Loaders: text / file / url
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

    looks_html = (
        ext in ("html", "htm")
        or "<html" in decoded[:1400].lower()
        or "<!doctype html" in decoded[:1400].lower()
    )

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
# OTA: targets + loader
# ----------------------------
def _project_root() -> Path:
    """
    backend/policy_loader.py -> project root is one level up from backend/
    """
    return Path(__file__).resolve().parents[1]


def _default_targets_path() -> Path:
    """
    Default location (your layout):
      <project_root>/sources/ota_targets.json
    """
    return _project_root() / "sources" / "ota_targets.json"


def load_ota_targets(targets_path: Optional[str | Path] = None) -> List[Dict[str, Any]]:
    p = Path(targets_path) if targets_path else _default_targets_path()
    if not p.exists():
        raise FileNotFoundError(f"ota_targets.json not found at: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("ota_targets.json must be a JSON list of target objects")
    return data


def parse_ota_selector(selector: str) -> Tuple[str, str]:
    """
    Accept:
      - "chatgpt:privacy_policy"
      - "chatgpt/privacy_policy"
    """
    s = (selector or "").strip()
    if not s:
        raise ValueError("OTA selector is empty")
    if ":" in s:
        a, b = s.split(":", 1)
    elif "/" in s:
        a, b = s.split("/", 1)
    else:
        raise ValueError("OTA selector must look like service_id:doc_type (e.g., chatgpt:privacy_policy)")
    return a.strip(), b.strip()


def find_ota_target(
    service_id: str,
    doc_type: str,
    targets_path: Optional[str | Path] = None,
) -> Dict[str, Any]:
    targets = load_ota_targets(targets_path)
    for t in targets:
        if t.get("service_id") == service_id and t.get("doc_type") == doc_type:
            return t
    raise KeyError(f"No OTA target found for service_id={service_id} doc_type={doc_type}")


def ota_target_raw_url(target: Dict[str, Any]) -> str:
    repo = target["repo"]
    branch = target.get("branch") or "main"
    path = target["path"]
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"


def load_from_ota_target(
    *,
    service_id: str,
    doc_type: str,
    targets_path: Optional[str | Path] = None,
    timeout: float = 25.0,
) -> LoadedPolicy:
    target = find_ota_target(service_id, doc_type, targets_path=targets_path)
    url = ota_target_raw_url(target)
    loaded = load_from_url(url, timeout=timeout)

    loaded.meta.update({
        "source_type": "ota",
        "service_id": service_id,
        "doc_type": doc_type,
        "target_name": target.get("name"),
        "repo": target.get("repo"),
        "branch": target.get("branch", "main"),
        "path": target.get("path"),
    })
    return loaded


# ----------------------------
# Convenience: load two versions (text/url/file)
# ----------------------------
def load_pair(
    *,
    old_text: Optional[str] = None,
    new_text: Optional[str] = None,
    old_url: Optional[str] = None,
    new_url: Optional[str] = None,
    old_file: Optional[Tuple[bytes, str]] = None,
    new_file: Optional[Tuple[bytes, str]] = None,
) -> Tuple[LoadedPolicy, LoadedPolicy]:
    """
    Exactly one source per side:
      - text OR url OR file
    (OTA is handled separately in api_main for clarity.)
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

    def pick(
        side: str,
        text: Optional[str],
        url: Optional[str],
        file_obj: Optional[Tuple[bytes, str]],
    ) -> LoadedPolicy:
        if _chosen_count(text, url, file_obj) != 1:
            raise ValueError(f"{side}: provide exactly one of text, url, or file.")

        if text is not None and text.strip() != "":
            return load_from_text(text, source=f"{side}_text")
        if url is not None and url.strip() != "":
            return load_from_url(url)
        if file_obj is not None:
            b, name = file_obj
            return load_from_file_bytes(b, name)

        raise ValueError(f"{side}: no valid input provided")

    old_loaded = pick("old", old_text, old_url, old_file)
    new_loaded = pick("new", new_text, new_url, new_file)
    return old_loaded, new_loaded
