"""Tier-1 portal (BFF).

Serves the static visitor frontend and proxies the visitor's *allowlisted* action
requests to the trusted Tier-2 backend. This tier holds NOTHING — no Proxmox
token, no SOPS key, no SSH key, no route to the lab network. It resolves the
visitor's identity/role and forwards them as trusted headers; the backend
enforces the allowlist + guardrails. A compromised portal can therefore only ever
*ask* for actions that already exist, at the role a visitor is granted.

Identity comes ONLY from the edge: BunkerWeb runs the Authentik auth subrequest
and copies the verified email/groups upstream as X-Forwarded-Email/-Groups,
stripping any client-supplied copies. From those we derive:

- role:            admin iff member of ADMIN_GROUP (default lab-admins)
- booking-exempt:  member of BOOKING_EXEMPT_GROUPS (default lab-admins,
                   lab-approved — the tester override group)

Everyone else is a visitor whose MUTATING actions require a booked session that
is active right now (enforced by the backend; the UI mirrors it).

Run:  uvicorn portal:app --host 0.0.0.0 --port 8080
Env:  BACKEND_URL (default http://127.0.0.1:8000) — the Tier-2 backend.
      ADMIN_GROUP / BOOKING_EXEMPT_GROUPS / BOOK_URL — see defaults above/below.
"""
import os
import uuid

import httpx
from fastapi import Cookie, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

BACKEND = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

ADMIN_GROUP = os.environ.get("ADMIN_GROUP", "lab-admins")
EXEMPT_GROUPS = {g.strip() for g in os.environ.get(
    "BOOKING_EXEMPT_GROUPS", "lab-admins,lab-approved").split(",") if g.strip()}
BOOK_URL = os.environ.get(
    "BOOK_URL", "https://book.labaccessnow.com/labaccessnow/self-service-lab")
# The embedded-outpost sign-out path; the edge proxies /outpost.goauthentik.io/.
SIGN_OUT_PATH = "/outpost.goauthentik.io/sign_out"

app = FastAPI(title="ise-lab-demo portal", docs_url=None, redoc_url=None)
_client = httpx.AsyncClient(base_url=BACKEND, timeout=300.0)


@app.middleware("http")
async def _revalidate_static(request: Request, call_next):
    # Make browsers revalidate the SPA assets so a deploy never leaves a visitor on
    # a stale app.js (which once showed the full lab before the booking gate loaded).
    resp = await call_next(request)
    p = request.url.path
    if p == "/" or p.endswith((".js", ".css", ".html")):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


def _identity(request: Request) -> tuple[str, set[str]]:
    """Edge-verified identity (email, groups). Absent headers (edge not yet
    forwarding identity) just mean anonymous — never an error."""
    email = (request.headers.get("X-Forwarded-Email") or "").strip().lower()
    raw = request.headers.get("X-Forwarded-Groups") or ""
    groups = {g.strip() for part in raw.split("|") for g in part.split(",") if g.strip()}
    return email, groups


def _role(groups: set[str]) -> str:
    return "admin" if ADMIN_GROUP in groups else "visitor"


def _client_ip(request: Request) -> str:
    # The edge (BunkerWeb) sets X-Forwarded-For with the real visitor IP as the first
    # hop; fall back to the direct peer. The backend rate-limits mutating actions on
    # this, so a client can't dodge the cap by rotating a self-chosen session id.
    xff = request.headers.get("X-Forwarded-For", "")
    return (xff.split(",")[0].strip() if xff else "") or (request.client.host if request.client else "")


async def _proxy(method: str, path: str, request: Request, sid: str, json_body=None) -> JSONResponse:
    email, groups = _identity(request)
    headers = {
        "X-Role": _role(groups),
        "X-Session": sid,
        "X-Client-IP": _client_ip(request),
        "X-Identity-Email": email,
        "X-Booking-Exempt": "1" if (EXEMPT_GROUPS & groups) else "0",
    }
    try:
        r = await _client.request(method, path, headers=headers, json=json_body)
    except httpx.HTTPError as e:
        return JSONResponse(status_code=502, content={"detail": f"backend unreachable: {e.__class__.__name__}"})
    try:
        body = r.json()
    except Exception:
        body = {"detail": "backend returned non-JSON"}
    resp = JSONResponse(status_code=r.status_code, content=body)
    resp.set_cookie("sid", sid, httponly=True, samesite="lax", max_age=86400)
    return resp


@app.get("/api/me")
async def me(request: Request):
    """Who the edge says you are + your booking picture — drives the landing UI
    (book CTA / countdown / unlocked lab). Never includes a session token."""
    email, groups = _identity(request)
    booking = {"state": "none"}
    if email:
        try:
            r = await _client.get("/api/booking-state",
                                  headers={"X-Identity-Email": email})
            if r.status_code == 200:
                booking = r.json()
        except httpx.HTTPError:
            pass
    return {"email": email, "role": _role(groups),
            "booking_exempt": bool(EXEMPT_GROUPS & groups),
            "booking": booking, "book_url": BOOK_URL, "sign_out": SIGN_OUT_PATH}


@app.post("/api/book")
async def book(request: Request):
    """Book the lab for the signed-in visitor. Identity is taken ONLY from the
    edge-verified header and forwarded to the backend as X-Identity-Email; the
    client body may carry a start time and display name, never the email — so a
    visitor can only ever book the lab as themselves."""
    email, groups = _identity(request)
    if not email:
        return JSONResponse(status_code=401, content={"detail": "Sign in to book."})
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        r = await _client.post(
            "/api/book",
            headers={"X-Identity-Email": email},
            json={"start": (body or {}).get("start"), "name": (body or {}).get("name")},
        )
    except httpx.HTTPError as e:
        return JSONResponse(status_code=502, content={"detail": f"backend unreachable: {e.__class__.__name__}"})
    try:
        data = r.json()
    except Exception:
        data = {"detail": "backend returned non-JSON"}
    return JSONResponse(status_code=r.status_code, content=data)


@app.get("/api/actions")
async def actions(request: Request, sid: str = Cookie(None)):
    return await _proxy("GET", "/api/actions", request, sid or uuid.uuid4().hex)


@app.get("/api/catalog")
async def catalog(request: Request, sid: str = Cookie(None)):
    return await _proxy("GET", "/api/catalog", request, sid or uuid.uuid4().hex)


@app.get("/api/session/{token}")
async def session_check(token: str, request: Request):
    # Validate a booking handoff token (presence + expiry) against the backend.
    return await _proxy("GET", f"/api/session/{token}", request, token)


@app.post("/api/session/claim")
async def session_claim(request: Request):
    """Redeem the ?session= booking token against the edge-verified identity.

    The identity comes ONLY from the trusted forward-auth header that the edge sets
    from the Authentik auth subrequest (X-Forwarded-Email) — never from the client
    body. The edge MUST strip any client-supplied copy of this header (see infra
    notes). On success the booking token is consumed and we set an httponly `sid`
    cookie = the server-minted session id; the token never goes back to the client.
    """
    email, _ = _identity(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    token = (body or {}).get("token")
    try:
        r = await _client.post("/api/session/claim",
                               headers={"X-Identity-Email": email}, json={"token": token})
    except httpx.HTTPError as e:
        return JSONResponse(status_code=502, content={"detail": f"backend unreachable: {e.__class__.__name__}"})
    try:
        data = r.json()
    except Exception:
        data = {"detail": "backend returned non-JSON"}
    if r.status_code != 200:
        return JSONResponse(status_code=r.status_code, content=data)
    resp = JSONResponse(status_code=200, content={"ok": True, "lab": data["lab_id"],
                                                  "expires_at": data["expires_at"]})
    resp.set_cookie("sid", data["server_sid"], httponly=True, samesite="lax", max_age=86400)
    return resp


@app.post("/api/action/{action_id}")
async def action(action_id: str, request: Request, sid: str = Cookie(None)):
    try:
        body = await request.json()
    except Exception:
        body = None
    return await _proxy("POST", f"/api/action/{action_id}", request,
                        sid or uuid.uuid4().hex, json_body=body)


@app.get("/healthz")
async def healthz():
    try:
        r = await _client.get("/healthz")
        return {"portal": True, "backend": r.json()}
    except httpx.HTTPError as e:
        return JSONResponse(status_code=502, content={"portal": True, "backend_error": e.__class__.__name__})


# Static frontend last, so /api/* and /healthz match first.
app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
