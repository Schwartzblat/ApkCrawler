# Crawler

Two independent pipelines, selected with `--pipeline {build,artifacts,all}` (default `build`).

## Pipelines

**build** (default, run by hand): downloads new versions of the apps in `apps.py` from Google Play, APKPure
and APKMirror into `/opt/patched` and patches them with `--paywall`. An app listing only `build` in its
`pipelines` goes through this one.

    ./run_crawler.sh                      # build pipeline
    ./run_crawler.sh -r user@server[:path]  # also upload the patched APKs over SSH
    ./run_crawler.sh -b N                 # also fetch the missing ones among each app's newest N releases

**artifacts** (scheduled, see below): for each app whose `pipelines` contains `artifacts` (today WhatsApp),
polls the app's direct URL (`direct_url` in `apps.py`), and when the APK changed runs the patcher's
signature finders (`main.py --artifactory-only`). The resulting version record is posted to the server
(`POST $PATCH_SERVER_URL/api/internal/records`, header `X-Internal-Token`).

    ./run_crawler.sh --pipeline artifacts
    ./run_crawler.sh --pipeline artifacts --retry-failed   # see "Failures" below
    ./run_crawler.sh --pipeline all                         # both

Every alert is an email (when configured) and a line in `alerts.log`; each problem alerts once:

- A patcher crash, a rejected record and an unsupported record (or one with features off) alert at once.
- Failures every run retries by itself (fetching the APK, posting while the server is unavailable,
  reading `PATCHER_VERSION`) alert after an hour of continuous failure. The first success ends the
  streak, so the next outage alerts again.
- An unexpected error in an app's processing (for example a corrupt `state.json`) prints a traceback,
  alerts once per distinct error and lets the other apps run; a clean run of that app re-arms it.

## Configuration

`run_crawler.sh` changes to its own directory, sources `.env` next to it (exported to the crawler) and
activates `.venv`. `.env` holds secrets: `chmod 600 .env`. Never commit it.

| Variable | Pipeline | Meaning |
| --- | --- | --- |
| `PATCHERS_DIR` | both | Directory holding the patchers (`<PatcherName>/main.py`) |
| `PAYWALL_PATH` | build | The PatchPaywall checkout passed to the patchers |
| `GOOGLE_API_KEY` | build, optional | Passed to the downloader with `-g` |
| `PATCH_SERVER_URL` | artifacts | Server base URL with its scheme, e.g. `https://androidmod.site` |
| `CRAWLER_SECRET` | artifacts | Must equal the server's `CRAWLER_SECRET` |
| `ARTIFACTS_DIR` | artifacts | State directory, default `~/.local/share/androidmod-crawler` |
| `ALERT_EMAIL_TO` | artifacts | Recipient of alert emails; no email is sent when unset |
| `SMTP_HOST` | artifacts | Default `smtp.gmail.com` |
| `SMTP_PORT` | artifacts | `465` (default) uses implicit TLS, any other port uses STARTTLS |
| `SMTP_USERNAME`, `SMTP_PASSWORD`, `MAIL_FROM` | artifacts | SMTP login and sender (`MAIL_FROM` defaults to the username) |

The SMTP names match PatchingSite's server, so one `.env` can serve both. Alert emails need
`ALERT_EMAIL_TO`, `SMTP_USERNAME` and `SMTP_PASSWORD`; otherwise alerts only go to `alerts.log`.

## State (artifacts pipeline)

    $ARTIFACTS_DIR/
      .lock                         # one run at a time
      alerts.log                    # every alert, also when email is off
      tmp/                          # the patcher's work dirs, cleared at the start of each run
      <package>/
        state.json
        apks/<sha256>.apk           # the newest 3 downloads are kept
        last_crash.txt              # the last unexpected error alerted, removed by a clean run

`state.json` holds the `etag`, `last_modified` and `length` of the last download (to skip unchanged
downloads), a `kept` list, `alerted` and `failing` (when each ongoing failure streak started). Each
`kept` entry has `apk_sha256`, `path`, `version_code`, `downloaded_at`, `processed_with` (the patcher
version that processed it), `posted` and `last_error`.

A new `PATCHER_VERSION` reprocesses the kept APKs automatically. Files in `apks/` that no `kept` entry
names (partial downloads, an APK whose run was killed before saving `state.json`) are deleted on the next
run. The patcher runs with a 10 minute timeout and without `CRAWLER_SECRET`, `BUNDLE_UPLOAD_SECRET`,
`SMTP_PASSWORD`, `KEYSTORE_PASSWORD` and `KEY_PASSWORD` in its environment.

### Failures

A patcher crash, or a 4xx (other than 408 and 429, which are retried) or redirect from the server,
alerts once and parks that APK until the next patcher release, so a broken APK does not email on every
run. Redirects are not followed: point `PATCH_SERVER_URL` at the final URL. After fixing the cause (patcher bug, wrong
`CRAWLER_SECRET`, ...), retry immediately:

    ./run_crawler.sh --pipeline artifacts --retry-failed

If the retry fails again, it prints the error and alerts again.

## Scheduling the artifacts pipeline

`deploy/` holds a systemd user unit pair that runs the pipeline every hour (`Persistent=true`
catches up after downtime, `RandomizedDelaySec=60`, 45 minute timeout). No root needed.

`ExecStart` in `deploy/crawler-artifacts.service` is `%h/PatchingMonorepo/tools/crawler/run_crawler.sh`.
**Edit it if the checkout lives elsewhere.**

    mkdir -p ~/.config/systemd/user
    cp deploy/crawler-artifacts.service deploy/crawler-artifacts.timer ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --now crawler-artifacts.timer
    loginctl enable-linger "$USER"      # run the timer without a login session

Check on it:

    systemctl --user list-timers crawler-artifacts.timer
    systemctl --user start crawler-artifacts.service    # run once now
    journalctl --user -u crawler-artifacts

## Releasing a new patcher version

Records posted for a patcher version that has no bundle on the server are invisible to the server's
`latest`, so release in this order:

1. Upload the new version's bundle from the patcher checkout: `python bundle.py --paywall ... --signing-key ...
   --upload` (see the patcher's README).
2. Then update the crawler's patcher checkout (`$PATCHERS_DIR/<PatcherName>`). The next run sees the new
   `PATCHER_VERSION` and reprocesses the kept APKs.

## Launch-day step (not done yet)

While WhatsApp is still also built by the crawler, subscribers receive crawler-built WhatsApp. On launch of
on-device patching:

1. Remove `"build"` from WhatsApp's `pipelines` in `apps.py` (leaving `frozenset({"artifacts"})`).
2. Set the server's `ON_DEVICE_PACKAGES` to include `com.whatsapp`.

## Tests

    .venv/bin/python -m pytest -q
