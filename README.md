# Caldera Commons Presentation

This is the presentation-ready version of Caldera Commons: a faith-centered stewardship, accountability, and live broadcast platform built with FastAPI, PostgreSQL, Nginx, and Docker.

The copy in this folder is sanitized for sharing. Real credentials, personal email addresses, and live production values have been replaced with demo placeholders in [.env.example](.env.example).

## Purpose

Caldera Commons is a Christian activity tracker and stewardship ecosystem. It helps people rebuild structure after chaos by making daily work visible, measurable, and encouraging. Chores, work hours, service, and shared wisdom all become part of a larger story: men who have outgrown drugs and crime repurposing their skills into productive, faithful living.

The leaderboard is not about vanity. It is about consistency, discipline, and momentum. The live stream and podcast tools give the Director a way to speak encouragement in real time, while the Water Initiative keeps the mission bigger than survival. That larger vision ties personal restoration to stewardship of the land, productive work, and a reason to keep building something useful for the community and the world.

In short: this ecosystem exists to turn testimony into structure, structure into service, and service into a witness that God can redeem a life and make it fruitful.

## What it includes

- FastAPI web app with login, dashboard, community board, tasks, skills, live broadcast, and leadership views
- Ollama-powered talking points generator for live broadcasts
- Docker Compose setup for local demonstration
- Demo-mode login fallback so the presentation copy can be shown without real Google OAuth credentials

## One-Paragraph Pitch

Caldera Commons is a faith-based stewardship platform that helps men build productive lives after recovery by tracking work hours, chores, and service while also providing live broadcast and AI-generated talking points for encouragement and discipleship. The system turns progress into visible momentum, links daily responsibility to a larger mission, and gives the community a practical way to celebrate growth, accountability, and purpose.

## Ollama Setup (Required for AI Features)

The talking points generator and director insights require a local [Ollama](https://ollama.com) instance running the `CalderaAI` model.

1. Install Ollama on your host machine from https://ollama.com/download

2. Create a file named `CalderaModel` (no extension) with your system prompt, then build and register it:

```bash
ollama create CalderaAI -f ./CalderaModel
```

3. Verify it is running:

```bash
ollama list
```

You should see `CalderaAI:latest` in the list.

4. Ollama must be running on the host while Docker is up. The app reaches it at `http://host.docker.internal:11434/api/generate`. Set `OLLAMA_URL` in your `.env` if your host address differs.

> **Note:** Ollama runs entirely on your local hardware. On a CPU-only machine (no GPU), allow up to 60 seconds for model responses. This is expected behavior.

## Quick Start

1. Copy the example environment file:

```bash
cp .env.example .env
```

2. Start Ollama and the app:

```bash
# In one terminal — start Ollama
ollama serve

# In another terminal — start the Docker stack
docker compose up --build
```

3. Open the app in your browser.

## Demo Mode

If `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are left as demo values, the app uses a built-in demo login path so you can present the site without real OAuth keys.

## Environment

The demo environment file includes placeholders for:

- `DATABASE_URL`
- `SESSION_SECRET_KEY`
- `OLLAMA_MODEL`
- `OLLAMA_URL`
- `DIRECTOR_EMAILS`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `REDIRECT_URI`

## Project Structure

- `web/` application code, templates, static assets, and tests
- `docker-compose.yml` local container setup
- `nginx/` reverse proxy configuration
- `stream.sh` helper script for the live broadcast pipeline

## Notes

- Do not commit a real `.env` file.
- Do not add real OAuth secrets or production database credentials to this repo.
- The bundled archive file is a local export artifact and should not be committed.

## License

Add a license file before publishing publicly if you want others to reuse the code legally.