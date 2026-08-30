"""Stage 7: upload to YouTube via the Data API v3.

Defaults to privacy_status=private. Publishing an unreviewed automated render
straight to public is how a channel accumulates strikes it can't see coming --
make `--publish` a deliberate act, or set a scheduled publishAt after review.

One-time setup: create an OAuth *desktop app* client in Google Cloud Console
with the YouTube Data API v3 enabled, download client_secret.json, then run
`python -m pipeline.cli auth` once to mint the refresh token.

Quota: an upload costs ~1600 units against a default 10,000/day, so a daily
schedule is comfortable but leaves no room for bulk API experimentation on the
same project.
"""
from __future__ import annotations

from pathlib import Path

from ..config import ROOT, Config, env
from ..state import Manifest

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]
CATEGORY_ENTERTAINMENT = "24"


def _service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    token_path = ROOT / env("YOUTUBE_TOKEN_FILE", required=False,
                            default="youtube_token.json")
    secret_path = ROOT / env("YOUTUBE_CLIENT_SECRET_FILE", required=False,
                             default="client_secret.json")

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not secret_path.exists():
                raise SystemExit(
                    f"Missing {secret_path}. Create an OAuth desktop-app client "
                    f"in Google Cloud Console and download it there."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())
    return build("youtube", "v3", credentials=creds)


def authorize() -> None:
    _service()
    print("YouTube OAuth token stored.")


def run(m: Manifest, cfg: Config, force: bool = False, publish: bool = False,
        publish_at: str | None = None) -> Manifest:
    if m.done("upload") and not force:
        print("  upload: already done, skipping")
        return m

    from googleapiclient.http import MediaFileUpload

    video = m.path(m.data["video"]["path"])
    if not video.exists():
        raise SystemExit(f"No rendered video at {video}")

    meta = m.data.get("metadata", {})
    yt = _service()

    status = {
        "privacyStatus": "public" if publish else "private",
        "selfDeclaredMadeForKids": False,
        # YouTube requires disclosure of realistic synthetic media. Narration is
        # synthetic and the stills are generated, so this is set unconditionally.
        "containsSyntheticMedia": True,
    }
    if publish_at:
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at

    body = {
        "snippet": {
            "title": meta.get("title", m.data.get("title", m.slug))[:100],
            "description": meta.get("description", "")[:5000],
            "tags": meta.get("tags", [])[:30],
            "categoryId": CATEGORY_ENTERTAINMENT,
            "defaultLanguage": "en",
        },
        "status": status,
    }

    print(f"  upload: sending {video.name} ({video.stat().st_size / 1e6:.1f} MB) ...")
    request = yt.videos().insert(
        part="snippet,status", body=body,
        media_body=MediaFileUpload(str(video), chunksize=8 * 1024 * 1024,
                                   resumable=True, mimetype="video/mp4"),
    )
    response = None
    while response is None:
        chunk_status, response = request.next_chunk()
        if chunk_status:
            print(f"  upload: {int(chunk_status.progress() * 100)}%",
                  end="\r", flush=True)

    vid = response["id"]

    thumb = m.path("images", "thumbnail.png")
    if thumb.exists():
        try:
            yt.thumbnails().set(videoId=vid, media_body=str(thumb)).execute()
        except Exception as exc:  # noqa: BLE001 - needs a verified channel
            print(f"  upload: thumbnail rejected ({exc}); set it by hand")

    srt = m.path("meta", "captions.srt")
    if srt.exists():
        try:
            yt.captions().insert(
                part="snippet",
                body={"snippet": {"videoId": vid, "language": "en",
                                  "name": "English", "isDraft": False}},
                media_body=str(srt),
            ).execute()
        except Exception as exc:  # noqa: BLE001
            print(f"  upload: caption upload failed ({exc})")

    url = f"https://youtu.be/{vid}"
    m.data["youtube"] = {"video_id": vid, "url": url,
                         "privacy": status["privacyStatus"]}
    m.mark("upload", video_id=vid, url=url, privacy=status["privacyStatus"])
    print(f"  upload: {url} ({status['privacyStatus']})")
    return m
