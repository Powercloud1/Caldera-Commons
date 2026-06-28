# Caldera Commons Presentation

This is the presentation-ready version of Caldera Commons: a faith-centered stewardship, accountability, and live broadcast platform built with FastAPI, PostgreSQL, Nginx, and Docker.

The copy in this folder is sanitized for sharing. Real credentials, personal email addresses, and live production values have been replaced with demo placeholders in [.env.example](.env.example).

## What it includes

- FastAPI web app with login, dashboard, community board, tasks, skills, live broadcast, and leadership views
- Ollama-powered talking points generator for live broadcasts
- Docker Compose setup for local demonstration
- Demo-mode login fallback so the presentation copy can be shown without real Google OAuth credentials

## Quick Start

1. Copy the example environment file:

```bash
cp .env.example .env
```

2. Start the stack:

```bash
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