#!/usr/bin/env python3
"""
LinkedIn OAuth 2.0 authorization for SynterAI org posting.

Starts a local server on port 8080, opens LinkedIn consent page,
catches the callback, and exchanges for access + refresh tokens.

Usage:
    export LINKEDIN_CLIENT_SECRET=$(doppler secrets get LINKEDIN_CLIENT_SECRET --project synter-media --config prd --plain)
    python3 scripts/linkedin_auth.py
"""

import http.server
import json
import os
import sys
import urllib.parse
import urllib.request
import webbrowser

CLIENT_ID = os.environ.get("LINKEDIN_CLIENT_ID", "86jcu6xeaod28m")
CLIENT_SECRET = os.environ.get("LINKEDIN_CLIENT_SECRET", "")
REDIRECT_URI = "http://localhost:8080/callback"
SCOPES = "openid profile email w_organization_social r_organization_social w_member_social"

if not CLIENT_SECRET:
    print("Set LINKEDIN_CLIENT_SECRET first:")
    print("  export LINKEDIN_CLIENT_SECRET=$(doppler secrets get LINKEDIN_CLIENT_SECRET --project synter-media --config prd --plain)")
    sys.exit(1)


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    code = None

    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if "code" in params:
            CallbackHandler.code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>LinkedIn authorized! Close this tab.</h1>")
        else:
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(f"<h1>Error: {params}</h1>".encode())

    def log_message(self, *args):
        pass


def main():
    auth_url = (
        "https://www.linkedin.com/oauth/v2/authorization?"
        + urllib.parse.urlencode({
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
        })
    )

    print(f"\nOpening browser for LinkedIn authorization...")
    webbrowser.open(auth_url)

    server = http.server.HTTPServer(("localhost", 8080), CallbackHandler)
    print("Waiting for callback on localhost:8080...")
    while CallbackHandler.code is None:
        server.handle_request()

    print(f"Got code, exchanging for tokens...")

    token_data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": CallbackHandler.code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }).encode()

    req = urllib.request.Request(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data=token_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    try:
        resp = urllib.request.urlopen(req, timeout=15)
    except urllib.error.HTTPError as e:
        print(f"Error {e.code}: {e.read().decode()}")
        sys.exit(1)

    tokens = json.loads(resp.read())
    access_token = tokens.get("access_token", "")
    refresh_token = tokens.get("refresh_token", "")
    expires_in = tokens.get("expires_in", 0)

    print(f"\n{'='*60}")
    print(f"Access Token:  {access_token[:40]}... ({expires_in//86400}d)")
    print(f"Refresh Token: {refresh_token[:40]}..." if refresh_token else "Refresh Token: (none)")
    print(f"Scope: {tokens.get('scope', 'n/a')}")
    print(f"{'='*60}")

    print(f"\nAdd to Doppler:")
    cmd = f'doppler secrets set LINKEDIN_ACCESS_TOKEN="{access_token}"'
    if refresh_token:
        cmd += f' LINKEDIN_REFRESH_TOKEN="{refresh_token}"'
    cmd += " --project synter-media --config prd"
    print(f"  {cmd}")


if __name__ == "__main__":
    main()
