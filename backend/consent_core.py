from __future__ import annotations

from typing import List, Dict, Optional
import re

# Optional import: only needed for semantic mode
try:
    from sentence_transformers import SentenceTransformer, util
    import torch

    _SEMANTIC_AVAILABLE = True
except ImportError:
    _SEMANTIC_AVAILABLE = False

# Optional import: spaCy for sentence segmentation
try:
    import spacy

    _SPACY_AVAILABLE = True
except ImportError:
    _SPACY_AVAILABLE = False

_nlp = None


def get_spacy_nlp():
    """Lazy-load spaCy English model if available."""
    global _nlp
    if not _SPACY_AVAILABLE:
        raise ImportError(
            "spaCy is not installed. Install via `pip install spacy` and "
            "download model with `python -m spacy download en_core_web_sm`."
        )
    if _nlp is None:
        _nlp = spacy.load("en_core_web_sm")
    return _nlp


def split_into_sentences(text: str) -> List[str]:
    """Split policy text into sentences using spaCy if available, else line-based."""
    if _SPACY_AVAILABLE:
        nlp = get_spacy_nlp()
        doc = nlp(text or "")
        return [sent.text.strip() for sent in doc.sents if sent.text.strip()]
    return [s.strip() for s in (text or "").splitlines() if s.strip()]


def clean_line(s: str) -> str:
    """Remove BOM and extra whitespace."""
    return (s or "").replace("\ufeff", "").strip()


# ---------------------------------------------------------------------
# Helpers for semantic trivial-change detection
# ---------------------------------------------------------------------


def _normalize_trivial(text: str) -> str:
    """Normalise text for trivial-change detection / signatures."""
    t = (text or "").lower()
    t = re.sub(r"[\"'`’“”]", "", t)
    t = re.sub(r"[.,;:!?()\-\[\]]", " ", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _is_trivial_change(old: str, new: str, similarity: float) -> bool:
    """True if change is trivial (formatting / punctuation / tiny wording)."""
    if not old or not new:
        return False

    if similarity >= 0.98:
        return True

    if _normalize_trivial(old) == _normalize_trivial(new):
        return True

    return False


# ---------------------------------------------------------------------
# ✅ Semantic cleanup: strip markdown/html + suppress headings/outlines
# ---------------------------------------------------------------------

_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    t = re.sub(r"(?i)<br\s*/?>", "\n", text or "")
    t = _HTML_TAG_RE.sub(" ", t)
    return t


def _strip_markdown(text: str) -> str:
    t = text or ""
    t = _MD_LINK_RE.sub(r"\1", t)
    t = t.replace("**", " ").replace("__", " ").replace("*", " ").replace("_", " ")
    t = re.sub(r"^\s{0,3}#{1,6}\s+", "", t)
    t = t.replace("`", " ")
    return t


def _cleanup_for_semantic(text: str) -> str:
    """Normalize text so heading fragments / bullets / table junk don't inflate changes."""
    t = clean_line(text)
    if not t:
        return ""

    t = _strip_html(t)
    t = _strip_markdown(t)
    t = re.sub(r"\s+", " ", t).strip()
    if not t:
        return ""

    # Drop markdown table fragments / pipe-only junk
    if "|" in t:
        alnum = sum(ch.isalnum() for ch in t)
        pipes = t.count("|")
        if alnum <= 2 and pipes >= 1:
            return ""
        if pipes >= 3 and len(t.split()) <= 6 and alnum <= 8:
            return ""

    return t


# ---------------------------------------------------------------------
# Heading / stub suppression (strong)
# ---------------------------------------------------------------------

_CLAUSE_MARKERS = {
    "we",
    "your",
    "you",
    "may",
    "will",
    "must",
    "can",
    "collect",
    "share",
    "process",
    "retain",
    "store",
    "use",
    "disclose",
    "transfer",
    "sell",
    "delete",
    "access",
    "opt",
    "object",
    "provide",
}


def _has_minimum_substance(s: str) -> bool:
    """Final guardrail: kill short labels that look like headings."""
    words = re.findall(r"[A-Za-z]+", s or "")
    if len(words) >= 6:
        return True

    low_words = {w.lower() for w in words}
    # keep if it's clearly a clause / action
    if low_words & _CLAUSE_MARKERS:
        return True

    return False


def _looks_like_heading(s: str) -> bool:
    """True if sentence is probably a section heading / label rather than a clause."""
    if not s:
        return True

    t = s.strip()
    low = t.lower()

    # Final "minimum substance" rule (your request)
    if not _has_minimum_substance(t):
        return True

    boilerplate = (
        "this content should be read in conjunction",
        "read in conjunction with",
        "for more information",
        "see our privacy policy",
        "see our policy",
        "in conjunction with the rest of our privacy policy",
    )
    if any(p in low for p in boilerplate):
        return True

    if re.match(r"^\d+(\.\d+)*\s+\S+", t) and len(t.split()) <= 14:
        return True

    if t.endswith(":") and len(t.split()) <= 14:
        return True

    words = t.split()
    if len(words) <= 3:
        return True

    verb_markers = {
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "may",
        "might",
        "must",
        "can",
        "could",
        "should",
        "will",
        "would",
        "collect",
        "use",
        "share",
        "process",
        "retain",
        "store",
        "provide",
        "disclose",
        "transfer",
        "sell",
        "delete",
        "access",
        "opt",
        "object",
    }

    if not any(v in low.split() for v in verb_markers):
        alpha_tokens = re.findall(r"[A-Za-z][A-Za-z\-]+", t)
        if alpha_tokens:
            title_like = sum(1 for w in alpha_tokens if w[:1].isupper()) / max(1, len(alpha_tokens))
            if title_like >= 0.6 and len(words) <= 10:
                return True

    heading_nouns = (
        "information",
        "interactions",
        "account",
        "content",
        "communication",
        "definitions",
        "overview",
        "service providers",
        "third-party",
        "third parties",
        "purchase",
        "payments",
        "billing",
    )

    if len(words) <= 12 and any(h in low for h in heading_nouns):
        policy_verbs = (
            "collect",
            "use",
            "share",
            "retain",
            "process",
            "store",
            "sell",
            "disclose",
            "transfer",
            "provide",
        )
        if not any(v in low for v in policy_verbs):
            return True

    return False


# ---------------------------------------------------------------------
# ✅ Semantic noise filtering + dedupe (prevents "50 changes" spam)
# ---------------------------------------------------------------------


def _is_noise_sentence(s: str) -> bool:
    """Filters OTA/markdown noise + headings/stubs."""
    if not s:
        return True

    t = _cleanup_for_semantic(s)
    if not t:
        return True

    low = t.lower()

    if len(t) <= 3:
        return True

    if set(t) <= set("-*_[]() <>|:`"):
        return True

    if re.fullmatch(r"\[[^\]]+\]\([^)]+\)", (s or "").strip()):
        return True

    if t.startswith(("* ", "- ")) and len(t.split()) < 5:
        return True

    if "](https://" in (s or "") and len(t.split()) < 6:
        return True

    if ("cookies policy" in low or "/policies/cookies" in low or "/terms/" in low or "/policies/" in low):
        if len(t.split()) < 12:
            return True

    if re.search(r"^-{3,}\]", (s or "").strip()):
        return True

    if re.fullmatch(r"\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*", (s or "").strip()):
        return True

    if _looks_like_heading(t):
        return True

    return False


def _change_signature(ch: Dict) -> str:
    """Stable signature used to dedupe near-identical changes."""
    ctype = (ch.get("type") or "").strip()
    cat = (ch.get("category") or "").strip()

    if ctype in ("added", "modified"):
        base_text = (ch.get("new") or "").strip()
    else:
        base_text = (ch.get("old") or "").strip()

    base_text = _normalize_trivial(base_text)
    if len(base_text) > 220:
        base_text = base_text[:220]

    return f"{ctype}|{cat}|{base_text}"


def _dedupe_and_trim_changes(
    changes: List[Dict],
    *,
    max_total: int = 25,
    max_per_category: int = 6,
) -> List[Dict]:
    """Deduplicate + remove noisy fragments + cap repetition per category."""
    out: List[Dict] = []
    seen = set()
    per_cat_count: Dict[str, int] = {}

    for ch in changes:
        ctype = (ch.get("type") or "").strip()
        cat = (ch.get("category") or "Other policy change").strip()

        text_for_noise = (ch.get("new") if ctype in ("added", "modified") else ch.get("old")) or ""
        if _is_noise_sentence(text_for_noise):
            continue

        sig = _change_signature(ch)
        if sig in seen:
            continue
        seen.add(sig)

        per_cat_count[cat] = per_cat_count.get(cat, 0) + 1
        if per_cat_count[cat] > max_per_category:
            continue

        out.append(ch)
        if len(out) >= max_total:
            break

    return out


# ---------------------------------------------------------------------
# 1) BASIC LINE-BY-LINE ENGINE (baseline mode)
# ---------------------------------------------------------------------


def find_line_changes(old_lines: List[str], new_lines: List[str]) -> List[Dict]:
    """Very simple line-by-line comparison."""
    changes = []
    for idx, (o, n) in enumerate(zip(old_lines, new_lines), start=1):
        o_clean = clean_line(o)
        n_clean = clean_line(n)
        if o_clean != n_clean:
            changes.append({"line_number": idx, "old": o_clean, "new": n_clean})
    return changes


def _contains_any(text: str, keywords: List[str]) -> bool:
    return any(kw in text for kw in keywords)


def classify_change(old_line: str, new_line: str) -> Dict:
    """Rule-based classification."""
    old_lower = (old_line or "").lower()
    new_lower = (new_line or "").lower()

    norm_old = _normalize_trivial(old_lower)
    norm_new = _normalize_trivial(new_lower)

    # ---------- C1: Data Collection Expanded/Reduced ----------
    collection_markers = [
        "we collect",
        "we may collect",
        "information we collect",
        "data we collect",
        "we process information",
        "we may process information",
        "information we receive",
        "we receive information",
        "data we receive",
        "information we log",
        "log data",
        "log information",
    ]
    sensitive_fields = [
        "phone number",
        "location",
        "gps",
        "geolocation",
        "device id",
        "device identifier",
        "ip address",
        "contact list",
        "contacts",
        "payment information",
        "credit card",
        "debit card",
        "browsing history",
        "search history",
        "usage data",
        "usage information",
        "metadata",
        "biometric",
        "face recognition",
        "face data",
        "government id",
        "passport number",
        "national id",
        "date of birth",
    ]

    if _contains_any(new_lower, collection_markers) or _contains_any(old_lower, collection_markers):
        newly_added = [f for f in sensitive_fields if f in new_lower and f not in old_lower]
        newly_removed = [f for f in sensitive_fields if f in old_lower and f not in new_lower]

        if newly_added:
            return {
                "category": "Data collection expanded",
                "explanation": (
                    "The policy indicates that additional types of personal or usage data are now collected, "
                    f"including: {', '.join(newly_added)}."
                ),
                "suggested_action": (
                    "Review whether you are comfortable with these new types of data being collected. "
                    "If not, adjust your privacy settings or limit the information you provide."
                ),
            }

        if newly_removed:
            return {
                "category": "Data collection reduced",
                "explanation": (
                    "The policy suggests that some types of personal data are no longer collected, "
                    f"including: {', '.join(newly_removed)}."
                ),
                "suggested_action": (
                    "This may reduce the amount of personal data processed. "
                    "You can still review the policy to confirm how your remaining data is used."
                ),
            }

    # ---------- C3: Data Retention & Storage ----------
    if "stored for" in old_lower and "stored for" in new_lower:
        old_num = re.findall(r"\d+", old_lower)
        new_num = re.findall(r"\d+", new_lower)
        if old_num and new_num and new_num[0] != old_num[0]:
            return {
                "category": "Data retention & storage",
                "explanation": f"The period your data is stored appears to have changed from {old_num[0]} months to {new_num[0]} months.",
                "suggested_action": (
                    "Consider whether you are comfortable with this storage duration. "
                    "Check if you can delete older data or request data erasure."
                ),
            }

    retention_keywords = [
        "retain your data",
        "retain personal data",
        "retention period",
        "stored for",
        "we retain information",
        "we retain your information",
        "as long as necessary",
        "for as long as necessary",
        "for as long as you have an account",
    ]
    if _contains_any(new_lower, retention_keywords) and not _contains_any(old_lower, retention_keywords):
        return {
            "category": "Data retention & storage",
            "explanation": "The updated policy introduces or clarifies how long your personal data is retained.",
            "suggested_action": (
                "Review whether the retention period is acceptable to you and check if you have options "
                "to delete data or close your account."
            ),
        }

    # ---------- C2: Data Sharing & Third Parties ----------
    sharing_keywords = [
        "share your information",
        "share information",
        "share data",
        "disclose your information",
        "disclose information",
        "disclose data",
        "provide information to",
        "provide your information to",
        "third parties",
        "third-party",
        "third party",
        "partners",
        "affiliates",
        "service providers",
        "vendors",
        "processors",
        "advertising partners",
        "ad partners",
        "analytics providers",
        "social media partners",
        "data brokers",
        "measurement partners",
        "business partners",
        "other companies in our group",
        "group companies",
        "sell your data",
        "sell your personal data",
        "sell personal information",
        "monetize your data",
        "monetise your data",
    ]

    no_sell_phrases_norm = [
        "we dont sell your personal data",
        "we do not sell your personal data",
        "we dont sell your personal information",
        "we do not sell your personal information",
        "we never sell your personal data",
        "we never sell your personal information",
    ]

    old_sharing = _contains_any(old_lower, sharing_keywords)
    new_sharing = _contains_any(new_lower, sharing_keywords)

    old_no_sell = any(p in norm_old for p in no_sell_phrases_norm)
    new_no_sell = any(p in norm_new for p in no_sell_phrases_norm)

    if new_no_sell:
        return {
            "category": "Data sharing & third parties",
            "explanation": (
                "The policy confirms that your personal data is not sold to third parties, including data brokers. "
                "This maintains or clarifies an existing protection against the sale of your personal data."
            ),
            "suggested_action": (
                "You may still wish to review how your data is shared with partners or service providers for "
                "non-selling purposes such as analytics or advertising."
            ),
        }

    if old_no_sell and not new_no_sell:
        return {
            "category": "Data sharing & third parties",
            "explanation": (
                "A previous statement that your personal data would not be sold to third parties no longer appears in the policy. "
                "This may signal a change in how your data can be monetised or shared."
            ),
            "suggested_action": (
                "Review the updated sharing and monetisation terms carefully and check whether you can limit certain types "
                "of data sharing or advertising in your account settings."
            ),
        }

    if new_sharing and not old_sharing:
        return {
            "category": "Data sharing & third parties",
            "explanation": (
                "The updated policy indicates that your data may now be shared with additional third parties, such as partners, "
                "advertisers, service providers, or group companies."
            ),
            "suggested_action": (
                "Check which third parties are involved and whether you can opt out of certain types of sharing or limit data "
                "transfers in your account settings."
            ),
        }

    if "advertising partners" in new_lower and "advertising partners" not in old_lower:
        return {
            "category": "Data sharing & third parties",
            "explanation": "Your usage data may now be shared specifically with advertising partners.",
            "suggested_action": "Review your advertising preferences and, if desired, opt out of personalised ads or tracking.",
        }

    # ---------- C4: User Rights & Controls ----------
    rights_keywords = [
        "you have the right to",
        "you have certain rights",
        "your privacy rights",
        "data subject rights",
        "your rights and choices",
        "you may opt out",
        "you can opt out",
        "you may opt-out",
        "you can opt-out",
        "you can access",
        "you may access",
        "you can delete",
        "you may delete",
        "you can request deletion",
        "you can request erasure",
        "right to erasure",
        "right to deletion",
        "you can download your data",
        "you may download your data",
        "you can port your data",
        "data portability",
        "you can object",
        "you may object",
        "you can restrict processing",
        "restriction of processing",
        "withdraw your consent",
        "you can withdraw your consent",
    ]

    if _contains_any(new_lower, rights_keywords) and not _contains_any(old_lower, rights_keywords):
        return {
            "category": "User rights & controls",
            "explanation": (
                "The updated policy describes additional rights or controls you have over your personal data, such as new ways "
                "to opt out, delete your data, or exercise privacy rights."
            ),
            "suggested_action": (
                "Review the available rights and consider whether you wish to exercise any of them, for example by requesting "
                "data deletion or adjusting consent settings."
            ),
        }

    # ---------- C5: Purpose & Legal Basis ----------
    purpose_keywords = [
        "for advertising",
        "for targeted advertising",
        "for marketing",
        "for analytics",
        "for measurement",
        "for research",
        "for research purposes",
        "to personalise content",
        "to personalize content",
        "for personalised content",
        "for personalized content",
        "for personalisation",
        "to provide personalised services",
        "for safety and integrity",
        "to improve our services",
        "to develop new services",
        "advertising",
        "targeted ads",
        "personalised ads",
        "personalized ads",
        "analytics",
        "measurement",
        "ad effectiveness",
        "legitimate interests",
        "our legitimate interests",
        "legal obligation",
        "comply with legal obligations",
        "contractual necessity",
        "performance of a contract",
    ]

    if _contains_any(new_lower, purpose_keywords) and not _contains_any(old_lower, purpose_keywords):
        return {
            "category": "Purpose & legal basis",
            "explanation": (
                "The updated policy introduces or expands the purposes for which your data is used (e.g., advertising, analytics, "
                "research, or security) or clarifies the legal basis for processing."
            ),
            "suggested_action": "Check whether you are comfortable with these purposes and, where applicable, adjust your consent or opt-out preferences.",
        }

    # ---------- C6: Security & Safety Measures ----------
    security_keywords = [
        "encryption",
        "encrypted",
        "encrypt",
        "secure",
        "security measures",
        "technical and organisational measures",
        "technical and organizational measures",
        "two-factor authentication",
        "2fa",
        "multi-factor authentication",
        "access controls",
        "access control",
        "logging",
        "monitoring",
        "intrusion detection",
        "firewalls",
        "security protocols",
        "industry-standard security",
        "safeguards",
        "security practices",
        "security controls",
    ]

    if _contains_any(new_lower, security_keywords) and not _contains_any(old_lower, security_keywords):
        return {
            "category": "Security & safety measures",
            "explanation": (
                "The updated policy describes new or enhanced security measures to protect your data, such as encryption, access "
                "controls, or monitoring."
            ),
            "suggested_action": "This may improve protection of your data. You can still review details to understand what changed.",
        }

    # ---------- C7: Billing & Financial Terms ----------
    billing_keywords = [
        "subscription",
        "subscription fee",
        "subscription plan",
        "billing",
        "billing cycle",
        "billing period",
        "charged",
        "will be charged",
        "charge your",
        "charge you",
        "payment",
        "payment method",
        "payment card",
        "credit card",
        "debit card",
        "invoice",
        "invoices",
        "pricing",
        "price",
        "prices",
        "fees",
        "service fee",
    ]

    strong_billing_keywords = [
        "subscription",
        "subscription fee",
        "billing",
        "billing cycle",
        "billing period",
        "charged",
        "will be charged",
        "charge your",
        "charge you",
        "pricing",
        "price",
        "prices",
        "fees",
        "service fee",
        "payment",
    ]

    if _contains_any(new_lower, billing_keywords) and not _contains_any(old_lower, billing_keywords):
        if _contains_any(new_lower, strong_billing_keywords):
            return {
                "category": "Billing & financial terms",
                "explanation": "The updated policy introduces or changes billing/payment-related terms (subscriptions, fees, pricing, or payment methods).",
                "suggested_action": "Review these financial terms carefully to understand any new costs or obligations.",
            }

    # ---------- C8: Explicit non-profiling / safeguards ----------
    negative_profiling_phrases = [
        "we do not engage in profiling",
        "we do not profile",
        "we do not use profiling",
        "we do not make decisions based solely on automated processing",
        "no automated decision-making that produces legal or similarly significant effects",
    ]

    if _contains_any(new_lower, negative_profiling_phrases) and not _contains_any(old_lower, negative_profiling_phrases):
        return {
            "category": "Profiling limitations & safeguards",
            "explanation": (
                "The updated policy explicitly limits profiling or automated decision-making that could significantly affect you, "
                "which generally strengthens your protections."
            ),
            "suggested_action": "This appears protective. You may still review how data is used for personalisation or recommendations.",
        }

    # ---------- C9: Tracking, analytics & profiling ----------
    tracking_keywords = [
        "cookies",
        "pixels",
        "web beacons",
        "tracking technologies",
        "device identifiers",
        "device identifier",
        "browser fingerprints",
        "unique identifiers",
        "usage information",
        "usage data",
        "interaction data",
        "how you use our services",
        "how you use the service",
        "engagement",
        "page views",
        "pages visited",
        "pages you visit",
        "links clicked",
        "requested url",
        "session data",
        "session information",
        "search terms",
        "search queries",
        "ad interactions",
        "interaction with ads",
        "content interactions",
        "viewing history",
        "click history",
        "personalization",
        "personalisation",
        "personalized recommendations",
        "personalised recommendations",
        "profile building",
        "profiling",
        "inferred information",
        "inference",
        "preferences based on your activity",
        "location data",
        "geolocation",
        "gps",
        "precise location",
        "approximate location",
        "bluetooth",
        "wifi",
        "ip address",
    ]

    non_precise_location_phrases = [
        "we don't track your precise location",
        "we do not track your precise location",
        "we don't track your exact location",
        "we do not track your exact location",
    ]

    if _contains_any(old_lower, non_precise_location_phrases) and not _contains_any(new_lower, non_precise_location_phrases):
        return {
            "category": "Tracking, analytics & profiling",
            "explanation": (
                "A previous reassurance that your precise location is not tracked appears to have been removed. "
                "This may indicate broader or more granular location tracking."
            ),
            "suggested_action": "Review location/tracking terms and consider restricting location access in device settings.",
        }

    if _contains_any(new_lower, tracking_keywords) and not _contains_any(old_lower, tracking_keywords):
        return {
            "category": "Tracking, analytics & profiling",
            "explanation": (
                "The updated policy indicates expanded tracking or behavioural analytics (e.g., interactions, pages visited, search terms, "
                "click activity, or location) which may be used for personalisation or profiling."
            ),
            "suggested_action": (
                "Review privacy settings to limit tracking/analytics. Consider disabling personalised ads, restricting cookies, or using privacy tools "
                "if concerned about behavioural profiling."
            ),
        }

    return {
        "category": "Other policy change",
        "explanation": "This section of the policy text has been modified.",
        "suggested_action": "Read this part of the policy carefully to understand how it affects your data.",
    }


# ---------------------------------------------------------------------
# Risk scoring (category + content triggers)
# ---------------------------------------------------------------------


def _estimate_risk(meta: Dict) -> float:
    """Category-driven base score."""
    cat = (meta.get("category") or "").lower()

    if "data sharing" in cat or "third parties" in cat or "advertisers" in cat:
        return 3.0
    if "tracking" in cat or "location" in cat or "profiling" in cat:
        return 2.5
    if "data retention" in cat or "storage" in cat:
        return 2.2
    if "user rights" in cat or "controls" in cat:
        return 2.2
    if "data collection expanded" in cat:
        return 2.0
    if "purpose" in cat or "legal basis" in cat:
        return 1.8
    if "billing" in cat or "financial" in cat:
        return 1.8
    if "security" in cat:
        return 1.5
    if "profiling limitations" in cat or "safeguards" in cat:
        return 0.7
    return 0.5


def _content_risk_bump(text: str) -> float:
    """Content-trigger bumping (your request)."""
    t = _normalize_trivial(text)

    bump = 0.0

    # +0.5 if contains: advertis, third party, partner, data broker
    if re.search(r"\b(advertis|ad\s|third\s+party|partner|data\s*broker)\b", t):
        bump += 0.5

    # +0.5 if contains: combine, across, affiliates, Meta companies
    if re.search(r"\b(combine|across|affiliate|affiliates|meta\s+companies)\b", t):
        bump += 0.5

    # +0.7 if contains: sell, share for advertising, profiling, inference
    if re.search(r"\b(sell|selling|share\s+for\s+advertis|profiling|inference|infer)\b", t):
        bump += 0.7

    return bump


def _risk_label(score: float) -> str:
    if score >= 2.5:
        return "High"
    if score >= 1.5:
        return "Medium"
    return "Low"


# ---------------------------------------------------------------------
# Public: theme assignment for UI grouping
# ---------------------------------------------------------------------


def infer_theme(category: str, text: str) -> str:
    c = (category or "").lower()
    t = (text or "").lower()

    if "sharing" in c or "third" in c or "sell" in t or "broker" in t:
        return "data_sharing"
    if "tracking" in c or "profil" in c or "cookie" in t or "pixel" in t:
        return "tracking"
    if "retention" in c or "storage" in c or "retain" in t:
        return "retention"
    if "rights" in c or "controls" in c or "opt" in t or "delete" in t:
        return "rights"
    if "collection" in c or "collect" in t or "receive" in t:
        return "collection"
    if "security" in c or "encrypt" in t or "2fa" in t:
        return "security"
    if "billing" in c or "subscription" in t or "fee" in t:
        return "billing"
    if "purpose" in c or "legal" in c or "advertising" in t or "analytics" in t:
        return "purpose"

    return "other"


THEME_TITLES = {
    "data_sharing": "Data sharing / third parties",
    "tracking": "Tracking / profiling",
    "retention": "Data retention",
    "rights": "User rights & controls",
    "collection": "Data collection",
    "purpose": "Purpose / legal basis",
    "security": "Security measures",
    "billing": "Billing / payments",
    "other": "Other",
}


# ---------------------------------------------------------------------
# BASIC MODE
# ---------------------------------------------------------------------


def analyze_policy_change_basic(old_text: str, new_text: str) -> List[Dict]:
    old_lines = (old_text or "").splitlines()
    new_lines = (new_text or "").splitlines()

    line_changes = find_line_changes(old_lines, new_lines)

    enriched: List[Dict] = []
    for ch in line_changes:
        meta = classify_change(ch["old"], ch["new"])
        joined = f"{ch.get('old','')} {ch.get('new','')}"
        base = _estimate_risk(meta)
        bump = _content_risk_bump(joined)
        score = base + bump
        enriched.append(
            {
                **ch,
                **meta,
                "risk_score": score,
                "risk_label": _risk_label(score),
                "confidence": 0.7,
                "theme": infer_theme(meta.get("category", ""), joined),
            }
        )

    enriched.sort(key=lambda x: float(x.get("risk_score", 0.0) or 0.0), reverse=True)
    return enriched


# ---------------------------------------------------------------------
# 2) SEMANTIC ALIGNMENT ENGINE (Sentence-BERT based)
# ---------------------------------------------------------------------


def align_sentences_semantic(
    old_sentences: List[str],
    new_sentences: List[str],
    model: "SentenceTransformer",
    threshold_same: float = 0.85,
    threshold_any_match: float = 0.60,
) -> List[Dict]:
    """Align old sentences to new sentences using semantic similarity."""
    old_emb = model.encode(old_sentences, convert_to_tensor=True)
    new_emb = model.encode(new_sentences, convert_to_tensor=True)

    sim = util.cos_sim(old_emb, new_emb)

    n_old = len(old_sentences)
    n_new = len(new_sentences)

    matched_new_indices = set()
    alignments: List[Dict] = []

    for i in range(n_old):
        sims_to_new = sim[i]
        best_j = int(torch.argmax(sims_to_new))
        best_score = float(sims_to_new[best_j])

        old = old_sentences[i]
        new = new_sentences[best_j]

        if best_score >= threshold_same:
            if old == new or _is_trivial_change(old, new, best_score):
                change_type = "unchanged"
            else:
                change_type = "modified"

            alignments.append(
                {
                    "old_index": i,
                    "new_index": best_j,
                    "old": old,
                    "new": new,
                    "similarity": best_score,
                    "type": change_type,
                }
            )
            matched_new_indices.add(best_j)

        elif best_score >= threshold_any_match:
            alignments.append(
                {
                    "old_index": i,
                    "new_index": best_j,
                    "old": old,
                    "new": new,
                    "similarity": best_score,
                    "type": "modified",
                }
            )
            matched_new_indices.add(best_j)
        else:
            alignments.append(
                {
                    "old_index": i,
                    "new_index": None,
                    "old": old,
                    "new": None,
                    "similarity": best_score,
                    "type": "removed",
                }
            )

    for j in range(n_new):
        if j not in matched_new_indices:
            alignments.append(
                {
                    "old_index": None,
                    "new_index": j,
                    "old": None,
                    "new": new_sentences[j],
                    "similarity": None,
                    "type": "added",
                }
            )

    return alignments


def analyze_policy_change_semantic(
    old_text: str,
    new_text: str,
    model: Optional["SentenceTransformer"] = None,
) -> List[Dict]:
    """Semantic mode with strong noise suppression, dedupe, impact scoring, and confidence."""
    if not _SEMANTIC_AVAILABLE:
        raise ImportError(
            "sentence-transformers is not installed. Install it with `pip install sentence-transformers`."
        )

    if model is None:
        model = SentenceTransformer("all-MiniLM-L6-v2")

    old_sentences = split_into_sentences(old_text or "")
    new_sentences = split_into_sentences(new_text or "")

    old_sentences = [_cleanup_for_semantic(s) for s in old_sentences]
    new_sentences = [_cleanup_for_semantic(s) for s in new_sentences]

    old_sentences = [s for s in old_sentences if s and not _is_noise_sentence(s)]
    new_sentences = [s for s in new_sentences if s and not _is_noise_sentence(s)]

    if not old_sentences or not new_sentences:
        return []

    alignments = align_sentences_semantic(old_sentences, new_sentences, model=model)

    enriched: List[Dict] = []

    for a in alignments:
        change_type = a["type"]
        old_sent = a.get("old") or ""
        new_sent = a.get("new") or ""
        sim = a.get("similarity")

        if change_type == "unchanged":
            continue

        old_sent_c = _cleanup_for_semantic(old_sent)
        new_sent_c = _cleanup_for_semantic(new_sent)

        if change_type in ("added", "modified") and _is_noise_sentence(new_sent_c):
            continue
        if change_type == "removed" and _is_noise_sentence(old_sent_c):
            continue

        joined = f"{old_sent_c} {new_sent_c}".strip()

        if change_type == "modified":
            meta = classify_change(old_sent_c, new_sent_c)

            if meta.get("category") == "Other policy change" and sim is not None and float(sim) >= 0.95:
                continue

            base = _estimate_risk(meta)
            bump = _content_risk_bump(joined)
            score = base + bump

            confidence = float(sim) if sim is not None else 0.6

            enriched.append(
                {
                    **a,
                    "old": old_sent_c,
                    "new": new_sent_c,
                    **meta,
                    "risk_score": score,
                    "risk_label": _risk_label(score),
                    "confidence": confidence,
                    "theme": infer_theme(meta.get("category", ""), joined),
                }
            )
            continue

        if change_type == "added":
            if _looks_like_heading(new_sent_c):
                continue

            meta = classify_change("", new_sent_c)
            if meta.get("category") == "Other policy change" and len(new_sent_c.split()) < 10:
                continue

            base = _estimate_risk(meta)
            bump = _content_risk_bump(new_sent_c)
            score = base + 0.5 + bump

            enriched.append(
                {
                    **a,
                    "old": None,
                    "new": new_sent_c,
                    **meta,
                    "risk_score": score,
                    "risk_label": _risk_label(score),
                    "confidence": 0.6,
                    "theme": infer_theme(meta.get("category", ""), new_sent_c),
                }
            )
            continue

        if change_type == "removed":
            if _looks_like_heading(old_sent_c):
                continue

            meta = classify_change(old_sent_c, "")
            base = _estimate_risk(meta)
            bump = _content_risk_bump(old_sent_c)
            if meta.get("category") == "User rights & controls":
                base = max(base, 2.0)
            score = base + bump

            enriched.append(
                {
                    **a,
                    "old": old_sent_c,
                    "new": None,
                    **meta,
                    "risk_score": score,
                    "risk_label": _risk_label(score),
                    "confidence": 0.6,
                    "theme": infer_theme(meta.get("category", ""), old_sent_c),
                }
            )
            continue

    if enriched:
        enriched = sorted(
            enriched,
            key=lambda x: (float(x.get("risk_score", 0.0) or 0.0), x.get("category", "")),
            reverse=True,
        )

        enriched = _dedupe_and_trim_changes(enriched, max_total=25, max_per_category=6)

    return enriched
