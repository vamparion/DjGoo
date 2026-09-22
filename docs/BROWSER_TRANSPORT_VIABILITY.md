# Browser transport viability

DjGoo's proposed remote PWA depends on a normal browser being able to use the
Discord incoming-webhook message API. This is a release-blocking security gate,
not an assumption.

## Probe

`tools/browser_discord_transport_spike.py` launches an installed Chromium
browser in headless mode from a loopback-only test page. The webhook credential
is read from `DJGOO_TEST_WEBHOOK_URL` or an ignored secrets file, handed to that
page only in memory, and never printed or included in a build artifact.

The probe performs this sequence:

1. `POST ?wait=true` and read the returned message ID.
2. `GET` that exact webhook message.
3. `PATCH` its encrypted/test marker.
4. Poll `GET` until the edited response is observed.
5. `DELETE` the message in normal and failure cleanup paths.

Run it only with a disposable test webhook:

```powershell
$env:DJGOO_TEST_WEBHOOK_URL = Read-Host "Disposable webhook URL"
python tools/browser_discord_transport_spike.py --browser "C:\Program Files\Google\Chrome\Application\chrome.exe"
Remove-Item Env:DJGOO_TEST_WEBHOOK_URL
```

Never use a webhook committed to source or passed on the command line.

## Current result

On 2026-09-21, Chrome/Chromium successfully completed Discord's CORS preflight
for `POST`, `GET`, `PATCH`, and `DELETE`. Discord echoed the HTTPS test origin
and allowed `Content-Type` plus all four methods.

After the bot received `Manage Webhooks`, a disposable route completed the full
sequence in installed Chrome: POST 200, GET 200, PATCH 200, edited-response
detection true, and DELETE 204. The probe then deleted the disposable webhook.

This proves the required Chromium transport as of the date above. Android
Chromium and Safari/iOS remain real-device compatibility tests. Do not expose
port 8765, add a proxy, disable browser security, or substitute a public relay
if a future browser or Discord API change breaks this gate.
