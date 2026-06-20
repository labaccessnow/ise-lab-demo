#!/usr/bin/env python3
"""Add the desktop.labaccessnow.com vhost to the home BunkerWeb (VM120).

Mirrors the lab.* forward-auth pattern but proxies to Guacamole (guacamole.internal:8080)
and sets a fixed REMOTE_USER:demo header on the upstream (header-auth SSO). Run on
the BunkerWeb host. Idempotent.
"""
import re
import shutil

F = "/home/james/bunkerweb/docker-compose.yml"
shutil.copy(F, F + ".bak.desktop")

BLOCK = '''      desktop.labaccessnow.com_AUTO_LETS_ENCRYPT: "yes"
      desktop.labaccessnow.com_USE_REVERSE_PROXY: "yes"
      desktop.labaccessnow.com_REVERSE_PROXY_HOST: "http://guacamole.internal:8080"
      desktop.labaccessnow.com_REVERSE_PROXY_URL: "/"
      desktop.labaccessnow.com_REVERSE_PROXY_WS: "yes"
      desktop.labaccessnow.com_REVERSE_PROXY_HEADERS: "REMOTE_USER demo"
      desktop.labaccessnow.com_USE_MODSECURITY: "no"
      desktop.labaccessnow.com_MAX_CLIENT_SIZE: "50m"
      desktop.labaccessnow.com_USE_BAD_BEHAVIOR: "no"
      desktop.labaccessnow.com_USE_LIMIT_REQ: "no"
      desktop.labaccessnow.com_USE_LIMIT_CONN: "no"
      desktop.labaccessnow.com_REVERSE_PROXY_AUTH_REQUEST: "/authentik-auth"
      desktop.labaccessnow.com_REVERSE_PROXY_AUTH_REQUEST_SIGNIN_URL: "https://desktop.labaccessnow.com/outpost.goauthentik.io/start?rd=$$scheme://$$host$$request_uri"
      desktop.labaccessnow.com_REVERSE_PROXY_HOST_1: "http://authentik.internal:9000"
      desktop.labaccessnow.com_REVERSE_PROXY_URL_1: "/outpost.goauthentik.io"
      desktop.labaccessnow.com_REVERSE_PROXY_HOST_999: "http://authentik.internal:9000/outpost.goauthentik.io/auth/nginx"
      desktop.labaccessnow.com_REVERSE_PROXY_URL_999: "/authentik-auth"
      desktop.labaccessnow.com_REVERSE_PROXY_HEADERS_999: "X-Original-URL $$scheme://$$http_host$$request_uri;Content-Length \\"\\""
'''

lines = open(F).read().splitlines(True)
if any(l.lstrip().startswith("desktop.labaccessnow.com_") for l in lines):
    print("desktop block already present")
else:
    out = []
    for l in lines:
        out.append(l)
        if l.lstrip().startswith("lab.labaccessnow.com_REVERSE_PROXY_HEADERS_999"):
            out.append(BLOCK)
    open(F, "w").write("".join(out))
    print("desktop block inserted")

txt = open(F).read()
sn = re.search(r'SERVER_NAME:\s*"[^"]*"', txt).group(0)
if "desktop.labaccessnow.com" not in sn:
    txt = re.sub(r'(SERVER_NAME:\s*"[^"]*)"', r'\1 desktop.labaccessnow.com"', txt, count=1)
    open(F, "w").write(txt)
    print("added desktop to SERVER_NAME")
else:
    print("desktop already in SERVER_NAME")

print("desktop vhost keys:", sum(1 for l in open(F) if l.lstrip().startswith("desktop.labaccessnow.com_")))
