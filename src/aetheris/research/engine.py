"""ResearchEngine — the fourth read-only advisor, pointed at the outside world.

Structural guarantee (verified adversarially in the test suite): the engine
holds **no** tool handle, **no** SafetyLayer (execution gate), **no** planner
mutator, **no** memory/skill/config writer, **no** executive. Its only outputs
are **frozen evidence objects** (``EvidenceBundle``). Its only side effects are
appending to its own read-only research journal and maintaining a bounded
content cache. There is no code path from an evidence object to an edit, a shell
command, a plan mutation, or a promotion, because evidence has no field that
expresses one and the engine holds no handle that performs one.

The pipeline is strictly one-directional and terminates in data:

    Query -> Search -> Fetch -> Extract -> Validate -> Cite -> EvidenceBundle

Nothing exists after ``EvidenceBundle``. The only way to reach the network is
``self._perimeter.fetch()``; every safety rule applies to every byte.
"""
from __future__ import annotations

import time
from typing import Any

from .journal import ResearchJournal
from .model import (
    Citation,
    DomainTrust,
    Provenance,
    RawResponse,
    ResearchFinding,
    ResearchQuery,
    ResearchRequest,
    ResearchSession,
    Source,
    EvidenceBundle,
    PerimeterDenied,
    BudgetExceeded,
    bundle_from_parts,
    content_hash,
)
from .perimeter import NetworkPerimeter


_TRUST_WEIGHT = {
    DomainTrust.ALLOWLISTED_PRIMARY: 1.0,
    DomainTrust.ALLOWLISTED_SECONDARY: 0.7,
}

_CACHE_CAP = 64


class ResearchEngine:
    """Gathers evidence behind the NetworkPerimeter. Incapable of acting."""

    def __init__(
        self,
        allowlist: tuple[str, ...],
        search_map: dict[str, list[str]] | None = None,
        perimeter: NetworkPerimeter | None = None,
        journal: ResearchJournal | None = None,
        transport: Any = None,
        primary_domains: tuple[str, ...] = (),
    ) -> None:
        self._allowlist = tuple(allowlist)
        self._search_map = dict(search_map or {})
        self._primary_domains = set(primary_domains or allowlist)
        self._perimeter = perimeter or NetworkPerimeter(self._allowlist, transport=transport)
        self._journal = journal
        self._cache: dict[str, RawResponse] = {}

    # ------------------------------------------------------------------ #
    # Public entry: the whole pipeline, terminating in EvidenceBundle      #
    # ------------------------------------------------------------------ #

    def research(
        self,
        query: "str | ResearchQuery",
        session: ResearchSession,
    ) -> EvidenceBundle:
        q = query if isinstance(query, ResearchQuery) else ResearchQuery(raw=query)
        self._journal and self._journal.record("query", {"session_id": session.session_id, "query": q.raw})

        requests = self._search(q)
        if not requests:
            # Honest: we couldn't establish anything from the available sources.
            bundle = bundle_from_parts(
                q.raw, (), (), (f"no allowlisted source for: {q.raw}",), session,
                dry_run=session.dry_run,
            )
            self._journal and self._journal.record(
                "bundle", {"session_id": session.session_id, "findings": 0, "unknowns": 1}
            )
            return bundle

        findings: list[ResearchFinding] = []
        contradictions: list[str] = []
        for req in requests:
            resp = self._fetch(req, session)
            if resp is None:
                continue
            for claim in self._extract(resp, q):
                finding = self._cite(claim, resp, req)
                if finding is not None:
                    findings.append(finding)

        # Contradiction detection: distinct claims about the same subject.
        contradictions = self._detect_contradictions(findings, q)
        unknowns: list[str] = []
        if not findings:
            unknowns.append(f"no extractable evidence for: {q.raw}")

        bundle = bundle_from_parts(
            q.raw, tuple(findings), tuple(contradictions), tuple(unknowns), session,
            dry_run=session.dry_run,
        )
        self._journal and self._journal.record(
            "bundle",
            {
                "session_id": session.session_id,
                "findings": len(findings),
                "contradictions": len(contradictions),
                "unknowns": len(unknowns),
                "requests_made": session.requests_made,
                "bytes_fetched": session.bytes_fetched,
            },
        )
        return bundle

    # ------------------------------------------------------------------ #
    # Pipeline stages                                                     #
    # ------------------------------------------------------------------ #

    def _search(self, q: ResearchQuery) -> list[ResearchRequest]:
        """Deterministic mapping from a query to allowlisted doc URLs.

        Minimal-first: no general crawler. Known query substrings map to
        allowlisted documentation URLs; anything else yields no candidates and
        becomes an explicit unknown.
        """
        out: list[ResearchRequest] = []
        for key, urls in self._search_map.items():
            if key and key in q.normalized:
                for url in urls:
                    if urlparse(url).netloc in self._allowlist:
                        out.append(ResearchRequest(url=url))
        return out

    def _fetch(self, req: ResearchRequest, session: ResearchSession) -> RawResponse | None:
        """The ONLY egress. Returns None on any deny (gracefully recorded)."""
        try:
            resp = self._perimeter.fetch(req, session)
        except PerimeterDenied as exc:
            self._journal and self._journal.record(
                "perimeter_denied",
                {"session_id": session.session_id, "url": req.url, "reason": str(exc)},
            )
            return None
        except BudgetExceeded:
            # Session closed: stop fetching, leave whatever we have.
            return None
        ch = content_hash(resp.content)
        self._journal and self._journal.record(
            "perimeter_allowed",
            {
                "session_id": session.session_id, "url": resp.final_url,
                "content_hash": ch, "bytes": len(resp.content),
                "mime": resp.content_type,
            },
        )
        # Bounded content cache (content-addressed).
        if ch not in self._cache:
            if len(self._cache) >= _CACHE_CAP:
                self._cache.pop(next(iter(self._cache)))
            self._cache[ch] = resp
        return resp

    def _extract(self, resp: RawResponse, q: ResearchQuery) -> list[str]:
        """Deterministic extraction of candidate claims from bounded content."""
        text = resp.content.decode("utf-8", errors="replace")
        sentences = [s.strip() for s in text.replace("\n", " ").split(".") if s.strip()]
        keywords = [w for w in q.normalized.split() if len(w) > 3]
        kept: list[str] = []
        for s in sentences:
            low = s.lower()
            if any(k in low for k in keywords) or "signature" in low or "caused by" in low:
                kept.append(s)
        return kept or sentences[:1]

    def _cite(self, claim: str, resp: RawResponse, req: ResearchRequest) -> ResearchFinding | None:
        domain = urlparse(resp.final_url).netloc
        if not domain:
            domain = req.domain
        trust = (
            DomainTrust.ALLOWLISTED_PRIMARY if domain in self._primary_domains
            else DomainTrust.ALLOWLISTED_SECONDARY
        )
        src = Source(
            domain=domain, trust=trust,
            why_trusted=f"on allowlist as official docs ({trust.value})",
        )
        prov = Provenance(
            domain=domain, url=resp.final_url, fetched_at=time.time(),
            from_cache=resp.from_cache, content_hash=content_hash(resp.content),
            perimeter_decision="allowed",
        )
        citation = Citation(
            title=domain, url=resp.final_url, quote=claim, locator="extracted-span",
        )
        return ResearchFinding(
            claim=claim, source=src, citation=citation, provenance=prov,
            confidence=self._confidence(trust, resp), freshness=self._freshness(prov),
        )

    # ------------------------------------------------------------------ #
    # Confidence / honesty helpers (deterministic)                        #
    # ------------------------------------------------------------------ #

    def _confidence(self, trust: DomainTrust, resp: RawResponse) -> float:
        base = _TRUST_WEIGHT.get(trust, 0.5)
        return round(min(1.0, base), 4)

    def _freshness(self, prov: Provenance) -> float:
        age_s = time.time() - prov.fetched_at
        return round(max(0.0, min(1.0, 1.0 - age_s / (24 * 3600))), 4)

    def _detect_contradictions(self, findings: list[ResearchFinding], q: ResearchQuery) -> list[str]:
        """Flag distinct claims about the same subject as a contradiction."""
        by_subject: dict[str, set[str]] = {}
        for f in findings:
            subject = self._subject_of(f.claim, q)
            by_subject.setdefault(subject, set()).add(f.claim.strip().lower())
        out: list[str] = []
        for subject, claims in by_subject.items():
            if len(claims) > 1:
                out.append(f"sources disagree on '{subject}': {sorted(claims)}")
        return out

    def _subject_of(self, claim: str, q: ResearchQuery) -> str:
        for w in q.normalized.split():
            if len(w) > 3 and w in claim.lower():
                return w
        return q.normalized


def urlparse(url: str):  # local import shim to avoid top-level urllib in hot path
    from urllib.parse import urlparse as _up
    return _up(url)
