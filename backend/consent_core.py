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
    """
    Lazy-load spaCy English model if available.
    """
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
    """
    Split long policy text into sentences using spaCy if available,
    otherwise fall back to simple line-based splitting.
    """
    if _SPACY_AVAILABLE:
        nlp = get_spacy_nlp()
        doc = nlp(text)
        return [sent.text.strip() for sent in doc.sents if sent.text.strip()]
    else:
        # Fallback: keep simple behaviour
        return [s.strip() for s in text.splitlines() if s.strip()]


def clean_line(s: str) -> str:
    """Remove BOM and extra whitespace."""
    return s.replace("\ufeff", "").strip()


# ---------------------------------------------------------------------
# Helpers for semantic trivial-change detection
# ---------------------------------------------------------------------

def _normalize_trivial(text: str) -> str:
    """
    Normalise text for trivial-change detection:
    - lowercasing
    - remove quotes, punctuation
    - collapse whitespace
    """
    t = text.lower()
    # remove different quote characters
    t = re.sub(r"[\"'`’“”]", "", t)
    # remove basic punctuation
    t = re.sub(r"[.,;:!?()\-\[\]]", " ", t)
    # collapse whitespace
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _is_trivial_change(old: str, new: str, similarity: float) -> bool:
    """
    Decide if a change is trivial (formatting, quotes, tiny wording)
    and should be treated as 'unchanged'.
    """
    if not old or not new:
        return False

    # Very high semantic similarity → likely tiny edit
    if similarity >= 0.98:
        return True

    # Normalised strings identical → punctuation/quote-only change
    norm_old = _normalize_trivial(old)
    norm_new = _normalize_trivial(new)
    if norm_old == norm_new:
        return True

    return False


# ---------------------------------------------------------------------
# 1) BASIC LINE-BY-LINE ENGINE (baseline mode)
# ---------------------------------------------------------------------

def find_line_changes(old_lines: List[str], new_lines: List[str]) -> List[Dict]:
    """
    Very simple line-by-line comparison.
    Returns list of dicts with line_number, old, new.
    Assumes same ordering and similar line counts.
    """
    changes = []
    for idx, (o, n) in enumerate(zip(old_lines, new_lines), start=1):
        o_clean = clean_line(o)
        n_clean = clean_line(n)
        if o_clean != n_clean:
            changes.append({
                "line_number": idx,
                "old": o_clean,
                "new": n_clean,
            })
    return changes


def _contains_any(text: str, keywords: List[str]) -> bool:
    return any(kw in text for kw in keywords)


def classify_change(old_line: str, new_line: str) -> Dict:
    """
    Rule-based classification of a single change into a risk category,
    with explanation and suggested action.

    Risk categories (aligned with dissertation taxonomy):
      - Data collection expanded / reduced
      - Data sharing & third parties
      - Data retention & storage
      - User rights & controls
      - Purpose & legal basis
      - Security & safety measures
      - Billing & financial terms
      - Tracking, analytics & profiling
      - Profiling limitations & safeguards
      - Other policy change
    """
    old_lower = old_line.lower() if old_line is not None else ""
    new_lower = new_line.lower() if new_line is not None else ""

    # Normalised versions (remove punctuation/quotes) for robust phrase matching
    norm_old = _normalize_trivial(old_lower)
    norm_new = _normalize_trivial(new_lower)


    # ---------- C1: Data Collection Expanded/Reduced ----------
    collection_markers = [
        "we collect", "we may collect", "information we collect", "data we collect",
        "we process information", "we may process information",
        "information we receive", "we receive information", "data we receive",
        "information we log", "log data", "log information"
    ]
    sensitive_fields = [
        "phone number", "location", "gps", "geolocation",
        "device id", "device identifier", "ip address",
        "contact list", "contacts",
        "payment information", "credit card", "debit card",
        "browsing history", "search history", "usage data", "usage information",
        "metadata", "biometric", "face recognition", "face data",
        "government id", "passport number", "national id", "date of birth"
    ]

    if _contains_any(new_lower, collection_markers) or _contains_any(old_lower, collection_markers):
        newly_added = [field for field in sensitive_fields
                       if field in new_lower and field not in old_lower]
        newly_removed = [field for field in sensitive_fields
                         if field in old_lower and field not in new_lower]

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
                "explanation": (
                    f"The period your data is stored appears to have changed from "
                    f"{old_num[0]} months to {new_num[0]} months."
                ),
                "suggested_action": (
                    "Consider whether you are comfortable with this storage duration. "
                    "Check if you can delete older data or request data erasure."
                ),
            }

    retention_keywords = [
        "retain your data", "retain personal data", "retention period", "stored for",
        "we retain information", "we retain your information",
        "as long as necessary", "for as long as necessary",
        "for as long as you have an account"
    ]
    if _contains_any(new_lower, retention_keywords) and not _contains_any(old_lower, retention_keywords):
        return {
            "category": "Data retention & storage",
            "explanation": (
                "The updated policy introduces or clarifies how long your personal data is retained."
            ),
            "suggested_action": (
                "Review whether the retention period is acceptable to you and check if you have options "
                "to delete data or close your account."
            ),
        }

          # ---------- C2: Data Sharing & Third Parties ----------
    sharing_keywords = [
        # generic sharing
        "share your information", "share information", "share data",
        "disclose your information", "disclose information", "disclose data",
        "provide information to", "provide your information to",

        # actors
        "third parties", "third-party", "third party",
        "partners", "affiliates", "service providers", "vendors", "processors",
        "advertising partners", "ad partners", "analytics providers",
        "social media partners", "data brokers", "measurement partners",
        "business partners", "other companies in our group", "group companies",

        # monetisation
        "sell your data", "sell your personal data", "sell personal information",
        "monetize your data", "monetise your data"
    ]

    # Specific phrases about *not* selling data (in normalised form: no apostrophes)
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

    # Use normalised strings so straight / curly quotes both match
    old_no_sell = any(p in norm_old for p in no_sell_phrases_norm)
    new_no_sell = any(p in norm_new for p in no_sell_phrases_norm)

    # 2.1 Explicit protection still present (or strengthened)
    if new_no_sell:
        return {
            "category": "Data sharing & third parties",
            "explanation": (
                "The policy confirms that your personal data is not sold to third parties, "
                "including data brokers. This maintains or clarifies an existing protection "
                "against the sale of your personal data."
            ),
            "suggested_action": (
                "You may still wish to review how your data is shared with partners or service "
                "providers for non-selling purposes such as analytics or advertising."
            ),
        }

    # 2.2 Protection silently removed → potential weakening
    if old_no_sell and not new_no_sell:
        return {
            "category": "Data sharing & third parties",
            "explanation": (
                "A previous statement that your personal data would not be sold to third parties "
                "no longer appears in the policy. This may signal a change in how your data can be "
                "monetised or shared."
            ),
            "suggested_action": (
                "Review the updated sharing and monetisation terms carefully and check whether you "
                "can limit certain types of data sharing or advertising in your account settings."
            ),
        }

    # 2.3 Generic new sharing language
    if new_sharing and not old_sharing:
        return {
            "category": "Data sharing & third parties",
            "explanation": (
                "The updated policy indicates that your data may now be shared with additional third parties, "
                "such as partners, advertisers, service providers, or group companies."
            ),
            "suggested_action": (
                "Check which third parties are involved and whether you can opt out of certain types of sharing "
                "or limit data transfers in your account settings."
            ),
        }

    # 2.4 Specific case: new advertising partners
    if "advertising partners" in new_lower and "advertising partners" not in old_lower:
        return {
            "category": "Data sharing & third parties",
            "explanation": "Your usage data may now be shared specifically with advertising partners.",
            "suggested_action": (
                "Review your advertising preferences and, if desired, opt out of personalised ads or tracking."
            ),
        }

    # ---------- C4: User Rights & Controls ----------
    rights_keywords = [
        # explicit rights language
        "you have the right to", "you have certain rights", "your privacy rights",
        "data subject rights", "your rights and choices",

        # specific controls
        "you may opt out", "you can opt out", "you may opt-out", "you can opt-out",
        "you can access", "you may access",
        "you can delete", "you may delete", "you can request deletion",
        "you can request erasure", "right to erasure", "right to deletion",
        "you can download your data", "you may download your data",
        "you can port your data", "data portability",
        "you can object", "you may object",
        "you can restrict processing", "restriction of processing",
        "withdraw your consent", "you can withdraw your consent"
    ]

    if _contains_any(new_lower, rights_keywords) and not _contains_any(old_lower, rights_keywords):
        return {
            "category": "User rights & controls",
            "explanation": (
                "The updated policy describes additional rights or controls you have over your personal data, "
                "such as new ways to opt out, delete your data, or exercise privacy rights."
            ),
            "suggested_action": (
                "Review the available rights and consider whether you wish to exercise any of them, "
                "for example by requesting data deletion or adjusting consent settings."
            ),
        }

    # ---------- C5: Purpose & Legal Basis ----------
    purpose_keywords = [
        # purposes
        "for advertising", "for targeted advertising", "for marketing",
        "for analytics", "for measurement", "for research", "for research purposes",
        "to personalise content", "to personalize content",
        "for personalised content", "for personalized content", "for personalisation",
        "to provide personalised services",
        "for safety and integrity", "to improve our services",
        "to develop new services",

        # looser occurrences
        "advertising", "targeted ads", "personalised ads", "personalized ads",
        "analytics", "measurement", "ad effectiveness",

        # legal bases
        "legitimate interests", "our legitimate interests",
        "legal obligation", "comply with legal obligations",
        "contractual necessity", "performance of a contract"
    ]

    if _contains_any(new_lower, purpose_keywords) and not _contains_any(old_lower, purpose_keywords):
        return {
            "category": "Purpose & legal basis",
            "explanation": (
                "The updated policy introduces or expands the purposes for which your data is used, "
                "such as advertising, analytics, research, or security, or clarifies the legal basis for processing."
            ),
            "suggested_action": (
                "Check whether you are comfortable with these purposes and, where applicable, "
                "consider adjusting your consent or opt-out preferences."
            ),
        }

    # ---------- C6: Security & Safety Measures ----------
    security_keywords = [
        "encryption", "encrypted", "encrypt", "secure", "security measures",
        "technical and organisational measures", "technical and organizational measures",
        "two-factor authentication", "2fa", "multi-factor authentication",
        "access controls", "access control",
        "logging", "monitoring", "intrusion detection", "firewalls",
        "security protocols", "industry-standard security", "safeguards",
        "security practices", "security controls"
    ]

    if _contains_any(new_lower, security_keywords) and not _contains_any(old_lower, security_keywords):
        return {
            "category": "Security & safety measures",
            "explanation": (
                "The updated policy describes new or enhanced security measures to protect your data, "
                "such as encryption, access controls, or monitoring."
            ),
            "suggested_action": (
                "This may improve the protection of your data. You can still review the details to understand "
                "how security practices have changed."
            ),
        }

    # ---------- C7: Billing & Financial Terms ----------
    billing_keywords = [
        "subscription", "subscription fee", "subscription plan",
        "billing", "billing cycle", "billing period",
        "charged", "will be charged", "charge your", "charge you",
        "payment", "payment method", "payment card",
        "credit card", "debit card",
        "invoice", "invoices",
        "pricing", "price", "prices", "fees", "service fee"
    ]

    # Strong triggers so we don't classify just because of a single "invoice"
    strong_billing_keywords = [
        "subscription", "subscription fee", "billing", "billing cycle", "billing period",
        "charged", "will be charged", "charge your", "charge you",
        "pricing", "price", "prices", "fees", "service fee", "payment"
    ]

    if _contains_any(new_lower, billing_keywords) and not _contains_any(old_lower, billing_keywords):
        if not _contains_any(new_lower, strong_billing_keywords):
            # Let other categories or fallback handle weak mentions
            pass
        else:
            return {
                "category": "Billing & financial terms",
                "explanation": (
                    "The updated policy introduces or changes billing or payment-related terms, "
                    "such as subscriptions, fees, pricing, or payment methods."
                ),
                "suggested_action": (
                    "Review these financial terms carefully to understand any new costs or obligations. "
                    "Consider whether you wish to continue using the service under the new conditions."
                ),
            }

    # ---------- C8: Special case – explicit non-profiling / safeguards ----------
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
                "The updated policy explicitly limits profiling or automated decision-making that could "
                "significantly affect you, which generally strengthens your protections."
            ),
            "suggested_action": (
                "This change appears protective. You may still wish to review how your data is used for "
                "personalisation or recommendations, but the policy now clarifies boundaries on automated decisions."
            ),
        }

    # ---------- C9: Tracking, analytics & profiling ----------
    tracking_keywords = [
        # classic tracking tech
        "cookies", "pixels", "web beacons", "tracking technologies",
        "device identifiers", "device identifier", "browser fingerprints",
        "unique identifiers",

        # behavioural analytics
        "usage information", "usage data", "interaction data",
        "how you use our services", "how you use the service",
        "engagement", "page views", "pages visited", "pages you visit",
        "links clicked", "requested url", "session data", "session information",
        "search terms", "search queries", "ad interactions", "interaction with ads",
        "content interactions", "viewing history", "click history",

        # profiling / personalisation
        "personalization", "personalisation", "personalized recommendations",
        "personalised recommendations", "profile building",
        "profiling", "inferred information", "inference",
        "preferences based on your activity",

        # location-style tracking
        "location data", "geolocation", "gps", "precise location",
        "approximate location", "bluetooth", "wifi", "ip address"
    ]

    # Loss of "we don't track your precise location" style reassurance
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
            "suggested_action": (
                "Review the updated location and tracking terms. Consider restricting location access in "
                "your device settings or using privacy tools if you are concerned."
            ),
        }

    if _contains_any(new_lower, tracking_keywords) and not _contains_any(old_lower, tracking_keywords):
        return {
            "category": "Tracking, analytics & profiling",
            "explanation": (
                "The updated policy indicates expanded tracking or behavioural analytics, "
                "including monitoring how you use the service (e.g., interactions, pages visited, "
                "search terms, click activity, or location) which may be used for personalization or profiling."
            ),
            "suggested_action": (
                "Review privacy settings to limit tracking or analytics. "
                "Consider disabling personalised ads, restricting cookies, or using privacy tools "
                "if you are concerned about behavioural profiling."
            ),
        }

    # ---------- Fallback ----------
    return {
        "category": "Other policy change",
        "explanation": "This section of the policy text has been modified.",
        "suggested_action": (
            "Read this part of the policy carefully to understand how it affects your data."
        ),
    }


def _estimate_risk(meta: Dict) -> float:
    """
    Very simple heuristic risk scoring to prioritise changes in the UI.
    Higher score = more important to surface.
    """
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
        # Explicit safeguards: low risk (more like a positive change)
        return 0.7

    # Other policy changes = low default
    return 0.5


def _risk_label(score: float) -> str:
    """
    Map numeric risk score to a simple label for UI purposes.
    """
    if score >= 2.5:
        return "High"
    if score >= 1.5:
        return "Medium"
    return "Low"


def analyze_policy_change_basic(old_text: str, new_text: str) -> List[Dict]:
    """
    BASIC MODE:
    Takes old & new policy texts and uses simple line-by-line comparison.
    Returns list of enriched change objects:
      - line_number, old, new, category, explanation, suggested_action
    """
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()

    line_changes = find_line_changes(old_lines, new_lines)

    enriched = []
    for ch in line_changes:
        meta = classify_change(ch["old"], ch["new"])
        enriched.append({**ch, **meta})

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
    """
    Aligns old sentences to new sentences using semantic similarity.
    Returns a list of alignment dicts with:
      - old_index, new_index, old, new, similarity, type
      - type in {'unchanged', 'modified', 'removed', 'added'}
    """
    old_emb = model.encode(old_sentences, convert_to_tensor=True)
    new_emb = model.encode(new_sentences, convert_to_tensor=True)

    sim = util.cos_sim(old_emb, new_emb)  # [n_old x n_new]

    n_old = len(old_sentences)
    n_new = len(new_sentences)

    matched_new_indices = set()
    alignments: List[Dict] = []

    # 1) For each old sentence, find the best matching new sentence
    for i in range(n_old):
        sims_to_new = sim[i]
        best_j = int(torch.argmax(sims_to_new))
        best_score = float(sims_to_new[best_j])

        old = old_sentences[i]
        new = new_sentences[best_j]

        if best_score >= threshold_same:
            # treat trivial edits as unchanged
            if old == new or _is_trivial_change(old, new, best_score):
                change_type = "unchanged"
            else:
                change_type = "modified"

            alignments.append({
                "old_index": i,
                "new_index": best_j,
                "old": old,
                "new": new,
                "similarity": best_score,
                "type": change_type,
            })
            matched_new_indices.add(best_j)

        elif best_score >= threshold_any_match:
            # Related but not very close – treat as modified
            alignments.append({
                "old_index": i,
                "new_index": best_j,
                "old": old,
                "new": new,
                "similarity": best_score,
                "type": "modified",
            })
            matched_new_indices.add(best_j)
        else:
            # No sufficiently similar new sentence -> removed
            alignments.append({
                "old_index": i,
                "new_index": None,
                "old": old,
                "new": None,
                "similarity": best_score,
                "type": "removed",
            })

    # 2) Any new sentences that were never matched are considered 'added'
    for j in range(n_new):
        if j not in matched_new_indices:
            alignments.append({
                "old_index": None,
                "new_index": j,
                "old": None,
                "new": new_sentences[j],
                "similarity": None,
                "type": "added",
            })

    return alignments


def analyze_policy_change_semantic(
    old_text: str,
    new_text: str,
    model: Optional["SentenceTransformer"] = None,
) -> List[Dict]:
    """
    SEMANTIC MODE:
    - Uses spaCy to segment policies into sentences.
    - Uses Sentence-BERT to align old vs new sentences.
    - Classifies:
        * modified sentences (old+new)
        * added sentences (new-only clauses)
        * removed sentences (old-only clauses; loss of rights/protections)
    - Suppresses near-identical trivial changes.

    Returns a list of enriched change objects:
      - old_index, new_index, old, new, similarity, type,
        category, explanation, suggested_action, risk_score, risk_label
    """
    if not _SEMANTIC_AVAILABLE:
        raise ImportError(
            "sentence-transformers is not installed. "
            "Install it with `pip install sentence-transformers` in Colab."
        )

    if model is None:
        model = SentenceTransformer("all-MiniLM-L6-v2")

    # 1) Sentence segmentation
    old_sentences = split_into_sentences(old_text)
    new_sentences = split_into_sentences(new_text)

    # 2) Semantic alignment between old & new
    alignments = align_sentences_semantic(old_sentences, new_sentences, model=model)

    enriched: List[Dict] = []

    for a in alignments:
        change_type = a["type"]           # 'unchanged' | 'modified' | 'added' | 'removed'
        old_sent = a.get("old") or ""
        new_sent = a.get("new") or ""
        sim = a.get("similarity", None)

        # Skip unchanged
        if change_type == "unchanged":
            continue

        # ---------- MODIFIED ----------
        if change_type == "modified":
            meta = classify_change(old_sent, new_sent)

            # Suppress low-value generic changes that are almost identical
            if (
                meta.get("category") == "Other policy change"
                and sim is not None
                and sim >= 0.95
            ):
                continue

            base = _estimate_risk(meta)
            enriched.append({
                **a,
                **meta,
                "risk_score": base,
                "risk_label": _risk_label(base),
            })
            continue

        # ---------- ADDED ----------
        if change_type == "added":
            # Focus on what is NEW: pass empty old_sent so rules look at new_sent
            meta = classify_change("", new_sent)

            # If it's generic and extremely short, skip noise
            if meta.get("category") == "Other policy change":
                if len(new_sent.split()) < 6:
                    continue

            # For "added", bump risk a bit – additions matter more for users
            base = _estimate_risk(meta)
            score = base + 0.5
            enriched.append({
                **a,
                **meta,
                "risk_score": score,
                "risk_label": _risk_label(score),
            })
            continue

        # ---------- REMOVED ----------
        if change_type == "removed":
            # Look at what the user LOST: pass empty new_sent
            meta = classify_change(old_sent, "")

            base = _estimate_risk(meta)
            # If it's "loss of rights / controls", treat as high risk
            if meta.get("category") == "User rights & controls":
                base = max(base, 2.0)

            enriched.append({
                **a,
                **meta,
                "risk_score": base,
                "risk_label": _risk_label(base),
            })
            continue

    # Sort by risk_score descending, then category
    if enriched:
        enriched = sorted(
            enriched,
            key=lambda x: (x.get("risk_score", 0.0), x.get("category", "")),
            reverse=True,
        )

    return enriched
