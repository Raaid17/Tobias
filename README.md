# Discord Assistant Bot

A modular Discord bot built to grow into a general AI assistant. The first
module is **music** (Lavalink-powered voice playback via slash commands).

## Architecture

```
Discord Gateway
      │
   Bot core (bot.py)            config.py / core.logging
      │  loads ▼
   cogs/  ── general.py  (/ping, /help)
          └ music.py     (/play, /skip, …)  ── services/audio.py
                                                      │
                                              Lavalink (Docker service)
```

- **`cogs/`** — feature modules; each is a self-contained set of slash commands.
- **`services/`** — reusable capability logic (the audio/queue layer). Cogs talk
  to services, never to Lavalink or (later) an LLM directly. This is what makes
  new modules (AI, reminders, …) drop-in rather than rewrites.
- **`bot.py`** — wiring only: build the bot, connect Lavalink, load cogs, sync
  commands.

## Project layout

```
.
├── bot.py                  # entrypoint
├── config.py               # env loading + validation
├── core/logging.py         # central logging
├── cogs/
│   ├── general.py          # /ping, /help
│   └── music.py            # music slash commands
├── services/
│   └── audio.py            # queue/playback + embed helpers
├── lavalink/
│   └── application.yml      # Lavalink v4 config (+ YouTube source plugin)
├── Dockerfile
└── docker-compose.yml      # bot + lavalink stack
```

## Prerequisites

1. **Docker** (Docker Desktop on Windows, or Docker Engine on the homelab host).
2. **A Discord bot token** — see below.

## Create a Discord bot (one time)

1. Go to <https://discord.com/developers/applications> → **New Application**.
2. Open the **Bot** tab → **Reset Token** → copy the token (this is your
   `DISCORD_TOKEN`). Keep it secret.
3. Still on the **Bot** tab, no privileged intents are required (this bot uses
   slash commands and only the default intents).
4. Invite the bot: **OAuth2 → URL Generator** → scopes `bot` and
   `applications.commands` → bot permissions: **Connect**, **Speak**,
   **Send Messages**, **Embed Links**, **Use Slash Commands**. Open the
   generated URL and add the bot to your server.
5. (Optional, recommended for development) Copy your server's ID
   (enable Developer Mode → right-click the server → Copy Server ID) and set it
   as `DEV_GUILD_ID` so slash commands appear instantly instead of taking up to
   an hour to propagate globally.

## Run locally with Docker

```bash
cp .env.example .env        # then edit .env and paste your DISCORD_TOKEN
docker compose up --build
```

On first start Lavalink downloads the YouTube plugin (takes a few seconds). The
bot retries the Lavalink connection while it boots, then logs
`Lavalink node 'default' ready` and `Logged in as …`.

Try it in Discord: `/ping`, then join a voice channel and run
`/play never gonna give you up`.

Stop with `Ctrl+C`, or run detached with `docker compose up -d --build` and view
logs via `docker compose logs -f bot`.

## Configuration

All configuration is via environment variables (see `.env.example`):

| Variable            | Required | Default                  | Purpose                                   |
| ------------------- | -------- | ------------------------ | ----------------------------------------- |
| `DISCORD_TOKEN`     | ✅       | —                        | Discord bot token                         |
| `DEV_GUILD_ID`      |          | *(global sync)*          | Guild ID for instant slash-command sync   |
| `LAVALINK_URI`      |          | `http://localhost:2333`  | Lavalink address (compose sets the rest)  |
| `LAVALINK_PASSWORD` |          | `youshallnotpass`        | Must match `lavalink/application.yml`     |
| `LOG_LEVEL`         |          | `INFO`                   | `DEBUG` / `INFO` / `WARNING` / `ERROR`    |

## Commands

| Command                  | Description                          |
| ------------------------ | ------------------------------------ |
| `/play <query \| url>`   | Play or enqueue a track              |
| `/skip`                  | Skip the current track               |
| `/queue`                 | Show the queue                       |
| `/nowplaying`            | Show the current track               |
| `/pause` · `/resume`     | Pause / resume playback              |
| `/stop`                  | Stop and clear the queue             |
| `/leave`                 | Disconnect from voice                |
| `/ping` · `/help`        | Latency check / command list         |

The bot auto-disconnects after a period of inactivity.

## Roadmap

- [x] Phase 0 — Foundation (config, logging, bot core, `/ping`)
- [x] Phase 1 — Music MVP
- [x] Deployment pipeline — GitHub Actions → GHCR → Portainer (webhook deploy)
- [ ] Phase 2 — Music polish (volume, loop/shuffle, controls)
- [ ] Phase 3 — AI module (`/ask`, `/chat` via Claude)

## Deployment (homelab / Portainer)

Pipeline: **push to `main` → GitHub Actions builds the image → pushes to GHCR →
Portainer redeploys the stack via webhook.**

- `.github/workflows/deploy.yml` — builds `linux/amd64` and pushes
  `ghcr.io/raaid17/discord-bot:latest` (+ a `sha-…` tag for rollback), then
  POSTs the Portainer redeploy webhook.
- `docker-compose.prod.yml` — the stack Portainer runs; it *pulls* the GHCR
  image (no build) and reads secrets from the Portainer stack environment.

### One-time setup

1. **Create the GitHub repo** and push (run these in your terminal so any login
   prompt is interactive):
   ```powershell
   git remote add origin https://github.com/Raaid17/discord-bot.git
   git push -u origin main
   ```
   The first push triggers Actions, which builds and publishes the image.

2. **Make the image public** (so Portainer needs no registry login):
   GitHub → your profile → **Packages** → `discord-bot` → **Package settings**
   → **Change visibility** → **Public**.

3. **Add the stack in Portainer:** Stacks → **Add stack** → **Repository**.
   - Repository URL: `https://github.com/Raaid17/discord-bot`
   - Reference: `refs/heads/main`
   - Compose path: `docker-compose.prod.yml`
   - **Environment variables:** add `DISCORD_TOKEN` and `LAVALINK_PASSWORD`
     (and optionally `DEV_GUILD_ID`, `LOG_LEVEL`).
   - Enable the stack **Webhook** and copy its URL.
   - Deploy the stack.

4. **Wire the webhook back to CI:** GitHub repo → Settings → Secrets and
   variables → Actions → **New repository secret** named
   `PORTAINER_WEBHOOK_URL`, value = the webhook URL from step 3.

### From then on

`git push` to `main` → image rebuilds → Portainer re-pulls and redeploys
automatically. To roll back, set `BOT_IMAGE` in the Portainer stack to a pinned
tag (e.g. `ghcr.io/raaid17/discord-bot:sha-1a2b3c4`) and redeploy.

> Until `PORTAINER_WEBHOOK_URL` is set (i.e. before step 4), the build still
> runs and publishes the image; the redeploy step just skips itself.
