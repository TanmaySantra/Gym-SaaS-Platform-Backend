# Gym & Fitness SaaS — Prototype V1 (Backend)

Multi-tenant Gym & Fitness SaaS backend. FastAPI + SQLAlchemy 2.x + Postgres
+ Redis + Celery. See `FINAL_REPORT.md` for the full implementation report,
architecture notes, and test results.

Docker packaging is intentionally not included here — bring your own
`Dockerfile`/`docker-compose.yml` per your infra conventions. Everything
below runs directly against a local Postgres + Redis install.

## Prerequisites

- Python 3.12+
- PostgreSQL 16 (or compatible)
- Redis 7 (or compatible)

## Setup from a clean machine

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt --break-system-packages   # or drop the flag inside a venv

cp .env.example .env
# edit .env: DATABASE_URL, REDIS_URL, JWT_SECRET, JWT_REFRESH_SECRET, AI_API_KEY, etc.
```

Create the database and run migrations:

```bash
createdb gym_saas   # or: psql -c "CREATE DATABASE gym_saas;"
alembic upgrade head
```

Seed the first platform administrator (platform admins and owners are not
created through public signup):

```bash
python -m scripts.create_super_admin admin@yourgym.com "Platform Admin" "SomeStrongPassword123!"
```

## Running the API

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

OpenAPI docs: `http://localhost:8000/api/v1/docs`

Member signup is available at `POST /api/v1/auth/signup`. It requires the
membership ID code issued by an owner, plus the member's email and password.
The endpoint creates the MEMBER account, links it to the membership, and
returns access and refresh tokens. The existing `POST /api/v1/members/link`
endpoint remains available for clients that use the older two-step flow.

## Running Celery

Worker:

```bash
celery -A app.core.celery.celery_app worker --loglevel=info
```

Beat (scheduler — required for the membership payment/expiry/inactivity
checks and periodic analytics/AI insight generation):

```bash
celery -A app.core.celery.celery_app beat --loglevel=info
```

Both need `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, and
`DATABASE_URL` set in the environment (or `.env`).

## Migrations

```bash
alembic upgrade head                                    # apply
alembic downgrade base                                  # roll back everything
alembic revision --autogenerate -m "description here"    # generate a new migration after model changes
alembic check                                            # verify no un-migrated model changes exist
```

## Tests

Tests run against a real Postgres database (not SQLite — the spec assumes
real relational behavior: FKs, constraints, transactions). Create a
dedicated test database first:

```bash
createdb gym_saas_test
```

Then:

```bash
export DATABASE_URL="postgresql+psycopg://<user>:<password>@localhost:5432/gym_saas_test"
pytest tests/ -v
```

Test layout:

- `tests/unit/` — pure logic: password hashing, JWT, membership lifecycle
  state machine, membership ID generation, AI response validation
- `tests/integration/` — API endpoints against real Postgres, Celery task
  correctness, dashboard, finance, notifications
- `tests/security/` — cross-tenant IDOR attempts, restriction enforcement,
  adversarial/harsh-QA cases
- `tests/e2e/` — the full business flow from section 1 of the spec, start
  to finish, in one test

## Performance check

```bash
python -m scripts.performance_check
```

Seeds volume data (100 members, 1000+ progress/workout records) and times
the key operations. See `PERFORMANCE.md` for a captured run and findings.

## Project layout

```
app/
├── main.py                # FastAPI app + router registration
├── core/                  # config, database, security, celery, exceptions
├── common/                # enums, pagination, response envelopes, auth deps
├── auth/                  # login/logout/refresh/me, login-session tracking
├── admin/                 # platform-admin endpoints (SUPER_ADMIN only)
├── gyms/                  # owner-facing "my gym" endpoint
├── users/                 # User ORM model
├── members/               # member profiles + membership-ID linking
├── memberships/           # plans, memberships, lifecycle state machine
├── workouts/               # exercises, sessions, exercise logs
├── progress/               # progress records
├── attendance/             # manual attendance
├── payments/               # payments + expenses + finance summary
├── ai/                     # AI insight pipeline
├── analytics/               # owner dashboard aggregation
├── notifications/          # in-app notifications
└── tasks/                  # Celery tasks (membership, analytics, AI)

alembic/                    # migrations
scripts/                    # create_super_admin.py, performance_check.py
tests/                       # unit / integration / security / e2e
```
