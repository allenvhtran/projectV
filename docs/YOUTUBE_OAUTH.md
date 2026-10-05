# Creating the YouTube OAuth client

~15 minutes, free. You have to do this yourself: it is a browser flow against
your own Google account, and nobody else can authorise your channel.

Google renamed this area to **Google Auth Platform** and split it into
Branding / Audience / Clients / Data Access tabs. Older walkthroughs call it
"OAuth consent screen" and will not match what you see.

## 1. Project and API

1. <https://console.cloud.google.com> → project picker (top left) → **New
   project**. Name it anything; `projectv-uploader` is fine.
2. With that project selected, go to **APIs & Services → Library**, search
   **YouTube Data API v3**, open it, **Enable**.

Enabling the API is separate from authorising it. Both are required.

## 2. Configure the consent screen

**APIs & Services → OAuth consent screen** (or **Google Auth Platform**).

- **Audience / User type: External.** "Internal" is only available on Google
  Workspace accounts and only works for users inside that organisation. On a
  personal `@gmail.com` account, External is your only option.
- **Branding**: app name and a support email. The app name is what you will
  see on the consent screen, so make it recognisable — if a later prompt says
  an unfamiliar app wants your YouTube account, you want to know it is yours.
- **Data Access → Add scopes**: add exactly one —
  `https://www.googleapis.com/auth/youtube.force-ssl`

  That single scope authorises uploads, thumbnails and captions. Do **not**
  also add `youtube.upload`, `youtube` or `youtube.readonly`: they overlap, and
  overlapping YouTube scopes are a documented cause of verification rejection.
- **Audience → Test users**: add your own Google address.

## 3. Publish the app — this is the step that matters

On the **Audience** tab, press **Publish app** to move the status from
*Testing* to *In production*.

**Google expires the refresh tokens of apps left in Testing after exactly 7
days.** Your pipeline would authorise fine, upload for a week, and then start
failing every Monday with an invalid-grant error that looks like a code bug.
Publishing makes the refresh token last indefinitely.

Publishing does not mean submitting for verification. An unverified published
app still works for you; it shows an extra warning screen (see step 5) and is
capped at 100 users, which is 99 more than you need. You only need to go
through verification — including a demo video — if you ever distribute this to
other people's channels.

## 4. Create the client

**APIs & Services → Credentials → Create credentials → OAuth client ID**

- **Application type: Desktop app.** Not "Web application" — the pipeline uses
  a loopback redirect, and a Web client will reject it with
  `redirect_uri_mismatch`.
- Name it anything.
- **Download JSON**, save it to the repo root as `client_secret.json`.

It is already in `.gitignore`. It is a credential: treat it like a password.

## 5. Authorise

```bash
python -m pipeline.cli auth
```

A browser opens. Two things to expect:

- **"Google hasn't verified this app"** — because it is unverified, as planned.
  Click **Advanced** → **Go to <app name> (unsafe)**. It is your own app.
- Grant the YouTube permission. The token is written to `youtube_token.json`
  (also gitignored).

Then confirm:

```bash
make doctor      # YouTube OAuth client + token should both read ok
```

## 6. Verify the channel

Separately, phone-verify the channel at
<https://www.youtube.com/verify>. Custom thumbnails need a verified channel;
without it, `thumbnails().set` fails and the upload stage tells you to set the
thumbnail by hand.

## Quota

An upload costs ~1,600 units against a default 10,000 units/day. Daily uploads
are comfortable; roughly six per day is the ceiling, and bulk API
experimentation on the same project will eat into it.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `invalid_grant` after about a week | App still in Testing. Publish it (step 3). |
| `redirect_uri_mismatch` | Client created as "Web application". Make a Desktop app client. |
| `accessNotConfigured` | YouTube Data API v3 not enabled on *this* project. |
| `insufficientPermissions` | Token minted before the scope was added. Delete `youtube_token.json` and re-run `auth`. |
| Thumbnail rejected | Channel not phone-verified (step 6). |
| `quotaExceeded` | 10,000 units/day spent. Resets at midnight Pacific. |
