# Willkemedge Dashboard

Single-owner rental management dashboard for Dr. Wilson Osoro.
Captures M-Pesa + bank payments, tracks tenants, and surfaces real-time
unit status, arrears, and analytics.

> **Delivery window:** 2026-04-09 → 2026-04-15 (7-day compressed plan).
> See [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md) §16 for the day-by-day breakdown.

## Stack

- **Backend:** Django 5.1 + DRF + JWT (`simplejwt`) + PostgreSQL + Celery + Redis
- **Frontend:** React 18 + Vite + TypeScript + Tailwind + TanStack Query
- **Infra:** Render (backend + Postgres + Redis), Vercel (frontend), AWS S3 (files)
- **Integrations:** M-Pesa Daraja, SendGrid, Africa's Talking, Sentry

## Repo layout

```
willkemedge-dashboard/
├── backend/        Django project (config/, apps/, requirements/)
├── frontend/       Vite + React + TS + Tailwind SPA
├── .github/        CI workflows, PR + issue templates, CODEOWNERS
└── DEVELOPMENT_PLAN.md
```

## Quickstart — Backend

```bash
cd backend
python -m venv venv
source venv/Scripts/activate     # Windows bash
# source venv/bin/activate        # macOS/Linux
pip install -r requirements/dev.txt
cp .env.example .env
python manage.py migrate
python manage.py runserver
```

API available at <http://localhost:8000/api/health/>.

## Quickstart — Frontend

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

App available at <http://localhost:5173>.

## Branching

- `main` — production. Protected. Merge only via PR from `develop`.
- `develop` — integration branch. All feature work merges here first.
- `feat/<scope>` — short-lived feature branches off `develop`.

Use [conventional commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`.

## CI

GitHub Actions runs on every PR to `main`/`develop`:

- `.github/workflows/backend-ci.yml` — ruff lint, Django check, pytest
- `.github/workflows/frontend-ci.yml` — eslint, Vite production build

Path filters keep backend changes from triggering frontend CI and vice versa.

## Environment variables

Each app has a `.env.example`. Never commit `.env`. Production secrets live in
Render (backend) and Vercel (frontend) — see DEVELOPMENT_PLAN.md §5.
