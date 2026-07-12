"""The NetworkPerimeter — the single egress choke point.

This is the network analogue of the execution ``SafetyLayer``: deny-wins, one
gate, no other path out. Just as no tool executes except through
``SafetyLayer.run()``, **no byte leaves the machine except through
``NetworkPerimeter.fetch()``.**

It holds NO tool/edit/plan authority. Its maximal power is "permit an
allowlisted, HTTPS, budgeted byte to leave" — it grants no execution
authority. Every rule is checked *before* any egress; a denied request is a
``PerimeterDenied`` and is recorded as an unsafe attempt (so the adoption gate
can reject the run later, even though nothing left the machine).

The actual socket work is delegated to a ``transport`` callable
``(ResearchRequest) -> RawResponse``. The default transport uses the stdlib
``urllib`` and never attaches auth, cookies, or runs JavaScript. In tests a
fake transport is injected so the perimeter is exercised hermetically with
zero real egress.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

from .model import (
    BudgetExceeded,
    PerimeterDenied,
    RawResponse,
    ResearchRequest,
    ResearchSession,
)

# A transport performs the actual fetch and returns an immutable RawResponse.
Transport = Callable[[ResearchRequest], RawResponse]

_ALLOWED_MIME = frozenset({
    "text/html",
    "text/plain",
    "application/json",
    "text/markdown",
    "text/x-rst",
    "application/xml",
    "text/xml",
})

_REDIRECT_CAP = 4


@dataclass(frozen=True)
class _Decision:
    allowed: bool
    reason: str


class NetworkPerimeter:
    def __init__(
        self,
        allowlist: tuple[str, ...],
        transport: Transport | None = None,
        redirect_cap: int = _REDIRECT_CAP,
    ) -> None:
        self._allowlist = frozenset(allowlist)
        self._transport = transport or _urllib_transport
        self._redirect_cap = redirect_cap

    # ------------------------------------------------------------------ #
    # The single egress method                                            #
    # ------------------------------------------------------------------ #

    def fetch(self, req: ResearchRequest, session: ResearchSession) -> RawResponse:
        # Every request must be inside an explicit, still-open task session.
        if session is None or not session.still_open:
            if session is not None:
                session.unsafe_attempts += 1
            raise BudgetExceeded("session closed / request budget exhausted")

        # --- pre-egress deny-wins checks (no byte leaves yet) ---
        decision = self._evaluate(req, session)
        if not decision.allowed:
            # A denied egress *attempt* is still an unsafe request: it must be
            # visible to the adoption gate (the absolute clause), even though
            # nothing left the machine.
            session.unsafe_attempts += 1
            raise PerimeterDenied(decision.reason)

        if session.dry_run:
            # Preview exactly what WOULD be fetched; zero bytes leave.
            return RawResponse(
                url=req.url, final_url=req.url, status=0,
                content_type="text/plain", content=b"",
                from_cache=False, auth_sent=False, cookies_sent=False,
                js_executed=False,
            )

        # --- the only place bytes egress ---
        resp = self._transport(req)
        session.requests_made += 1
        session._request_times.append(time.time())
        session.bytes_fetched += len(resp.content)

        # --- post-egress deny-wins checks (MIME + size on the real response) ---
        self._validate_response(resp, session)
        return resp

    # ------------------------------------------------------------------ #
    # Deny-wins rule pipeline                                             #
    # ------------------------------------------------------------------ #

    def _evaluate(self, req: ResearchRequest, session: ResearchSession) -> _Decision:
        # 1) HTTPS only — plaintext is denied.
        if req.scheme != "https":
            return _Decision(False, f"plaintext scheme '{req.scheme}' denied (HTTPS only)")
        # 2) domain allowlist — deny-wins.
        if req.domain not in self._allowlist:
            return _Decision(False, f"domain '{req.domain}' not on allowlist")
        # 3) robots respect.
        if req.disallowed_by_robots:
            return _Decision(False, "disallowed by robots.txt")
        # 4) per-session request budget.
        if session.requests_made >= session.request_budget:
            return _Decision(False, "request budget exhausted")
        # 5) rate limit.
        if self._rate_exceeded(session):
            return _Decision(False, "rate limit exceeded")
        # 6) declared size over budget (pre-check; response is re-validated too).
        if req.declared_size is not None and req.declared_size > session.size_budget:
            return _Decision(False, "declared size over budget")
        return _Decision(True, "passed all perimeter rules")

    def _validate_response(self, resp: RawResponse, session: ResearchSession) -> None:
        # 6) MIME validation.
        ctype = (resp.content_type or "").split(";")[0].strip().lower()
        if ctype and ctype not in _ALLOWED_MIME:
            session.unsafe_attempts += 1
            raise PerimeterDenied(f"content type '{ctype}' not allowed")
        # 7) hard size cap.
        if len(resp.content) > session.size_budget:
            session.unsafe_attempts += 1
            raise PerimeterDenied("response over size budget")
        # 8) redirect cap / off-allowlist final hop.
        if resp.redirect_count > self._redirect_cap:
            session.unsafe_attempts += 1
            raise PerimeterDenied("too many redirects")
        final_domain = urlparse(resp.final_url).netloc
        if final_domain and final_domain not in self._allowlist:
            session.unsafe_attempts += 1
            raise PerimeterDenied(f"redirect left allowlist to '{final_domain}'")

    def _rate_exceeded(self, session: ResearchSession) -> bool:
        now = time.time()
        window = [t for t in session._request_times if now - t <= session.rate_window_s]
        session._request_times[:] = window
        return len(window) >= session.rate_budget

    def allowlist(self) -> frozenset[str]:
        return self._allowlist


def _urllib_transport(req: ResearchRequest) -> RawResponse:  # pragma: no cover - real egress
    """Default real transport. GET-only, no auth, no cookies, no JS.

    Used only when the engine is run against the live network; tests inject a
    fake transport so nothing actually leaves the machine. The perimeter's
    allowlist already guaranteed the URL is HTTPS + allowlisted before this
    runs, and re-checks the final redirect target afterward.
    """
    import urllib.request

    final_url = req.url
    redirect_count = 0
    content: bytes = b""
    content_type = "text/plain"
    last = None
    for _ in range(_REDIRECT_CAP + 1):
        r = urllib.request.urlopen(final_url, timeout=10)  # nosec - allowlisted only
        last = r
        content_type = r.headers.get("Content-Type", "text/plain")
        content = r.read()
        if r.geturl() != final_url:
            final_url = r.geturl()
            redirect_count += 1
            continue
        break
    return RawResponse(
        url=req.url, final_url=final_url, status=(last.status if last else 200),
        content_type=content_type, content=content,
        redirect_count=redirect_count, from_cache=False,
        auth_sent=False, cookies_sent=False, js_executed=False,
    )
