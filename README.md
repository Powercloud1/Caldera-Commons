# Caldera Commons Presentation

Caldera Commons is a FastAPI + Postgres + Nginx + MediaMTX stack for community accountability, task tracking, and live media operations.

## Stack

- FastAPI application in `web/`
- PostgreSQL 15
- Nginx reverse proxy
- MediaMTX for ingest and stream routing

## Configure Environment

Copy the example file and provide your deployment values:

```bash
cp .env.example .env
```

Required values in `.env`:

- `POSTGRES_PASSWORD`
- `DATABASE_URL`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `REDIRECT_URI`
- `SESSION_SECRET`

Optional values:

- `DIRECTOR_EMAILS`
- `OLLAMA_MODEL`
- `OLLAMA_URL`
- `MEDIAMTX_RTMP_PORT`

Notes:

- `REDIRECT_URI` must match your OAuth provider configuration exactly, for example `https://your-domain.com/auth`.
- Use a long random `SESSION_SECRET`.
- Keep `.env` out of source control.
- If port `1935` is already in use on your machine, set `MEDIAMTX_RTMP_PORT` to another host port.

## Run Locally

```bash
docker compose up -d --build
```

Check status:

```bash
docker compose ps
```

## Smoke Test

Health endpoint:

```bash
curl -sS https://your-domain.com/health
```

OAuth entrypoint:

```bash
curl -I https://your-domain.com/login
```

If OAuth environment variables are missing, `/login` intentionally returns a configuration error instead of failing with a hidden runtime issue.

## OAuth Setup

Configure your Google OAuth app with:

- Authorized redirect URI: `https://your-domain.com/auth`

## HTTPS and Domain

Nginx is configured for canonical non-www routing.

- `http://www.your-domain.com` -> `https://your-domain.com`
- `https://www.your-domain.com` -> `https://your-domain.com`

Your TLS certificate should include both hostnames:

- `your-domain.com`
- `www.your-domain.com`

## Testing

Run tests from the app folder:

```bash
cd web
pytest -q
```

## Project Layout

- `web/main.py` - routes and auth flow
- `web/templates/` - rendered pages
- `web/static/` - CSS and assets
- `nginx/default.conf` - proxy and TLS routing
- `docker-compose.yml` - local orchestration

## Security Notes

- No production secrets are committed.
- Use environment variables and `.env` for deployment secrets.
- Rotate any credentials that appeared in older copies or git history before publishing.
