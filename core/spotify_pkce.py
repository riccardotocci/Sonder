"""Flusso Spotify "Authorization Code with PKCE" (per-utente, senza client secret).

Ogni visitatore della web app accede con il PROPRIO account Spotify: l'app usa solo
Il Client ID pubblico (nessun secret, nessun server dedicato). Il token risultante
abilita, lato browser, la ricerca dei brani nel catalogo Spotify.

Documentazione:
  https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow
"""
from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import urlencode

import requests

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"

# Permessi minimi: lettura profilo (ricerca brani col token utente) +
# user-top-read per derivare temi narrativi dagli ascolti reali (task 10).
SCOPES = "user-read-private user-top-read"


class SpotifyPKCEError(RuntimeError):
    """Errore durante il flusso PKCE."""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def make_verifier() -> str:
    """Genera un code_verifier PKCE (43-128 caratteri URL-safe)."""
    return _b64url(secrets.token_bytes(64))


def make_challenge(verifier: str) -> str:
    """Deriva il code_challenge S256 dal verifier."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return _b64url(digest)


def make_state() -> str:
    return secrets.token_urlsafe(24)


def build_auth_url(
    client_id: str,
    redirect_uri: str,
    state: str,
    challenge: str,
    show_dialog: bool = True,
) -> str:
    """Costruisce l'URL di autorizzazione verso il quale reindirizzare l'utente."""
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": SCOPES,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "show_dialog": "true" if show_dialog else "false",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(
    client_id: str, redirect_uri: str, code: str, verifier: str, timeout: int = 15
) -> dict:
    """Scambia il 'code' ricevuto al callback con un access token (PKCE, senza secret)."""
    try:
        resp = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "code_verifier": verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise SpotifyPKCEError(f"Errore di rete durante lo scambio del token: {exc}") from exc

    if resp.status_code != 200:
        raise SpotifyPKCEError(
            f"Scambio token fallito ({resp.status_code}): {resp.text[:200]}"
        )
    return resp.json()


def refresh_access_token(client_id: str, refresh_token: str, timeout: int = 15) -> dict:
    """Rinnova l'access token usando il refresh_token (PKCE, senza secret)."""
    try:
        resp = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise SpotifyPKCEError(f"Errore di rete durante il refresh del token: {exc}") from exc

    if resp.status_code != 200:
        raise SpotifyPKCEError(
            f"Refresh token fallito ({resp.status_code}): {resp.text[:200]}"
        )
    return resp.json()
