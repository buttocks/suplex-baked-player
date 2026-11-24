# Baked.live iframe bridge (Lucha Tube pilot)

This GitHub Actions bridge lets an authorized editor ask for an iframe playlist audit or change from ChatGPT. The editor updates one JSON request in this repository. A GitHub Actions runner signs in as **buttman-gpt**, checks permissions, and performs only the requested playlist change. Neither the password nor a browser session is stored in Git.

## One-time secret setup

1. Open **https://github.com/buttocks/suplex-baked-player/settings/secrets/actions**
2. Click **New repository secret**.
3. Name: **BAKED_LIVE_PASSWORD**
4. Value: the password of the existing **buttman-gpt** account. Enter it directly in GitHub's secret form, not into source code, Actions logs, or a chat.
5. Ensure **buttman-gpt** has channel Admin rank for the Lucha Tube channel.

This is the only required manual configuration. The GitHub integration available to ChatGPT does not currently expose GitHub Secrets administration, so the secret cannot be installed by committing a file.

## How commands are delivered

The file **baked-bridge/request.json** is a single command. Adding or changing it on the main branch triggers **.github/workflows/baked-live-bridge.yml**. You can ask ChatGPT to prepare and commit a validated command to this file. No CLI or Work mode is required for normal requests after setup.

The first command should be a read-only audit:

    {
      "schema": 1,
      "request_id": "lucha_audit_001",
      "channel": "luchatube",
      "action": "audit"
    }

Add a permanent iframe at the end of the playlist:

    {
      "schema": 1,
      "request_id": "lucha_add_001",
      "channel": "luchatube",
      "action": "add_iframe",
      "title": "SlamVision 100% LUCHA",
      "src": "https://buttocks.github.io/suplex-baked-player/lucha-slamvision.html"
    }

Safely replace a single non-playing existing iframe at its current position:

    {
      "schema": 1,
      "request_id": "lucha_replace_001",
      "channel": "luchatube",
      "action": "replace_iframe",
      "title": "SlamVision 100% LUCHA",
      "old_src": "https://buttocks.github.io/suplex-baked-player/slamvision-feed.html?id=100-lucha",
      "src": "https://buttocks.github.io/suplex-baked-player/lucha-slamvision.html"
    }

Each request ID must be new when submitting a new command. Do not submit the same operation under different IDs while one is running. Check the workflow result before issuing another command. The only supported channel initially is luchatube; other channels are added to the allowlist after specific authorization.

## Safeguards

- **Audit is read-only** and reports the current playlist and custom iframe URLs.
- **No login secrets** in requests, commits, screenshots, or logs.
- A strict **channel allowlist** and **GitHub Pages player URL allowlist** prevent arbitrary channel operations or untrusted iframe URLs.
- The runner verifies the account identity, channel Admin rank and necessary playlist permissions.
- **Add is idempotent:** an existing exact iframe URL is not queued twice.
- **Replace requires exactly one matching old URL**, verifies the new entry is permanent and in position before deleting the original, and refuses to delete the currently playing item.
- If the replacement cannot finish safely, the old entry stays; a newly queued item may remain and should be audited before retry.
- A request is triggered only by a commit to the allowlisted request path. Other code pushes alone do not execute live playlist commands.
- Each run uploads a short JSON result artifact (7-day retention). Do not enable verbose browser/network tracing on authenticated sessions.

## Caveats

- Live access has **not** been tested yet. Until the secret is configured and the first audit passes, this is a deployed bridge scaffold rather than a verified Baked.live connection.
- Baked.live is CyTube-derived and may change form selectors, playlist permissions or Socket.IO event handling; the bridge will stop rather than continue blindly if checks fail.
- Updating the contents of an existing GitHub-hosted player normally requires **no** playlist edit: its stable URL stays the same. Use this bridge to add or replace playlist entries, not for routine JavaScript player changes.
- Custom embeds synchronize using the Baked.TV player's own clock, not Baked.live's custom-embed player synchronization.

## Developer checks

    node --check baked-bridge/bridge.mjs
    node baked-bridge/bridge.mjs --self-test

GitHub Action: https://github.com/buttocks/suplex-baked-player/actions/workflows/baked-live-bridge.yml
