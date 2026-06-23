#!/usr/bin/env bash
# boundary_test.sh — adversarial visitor-boundary test for the ise-lab-demo enclave.
#
# The #1 requirement: a demo VISITOR (website-only access) must NOT pivot into internal
# infra, reach the internet from the enclave, or bypass the Tier-2 / edge locks. This
# harness asserts the network + ufw + edge-SSO boundaries. App-layer checks (allowlist
# 404 / role 403 / rate-limit 429 / single-flight 409) need an authenticated portal
# session — see docs/security-boundary-test.md.
#
# READ-ONLY: pings / curls / ssh-reads only; mutates nothing. Run from a mgmt host that
# can reach the enclave (e.g. the controller). Internal targets come from the gitignored
# .env (placeholders below) so no real IP is committed; public FQDNs are inline.
#
#   ./scripts/boundary_test.sh
set -uo pipefail

ENVF="$(cd "$(dirname "$0")/.." && pwd)/.env"
# shellcheck disable=SC1090
[ -f "$ENVF" ] && { set -a; . "$ENVF"; set +a; }

ENCLAVE_JUMPBOX="${ENCLAVE_JUMPBOX:-jumpbox.lab.example}"  # ssh target inside the enclave
ENCLAVE_ISE="${ENCLAVE_ISE:-ise.lab.example}"             # an intra-enclave host (should be reachable)
PROD_HOST="${PROD_HOST:-prod.lab.example}"                # a production host (must be UNreachable)
MGMT_HOST="${MGMT_HOST:-mgmt.lab.example}"                # a mgmt host (must be UNreachable from enclave)
BACKEND_HOST="${BACKEND_HOST:-backend.lab.example}"       # Tier-2 :8000 (portal-only)
GUAC_HOST="${GUAC_HOST:-guac.lab.example}"                # Guacamole :8080 (edge-only)
INTERNET_HOST="${INTERNET_HOST:-dns.google}"              # a name, not an IP literal
LAB_FQDN="lab.labaccessnow.com"
DESK_FQDN="desktop.labaccessnow.com"
IDP_FQDN="id.labaccessnow.com"

pass=0; fail=0
ok(){ printf '  \033[32mPASS\033[0m %s\n' "$1"; pass=$((pass + 1)); }
no(){ printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=$((fail + 1)); }

_ssh(){ ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=6 "$@"; }

enclave_blocked(){ local d="$1"; shift
  if _ssh "$ENCLAVE_JUMPBOX" "$@" >/dev/null 2>&1; then no "$d (reachable — ISOLATION HOLE)"; else ok "$d (blocked)"; fi; }
enclave_ok(){ local d="$1"; shift
  if _ssh "$ENCLAVE_JUMPBOX" "$@" >/dev/null 2>&1; then ok "$d (reachable as expected)"; else no "$d (unreachable — should work)"; fi; }

echo "== A. Network isolation (from the enclave jumpbox $ENCLAVE_JUMPBOX) =="
enclave_blocked "enclave -> internet"     "ping -c1 -W2 $INTERNET_HOST"
enclave_blocked "enclave -> prod"         "ping -c1 -W2 $PROD_HOST"
enclave_blocked "enclave -> mgmt"         "ping -c1 -W2 $MGMT_HOST"
enclave_ok      "enclave -> intra (ISE)"  "ping -c1 -W2 $ENCLAVE_ISE"

echo "== D. Tier-2 ufw locks (from this non-portal/non-edge host) =="
if curl -sk --max-time 6 "http://$BACKEND_HOST:8000/" >/dev/null 2>&1; then
  no "backend :8000 reachable from a non-portal host (ufw HOLE)"
else ok "backend :8000 blocked from non-portal host"; fi
if curl -sk --max-time 6 "http://$GUAC_HOST:8080/" >/dev/null 2>&1; then
  no "guacamole :8080 reachable from a non-edge host (ufw HOLE)"
else ok "guacamole :8080 blocked from non-edge host"; fi

echo "== F. Edge SSO (public) — an unauthenticated request must hit the IdP =="
for fqdn in "$LAB_FQDN" "$DESK_FQDN"; do
  read -r code loc < <(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' --max-time 10 "https://$fqdn/")
  if [ "$code" = "302" ] || [ "$code" = "301" ] || printf '%s' "$loc" | grep -q "$IDP_FQDN"; then
    ok "$fqdn unauth -> IdP ($code)"
  else no "$fqdn unauth did NOT gate (got $code, loc=$loc)"; fi
done

echo
echo "== summary: $pass passed, $fail failed =="
echo "Next: run the authenticated app-layer checks from docs/security-boundary-test.md"
echo "(allowlist 404 / role 403 / rate-limit 429 / single-flight 409)."
[ "$fail" -eq 0 ]
