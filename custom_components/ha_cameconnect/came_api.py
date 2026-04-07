"""
Async CAME Connect API client.

Handles:
- OAuth2 Authorization Code + PKCE flow
- Token persistence via hass.storage
- Automatic token refresh on 401
- Device status polling
- Command execution (multi-endpoint fallback)
- Maneuver counter decoding
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import secrets
import json as _json
import time
from typing import Any
from urllib.parse import quote as urlquote

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    API_BASE_CANDIDATES,
    CODE_MAP,
    OAUTH_AUTH_CODE_SUFFIX,
    OAUTH_REDIRECT_URI,
    OAUTH_TOKEN_SUFFIX,
    STORAGE_KEY,
    STORAGE_VERSION,
    STATE_MOVING,
    STATE_UNKNOWN,
)

_LOGGER = logging.getLogger(__name__)

# Lock to prevent concurrent token refreshes
_TOKEN_LOCK: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    global _TOKEN_LOCK
    if _TOKEN_LOCK is None:
        _TOKEN_LOCK = asyncio.Lock()
    return _TOKEN_LOCK


# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _pkce_pair() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(32)).replace("-", "").replace("_", "")
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _basic_auth(client_id: str, client_secret: str) -> str:
    raw = f"{client_id}:{client_secret}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


# ---------------------------------------------------------------------------
# CameConnectClient
# ---------------------------------------------------------------------------

class CameConnectClient:
    """
    Async client for the CAME Connect cloud API.

    One instance per config entry (= one set of CAME credentials).
    Multiple devices share the same client / token.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client_id: str,
        client_secret: str,
        username: str,
        password: str,
        entry_id: str,
        session: aiohttp.ClientSession | None = None,  # unused, kept for API compat
    ) -> None:
        self._hass = hass
        # Dedicated session with own connector for CAME cloud calls.
        # Avoids restrictions that HA may apply to its shared session.
        self._session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=True),
        )
        self._client_id = client_id
        self._client_secret = client_secret
        self._username = username
        self._password = password
        # Per-entry storage key so multiple accounts don't collide
        self._store: Store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}_{entry_id}")
        self._token: dict[str, Any] | None = None
        self._base: str = API_BASE_CANDIDATES[0]

    async def async_close(self) -> None:
        """Close the dedicated aiohttp session."""
        if not self._session.closed:
            await self._session.close()

    async def async_delete_storage(self) -> None:
        """Delete the persisted token from hass.storage (cleanup after temp clients)."""
        await self._store.async_remove()

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    async def _load_token(self) -> None:
        """Load persisted token from hass.storage."""
        data = await self._store.async_load()
        if data and data.get("access_token"):
            self._token = data
            # Do NOT restore _base from the saved token: the base that worked
            # during config-flow setup may differ from what is reachable at
            # runtime (e.g. beta.* vs app.*). Always rediscover on first use.
            self._base = API_BASE_CANDIDATES[0]
            _LOGGER.debug("CAME Connect: token loaded from storage, base reset to %s", self._base)

    async def _save_token(self, tok: dict[str, Any]) -> None:
        await self._store.async_save(tok)

    def _token_valid(self) -> bool:
        """True if we have a token that isn't obviously expired."""
        if not self._token or not self._token.get("access_token"):
            return False
        exp = self._token.get("exp") or self._token.get("expires_at")
        if exp:
            # Leave a 60-second safety margin
            return time.time() < float(exp) - 60
        return True  # No expiry info — assume valid, refresh on 401

    async def _fetch_token(self) -> None:
        """
        Full OAuth2 Authorization Code + PKCE flow.
        Tries both app.* and beta.* base URLs.
        Raises CameAuthError on failure.
        """
        verifier, challenge = _pkce_pair()
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
            "Authorization": _basic_auth(self._client_id, self._client_secret),
        }
        # Use safe='@:' to preserve characters that CAME expects unencoded
        # (email addresses contain @ which must NOT be percent-encoded here)
        auth_code_body = (
            f"grant_type=authorization_code"
            f"&username={urlquote(self._username, safe='@')}"
            f"&password={urlquote(self._password, safe='')}"
            f"&client_id={urlquote(self._client_id, safe='')}"
        )
        params = {
            "client_id": self._client_id,
            "response_type": "code",
            "redirect_uri": OAUTH_REDIRECT_URI,
            "state": secrets.token_urlsafe(16),
            "nonce": secrets.token_urlsafe(8),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }

        last_err = "no candidates tried"
        for base in API_BASE_CANDIDATES:
            # Use a fresh single-use session with cookie jar so that auth-code
            # and token exchange share cookies/TCP — same behaviour as the
            # original httpx.Client(follow_redirects=True) context manager.
            jar = aiohttp.CookieJar()
            async with aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=True),
                cookie_jar=jar,
            ) as s:
                try:
                    # Step 1 — authorization code
                    _LOGGER.debug(
                        "CAME OAuth auth-code request: url=%s params=%s body=%s",
                        base + OAUTH_AUTH_CODE_SUFFIX, params, auth_code_body,
                    )
                    r = await s.post(
                        base + OAUTH_AUTH_CODE_SUFFIX,
                        data=auth_code_body,
                        headers=headers,
                        params=params,
                        timeout=aiohttp.ClientTimeout(total=30),
                        allow_redirects=True,
                    )
                    r_text = await r.text()
                    _LOGGER.debug("CAME OAuth auth-code raw response [%s]: %s", base, r_text)
                    if r.status != 200:
                        last_err = f"{base} auth-code HTTP {r.status}: {r_text}"
                        _LOGGER.debug("CAME OAuth auth-code failed: %s", last_err)
                        continue
                    try:
                        data = _json.loads(r_text)
                    except Exception:
                        last_err = f"{base} auth-code: invalid JSON: {r_text}"
                        _LOGGER.debug("CAME OAuth: %s", last_err)
                        continue

                    code = (
                        data.get("code")
                        or data.get("authorization_code")
                        or data.get("Code")
                    )
                    if not code:
                        last_err = f"{base} auth-code: no code in response: {data}"
                        _LOGGER.debug("CAME OAuth: %s", last_err)
                        continue

                    _LOGGER.debug(
                        "CAME OAuth code obtained [%s]: %s | cookies: %s",
                        base, code, [(c.key, c.value) for c in s.cookie_jar],
                    )

                    # Step 2 — token exchange on the same session (preserves cookies).
                    # Try multiple combinations: CAME may require a specific redirect_uri
                    # and may or may not validate the code_verifier here.
                    REDIRECT_CANDIDATES = [
                        "https://www.cameconnect.net/role",
                        "https://app.cameconnect.net/role",
                        "https://beta.cameconnect.net/role",
                    ]
                    tr_text = None
                    token_attempts = []
                    for redir in REDIRECT_CANDIDATES:
                        token_attempts.append({
                            "grant_type": "authorization_code",
                            "code": code,
                            "redirect_uri": redir,
                            "code_verifier": verifier,
                        })
                        token_attempts.append({
                            "grant_type": "authorization_code",
                            "code": code,
                            "redirect_uri": redir,
                        })
                    # Also try without redirect_uri entirely
                    token_attempts.append({
                        "grant_type": "authorization_code",
                        "code": code,
                        "code_verifier": verifier,
                    })
                    token_attempts.append({
                        "grant_type": "authorization_code",
                        "code": code,
                    })
                    for token_body in token_attempts:
                        _LOGGER.debug(
                            "CAME OAuth token exchange body [%s]: %s",
                            base, token_body,
                        )
                        tr = await s.post(
                            base + OAUTH_TOKEN_SUFFIX,
                            data=token_body,
                            headers=headers,
                            timeout=aiohttp.ClientTimeout(total=30),
                        )
                        tr_text = await tr.text()
                        if tr.status == 200:
                            break
                        _LOGGER.debug(
                            "CAME OAuth token exchange attempt failed %s: %s",
                            base, tr_text,
                        )
                    if tr.status != 200:
                        last_err = f"{base} token HTTP {tr.status}: {tr_text}"
                        _LOGGER.debug("CAME OAuth token exchange failed: %s", last_err)
                        continue
                    try:
                        tok = _json.loads(tr_text)
                    except Exception:
                        last_err = f"{base} token: invalid JSON: {tr_text}"
                        _LOGGER.debug("CAME OAuth: %s", last_err)
                        continue

                    tok["_base"] = base
                    tok["_fetched_at"] = time.time()
                    if "expires_in" in tok and "exp" not in tok:
                        tok["exp"] = time.time() + int(tok["expires_in"])

                    self._token = tok
                    self._base = base
                    await self._save_token(tok)
                    _LOGGER.info("CAME Connect: token obtained from %s", base)
                    return

                except aiohttp.ClientError as exc:
                    last_err = f"{base} network error: {exc}"
                    _LOGGER.debug("CAME OAuth network error: %s", last_err)

        raise CameAuthError(f"OAuth2 failed on all candidates: {last_err}")

    async def async_ensure_token(self) -> str:
        """Return a valid access token, refreshing if necessary."""
        async with _get_lock():
            if not self._token:
                await self._load_token()
            if not self._token:
                await self._fetch_token()
            elif not self._token_valid():
                _LOGGER.debug("CAME Connect: token expired, re-authenticating")
                await self._fetch_token()
        return self._token["access_token"]  # type: ignore[index]

    # ------------------------------------------------------------------
    # Low-level request helper
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        url: str,
        *,
        payload: Any = None,
        _retry: bool = True,
    ) -> aiohttp.ClientResponse:
        """
        Authenticated request with one auto-retry on 401 or network error.
        On network failure, re-authenticates (which rediscovers the working base URL)
        and retries once before giving up.
        Returns the response object.
        """
        access = await self.async_ensure_token()
        headers = {
            "Authorization": f"Bearer {access}",
            "Accept": "application/json",
        }
        kwargs: dict[str, Any] = {"headers": headers, "timeout": aiohttp.ClientTimeout(total=15)}
        if method.upper() == "POST" and payload is not None:
            kwargs["json"] = payload

        try:
            resp = await self._session.request(method, url, **kwargs)
        except aiohttp.ClientError as exc:
            if _retry:
                _LOGGER.warning(
                    "CAME Connect: network error on %s (%s) — re-authenticating and retrying",
                    url, exc,
                )
                async with _get_lock():
                    await self._fetch_token()
                # Rebuild URL with potentially new base after re-auth
                new_url = url.replace(
                    next((b for b in API_BASE_CANDIDATES if url.startswith(b)), ""),
                    self._base,
                    1,
                )
                return await self._request(method, new_url, payload=payload, _retry=False)
            raise

        if resp.status == 401 and _retry:
            _LOGGER.debug("CAME Connect: 401 on %s — refreshing token", url)
            async with _get_lock():
                await self._fetch_token()
            new_url = url.replace(
                next((b for b in API_BASE_CANDIDATES if url.startswith(b)), ""),
                self._base,
                1,
            )
            return await self._request(method, new_url, payload=payload, _retry=False)

        return resp

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def async_test_credentials(self) -> bool:
        """
        Validate credentials by performing a full OAuth flow.
        Called during config flow setup. Raises CameAuthError on failure.
        """
        await self._fetch_token()
        return True

    async def async_get_status(self, device_id: int) -> dict[str, Any]:
        """
        Fetch and normalize gate status for a device.

        Returns:
            state: open | closed | opening | closing | stopped | moving | unknown
            position: 0..100 or None
            moving: bool
            direction: opening | closing | stopped | unknown
            online: bool
            raw_code: int | None
            updated_at: str | None
            maneuvers: int | None
        """
        url = f"{self._base}/automations/{device_id}/status"
        try:
            resp = await self._request("GET", url)
        except aiohttp.ClientError as exc:
            # _request already retried once; give up
            raise CameConnectionError(f"Network error fetching status: {exc}") from exc

        if resp.status != 200:
            raise CameConnectionError(f"Status endpoint returned HTTP {resp.status}")

        try:
            data = await resp.json(content_type=None)
        except Exception as exc:
            raise CameConnectionError(f"Invalid JSON from status endpoint: {exc}") from exc

        payload = data.get("Data") or {}
        online = bool(payload.get("Online", True))
        states = payload.get("States") or []
        by_cmd = {e.get("CommandId"): e for e in states if isinstance(e, dict)}

        # State from CommandId=1 Data[0]
        code: int | None = None
        pos_entry = by_cmd.get(1)
        if pos_entry and isinstance(pos_entry.get("Data"), list) and pos_entry["Data"]:
            try:
                code = int(pos_entry["Data"][0])
            except (TypeError, ValueError):
                code = None

        # Moving flag from CommandId=3
        moving_flag = False
        mv_entry = by_cmd.get(3)
        if mv_entry and isinstance(mv_entry.get("Data"), list) and mv_entry["Data"]:
            try:
                moving_flag = int(mv_entry["Data"][0]) == 1
            except (TypeError, ValueError):
                moving_flag = False

        state = CODE_MAP.get(code, STATE_UNKNOWN)
        if state == STATE_UNKNOWN and moving_flag:
            state = STATE_MOVING

        direction: str
        if state in ("opening", "closing"):
            direction = state
        elif state == "stopped":
            direction = "stopped"
        else:
            direction = "unknown"

        position: int | None
        if state == "open":
            position = 100
        elif state == "closed":
            position = 0
        else:
            position = None

        timestamps = []
        for e in (pos_entry, mv_entry):
            if e and e.get("UpdatedAt"):
                timestamps.append(e["UpdatedAt"])
        updated_at = max(timestamps) if timestamps else payload.get("ConfiguredLastUpdate")

        # Maneuver counter from CommandId=18
        maneuvers = _decode_maneuvers(states)
        if maneuvers is None:
            # Fallback: try alternative endpoints
            try:
                maneuvers = await self._async_fetch_maneuvers(device_id)
            except Exception:
                maneuvers = None

        return {
            "state": state,
            "position": position,
            "moving": state in ("opening", "closing") or moving_flag,
            "direction": direction,
            "online": online,
            "raw_code": code,
            "updated_at": updated_at,
            "maneuvers": maneuvers,
        }

    async def async_send_command(self, device_id: int, command_id: int) -> bool:
        """
        Send a command to a device, trying multiple endpoint variants.
        Returns True on success.
        """
        candidates = [
            ("POST", f"{self._base}/automations/{device_id}/commands/{command_id}", None),
            ("POST", f"{self._base}/devices/{device_id}/commands/{command_id}", None),
            ("GET",  f"{self._base}/devices/{device_id}/command/{command_id}", None),
        ]
        for method, url, payload in candidates:
            try:
                resp = await self._request(method, url, payload=payload)
                if resp.status in (200, 202, 204):
                    _LOGGER.debug(
                        "CAME command %s for device %s: OK via %s %s",
                        command_id, device_id, method, url,
                    )
                    return True
                _LOGGER.debug(
                    "CAME command %s candidate %s %s → HTTP %s",
                    command_id, method, url, resp.status,
                )
            except aiohttp.ClientError as exc:
                _LOGGER.debug("CAME command %s candidate error: %s", command_id, exc)

        _LOGGER.error(
            "CAME Connect: all command endpoints failed for device=%s command=%s",
            device_id, command_id,
        )
        return False

    async def _async_fetch_maneuvers(self, device_id: int) -> int | None:
        """Try alternative status endpoints to extract maneuver count."""
        candidates = [
            f"{self._base}/automations/{device_id}/info",
            f"{self._base}/devices/{device_id}/info",
            f"{self._base}/automations/{device_id}/status",
            f"{self._base}/devices/{device_id}/status",
            f"{self._base}/devicestatus?devices=%5B{device_id}%5D",
        ]
        for url in candidates:
            try:
                resp = await self._request("GET", url)
                if resp.status != 200:
                    continue
                j = await resp.json(content_type=None)
                data = j.get("Data")
                states: list | None = None
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    states = data[0].get("States")
                elif isinstance(data, dict):
                    states = data.get("States")
                if states:
                    result = _decode_maneuvers(states)
                    if result is not None:
                        return result
            except Exception:
                continue
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decode_maneuvers(states: list[dict]) -> int | None:
    """Decode maneuver counter from States/CommandId=18."""
    if not isinstance(states, list):
        return None
    state18 = next(
        (s for s in states if isinstance(s, dict) and s.get("CommandId") == 18), None
    )
    if not state18:
        return None
    d = state18.get("Data") or []
    if not (isinstance(d, list) and len(d) >= 8):
        return None
    try:
        return int(d[2]) * 256 + int(d[3]) + int(d[6]) * 256 + int(d[7])
    except (TypeError, ValueError, IndexError):
        return None


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class CameAuthError(Exception):
    """OAuth2 authentication failure."""


class CameConnectionError(Exception):
    """Network or API communication failure."""
