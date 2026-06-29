# Open Source Publish Checklist

## Before Publishing

1. Confirm no secrets remain in tracked files.
2. Ensure `.env` exists locally and is not committed.
3. Verify `.gitignore` covers `.env`, caches, virtualenvs, and logs.
4. Verify OAuth credentials are loaded only through environment variables.
5. Verify session secret is loaded from `SESSION_SECRET`.
6. Verify DB credentials are environment-driven through `DATABASE_URL` and `POSTGRES_PASSWORD`.

## Domain and TLS

1. DNS A records for apex and www point to your host.
2. TLS certificate includes both apex and www SANs.
3. Canonical redirects behave as expected.

## Runtime Validation

1. `docker compose up -d --build` completes.
2. `docker compose ps` shows healthy web, db, and proxy containers.
3. `/health` returns 200.
4. `/login` redirects to the OAuth provider when configured.
5. www host redirects to canonical non-www host.

## Final Security Hygiene

1. Rotate OAuth client secret if it was previously exposed.
2. Rotate database password if it was previously exposed.
3. Rotate session secret if it was previously exposed.
4. Review git history for leaked keys before making the repository public.

## Release

1. Add repository description and topics.
2. Tag a release commit.
3. Publish the repository.
