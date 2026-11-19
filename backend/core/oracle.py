"""Official portal resolution and domain-safety checks.

The registry is a fast, auditable allow-list.  Unknown queries are resolved
with TinyFish Search and only accepted when the result is an official
government / academic domain.  There is no silent default to a random portal.
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from . import settings
from .tinyfish_client import TinyFishClient, TinyFishError


class OracleResult(BaseModel):
    query: str
    official_name: str
    target_url: str
    is_gov_domain: bool
    domain_trust_score: int
    authority_type: str
    domain_suffix: str
    advisory: str
    hindi_advisory: str
    source_citation: str
    official_verified: bool
    is_practice: bool = False
    confidence: int = 100
    resolved_via: str = "registry"
    candidates: List[Dict[str, Any]] = Field(default_factory=list)


OFFICIAL_PORTAL_REGISTRY = [
    {
        "keywords": ["railway", "rrb", "rrb ntpc", "alp", "group d", "railway recruitment", "loco pilot", "rpf"],
        "name": "Railway Recruitment Boards (RRB) — Ministry of Railways",
        "url": "https://www.rrbapply.gov.in/#/auth/home",
        "authority": "Ministry of Railways, Govt of India",
        "tld": "gov.in",
        "trust": 100,
        "advisory": "Official Railway application portal verified. Apply only through rrbapply.gov.in.",
        "hindi_advisory": "Railway ka official portal verify ho gaya hai. Sirf rrbapply.gov.in se apply karein.",
    },
    {
        "keywords": ["ssc", "ssc cgl", "ssc chsl", "ssc gd", "staff selection commission", "ssc mts", "cpo"],
        "name": "Staff Selection Commission (SSC) — DoPT Govt of India",
        "url": "https://ssc.gov.in",
        "authority": "Staff Selection Commission, Govt of India",
        "tld": "gov.in",
        "trust": 100,
        "advisory": "Official SSC portal verified. Use the official OTR link to begin.",
        "hindi_advisory": "SSC ka official portal verify ho gaya hai. OTR ke liye official link use karein.",
    },
    {
        "keywords": ["bpsc", "bihar psc", "bihar public service commission", "bpsc teacher", "tre", "70th bpsc"],
        "name": "Bihar Public Service Commission (BPSC) — Govt of Bihar",
        "url": "https://onlinebpsc.bihar.gov.in",
        "authority": "Government of Bihar",
        "tld": "gov.in",
        "trust": 100,
        "advisory": "Official BPSC portal verified. The page may load slowly; we will wait for it.",
        "hindi_advisory": "BPSC ka official portal verify ho gaya hai. Page dheere khul sakta hai, hum wait karenge.",
    },
    {
        "keywords": ["upsc", "civil services", "ias", "ips", "nda", "cds", "union public service commission"],
        "name": "Union Public Service Commission (UPSC) — Govt of India",
        "url": "https://upsconline.nic.in",
        "authority": "UPSC / National Informatics Centre (NIC)",
        "tld": "nic.in",
        "trust": 100,
        "advisory": "Official UPSC portal verified. Use the official OTR link.",
        "hindi_advisory": "UPSC ka official portal verify ho gaya hai. OTR ke liye official link use karein.",
    },
    {
        "keywords": ["csbc", "bihar police", "constable", "bihar police constable"],
        "name": "Central Selection Board of Constable (CSBC) — Bihar",
        "url": "https://csbc.bih.nic.in",
        "authority": "CSBC Bihar / NIC",
        "tld": "nic.in",
        "trust": 98,
        "advisory": "Official CSBC Bihar portal verified.",
        "hindi_advisory": "Bihar Police Constable ka official portal verify ho gaya hai.",
    },
    {
        "keywords": ["uppsc", "up psc", "uttar pradesh psc", "ro aro", "up pcs"],
        "name": "Uttar Pradesh Public Service Commission (UPPSC)",
        "url": "https://uppsc.up.nic.in",
        "authority": "Govt of Uttar Pradesh / NIC",
        "tld": "nic.in",
        "trust": 99,
        "advisory": "Official UPPSC portal verified.",
        "hindi_advisory": "UPPSC ka official portal verify ho gaya hai.",
    },
    {
        # JEE Advanced is a separate portal from JEE Main.  It must be matched
        # before the generic "jee" entry, otherwise "JEE Advanced" resolves to
        # the Main portal.
        "keywords": ["jee advanced", "jee adv", "joint entrance examination advanced", "iit jee advanced", "advanced jee"],
        "name": "JEE (Advanced) — Joint Admission Board / IITs",
        "url": "https://jeeadv.ac.in/",
        "authority": "Joint Admission Board (JAB), IITs",
        "tld": "ac.in",
        "trust": 98,
        "advisory": "Official JEE (Advanced) portal verified. Apply only through jeeadv.ac.in.",
        "hindi_advisory": "JEE Advanced ka official portal verify ho gaya hai. Sirf jeeadv.ac.in se apply karein.",
    },
    {
        "keywords": ["jee main", "jee mains", "jee (main)", "joint entrance examination main", "nta jee main", "jee main session"],
        "name": "JEE (Main) — National Testing Agency",
        "url": "https://jeemain.nta.nic.in/",
        "authority": "National Testing Agency (NTA), Ministry of Education",
        "tld": "nic.in",
        "trust": 99,
        "advisory": "Official JEE (Main) portal verified. Apply only through jeemain.nta.nic.in.",
        "hindi_advisory": "JEE Main ka official portal verify ho gaya hai. Sirf jeemain.nta.nic.in se apply karein.",
    },
    {
        # A bare "JEE" is the most common way a candidate asks for this exam.
        # Keep this after the two specific entries so it is the fallback.
        "keywords": ["jee", "joint entrance examination"],
        "name": "JEE (Main) — National Testing Agency",
        "url": "https://jeemain.nta.nic.in/",
        "authority": "National Testing Agency (NTA), Ministry of Education",
        "tld": "nic.in",
        "trust": 98,
        "advisory": "JEE resolves to the official JEE (Main) portal. Use JEE (Advanced) if you mean the IIT exam.",
        "hindi_advisory": "JEE ka official JEE (Main) portal khul raha hai. IIT exam ke liye JEE (Advanced) likhein.",
    },
    {
        "keywords": ["cuet", "nta", "neet", "national testing agency"],
        "name": "National Testing Agency (NTA) — Ministry of Education",
        "url": "https://exams.nta.ac.in",
        "authority": "Ministry of Education, Govt of India",
        "tld": "ac.in / gov.in",
        "trust": 99,
        "advisory": "Official National Testing Agency exam portal verified.",
        "hindi_advisory": "NTA ka official portal verify ho gaya hai.",
    },
    {
        "keywords": ["simulator", "test", "demo", "sandbox", "gov demo", "mock portal", "formpilot demo", "gov-portal-simulator"],
        "name": "FormPilot Practice Portal (Demo)",
        "url": getattr(settings, "PRACTICE_PORTAL_URL", "https://gov-portal-simulator.vercel.app"),
        "authority": "FormPilot practice environment",
        "tld": "practice",
        "trust": 100,
        "advisory": "A safe practice portal for trying the full application flow. No real application is submitted.",
        "hindi_advisory": "Yeh ek practice portal hai. Yahan koi asli application submit nahi hoti.",
    },
]

OFFICIAL_SUFFIXES = (".gov.in", ".nic.in", ".ac.in", ".edu.in", ".gov", ".nic")


def _hostname(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
        return (parsed.hostname or "").lower()
    except Exception:
        return ""


def is_official_host(hostname: str) -> bool:
    hostname = (hostname or "").lower()
    return hostname.endswith(OFFICIAL_SUFFIXES)


def is_practice_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
        hostname = (parsed.hostname or "").lower()
    except Exception:
        return False
    if hostname in {"localhost", "127.0.0.1"} or hostname.endswith(".local"):
        return True
    practice_host = _hostname(getattr(settings, "PRACTICE_PORTAL_URL", ""))
    if practice_host and hostname == practice_host:
        return True
    if "gov-portal-simulator" in hostname:
        return True
    return False


class PortalOracle:
    """Resolve a natural-language request or URL into a verified portal."""

    @staticmethod
    def audit_url(url: str) -> Dict[str, Any]:
        hostname = _hostname(url)
        is_practice = is_practice_url(url)
        is_local = hostname in {"localhost", "127.0.0.1"} or hostname.endswith(".local") or is_practice
        is_gov = is_official_host(hostname)
        third_party = bool(hostname) and not is_gov and not is_local

        if is_gov:
            trust_score = 99
        elif is_local:
            trust_score = 100
        elif third_party:
            trust_score = 60
        else:
            trust_score = 40

        return {
            "hostname": hostname,
            "is_gov": is_gov,
            "is_aggregator": third_party,
            "is_local": is_local,
            "is_practice": is_practice,
            "trust_score": trust_score,
            "scheme": urllib.parse.urlparse(url).scheme or "https",
        }

    @staticmethod
    def _looks_like_bare_domain(text: str) -> bool:
        """True for ``jeeadv.ac.in`` / ``example.gov.in/path`` without a scheme.

        A candidate often pastes the address bar contents with the scheme
        stripped.  Treat that as a direct URL instead of an unknown query so it
        does not depend on live search being available.
        """
        value = (text or "").strip()
        if not value or " " in value or value.startswith(("/", ".")):
            return False
        return bool(
            re.fullmatch(
                r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}(?:[/?#][^\s]*)?",
                value,
                re.IGNORECASE,
            )
        )

    @classmethod
    def _registry_match(cls, text: str) -> Optional[Dict[str, Any]]:
        lower = (text or "").lower().strip()
        if not lower:
            return None
        for entry in OFFICIAL_PORTAL_REGISTRY:
            for keyword in entry["keywords"]:
                # Word boundaries stop "jee" from matching inside "jeevan" and
                # keep a two-word keyword from matching as a substring.
                pattern = r"(?<![a-z0-9])" + re.escape(keyword.lower()) + r"(?![a-z0-9])"
                if re.search(pattern, lower):
                    return entry
        return None

    @classmethod
    def resolve_nta_live_application_url(cls, cms_url: str) -> str:
        """Dynamically resolve active examinationservices.nic.in application link from NTA CMS."""
        if "jeemain.nta.nic.in" not in cms_url and "exams.nta.ac.in" not in cms_url:
            return cms_url
        try:
            req = urllib.request.Request(
                cms_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
            )
            with urllib.request.urlopen(req, timeout=4) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
                matches = re.findall(r'https://examinationservices\.nic\.in/[^"\'<>\s]*Home\.aspx[^"\'<>\s]*', html, re.I)
                if matches:
                    unique = list(dict.fromkeys(matches))
                    sorted_matches = sorted(
                        unique,
                        key=lambda x: re.findall(r'\d{4}', x)[-1] if re.findall(r'\d{4}', x) else '0',
                        reverse=True,
                    )
                    return sorted_matches[0].replace("&amp;", "&")
                m2 = re.search(r'href=["\'](https://examinationservices\.nic\.in/[^"\']*)["\']', html)
                if m2:
                    return m2.group(1).replace("&amp;", "&")
        except Exception:
            pass
        return cms_url

    @classmethod
    def _result_from_entry(
        cls,
        query: str,
        entry: Dict[str, Any],
        *,
        advisory: Optional[str] = None,
        hindi_advisory: Optional[str] = None,
        source_citation: str = "Verified official portal registry",
        resolved_via: str = "registry",
        confidence: int = 100,
    ) -> OracleResult:
        target_url = entry["url"]
        audit = cls.audit_url(target_url)
        is_practice = bool(audit["is_local"])
        return OracleResult(
            query=query,
            official_name=entry["name"],
            target_url=target_url,
            is_gov_domain=bool(audit["is_gov"]),
            domain_trust_score=int(entry["trust"]),
            authority_type=entry["authority"],
            domain_suffix=entry["tld"],
            advisory=advisory or entry["advisory"],
            hindi_advisory=hindi_advisory or entry["hindi_advisory"],
            source_citation=source_citation,
            official_verified=bool(audit["is_gov"]),
            is_practice=is_practice,
            confidence=confidence,
            resolved_via=resolved_via,
        )

    @classmethod
    def resolve_target(cls, user_input: str) -> OracleResult:
        """Synchronous registry/direct-URL resolution (used by tests and UI)."""
        cleaned = (user_input or "").strip()
        if not cleaned:
            return cls._no_match(cleaned, "Enter a portal name or official URL.")

        # Accept an address-bar paste such as "jeemain.nta.nic.in" without a
        # scheme.  This is a direct URL, not an unknown query.
        if cls._looks_like_bare_domain(cleaned):
            cleaned = "https://" + cleaned

        if cleaned.startswith(("http://", "https://")):
            audit = cls.audit_url(cleaned)
            hostname = audit["hostname"]

            if audit["is_local"]:
                return OracleResult(
                    query=cleaned,
                    official_name="FormPilot Practice Portal (Demo)",
                    target_url=cleaned,
                    is_gov_domain=False,
                    domain_trust_score=100,
                    authority_type="Practice / local demo",
                    domain_suffix="practice",
                    advisory=(
                        "This is a safe practice portal for trying the full application flow. "
                        "It is not a government website and no real application is submitted."
                    ),
                    hindi_advisory=(
                        "Yeh ek safe practice portal hai, government website nahi. "
                        "Yahan koi asli application submit nahi hoti."
                    ),
                    source_citation="FormPilot Practice Environment",
                    # A practice portal is by definition not an official
                    # government source, so this must stay False.
                    official_verified=False,
                    is_practice=True,
                    confidence=100,
                    resolved_via="practice_url",
                )

            # A third-party link that clearly references a known recruitment
            # body is redirected to the authoritative registry entry.
            if audit["is_aggregator"]:
                entry = cls._registry_match(cleaned)
                if entry:
                    return cls._result_from_entry(
                        cleaned,
                        entry,
                        advisory=f"Third-party link replaced with the official government link: {entry['url']}",
                        hindi_advisory=f"Third-party link hata kar official government link ({entry['url']}) use karein.",
                        source_citation="Domain check + government portal registry",
                        resolved_via="domain_guard",
                        confidence=98,
                    )

            return OracleResult(
                query=cleaned,
                official_name=f"Custom Portal ({hostname or 'unknown host'})",
                target_url=cleaned,
                is_gov_domain=audit["is_gov"],
                domain_trust_score=audit["trust_score"],
                authority_type="Government / Public Portal" if audit["is_gov"] else "Third-Party / Web Form",
                domain_suffix=hostname.split(".")[-1] if "." in hostname else "",
                advisory="Official government domain verified." if audit["is_gov"] else "This link is not a verified government domain. Continue only if you trust it.",
                hindi_advisory="Official government domain verify ho gaya hai." if audit["is_gov"] else "Yeh verified government domain nahi hai. Sirf tab continue karein jab aap is link par bharosa karte hain.",
                source_citation="Direct URL input and domain check",
                official_verified=audit["is_gov"],
                confidence=100 if audit["is_gov"] else 55,
                resolved_via="direct_url",
            )

        entry = cls._registry_match(cleaned)
        if entry:
            return cls._result_from_entry(cleaned, entry)

        return cls._no_match(
            cleaned,
            "No official portal was found for this request. Paste the official notification link.",
        )

    @classmethod
    async def resolve_target_live(
        cls,
        user_input: str,
        client: Optional[TinyFishClient] = None,
    ) -> OracleResult:
        """Resolve with the registry first, then TinyFish Search for unknowns."""
        cleaned = (user_input or "").strip()
        base = cls.resolve_target(cleaned)
        if base.target_url or not client or not client.is_configured:
            return base

        query = f"{cleaned} official recruitment notification"
        try:
            results = await client.search(
                query,
                location="IN",
                limit=8,
                purpose="Find the official government application portal for a candidate",
            )
        except TinyFishError as exc:
            return cls._no_match(cleaned, "Live search is unavailable right now. Paste the official notification link.")
        except Exception as exc:  # defensive: search must never break the run
            return cls._no_match(cleaned, "Live search is unavailable right now. Paste the official notification link.")

        official: list[dict[str, Any]] = []
        for result in results:
            url = str(result.get("url") or "")
            hostname = _hostname(url)
            if is_official_host(hostname):
                official.append(result)

        if not official:
            return cls._no_match(
                cleaned,
                "Live search found no official government link. Paste the official notification link.",
                candidates=results,
            )

        first = official[0]
        url = str(first.get("url") or "")
        title = str(first.get("title") or "Official government portal")
        hostname = _hostname(url)
        return OracleResult(
            query=cleaned,
            official_name=title,
            target_url=url,
            is_gov_domain=True,
            domain_trust_score=95,
            authority_type="Official government / academic domain",
            domain_suffix=hostname.split(".")[-1] if "." in hostname else "",
            advisory="Live web search found this official government domain. Confirm the notification and eligibility before applying.",
            hindi_advisory="Live search se official government domain mila hai. Apply karne se pehle notification aur eligibility check karein.",
            source_citation=f"Official web result: {title} — {url}",
            official_verified=False,
            confidence=85,
            resolved_via="tinyfish_search",
            candidates=official[:5],
        )

    @classmethod
    def _no_match(
        cls,
        query: str,
        advisory: str,
        *,
        candidates: Optional[list[dict[str, Any]]] = None,
    ) -> OracleResult:
        return OracleResult(
            query=query,
            official_name="Unverified portal",
            target_url="",
            is_gov_domain=False,
            domain_trust_score=0,
            authority_type="Unverified",
            domain_suffix="",
            advisory=advisory,
            hindi_advisory="Portal verify nahi ho paya. Official notification ka link paste karein.",
            source_citation="No official source matched",
            official_verified=False,
            confidence=0,
            resolved_via="unverified",
            candidates=candidates or [],
        )

    @staticmethod
    def directory() -> List[Dict[str, Any]]:
        return [
            {
                "name": entry["name"],
                "url": entry["url"],
                "authority": entry["authority"],
                "keywords": entry["keywords"],
            }
            for entry in OFFICIAL_PORTAL_REGISTRY
        ]
