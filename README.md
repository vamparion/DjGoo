# DiscordBot

Project-local Red-DiscordBot setup for DjGoo.

## Start

Run:

```powershell
.\Start-DjGoo.command.ps1
```

## Stop

Run:

```powershell
.\stop-djgoo.ps1
```

## Command Prefixes

The normal `!` prefix still works.

DjGoo also works as a natural command prefix:

```text
DjGoo play final countdown
DjGoo, skip
DJ Goo: stop
```

Those are handled like:

```text
!play final countdown
!skip
!stop
```

Red commands still need to be actual Red command text after the DjGoo prefix.

## Webhook Welcome Screen

Paste a newly generated Discord webhook URL into:

```text
config\secrets.json
```

Replace `PASTE_NEW_WEBHOOK_URL_HERE` with the new webhook URL.

When someone joins a voice channel, the `djgoowelcome` cog posts a DjGoo command welcome screen to that webhook's channel.

## Local Voice Listener

Install voice dependencies once:

```powershell
.\install-voice-deps.ps1
```

Start the local microphone listener:

```powershell
.\Start-DjGoo-Voice.command.ps1
```

Stop the local microphone listener:

```powershell
.\Stop-DjGoo-Voice.ps1
```

The first run may download the local Whisper model. Voice logs go to:

```text
logs\voice-listener.log
```

The listener uses the default Windows microphone and only reacts to commands with `DjGoo` or `DJ Goo`.

The voice listener writes local commands into DjGoo's command queue. The Red cog reads that queue and runs the supported Audio actions.

## Radio Stations

Playlists and stations are separate.

Start or resume a station:

```text
DjGoo radio Sandstorm
```

This creates or resumes `Sandstorm radio`.

Curate the active station:

```text
DjGoo like this
DjGoo more like this
DjGoo less like this
DjGoo don't play this again
DjGoo station status
```

Station memory is stored in:

```text
data\djgoo-stations.json
```

Radio overlays are visual-only Discord embeds.
