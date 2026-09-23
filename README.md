# Task API: Jenkins CI/CD demonstration

A deployable Python task service with registration, login, per-user CRUD tasks, SQLite persistence, health checks, and Prometheus metrics. Passwords use salted PBKDF2; tokens have an HMAC signature and one-hour lifetime.

## Run and test

```sh
export TOKEN_SECRET='replace-with-a-random-secret-of-at-least-32-characters'
export APP_IMAGE=task-api:local APP_PORT=18080
docker build -t "$APP_IMAGE" .
docker compose -p task-staging up -d --wait
python3 -m unittest discover -s tests -v
BASE_URL=http://127.0.0.1:18080 python3 scripts/smoke.py
```

API: `POST /register`, `POST /login`, `GET|POST /tasks`, `PUT|DELETE /tasks/{id}`. Task requests require `Authorization: Bearer <token>`. `GET /health` and `GET /metrics` are public. The example uses plain HTTP for local demonstration; put TLS and network access controls in front of any Internet-facing installation.

## Jenkins setup

Create a multibranch pipeline pointing at this Git repository, with `main` as the release branch. The Jenkins agent labeled `docker` needs Docker Engine and Compose v2, Python 3 with venv, and curl. Permit it to manage Docker containers on the deployment host. Configure two Jenkins secret-text credentials: `task-api-token-secret` (a random string of at least 32 characters) and `task-alert-gmail-address` (the Gmail address receiving alerts), and `task-alert-gmail-app-password` (a Google app password for that account). Enable Google 2-Step Verification to create an app password. Never use your normal Google password. Do not commit real secrets.

The seven stages are Build (Docker image and archived tar), Test (unit/API tests), Code Quality (Ruff lint gate and Radon complexity report), Security (Bandit and Trivy high/critical image scan), Deploy (staging Compose plus live smoke test), Release (manual promotion of the exact tested image on `main` plus production smoke test), and Monitoring and Alerting (Prometheus rules and Alertmanager relay delivering Gmail messages). Production and staging use separate Compose project names, ports, and persistent volumes. The release and monitoring stages run only for `main`. The monitoring check confirms Prometheus is responding and rules load; delivery of an alert to the Gmail inbox should also be tested in that environment.

The image tar is archived by Jenkins. With a single Docker host, Compose promotes the same local image tag. For separate hosts, push the image to a registry and deploy by immutable digest; `docker save` alone will not transfer it. The production token secret must remain stable across deployments or existing tokens become invalid. SQLite volumes persist across container replacements, but this sample has no backup or multi-host database setup.

## Security findings log

No vulnerability finding is claimed until Bandit and Trivy actually run on the Jenkins host. Each Jenkins Security stage fails on Bandit medium/high findings or Trivy high/critical fixed vulnerabilities. For each reported finding record its package/file, description, severity, remediation and rerun result in the Jenkins build record or an issue; upgrade the package/base image, or document a verified false positive before an exception. Trivy uses `--ignore-unfixed`, so unresolved upstream vulnerabilities do not block this demonstration and should still be reviewed separately.

## Repository publication

This workspace can be initialized with Git (`git init -b main && git add . && git commit -m 'Add task API and Jenkins pipeline'`). To publish, create a remote repository you control, add its URL as `origin`, and `git push -u origin main`.
