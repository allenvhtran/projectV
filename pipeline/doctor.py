"""Preflight: check every credential and tool the pipeline needs.

Each check reports one of PASS / MISSING / FAIL and, when it isn't PASS, the
specific thing to do about it. Live calls are read-only and free -- the point
is to find a bad key now rather than nine minutes into a render.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from .config import ASSETS, ROOT, Config


def _reason(exc: Exception) -> str:
    """Network failures arrive wrapped in several layers of urllib3 detail that
    say nothing useful. Name the class of problem instead."""
    import requests

    if isinstance(exc, requests.exceptions.ProxyError):
        return "could not reach the API through the network proxy"
    if isinstance(exc, requests.exceptions.SSLError):
        return "TLS verification failed (corporate proxy or clock skew?)"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "could not reach the API (no network / DNS / firewall)"
    if isinstance(exc, requests.exceptions.Timeout):
        return "the API did not respond in time"
    return str(exc).split("\n")[0][:110]

PASS, MISS, FAIL, WARN = "PASS", "MISSING", "FAIL", "WARN"
MARK = {PASS: "  ok  ", MISS: " miss ", FAIL: " FAIL ", WARN: " warn "}


class Check:
    def __init__(self, name: str, status: str, detail: str = "", fix: str = ""):
        self.name, self.status, self.detail, self.fix = name, status, detail, fix


def _ffmpeg() -> Check:
    if shutil.which("ffmpeg"):
        return Check("ffmpeg", PASS, shutil.which("ffmpeg"))
    try:
        import imageio_ffmpeg

        return Check("ffmpeg", WARN, "bundled build only (no ffprobe)",
                     "brew install ffmpeg  /  apt-get install ffmpeg")
    except ImportError:
        return Check("ffmpeg", MISS, "not on PATH",
                     "brew install ffmpeg  /  apt-get install ffmpeg")


def _deps() -> list[Check]:
    out = []
    for mod, why in (("anthropic", "script + metadata"), ("requests", "voice + images"),
                     ("yaml", "config"), ("PIL", "dry-run cards"),
                     ("googleapiclient", "upload")):
        try:
            __import__(mod)
            out.append(Check(f"python: {mod}", PASS, why))
        except ImportError:
            out.append(Check(f"python: {mod}", MISS, why,
                             "pip install -r requirements.txt"))
    return out


def _anthropic() -> Check:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return Check("Anthropic", MISS, "ANTHROPIC_API_KEY not set",
                     "console.anthropic.com -> API keys; add to .env")
    try:
        from anthropic import Anthropic

        models = Anthropic(api_key=key).models.list(limit=1)
        return Check("Anthropic", PASS, f"key valid ({models.data[0].id} reachable)")
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "authentication_error" in msg or "401" in msg:
            return Check("Anthropic", FAIL, "401 - API key is invalid",
                         "console.anthropic.com -> API keys; regenerate")
        if "credit" in msg.lower() or "quota" in msg.lower():
            return Check("Anthropic", FAIL, "key valid but out of credit",
                         "console.anthropic.com -> Billing")
        return Check("Anthropic", FAIL, _reason(exc),
                     "check the key is active and has credit")


def _elevenlabs() -> list[Check]:
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        return [Check("ElevenLabs", MISS, "ELEVENLABS_API_KEY not set",
                      "elevenlabs.io -> Profile -> API Keys; add to .env")]
    try:
        import requests

        r = requests.get("https://api.elevenlabs.io/v1/user/subscription",
                         headers={"xi-api-key": key}, timeout=20)
        if r.status_code == 401:
            return [Check("ElevenLabs", FAIL, "401 - key not recognised",
                          "regenerate the key at elevenlabs.io -> Profile -> API Keys")]
        if r.status_code == 403:
            # A 403 can come from ElevenLabs (scoped key missing a permission)
            # or from something in between (corporate proxy, egress filter,
            # firewall). They need opposite fixes, and blaming the key for a
            # blocked network sends you to regenerate a key that was fine.
            # ElevenLabs answers with a JSON body; an intermediary rarely does.
            body = r.text[:200]
            looks_like_elevenlabs = "detail" in body or "status" in body
            if not looks_like_elevenlabs:
                return [Check(
                    "ElevenLabs", FAIL,
                    "403 from an intermediary, not from ElevenLabs",
                    "Something between you and the API refused the connection "
                    "(proxy, VPN, egress filter). The key is not implicated. "
                    f"Response was: {body!r}")]
            return [Check(
                "ElevenLabs", FAIL,
                "403 - key is recognised but lacks permission for this call",
                "The key was created with scopes disabled. At elevenlabs.io -> "
                "Profile -> API Keys, edit it (or make a new one) with "
                "'User: read', 'Models: read', 'Voices: read' and "
                "'Text to Speech' enabled.")]
        r.raise_for_status()
        sub = r.json()
        tier = sub.get("tier", "?")
        used, limit = sub.get("character_count", 0), sub.get("character_limit", 0)
        checks = [Check("ElevenLabs", PASS,
                        f"tier={tier}, {used:,}/{limit:,} chars used")]
        if tier in ("free", "starter"):
            checks.append(Check("ElevenLabs licence", WARN,
                                f"tier '{tier}' - free has no commercial licence",
                                "Creator ($22) or above before monetising"))
    except Exception as exc:  # noqa: BLE001
        return [Check("ElevenLabs", FAIL, _reason(exc), "")]

    voice = os.environ.get("ELEVENLABS_VOICE_ID")
    if not voice:
        checks.append(Check("ElevenLabs voice", MISS, "ELEVENLABS_VOICE_ID not set",
                            "python -m pipeline.cli voices  -> paste an id into .env"))
    else:
        try:
            vr = requests.get(f"https://api.elevenlabs.io/v1/voices/{voice}",
                              headers={"xi-api-key": key}, timeout=20)
            checks.append(
                Check("ElevenLabs voice", PASS, vr.json().get("name", voice))
                if vr.ok else
                Check("ElevenLabs voice", FAIL, f"{vr.status_code} for id {voice}",
                      "python -m pipeline.cli voices")
            )
        except Exception as exc:  # noqa: BLE001
            checks.append(Check("ElevenLabs voice", FAIL, _reason(exc), ""))
    return checks


def _replicate() -> Check:
    key = os.environ.get("REPLICATE_API_TOKEN")
    if not key:
        return Check("Replicate", MISS, "REPLICATE_API_TOKEN not set",
                     "replicate.com/account/api-tokens; add to .env "
                     "(billing must be enabled to run models)")
    try:
        import requests

        r = requests.get("https://api.replicate.com/v1/account",
                         headers={"Authorization": f"Bearer {key}"}, timeout=20)
        if r.status_code in (401, 403):
            return Check("Replicate", FAIL, f"{r.status_code} - token rejected",
                         "regenerate at replicate.com/account/api-tokens")
        r.raise_for_status()
        acct = r.json()
        return Check("Replicate", PASS,
                     f"{acct.get('username', 'account')} ({acct.get('type', '?')})")
    except Exception as exc:  # noqa: BLE001
        return Check("Replicate", FAIL, _reason(exc), "")


def _youtube() -> list[Check]:
    secret = ROOT / os.environ.get("YOUTUBE_CLIENT_SECRET_FILE", "client_secret.json")
    token = ROOT / os.environ.get("YOUTUBE_TOKEN_FILE", "youtube_token.json")
    out = []
    out.append(
        Check("YouTube OAuth client", PASS, secret.name) if secret.exists() else
        Check("YouTube OAuth client", MISS, f"{secret.name} not found",
              "Google Cloud Console: new project -> enable 'YouTube Data API v3' "
              "-> Credentials -> OAuth client ID -> Desktop app -> download JSON "
              "to the repo root")
    )
    out.append(
        Check("YouTube token", PASS, token.name) if token.exists() else
        Check("YouTube token", MISS, "not authorised yet",
              "python -m pipeline.cli auth  (needs the OAuth client above)")
    )
    return out


def _music() -> Check:
    tracks = [p for p in (ASSETS / "music").iterdir()
              if p.suffix.lower() in {".mp3", ".wav", ".flac", ".m4a"}]
    if tracks:
        return Check("Music library", PASS, f"{len(tracks)} track(s)")
    return Check("Music library", WARN, "assets/music/ is empty",
                 "episodes render narration-only until you add licensed ambient "
                 "tracks (Artlist / Epidemic / Storyblocks). 5-6 is plenty.")


def run() -> int:
    Config.load()  # surfaces a malformed config before anything else
    groups = [
        ("Tools", [_ffmpeg()] + _deps()),
        ("Script generation", [_anthropic()]),
        ("Voiceover", _elevenlabs()),
        ("Images", [_replicate()]),
        ("Upload", _youtube()),
        ("Assets", [_music()]),
    ]

    blocking, fixes = 0, []
    for title, checks in groups:
        print(f"\n{title}")
        for c in checks:
            print(f"  [{MARK[c.status]}] {c.name:<24} {c.detail}")
            if c.status in (MISS, FAIL):
                blocking += 1
            if c.status != PASS and c.fix:
                fixes.append((c.name, c.fix))

    if fixes:
        print("\n" + "-" * 68 + "\nTo fix:\n")
        for name, fix in fixes:
            print(f"  {name}\n    {fix}\n")

    if blocking:
        print(f"{blocking} blocking item(s). "
              f"Meanwhile `--dry-run` needs none of them:\n"
              f"  python -m pipeline.cli seed ep001\n"
              f"  python -m pipeline.cli run --dry-run")
    else:
        print("\nAll clear. python -m pipeline.cli new")
    return 1 if blocking else 0
