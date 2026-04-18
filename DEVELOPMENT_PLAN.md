# Dr. William Osoro Rental Management Dashboard — Development & Implementation Plan

> **Version:** 1.1 (7-day compressed delivery)
> **Date:** 2026-04-09
> **Authors:** William, Barclay Mogambi
> **Status:** Draft
> **Delivery Window:** 2026-04-09 → 2026-04-15

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Development Philosophy & Principles](#2-development-philosophy--principles)
3. [Technology Stack Breakdown](#3-technology-stack-breakdown)
4. [Repository & Project Structure](#4-repository--project-structure)
5. [Environment Setup](#5-environment-setup)
6. [Database Design & Schema](#6-database-design--schema)
7. [Backend Implementation Plan](#7-backend-implementation-plan)
8. [Frontend Implementation Plan](#8-frontend-implementation-plan)
9. [Authentication & Security Implementation](#9-authentication--security-implementation)
10. [Payment Integration Implementation](#10-payment-integration-implementation)
11. [File Storage Implementation](#11-file-storage-implementation)
12. [Notifications (Email & SMS)](#12-notifications-email--sms)
13. [Reporting & Analytics Engine](#13-reporting--analytics-engine)
14. [Testing Strategy](#14-testing-strategy)
15. [CI/CD Pipeline & Deployment](#15-cicd-pipeline--deployment)
16. [Sprint Plan & Milestones](#16-sprint-plan--milestones)
17. [Risk Register & Mitigations](#17-risk-register--mitigations)
18. [Post-Deployment Checklist](#18-post-deployment-checklist)
19. [Penetration Testing Preparation](#19-penetration-testing-preparation)
20. [Appendices](#20-appendices)

---

## 1. Project Overview

### 1.1 What We Are Building

A single-owner, web-based rental property management dashboard that:

- Captures payments automatically from M-Pesa Paybill and bank transfers
- Provides real-time unit status visualization (occupied, vacant, partial, arrears)
- Manages the full tenant lifecycle (move-in, active tenancy, move-out, archived)
- Retains all financial records permanently
- Generates reports and analytics with exportable PDFs
- Runs on any device (responsive mobile-first design)

### 1.2 What Is Explicitly Out of Scope (v1)

| Out of Scope | Reason |
|---|---|
| Multi-user roles (caretaker, viewer) | Future v2 consideration |
| Commercial leasing workflows | Residential rental only |
| Tenant self-service portal | Owner-only dashboard in v1 |
| Mobile native app | Responsive web covers mobile use cases |
| Multi-property owner support | Single owner system |

### 1.3 Key Constraints

- **Single admin user** — no multi-tenancy complexity in auth
- **Kenyan financial ecosystem** — M-Pesa Daraja API, KES currency, local bank APIs
- **Kenya Data Protection Act 2019** — minimum 7-year personal data retention post move-out
- **Budget-conscious hosting** — Render (backend + DB), Vercel (frontend), AWS S3 (files)

---

## 2. Development Philosophy & Principles

### 2.1 Core Principles

| Principle | Application |
|---|---|
| **Ship incrementally** | Each sprint delivers a usable vertical slice, not isolated layers |
| **Security-first** | Auth, input validation, and HTTPS are not "later" items — they go in from sprint 1 |
| **Data integrity above all** | Financial records are immutable. No soft deletes on payments. Full audit trails |
| **Mobile-first responsive** | Tailwind's mobile-first breakpoints. Test on Chrome Android and Safari iOS from day 1 |
| **Convention over configuration** | Follow Django and React community conventions. Don't reinvent patterns |
| **Fail loudly in dev, gracefully in prod** | Detailed error logging internally, generic messages to the client |

### 2.2 Code Standards

- **Python:** Follow PEP 8. Use type hints on all function signatures. Max line length 120 chars
- **JavaScript/React:** ESLint + Prettier. Functional components only. Named exports
- **Git:** Conventional commits (`feat:`, `fix:`, `chore:`, `docs:`). Feature branches off `develop`. PRs required for merge
- **Documentation:** Docstrings on all Django views and serializers. JSDoc on complex React hooks

### 2.3 Branching Strategy

```
main (production - auto-deploys to Render/Vercel)
  └── develop (integration branch)
       ├── feat/auth-system
       ├── feat/unit-management
       ├── feat/payment-integration
       ├── fix/mpesa-callback-validation
       └── ...
```

- `main` = production. Protected branch. Merge only via PR from `develop`
- `develop` = integration. All feature branches merge here first
- Feature branches = short-lived. One feature per branch. Squash merge to `develop`

---

## 3. Technology Stack Breakdown

### 3.1 Backend Stack

| Component | Technology | Version | Purpose |
|---|---|---|---|
| Framework | Django | 5.1+ | Web framework with batteries included |
| API Layer | Django REST Framework (DRF) | 3.15+ | RESTful API serialization, viewsets, permissions |
| Auth Tokens | `djangorestframework-simplejwt` | 5.3+ | JWT access + refresh token management |
| Password Hashing | `bcrypt` via `django-bcrypt` | — | bcrypt with 12+ salt rounds |
| Task Queue | Celery | 5.4+ | Async tasks: receipts, SMS, status recalculation |
| Task Broker | Redis | 7+ | Message broker for Celery |
| Scheduler | Celery Beat | — | Nightly arrears recalculation, bank polling fallback |
| PDF Generation | `weasyprint` or `reportlab` | — | Payment receipts, monthly reports |
| HTTP Client | `httpx` | — | Daraja API OAuth, bank API calls |
| CORS | `django-cors-headers` | — | Restrict origins to Vercel frontend domain |
| Rate Limiting | `django-ratelimit` | — | Login + API throttling |
| Storage | `django-storages` + `boto3` | — | AWS S3 integration for file uploads |
| Environment | `python-decouple` or `django-environ` | — | Environment variable management |

### 3.2 Frontend Stack

| Component | Technology | Version | Purpose |
|---|---|---|---|
| Framework | React | 18+ | Component-based SPA |
| Build Tool | Vite | 5+ | Fast builds, HMR, optimized production bundles |
| Routing | React Router | 6+ | Client-side routing with protected routes |
| State Management | React Query (TanStack Query) | 5+ | Server state caching, auto-refetch, optimistic updates |
| Forms | React Hook Form + Zod | — | Performant forms with schema validation |
| Styling | Tailwind CSS | 3+ | Utility-first responsive design |
| Charts | Chart.js + react-chartjs-2 | 4+ | Bar, line, doughnut charts for analytics |
| Tables | TanStack Table | 8+ | Sortable, filterable, paginated data tables |
| PDF Export | `html2canvas` + `jspdf` or backend-generated | — | Client-triggered PDF downloads |
| HTTP Client | Axios | — | API calls with interceptors for JWT refresh |
| Notifications | React Hot Toast | — | Toast notifications for actions |
| Icons | Lucide React | — | Consistent icon set |
| Date Handling | date-fns | — | Lightweight date formatting and manipulation |

### 3.3 Infrastructure

| Component | Service | Purpose |
|---|---|---|
| Backend Hosting | Render (Web Service) | Django app with auto-deploy from GitHub |
| Database | Render (Managed PostgreSQL) | Automated backups, 30-day retention |
| Redis | Render (Redis instance) or Upstash | Celery broker |
| Frontend Hosting | Vercel | Static SPA hosting with CDN |
| File Storage | AWS S3 | Tenant documents (ID scans, agreements) |
| Email | SendGrid | Transactional emails (password reset, receipts) |
| SMS | Africa's Talking | Payment confirmation SMS to tenants |
| Domain/DNS | Cloudflare or Vercel DNS | DNS management, optional CDN layer |
| Monitoring | Sentry | Error tracking for both frontend and backend |

---

## 4. Repository & Project Structure

### 4.1 Monorepo Layout

```
willkemedge-dashboard/
├── backend/
│   ├── manage.py
│   ├── requirements/
│   │   ├── base.txt
│   │   ├── dev.txt
│   │   └── prod.txt
│   ├── config/                    # Django project settings
│   │   ├── __init__.py
│   │   ├── settings/
│   │   │   ├── __init__.py
│   │   │   ├── base.py           # Shared settings
│   │   │   ├── development.py    # Dev overrides (DEBUG=True)
│   │   │   └── production.py     # Prod overrides (DEBUG=False)
│   │   ├── urls.py               # Root URL configuration
│   │   ├── wsgi.py
│   │   └── asgi.py
│   ├── apps/
│   │   ├── accounts/             # User auth, login audit, password reset
│   │   │   ├── models.py
│   │   │   ├── serializers.py
│   │   │   ├── views.py
│   │   │   ├── urls.py
│   │   │   ├── permissions.py
│   │   │   ├── signals.py
│   │   │   ├── tasks.py          # Celery tasks (email sending)
│   │   │   ├── tests/
│   │   │   │   ├── test_models.py
│   │   │   │   ├── test_views.py
│   │   │   │   └── test_auth_flow.py
│   │   │   └── admin.py
│   │   ├── buildings/            # Building & unit management
│   │   │   ├── models.py
│   │   │   ├── serializers.py
│   │   │   ├── views.py
│   │   │   ├── urls.py
│   │   │   ├── services.py       # Status transition logic
│   │   │   ├── tests/
│   │   │   └── admin.py
│   │   ├── tenants/              # Tenant lifecycle management
│   │   │   ├── models.py
│   │   │   ├── serializers.py
│   │   │   ├── views.py
│   │   │   ├── urls.py
│   │   │   ├── services.py       # Move-in/move-out business logic
│   │   │   ├── tasks.py          # Welcome SMS, move-out summary
│   │   │   ├── tests/
│   │   │   └── admin.py
│   │   ├── payments/             # Payment processing & M-Pesa/bank integration
│   │   │   ├── models.py
│   │   │   ├── serializers.py
│   │   │   ├── views.py
│   │   │   ├── urls.py
│   │   │   ├── services.py       # Payment matching, overpayment handling
│   │   │   ├── mpesa.py          # Daraja API client (OAuth, C2B registration)
│   │   │   ├── bank.py           # Bank webhook handler
│   │   │   ├── receipt.py        # PDF receipt generation
│   │   │   ├── tasks.py          # Async receipt gen, SMS dispatch, bank polling
│   │   │   ├── tests/
│   │   │   └── admin.py
│   │   ├── reports/              # Reporting & analytics
│   │   │   ├── views.py
│   │   │   ├── urls.py
│   │   │   ├── services.py       # Report data aggregation
│   │   │   ├── exporters.py      # PDF export logic
│   │   │   ├── tests/
│   │   │   └── admin.py
│   │   └── core/                 # Shared utilities
│   │       ├── models.py         # Abstract base models (TimestampedModel)
│   │       ├── pagination.py     # Custom pagination class
│   │       ├── exceptions.py     # Custom exception handler
│   │       └── middleware.py     # Rate limiting, security headers
│   ├── celery_app.py             # Celery configuration
│   ├── Dockerfile
│   ├── render.yaml               # Render deployment config
│   └── .env.example
├── frontend/
│   ├── index.html
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   ├── tsconfig.json
│   ├── package.json
│   ├── public/
│   │   └── favicon.ico
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── api/                  # API client & endpoint definitions
│       │   ├── client.ts         # Axios instance with interceptors
│       │   ├── auth.ts
│       │   ├── units.ts
│       │   ├── tenants.ts
│       │   ├── payments.ts
│       │   └── reports.ts
│       ├── hooks/                # Custom React hooks
│       │   ├── useAuth.ts
│       │   ├── useUnits.ts
│       │   ├── useTenants.ts
│       │   ├── usePayments.ts
│       │   └── useDashboard.ts
│       ├── components/           # Reusable UI components
│       │   ├── ui/               # Primitives (Button, Input, Card, Badge, Modal)
│       │   ├── layout/           # Shell, Sidebar, Header, MobileNav
│       │   ├── charts/           # Chart.js wrapper components
│       │   │   ├── IncomeLineChart.tsx
│       │   │   ├── CollectionBarChart.tsx
│       │   │   ├── OccupancyDoughnut.tsx
│       │   │   └── TenantPaymentChart.tsx
│       │   ├── units/            # UnitCard, UnitGrid, StatusBadge, ProgressBar
│       │   ├── tenants/          # TenantForm, TenantCard, TenantTable
│       │   ├── payments/         # PaymentTable, PaymentForm, RecentPaymentsFeed
│       │   └── dashboard/        # KPICard, AlertsPanel, CollectionProgress
│       ├── pages/                # Route-level page components
│       │   ├── LoginPage.tsx
│       │   ├── DashboardPage.tsx
│       │   ├── UnitsPage.tsx
│       │   ├── UnitDetailPage.tsx
│       │   ├── TenantsPage.tsx
│       │   ├── TenantDetailPage.tsx
│       │   ├── PaymentsPage.tsx
│       │   ├── ReportsPage.tsx
│       │   ├── SettingsPage.tsx
│       │   └── NotFoundPage.tsx
│       ├── contexts/             # React contexts
│       │   └── AuthContext.tsx
│       ├── lib/                  # Utility functions
│       │   ├── constants.ts
│       │   ├── formatters.ts     # Currency, date, percentage formatting
│       │   └── validators.ts     # Zod schemas
│       ├── types/                # TypeScript type definitions
│       │   ├── auth.ts
│       │   ├── unit.ts
│       │   ├── tenant.ts
│       │   ├── payment.ts
│       │   └── report.ts
│       └── styles/
│           └── globals.css       # Tailwind directives + custom CSS variables
├── docs/                         # Project documentation
│   └── api-endpoints.md
├── .github/
│   └── workflows/
│       ├── backend-ci.yml
│       └── frontend-ci.yml
├── .gitignore
├── DEVELOPMENT_PLAN.md
└── README.md
```

---

## 5. Environment Setup

### 5.1 Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.12+ | Backend runtime |
| Node.js | 20 LTS+ | Frontend build tooling |
| PostgreSQL | 16+ | Local development database |
| Redis | 7+ | Local Celery broker |
| Git | 2.40+ | Version control |

### 5.2 Backend Setup Steps

```bash
# 1. Create virtual environment
cd backend
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# 2. Install dependencies
pip install -r requirements/dev.txt

# 3. Configure environment
cp .env.example .env
# Edit .env with local DATABASE_URL, SECRET_KEY, etc.

# 4. Run migrations
python manage.py migrate

# 5. Create superuser (the single admin account)
python manage.py createsuperuser

# 6. Seed development data (custom management command)
python manage.py seed_dev_data

# 7. Start development server
python manage.py runserver

# 8. Start Celery worker (separate terminal)
celery -A celery_app worker --loglevel=info

# 9. Start Celery Beat scheduler (separate terminal)
celery -A celery_app beat --loglevel=info
```

### 5.3 Frontend Setup Steps

```bash
# 1. Install dependencies
cd frontend
npm install

# 2. Configure environment
cp .env.example .env.local
# Edit with VITE_API_BASE_URL=http://localhost:8000/api

# 3. Start development server
npm run dev
```

### 5.4 Environment Variables

**Backend (.env)**:

```env
# Django
SECRET_KEY=<generate-random-50-char-key>
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
DJANGO_SETTINGS_MODULE=config.settings.development

# Database
DATABASE_URL=postgres://user:pass@localhost:5432/willkemedge_db

# Redis
REDIS_URL=redis://localhost:6379/0

# JWT
JWT_ACCESS_TOKEN_LIFETIME_HOURS=8

# AWS S3
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_STORAGE_BUCKET_NAME=willkemedge-documents
AWS_S3_REGION_NAME=af-south-1

# M-Pesa Daraja
MPESA_CONSUMER_KEY=
MPESA_CONSUMER_SECRET=
MPESA_SHORTCODE=
MPESA_PASSKEY=
MPESA_ENV=sandbox  # sandbox or production

# Africa's Talking
AT_API_KEY=
AT_USERNAME=sandbox
AT_SENDER_ID=

# SendGrid
SENDGRID_API_KEY=
DEFAULT_FROM_EMAIL=noreply@willkemedge.co.ke

# CORS
CORS_ALLOWED_ORIGINS=http://localhost:5173

# Sentry
SENTRY_DSN=
```

**Frontend (.env.local)**:

```env
VITE_API_BASE_URL=http://localhost:8000/api
VITE_APP_NAME="Dr. William Osoro - Property Dashboard"
```

---

## 6. Database Design & Schema

### 6.1 Entity Relationship Diagram (Textual)

```
users (1) ──────── (N) login_audit
users (1) ──────── (N) buildings
buildings (1) ──── (N) units
units (1) ──────── (N) tenants        (one active tenant at a time)
units (1) ──────── (N) payments
units (1) ──────── (N) arrears
tenants (1) ────── (N) payments
tenants (1) ────── (N) arrears
tenants (1) ────── (N) tenant_documents
```

### 6.2 Model Definitions (Django ORM)

#### `core/models.py` — Abstract Base

```python
from django.db import models
import uuid

class TimestampedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
```

> **Design Decision — UUIDs vs Auto-Increment:**
> Use UUIDs for all primary keys. This prevents IDOR attacks (sequential IDs are trivially enumerable), eliminates ID collision risks, and is the standard for APIs. The tradeoff is slightly larger index size — negligible at 500-unit scale.

#### `accounts/models.py`

```python
from django.contrib.auth.models import AbstractUser

class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    failed_login_attempts = models.IntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

class LoginAudit(TimestampedModel):
    user = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    email_attempted = models.EmailField()
    success = models.BooleanField()
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp']),
            models.Index(fields=['email_attempted', '-timestamp']),
        ]
```

#### `buildings/models.py`

```python
class Building(TimestampedModel):
    name = models.CharField(max_length=200)
    address = models.TextField()
    owner = models.ForeignKey('accounts.User', on_delete=models.PROTECT)

class UnitStatus(models.TextChoices):
    OCCUPIED_PAID = 'occupied_paid', 'Occupied - Paid'
    OCCUPIED_PARTIAL = 'occupied_partial', 'Occupied - Partial'
    OCCUPIED_UNPAID = 'occupied_unpaid', 'Occupied - Unpaid'
    IN_ARREARS = 'in_arrears', 'In Arrears'
    VACANT = 'vacant', 'Vacant'
    NOTICE_GIVEN = 'notice_given', 'Notice Given'
    UNDER_MAINTENANCE = 'under_maintenance', 'Under Maintenance'

class UnitType(models.TextChoices):
    STUDIO = 'studio', 'Studio'
    ONE_BR = '1br', '1 Bedroom'
    TWO_BR = '2br', '2 Bedrooms'
    THREE_BR = '3br', '3 Bedrooms'

class Unit(TimestampedModel):
    building = models.ForeignKey(Building, on_delete=models.CASCADE, related_name='units')
    unit_number = models.CharField(max_length=20)
    floor = models.IntegerField(default=0)
    unit_type = models.CharField(max_length=10, choices=UnitType.choices)
    monthly_rent = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=UnitStatus.choices, default=UnitStatus.VACANT)

    class Meta:
        unique_together = ['building', 'unit_number']
        ordering = ['building', 'unit_number']
```

#### `tenants/models.py`

```python
class Tenant(TimestampedModel):
    full_name = models.CharField(max_length=200)
    id_number = models.CharField(max_length=20)  # National ID
    phone = models.CharField(max_length=15)
    email = models.EmailField(blank=True)
    emergency_contact = models.CharField(max_length=200)
    unit = models.ForeignKey('buildings.Unit', on_delete=models.PROTECT, related_name='tenants')
    move_in_date = models.DateField()
    move_out_date = models.DateField(null=True, blank=True)
    move_out_reason = models.CharField(max_length=50, blank=True)  # end_of_term / notice / eviction / voluntary
    monthly_rent = models.DecimalField(max_digits=10, decimal_places=2)  # Snapshot at time of tenancy
    deposit_amount = models.DecimalField(max_digits=10, decimal_places=2)
    deposit_refund_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    forwarding_address = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    credit_balance = models.DecimalField(max_digits=10, decimal_places=2, default=0)  # Overpayment credits

    class Meta:
        indexes = [
            models.Index(fields=['is_active', 'unit']),
            models.Index(fields=['id_number']),
        ]

class TenantDocument(TimestampedModel):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='documents')
    document_type = models.CharField(max_length=30)  # national_id / rental_agreement
    file_url = models.URLField()
    file_key = models.CharField(max_length=500)  # S3 object key
```

#### `payments/models.py`

```python
class PaymentMethod(models.TextChoices):
    MPESA = 'mpesa', 'M-Pesa'
    BANK = 'bank', 'Bank Transfer'
    CASH = 'cash', 'Cash'

class Payment(TimestampedModel):
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.PROTECT, related_name='payments')
    unit = models.ForeignKey('buildings.Unit', on_delete=models.PROTECT, related_name='payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_date = models.DateTimeField()
    method = models.CharField(max_length=10, choices=PaymentMethod.choices)
    reference_code = models.CharField(max_length=100, unique=True)
    month_paid_for = models.CharField(max_length=7)  # YYYY-MM format
    receipt_url = models.URLField(blank=True)
    is_verified = models.BooleanField(default=True)  # False for manual entries pending review

    class Meta:
        ordering = ['-payment_date']
        indexes = [
            models.Index(fields=['tenant', 'month_paid_for']),
            models.Index(fields=['unit', 'month_paid_for']),
            models.Index(fields=['reference_code']),
            models.Index(fields=['-payment_date']),
        ]

class PaymentStatus(models.TextChoices):
    PAID = 'paid', 'Paid'
    PARTIAL = 'partial', 'Partially Paid'
    UNPAID = 'unpaid', 'Unpaid'

class Arrears(TimestampedModel):
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.PROTECT)
    unit = models.ForeignKey('buildings.Unit', on_delete=models.PROTECT)
    month = models.CharField(max_length=7)  # YYYY-MM
    amount_due = models.DecimalField(max_digits=10, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    balance = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)

    class Meta:
        unique_together = ['tenant', 'unit', 'month']
        ordering = ['-month']
```

### 6.3 Database Indexing Strategy

| Table | Index | Purpose |
|---|---|---|
| `payments` | `(tenant_id, month_paid_for)` | Fast lookup of payments for a tenant in a specific month |
| `payments` | `(unit_id, month_paid_for)` | Unit payment status calculation |
| `payments` | `(reference_code)` UNIQUE | Duplicate payment detection (M-Pesa replay protection) |
| `payments` | `(-payment_date)` | Recent payments feed on dashboard |
| `tenants` | `(is_active, unit_id)` | Active tenant lookup by unit |
| `arrears` | `(tenant_id, unit_id, month)` UNIQUE | One arrears record per tenant per unit per month |
| `login_audit` | `(-timestamp)` | Login history display |

### 6.4 Data Retention Rules

| Data | Retention | Mechanism |
|---|---|---|
| Payment records | **Permanent** | No delete operations. No archive jobs |
| Tenant records | **Permanent** (minimum 7 years post move-out per KDPA 2019) | `is_active=False` on move-out. Never deleted |
| Tenant documents (S3) | **Permanent** | S3 lifecycle: move to Glacier after 2 years for cost savings |
| Login audit logs | **2 years** | Celery Beat monthly cleanup task |
| Database backups | **30 days** | Render managed PostgreSQL backup policy |

---

## 7. Backend Implementation Plan

### 7.1 API Endpoint Inventory

#### Authentication (`/api/auth/`)

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/auth/login/` | Email + password login, returns JWT pair |
| POST | `/api/auth/refresh/` | Refresh access token using refresh token |
| POST | `/api/auth/logout/` | Blacklist refresh token |
| POST | `/api/auth/password-reset/` | Request password reset email |
| POST | `/api/auth/password-reset/confirm/` | Set new password with reset token |
| GET | `/api/auth/me/` | Get current user profile |
| GET | `/api/auth/login-audit/` | List login audit log (paginated) |
| POST | `/api/auth/unlock/` | Manually unlock locked account |

#### Buildings & Units (`/api/buildings/`, `/api/units/`)

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/buildings/` | List all buildings |
| POST | `/api/buildings/` | Create a building |
| GET | `/api/buildings/{id}/` | Building detail with unit summary |
| GET | `/api/units/` | List all units (filterable by building, status) |
| POST | `/api/units/` | Create a unit |
| GET | `/api/units/{id}/` | Unit detail with current tenant, payment status |
| PATCH | `/api/units/{id}/` | Update unit (rent amount, status) |
| PATCH | `/api/units/{id}/status/` | Manual status change (maintenance, etc.) |
| GET | `/api/units/status-summary/` | Aggregate count per status (for KPI cards) |

#### Tenants (`/api/tenants/`)

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/tenants/` | List tenants (filterable: active/past, unit, name, date range) |
| POST | `/api/tenants/` | Register new tenant (triggers unit status change) |
| GET | `/api/tenants/{id}/` | Tenant detail with payment summary |
| PATCH | `/api/tenants/{id}/` | Update tenant details |
| POST | `/api/tenants/{id}/move-out/` | Process move-out (triggers status change, summary generation) |
| GET | `/api/tenants/{id}/payments/` | All payments for this tenant |
| GET | `/api/tenants/{id}/move-out-summary/` | Generated move-out summary |
| POST | `/api/tenants/{id}/documents/` | Upload tenant document to S3 |
| GET | `/api/tenants/{id}/documents/` | List tenant documents |

#### Payments (`/api/payments/`)

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/payments/` | List all payments (filterable by tenant, unit, month, method) |
| POST | `/api/payments/` | Manual payment entry (cash) |
| GET | `/api/payments/{id}/` | Payment detail |
| GET | `/api/payments/{id}/receipt/` | Download PDF receipt |
| GET | `/api/payments/recent/` | Last 10 transactions (dashboard feed) |
| GET | `/api/payments/collection-progress/` | Current month: collected vs expected |
| POST | `/api/payments/mpesa/validate/` | M-Pesa validation callback (Daraja) |
| POST | `/api/payments/mpesa/confirm/` | M-Pesa confirmation callback (Daraja) |
| POST | `/api/payments/bank/webhook/` | Bank payment webhook |

#### Reports (`/api/reports/`)

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/reports/monthly-collection/` | Monthly collection report (query: `?month=2026-04`) |
| GET | `/api/reports/annual-income/` | 12-month income trend data (query: `?year=2026`) |
| GET | `/api/reports/arrears/` | Current arrears report |
| GET | `/api/reports/occupancy-history/` | Vacancy duration per unit |
| GET | `/api/reports/tenant-payment-history/{tenant_id}/` | Per-tenant payment chart data |
| GET | `/api/reports/move-in-move-out-log/` | Chronological tenant movements |
| GET | `/api/reports/export/monthly-collection/` | PDF export of monthly collection |
| GET | `/api/reports/export/arrears/` | PDF export of arrears report |

#### Dashboard (`/api/dashboard/`)

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/dashboard/summary/` | All KPI data in one call (unit counts, collection progress, alerts) |
| GET | `/api/dashboard/income-trend/` | 12-month income chart data |
| GET | `/api/dashboard/alerts/` | Overdue rents, partial payments, upcoming move-outs |

### 7.2 Business Logic Services

#### Payment Processing Service (`payments/services.py`)

This is the most critical piece of business logic. It handles:

1. **Payment matching:** When a webhook fires, match the account reference (unit number) to the active tenant on that unit
2. **Duplicate detection:** Check `reference_code` uniqueness. Reject replays
3. **Amount classification:**
   - Payment >= monthly rent → status = Paid, excess → `tenant.credit_balance`
   - Payment < monthly rent → status = Partial, progress bar = `(amount_paid / amount_due) * 100`
4. **Credit application:** On new month, if `tenant.credit_balance > 0`, auto-apply to new month's arrears
5. **Unit status update:** After every payment, recalculate unit status based on current month's arrears record
6. **Receipt generation:** Dispatch Celery task to generate PDF and send via SMS/email

#### Unit Status Service (`buildings/services.py`)

Handles all status transitions as defined in the spec:

```python
def recalculate_unit_status(unit_id: UUID) -> str:
    """
    Called after: payment received, tenant registered, tenant moved out,
    and nightly by Celery Beat.

    Returns the new status string.
    """
    # 1. Check if unit has an active tenant
    # 2. If no active tenant → VACANT (unless UNDER_MAINTENANCE)
    # 3. If active tenant with NOTICE_GIVEN flag → NOTICE_GIVEN
    # 4. Get current month's arrears record
    # 5. If amount_paid >= amount_due → OCCUPIED_PAID
    # 6. If amount_paid > 0 → OCCUPIED_PARTIAL
    # 7. If today > grace_day and amount_paid == 0 → IN_ARREARS
    # 8. Else → OCCUPIED_UNPAID
```

#### Nightly Arrears Job (Celery Beat)

Runs at 00:30 EAT daily:

1. For each active tenant, ensure an `arrears` record exists for the current month
2. Recalculate all unit statuses
3. On the 1st of each month: create new arrears records, apply credits from previous month overpayments
4. After grace day (10th): flag unpaid units as IN_ARREARS, trigger alert

### 7.3 Django Management Commands

| Command | Purpose |
|---|---|
| `seed_dev_data` | Create sample buildings, units, tenants, and payments for development |
| `recalculate_statuses` | Force recalculation of all unit statuses (manual fallback) |
| `generate_monthly_arrears` | Create arrears records for a specific month (recovery tool) |
| `cleanup_audit_logs` | Remove login audit records older than 2 years |

---

## 8. Frontend Implementation Plan

### 8.1 Page Inventory & Routing

```tsx
// App.tsx - Route structure
<Routes>
  {/* Public */}
  <Route path="/login" element={<LoginPage />} />
  <Route path="/reset-password" element={<PasswordResetPage />} />
  <Route path="/reset-password/confirm/:token" element={<PasswordResetConfirmPage />} />

  {/* Protected (require auth) */}
  <Route element={<AuthLayout />}>
    <Route path="/" element={<DashboardPage />} />
    <Route path="/units" element={<UnitsPage />} />
    <Route path="/units/:id" element={<UnitDetailPage />} />
    <Route path="/tenants" element={<TenantsPage />} />
    <Route path="/tenants/new" element={<TenantFormPage />} />
    <Route path="/tenants/:id" element={<TenantDetailPage />} />
    <Route path="/tenants/:id/edit" element={<TenantFormPage />} />
    <Route path="/payments" element={<PaymentsPage />} />
    <Route path="/payments/new" element={<PaymentFormPage />} />
    <Route path="/reports" element={<ReportsPage />} />
    <Route path="/settings" element={<SettingsPage />} />
  </Route>

  <Route path="*" element={<NotFoundPage />} />
</Routes>
```

### 8.2 Key Component Specifications

#### Dashboard Page

```
┌──────────────────────────────────────────────────────┐
│  Dr. William Osoro - Property Dashboard    [Logout]  │
├──────────┬───────────────────────────────────────────┤
│          │  KPI Cards Row                            │
│          │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐    │
│  Sidebar │  │Total │ │Occup.│ │Vacant│ │Arrear│    │
│          │  │ 24   │ │  18  │ │  4   │ │  2   │    │
│  - Dash  │  └──────┘ └──────┘ └──────┘ └──────┘    │
│  - Units │                                           │
│  - Tenant│  Collection Progress Bar                  │
│  - Pay   │  ████████████████░░░░░  KES 156K / 200K  │
│  - Report│                                           │
│  - Settin│  ┌─ Income Trend ──────┐ ┌─ Occupancy ─┐│
│          │  │  📈 12-month line   │ │  🍩 Doughnut ││
│          │  │  chart (Chart.js)   │ │  chart       ││
│          │  └─────────────────────┘ └──────────────┘│
│          │                                           │
│          │  ┌─ Recent Payments ──┐ ┌─ Alerts ──────┐│
│          │  │ Last 10 txns table │ │ Overdue list   ││
│          │  │ name|unit|amt|date │ │ Partial list   ││
│          │  └────────────────────┘ │ Move-outs      ││
│          │                         └────────────────┘│
│          │  Quick Actions: [Add Tenant] [Record Pay] │
└──────────┴───────────────────────────────────────────┘
```

#### Unit Grid View

Each unit rendered as a card with:
- Unit number and building name
- Status badge (colour-coded per spec)
- Current tenant name (if occupied)
- Payment progress bar (current month)
- Monthly rent amount

Click → Unit Detail Page showing full history.

#### Tenant Form

React Hook Form with Zod validation:
- Full name (required)
- National ID (required, format validation)
- Phone (required, Kenyan format: +254...)
- Email (optional, format validation)
- Emergency contact (required)
- Unit selection (dropdown, only vacant units)
- Move-in date (date picker)
- Monthly rent (pre-filled from unit, editable)
- Deposit amount (required)
- Document uploads (ID scan + rental agreement)

### 8.3 API Client Architecture

```typescript
// api/client.ts
const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  withCredentials: true,  // Send httpOnly cookies
});

// Request interceptor: attach access token
apiClient.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// Response interceptor: handle 401 → refresh token → retry
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response?.status === 401 && !error.config._retry) {
      error.config._retry = true;
      const newToken = await refreshAccessToken();
      error.config.headers.Authorization = `Bearer ${newToken}`;
      return apiClient(error.config);
    }
    return Promise.reject(error);
  }
);
```

### 8.4 State Management Strategy

| Data Type | Tool | Rationale |
|---|---|---|
| Server data (units, tenants, payments) | TanStack Query | Auto-caching, background refetch, stale-while-revalidate |
| Auth state (user, tokens) | React Context + localStorage | Persists across page refreshes |
| Form state | React Hook Form | No re-renders on every keystroke |
| UI state (modals, sidebar) | Local component state | No need to lift these |

### 8.5 Chart.js Configurations

#### Income Trend (Line Chart)
- Type: `line`
- X-axis: 12 months (labels: Jan–Dec)
- Y-axis: KES amount (formatted with `toLocaleString('en-KE')`)
- Dataset: single blue line, point markers, area fill with 10% opacity
- Tooltip: month name + exact amount

#### Collection Bar Chart (Stacked Bar)
- Type: `bar` (stacked)
- X-axis: months
- Datasets: 3 stacked series (Full=green, Partial=amber, Unpaid=red)
- Annotation plugin: dashed gold horizontal line for expected rent
- Tooltip: breakdown of each category

#### Occupancy Doughnut
- Type: `doughnut`
- Segments: Occupied (green), Partial (amber), Vacant (grey), Arrears (red)
- Center text plugin: total unit count
- Legend: bottom position

---

## 9. Authentication & Security Implementation

### 9.1 JWT Flow

```
Login Request (email + password)
         │
         ▼
  Validate credentials (bcrypt compare)
         │
    ┌────┴────┐
    │ Failed  │──→ Increment failed_login_attempts
    │         │    Log to login_audit (success=False)
    │         │    If attempts >= 5 → lock for 30 min
    └─────────┘
         │
    ┌────┴────┐
    │ Success │──→ Reset failed_login_attempts
    │         │    Log to login_audit (success=True)
    │         │    Issue JWT pair:
    │         │      access_token  (8hr expiry, signed)
    │         │      refresh_token (7day expiry, httpOnly cookie)
    └─────────┘
         │
         ▼
  Return access_token in response body
  Set refresh_token as httpOnly, Secure, SameSite=Lax cookie
```

### 9.2 Password Reset Flow

```
1. User submits email → POST /api/auth/password-reset/
2. Backend generates crypto-random token, stores hash in DB with 15-min expiry
3. SendGrid sends email with reset link: https://dashboard.willkemedge.co.ke/reset-password/confirm/{token}
4. User clicks link → frontend renders new password form
5. User submits new password → POST /api/auth/password-reset/confirm/
6. Backend validates token (not expired, not used), hashes new password with bcrypt, invalidates token
7. All existing JWT tokens for this user are blacklisted
```

### 9.3 Security Headers Middleware

```python
# core/middleware.py
class SecurityHeadersMiddleware:
    def __call__(self, request):
        response = self.get_response(request)
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-Frame-Options'] = 'DENY'
        response['X-XSS-Protection'] = '0'  # Disabled per modern best practice
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        response['Content-Security-Policy'] = "default-src 'self'; ..."
        if not settings.DEBUG:
            response['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response
```

### 9.4 Rate Limiting Configuration

| Endpoint | Limit | Window | Key |
|---|---|---|---|
| `/api/auth/login/` | 5 requests | 15 minutes | IP address |
| `/api/auth/password-reset/` | 3 requests | 15 minutes | IP address |
| All other API endpoints | 100 requests | 1 minute | Authenticated user |
| M-Pesa/Bank webhooks | 50 requests | 1 minute | IP address (whitelisted Safaricom IPs exempt) |

### 9.5 Input Validation Layers

| Layer | Tool | What It Catches |
|---|---|---|
| Frontend forms | Zod schemas | Type errors, format errors, missing required fields |
| API serializers | DRF Serializers | Type coercion, field validation, cross-field validation |
| Database | PostgreSQL constraints | Unique violations, FK integrity, NOT NULL enforcement |
| File uploads | Custom validator | File type (PDF/JPG/PNG only), max size (5MB), filename sanitization |

---

## 10. Payment Integration Implementation

### 10.1 M-Pesa Daraja Integration

#### Setup Steps

1. Register on Safaricom Developer Portal → get sandbox Consumer Key + Secret
2. Register C2B URLs (Validation + Confirmation) via the Daraja API
3. Implement OAuth token refresh (every 55 minutes)
4. Build and test in sandbox with simulated transactions
5. Go live: get production credentials, register production URLs

#### Daraja Client (`payments/mpesa.py`)

```python
class DarajaClient:
    """Safaricom M-Pesa Daraja API client."""

    def __init__(self):
        self.consumer_key = settings.MPESA_CONSUMER_KEY
        self.consumer_secret = settings.MPESA_CONSUMER_SECRET
        self.base_url = (
            'https://sandbox.safaricom.co.ke'
            if settings.MPESA_ENV == 'sandbox'
            else 'https://api.safaricom.co.ke'
        )
        self._token = None
        self._token_expiry = None

    async def get_access_token(self) -> str:
        """OAuth2 token with automatic refresh."""
        if self._token and self._token_expiry > timezone.now():
            return self._token
        # ... fetch new token from /oauth/v1/generate?grant_type=client_credentials
        # Cache for 55 minutes (tokens expire at 60 min)

    async def register_c2b_urls(self):
        """Register validation and confirmation URLs with Daraja."""
        # POST /mpesa/c2b/v1/registerurl
        # ShortCode, ResponseType, ConfirmationURL, ValidationURL

    def validate_callback_ip(self, request) -> bool:
        """Verify the request comes from Safaricom's IP range."""
        # Check against known Safaricom IP ranges
```

#### Validation Endpoint (`POST /api/payments/mpesa/validate/`)

```python
def mpesa_validate(request):
    """
    Called by Safaricom BEFORE confirming the transaction.
    Return {"ResultCode": 0} to accept, {"ResultCode": 1} to reject.
    """
    # 1. Verify request IP is from Safaricom
    # 2. Parse: TransAmount, BillRefNumber (unit number), TransID
    # 3. Validate: amount > 0, unit number exists, unit has active tenant
    # 4. Check TransID not already processed (replay protection)
    # 5. Accept or reject
```

#### Confirmation Endpoint (`POST /api/payments/mpesa/confirm/`)

```python
def mpesa_confirm(request):
    """
    Called by Safaricom AFTER the transaction is confirmed.
    This is where we record the payment.
    """
    # 1. Verify request IP
    # 2. Parse full payload: TransID, TransAmount, BillRefNumber, MSISDN, TransTime
    # 3. Idempotency check: if TransID already in payments → return success (no duplicate)
    # 4. Match to tenant via unit number (BillRefNumber)
    # 5. Call payment processing service
    # 6. Dispatch receipt generation task (Celery)
    # 7. Return {"ResultCode": 0}
```

### 10.2 Bank Webhook Integration

```python
def bank_webhook(request):
    """
    Bank sends HTTP POST when a transfer is received.
    Payload varies by bank — normalize to common format.
    """
    # 1. Verify webhook signature/secret
    # 2. Parse: amount, sender_name, reference, timestamp, bank_reference
    # 3. Extract unit number from reference field
    # 4. If unit number parseable → auto-match and process
    # 5. If reference unparseable → flag for manual review (create pending payment)
    # 6. Dispatch receipt task
```

### 10.3 Bank Polling Fallback (Celery Beat)

For banks without webhook support:

```python
@celery_app.task
def poll_bank_statement():
    """
    Runs hourly via Celery Beat.
    Calls bank API to fetch recent transactions.
    Processes any new transactions not already in the system.
    """
    # 1. Get last poll timestamp from cache/DB
    # 2. Fetch transactions since last poll
    # 3. For each: check if reference_code exists → skip if duplicate
    # 4. Process new transactions through payment service
    # 5. Update last poll timestamp
```

### 10.4 Payment Processing Flowchart

```
Payment Received (M-Pesa / Bank / Manual)
         │
         ▼
  Duplicate check (reference_code)
         │
    ┌────┴────┐
    │ Exists  │──→ Return success (idempotent)
    └─────────┘
         │
         ▼
  Match to tenant via unit number
         │
    ┌────┴──────┐
    │ No match  │──→ Flag for manual review
    └───────────┘
         │
         ▼
  Get/create arrears record for month_paid_for
         │
         ▼
  Calculate: amount_paid_this_month = existing_payments + new_amount
         │
    ┌────┴──────────────┐
    │ amount >= due      │──→ Status: PAID
    │ excess > 0?        │    Add excess to tenant.credit_balance
    └────────────────────┘
    ┌────┴──────────────┐
    │ 0 < amount < due  │──→ Status: PARTIAL
    └────────────────────┘
         │
         ▼
  Save Payment record
  Update Arrears record
  Recalculate Unit status
  Dispatch: generate_receipt.delay(payment_id)
  Dispatch: send_payment_sms.delay(payment_id)
```

---

## 11. File Storage Implementation

### 11.1 AWS S3 Configuration

```python
# config/settings/base.py
AWS_S3_FILE_OVERWRITE = False
AWS_DEFAULT_ACL = 'private'  # All files private by default
AWS_S3_SIGNATURE_VERSION = 's3v4'
AWS_S3_REGION_NAME = 'af-south-1'  # Cape Town region (closest to Kenya)
AWS_QUERYSTRING_AUTH = True  # Pre-signed URLs for access
AWS_QUERYSTRING_EXPIRE = 3600  # URLs valid for 1 hour

# S3 bucket structure:
# willkemedge-documents/
#   tenants/{tenant_id}/
#     national_id/{filename}
#     rental_agreement/{filename}
#   receipts/{year}/{month}/
#     {payment_id}.pdf
```

### 11.2 Upload Flow

```
1. Frontend: user selects file in TenantForm
2. Frontend: POST /api/tenants/{id}/documents/ with multipart/form-data
3. Backend: validate file type (PDF, JPG, PNG only) and size (max 5MB)
4. Backend: sanitize filename (strip path traversal characters, generate UUID prefix)
5. Backend: upload to S3 using django-storages
6. Backend: save TenantDocument record with S3 key
7. Backend: return document metadata (not the URL — URLs are generated on-demand)
```

### 11.3 Secure File Access

```python
def get_document_url(request, document_id):
    """Generate a pre-signed S3 URL valid for 1 hour."""
    doc = get_object_or_404(TenantDocument, id=document_id)
    url = default_storage.url(doc.file_key)  # Pre-signed URL via django-storages
    return Response({'url': url})
```

---

## 12. Notifications (Email & SMS)

### 12.1 Email via SendGrid

| Trigger | Template | Recipient |
|---|---|---|
| Password reset requested | Reset link with 15-min expiry | Admin email |
| Payment receipt | PDF attachment + summary | Tenant email (if provided) |
| Monthly collection report | PDF attachment | Admin email |

```python
# Celery task
@celery_app.task(bind=True, max_retries=3)
def send_payment_receipt_email(self, payment_id):
    payment = Payment.objects.select_related('tenant').get(id=payment_id)
    if not payment.tenant.email:
        return  # No email on file

    pdf_content = generate_receipt_pdf(payment)
    # Send via SendGrid with PDF attachment
```

### 12.2 SMS via Africa's Talking

| Trigger | Message Content | Recipient |
|---|---|---|
| Tenant registered | Welcome message + Paybill number + account reference | Tenant phone |
| Payment received | Confirmation + amount + balance | Tenant phone |
| Receipt generated | SMS with link to download receipt PDF | Tenant phone |

```python
@celery_app.task(bind=True, max_retries=3)
def send_payment_sms(self, payment_id):
    payment = Payment.objects.select_related('tenant', 'unit').get(id=payment_id)
    message = (
        f"Payment of KES {payment.amount:,.2f} received for "
        f"Unit {payment.unit.unit_number}. "
        f"Ref: {payment.reference_code}. Thank you."
    )
    # Send via Africa's Talking API
```

---

## 13. Reporting & Analytics Engine

### 13.1 Report Data Services

```python
# reports/services.py

def get_monthly_collection(month: str) -> dict:
    """
    Returns: {
        'month': '2026-04',
        'total_expected': Decimal,
        'total_collected': Decimal,
        'collection_rate': float,  # percentage
        'units': [
            {'unit_number': 'A1', 'tenant': 'J. Kariuki', 'expected': 15000,
             'paid': 10000, 'status': 'partial', 'percentage': 66.7}
        ]
    }
    """

def get_annual_income(year: int) -> dict:
    """
    Returns monthly totals for Chart.js line chart.
    {
        'year': 2026,
        'months': [
            {'month': '2026-01', 'collected': 180000, 'expected': 200000},
            ...
        ],
        'total_collected': Decimal,
        'total_expected': Decimal,
        'average_occupancy_rate': float
    }
    """

def get_arrears_report() -> list:
    """All currently unpaid/partial units with tenant details and days overdue."""

def get_tenant_payment_history(tenant_id: UUID) -> list:
    """Monthly payment data for Chart.js bar chart (per-tenant view)."""

def get_occupancy_history(unit_id: UUID) -> list:
    """Timeline of tenancy periods and vacancy gaps for a specific unit."""
```

### 13.2 PDF Export

Using **WeasyPrint** for server-side PDF generation:

```python
# reports/exporters.py

def export_monthly_collection_pdf(month: str) -> bytes:
    """
    1. Get monthly collection data from service
    2. Render Django HTML template with data
    3. Convert HTML → PDF via WeasyPrint
    4. Return PDF bytes
    """
    data = get_monthly_collection(month)
    html = render_to_string('reports/monthly_collection.html', {'data': data})
    pdf = weasyprint.HTML(string=html).write_pdf()
    return pdf
```

PDF templates will be clean HTML with inline CSS, including:
- Header with branding ("Dr. William Osoro - Property Dashboard")
- Report title and date range
- Summary statistics
- Data table with colour-coded status indicators
- Footer with generation timestamp

---

## 14. Testing Strategy

### 14.1 Testing Pyramid

```
         ╱╲
        ╱  ╲        E2E Tests (Playwright)
       ╱    ╲       5-10 critical user journeys
      ╱──────╲
     ╱        ╲     Integration Tests
    ╱          ╲    API endpoints, payment webhooks, status transitions
   ╱────────────╲
  ╱              ╲   Unit Tests
 ╱                ╲  Models, services, serializers, utility functions
╱──────────────────╲
```

### 14.2 Backend Testing

| Type | Tool | What to Test | Target Coverage |
|---|---|---|---|
| Unit | pytest + pytest-django | Models, services, serializers, validators | 90%+ on business logic |
| Integration | pytest + DRF test client | API endpoints, auth flows, webhook handling | All endpoints |
| Task | pytest + celery.contrib.pytest | Celery tasks (receipt gen, SMS, status recalc) | All tasks |

#### Critical Test Cases

**Payment Processing:**
- Full payment → unit status becomes OCCUPIED_PAID
- Partial payment → unit status becomes OCCUPIED_PARTIAL, correct progress percentage
- Overpayment → excess stored as credit balance
- Duplicate M-Pesa callback (same TransID) → idempotent, no double recording
- Payment with invalid unit reference → rejection
- Negative payment amount → rejection
- Payment for unit with no active tenant → rejection

**Tenant Lifecycle:**
- Register tenant → unit status changes from VACANT to OCCUPIED_UNPAID
- Move out → unit status changes to VACANT, tenant.is_active = False
- Move out → all payment history preserved and queryable
- Cannot assign tenant to occupied unit
- Cannot delete tenant record (only deactivate)

**Authentication:**
- Valid login → JWT pair issued, audit log entry
- Invalid password → audit log, attempt counter incremented
- 5 failed attempts → account locked for 30 minutes
- Expired JWT → 401 response
- Refresh token → new access token issued
- Password reset → token email sent, single-use enforcement

**Unit Status Transitions:**
- All transitions from the spec (Section 9.1) have dedicated test cases
- Nightly recalculation produces correct statuses
- Grace period logic (day 10 threshold)

### 14.3 Frontend Testing

| Type | Tool | What to Test |
|---|---|---|
| Component | Vitest + React Testing Library | Component rendering, user interactions |
| Hook | Vitest + renderHook | Custom hooks (useAuth, usePayments) |
| E2E | Playwright | Login flow, add tenant, record payment, view reports |

### 14.4 E2E Test Scenarios (Playwright)

1. **Login → Dashboard:** Login with valid credentials, verify KPI cards render, verify charts load
2. **Add Tenant:** Navigate to tenant form, fill all fields, upload document, submit, verify unit status changes
3. **Record Cash Payment:** Navigate to payment form, enter details, submit, verify unit progress bar updates
4. **View Reports:** Navigate to reports, select monthly collection, verify data renders, export PDF
5. **Move Out Tenant:** Navigate to tenant, initiate move-out, fill details, confirm, verify unit becomes vacant

---

## 15. CI/CD Pipeline & Deployment

### 15.1 GitHub Actions — Backend

```yaml
# .github/workflows/backend-ci.yml
name: Backend CI

on:
  push:
    branches: [develop, main]
    paths: ['backend/**']
  pull_request:
    branches: [develop, main]
    paths: ['backend/**']

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_DB: test_db
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
        ports: ['5432:5432']
      redis:
        image: redis:7
        ports: ['6379:6379']

    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install dependencies
        run: pip install -r backend/requirements/dev.txt
      - name: Run linter
        run: cd backend && ruff check .
      - name: Run type checker
        run: cd backend && mypy apps/
      - name: Run tests
        run: cd backend && pytest --cov=apps --cov-report=xml
        env:
          DATABASE_URL: postgres://test:test@localhost:5432/test_db
          REDIS_URL: redis://localhost:6379/0
      - name: Upload coverage
        uses: codecov/codecov-action@v3
```

### 15.2 GitHub Actions — Frontend

```yaml
# .github/workflows/frontend-ci.yml
name: Frontend CI

on:
  push:
    branches: [develop, main]
    paths: ['frontend/**']
  pull_request:
    branches: [develop, main]
    paths: ['frontend/**']

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - name: Install dependencies
        run: cd frontend && npm ci
      - name: Lint
        run: cd frontend && npm run lint
      - name: Type check
        run: cd frontend && npm run typecheck
      - name: Run tests
        run: cd frontend && npm run test -- --run
      - name: Build
        run: cd frontend && npm run build
```

### 15.3 Deployment Architecture

```
GitHub (develop branch)
    │
    ├──→ Render (auto-deploy on push to main)
    │      ├── Web Service: Django API
    │      ├── Worker: Celery worker
    │      ├── Cron: Celery Beat
    │      └── PostgreSQL (managed)
    │
    └──→ Vercel (auto-deploy on push to main)
           └── Static SPA: React frontend
```

#### Render Configuration (`render.yaml`)

```yaml
services:
  - type: web
    name: willkemedge-api
    env: python
    buildCommand: pip install -r requirements/prod.txt && python manage.py collectstatic --noinput && python manage.py migrate
    startCommand: gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 3
    envVars:
      - key: DJANGO_SETTINGS_MODULE
        value: config.settings.production
      - key: DATABASE_URL
        fromDatabase:
          name: willkemedge-db
          property: connectionString

  - type: worker
    name: willkemedge-celery
    env: python
    buildCommand: pip install -r requirements/prod.txt
    startCommand: celery -A celery_app worker --loglevel=info --concurrency=2

  - type: cron
    name: willkemedge-celery-beat
    env: python
    buildCommand: pip install -r requirements/prod.txt
    schedule: "*/1 * * * *"
    startCommand: celery -A celery_app beat --loglevel=info

databases:
  - name: willkemedge-db
    plan: starter
    databaseName: willkemedge
    postgresMajorVersion: 16
```

---

## 16. Sprint Plan & Milestones

### Overview: 7-Day Compressed Delivery Plan (2026-04-09 → 2026-04-15)

> **Note:** This is an aggressive 7-day delivery schedule replacing the original 16-week plan. Each day is structured into Morning (4h), Afternoon (4h), and Evening (3h) blocks for ~11 productive hours/day. Work is split in parallel between William (frontend lead) and Barclay (backend lead) wherever possible. HIGH priority items are non-negotiable; MEDIUM/LOW items are best-effort.

```
Day 1 (Thu Apr 9):  Foundation — Project Skeleton + Auth + CI/CD
Day 2 (Fri Apr 10): Buildings, Units & Core Layout
Day 3 (Sat Apr 11): Tenants + S3 File Storage
Day 4 (Sun Apr 12): Payments + Arrears + Receipts
Day 5 (Mon Apr 13): M-Pesa + Bank Integration + Notifications
Day 6 (Tue Apr 14): Dashboard + Charts + Reports + PDF Export
Day 7 (Wed Apr 15): Polish, E2E Testing & Production Deployment
```

---

### Day 1 — Foundation: Project Skeleton + Authentication (Thu Apr 9)

**Goal:** Both apps running locally, deployed to staging, login flow end-to-end working.

**Morning (4h) — Project Bootstrap (parallel)**

| # | Task | Owner | Priority |
|---|---|---|---|
| 1.1 | Initialize Django project with split settings (base/dev/prod) | Barclay | HIGH |
| 1.2 | Initialize React + Vite + TypeScript + Tailwind project | William | HIGH |
| 1.3 | Provision PostgreSQL locally + on Render | Barclay | HIGH |
| 1.4 | Configure `.env` files, `python-decouple`, base settings | Barclay | HIGH |
| 1.5 | Set up Tailwind theme tokens, base layout components | William | HIGH |

**Afternoon (4h) — Authentication Backend + Frontend Shell**

| # | Task | Owner | Priority |
|---|---|---|---|
| 1.6 | Custom User model with bcrypt hashing + migration | Barclay | HIGH |
| 1.7 | JWT login/refresh/logout endpoints (`simplejwt`) | Barclay | HIGH |
| 1.8 | Login audit logging model + signal | Barclay | HIGH |
| 1.9 | Account lockout (5 attempts / 30 min) | Barclay | HIGH |
| 1.10 | React Login page + React Hook Form + Zod validation | William | HIGH |
| 1.11 | Axios instance + JWT refresh interceptor | William | HIGH |
| 1.12 | React Router protected routes (`AuthLayout`) | William | HIGH |

**Evening (3h) — CI/CD + Deploy + Tests**

| # | Task | Owner | Priority |
|---|---|---|---|
| 1.13 | GitHub Actions CI (lint + test) for backend & frontend | Barclay | HIGH |
| 1.14 | Deploy skeleton to Render (backend) and Vercel (frontend) | Both | HIGH |
| 1.15 | Unit tests for auth models, views, lockout | Barclay | HIGH |
| 1.16 | Password reset flow (SendGrid) — defer to Day 5 if time-blocked | Barclay | MEDIUM |

**Deliverable:** Owner can log in on staging URL. Failed logins audited. CI green. Both repos auto-deploying.

---

### Day 2 — Buildings & Unit Management (Fri Apr 10)

**Goal:** All units visible with colour-coded status, sidebar shell complete.

**Morning (4h) — Backend Models & APIs**

| # | Task | Owner | Priority |
|---|---|---|---|
| 2.1 | Building & Unit models + migrations | Barclay | HIGH |
| 2.2 | `UnitStatus` enum + status transition service | Barclay | HIGH |
| 2.3 | Building + Unit CRUD endpoints (DRF ViewSets) | Barclay | HIGH |
| 2.4 | Unit status summary endpoint (KPI rollup) | Barclay | HIGH |
| 2.5 | `seed_dev_data` management command (test buildings/units) | Barclay | MEDIUM |

**Afternoon (4h) — Frontend Layout & Unit Views**

| # | Task | Owner | Priority |
|---|---|---|---|
| 2.6 | Responsive sidebar navigation + dashboard layout shell | William | HIGH |
| 2.7 | Unit grid/list page with colour-coded status badges | William | HIGH |
| 2.8 | Unit detail page (read-only + edit modal) | William | HIGH |
| 2.9 | Building add/edit form | William | HIGH |
| 2.10 | TanStack Query setup + global query client config | William | HIGH |

**Evening (3h) — Hardening + Tests**

| # | Task | Owner | Priority |
|---|---|---|---|
| 2.11 | Rate limiting middleware (`django-ratelimit`) | Barclay | MEDIUM |
| 2.12 | Security headers middleware (CSP, HSTS, X-Frame-Options) | Barclay | MEDIUM |
| 2.13 | Unit tests for status transition logic | Barclay | HIGH |
| 2.14 | Mobile responsive pass on unit grid | William | HIGH |

**Deliverable:** Owner views all units with real-time colour status. Buildings/units fully CRUD-able. Sidebar nav live.

---

### Day 3 — Tenant Management + S3 File Storage (Sat Apr 11)

**Goal:** Full tenant lifecycle (move-in → active → move-out) with document uploads.

**Morning (4h) — Tenant Backend + S3 Setup**

| # | Task | Owner | Priority |
|---|---|---|---|
| 3.1 | Tenant + TenantDocument models + migrations | Barclay | HIGH |
| 3.2 | AWS S3 bucket provisioning + IAM + `django-storages` config | Barclay | HIGH |
| 3.3 | Tenant CRUD endpoints (list, create, retrieve, update) | Barclay | HIGH |
| 3.4 | File upload endpoint with type/size validation + sanitization | Barclay | HIGH |
| 3.5 | Pre-signed URL generation for secure document download | Barclay | HIGH |

**Afternoon (4h) — Tenant Frontend + Move-in/out**

| # | Task | Owner | Priority |
|---|---|---|---|
| 3.6 | Tenant list page with search/filter (active/past/unit/name) | William | HIGH |
| 3.7 | Tenant registration form (RHF + Zod) with file upload | William | HIGH |
| 3.8 | Tenant detail page (info + documents + payment summary tab) | William | HIGH |
| 3.9 | Move-out workflow API (assign vacate date, archive) | Barclay | HIGH |
| 3.10 | Move-out modal + confirmation flow | William | HIGH |

**Evening (3h) — Lifecycle Wiring + Tests**

| # | Task | Owner | Priority |
|---|---|---|---|
| 3.11 | On move-in: unit → OCCUPIED_UNPAID + welcome notification stub | Barclay | HIGH |
| 3.12 | On move-out: unit → VACANT, tenant archived | Barclay | HIGH |
| 3.13 | Move-out summary auto-generation | Barclay | MEDIUM |
| 3.14 | Tests for tenant lifecycle transitions | Barclay | HIGH |

**Deliverable:** Tenants can be registered with ID/agreement uploads. Move-out flow archives correctly. Past tenants searchable.

---

### Day 4 — Payment Recording + Arrears + Receipts (Sun Apr 12)

**Goal:** Manual payment recording works end-to-end. Progress bars + arrears live. Celery online.

**Morning (4h) — Payment Backend + Processing Service**

| # | Task | Owner | Priority |
|---|---|---|---|
| 4.1 | Payment + Arrears models + migrations | Barclay | HIGH |
| 4.2 | Payment processing service (matching, partial, overpayment, credit) | Barclay | HIGH |
| 4.3 | Arrears creation/update logic | Barclay | HIGH |
| 4.4 | Payment CRUD + recent + collection progress endpoints | Barclay | HIGH |
| 4.5 | Hook payment processing → unit status recalculation | Barclay | HIGH |

**Afternoon (4h) — Payment Frontend + Receipts**

| # | Task | Owner | Priority |
|---|---|---|---|
| 4.6 | Manual payment entry form (cash/cheque) | William | HIGH |
| 4.7 | Payment progress bar component (0% / 1–99% / 100% colour) | William | HIGH |
| 4.8 | Wire progress bars into unit cards | William | HIGH |
| 4.9 | Payments list page with filters (date, tenant, source) | William | HIGH |
| 4.10 | PDF receipt generation (WeasyPrint template) | Barclay | MEDIUM |

**Evening (3h) — Celery + Nightly Jobs + Tests**

| # | Task | Owner | Priority |
|---|---|---|---|
| 4.11 | Celery + Redis setup (local + Render Redis instance) | Barclay | HIGH |
| 4.12 | Nightly arrears recalculation task (Celery Beat) | Barclay | HIGH |
| 4.13 | Comprehensive payment processing tests (all edge cases) | Barclay | HIGH |

**Deliverable:** Owner records cash payments. Progress bars + arrears auto-update. PDF receipts download. Celery scheduled jobs running.

---

### Day 5 — M-Pesa + Bank Integration + Notifications (Mon Apr 13)

**Goal:** Automated payment capture live in sandbox. Tenants receive SMS + email confirmations.

**Morning (4h) — M-Pesa Daraja Integration**

| # | Task | Owner | Priority |
|---|---|---|---|
| 5.1 | Daraja API client (OAuth + token refresh) | Barclay | HIGH |
| 5.2 | M-Pesa validation endpoint with IP whitelist | Barclay | HIGH |
| 5.3 | M-Pesa confirmation endpoint with idempotency (TransID dedup) | Barclay | HIGH |
| 5.4 | Register C2B URLs with Daraja sandbox | Barclay | HIGH |
| 5.5 | End-to-end M-Pesa simulation in sandbox | Barclay | HIGH |

**Afternoon (4h) — Bank Webhooks + Notifications**

| # | Task | Owner | Priority |
|---|---|---|---|
| 5.6 | Bank webhook endpoint | Barclay | HIGH |
| 5.7 | Bank polling fallback (Celery Beat hourly) | Barclay | MEDIUM |
| 5.8 | SMS notifications via Africa's Talking (payment confirmation) | Barclay | MEDIUM |
| 5.9 | Email receipt delivery via SendGrid | Barclay | MEDIUM |
| 5.10 | Password reset email flow (carryover from Day 1) | Barclay | MEDIUM |
| 5.11 | Payments page: surface M-Pesa/bank source badges | William | HIGH |

**Evening (3h) — Security + Integration Tests**

| # | Task | Owner | Priority |
|---|---|---|---|
| 5.12 | Replay attack protection verification | Barclay | HIGH |
| 5.13 | Integration tests for webhook endpoints | Barclay | HIGH |
| 5.14 | Tests for duplicate/out-of-order callback handling | Barclay | HIGH |

**Deliverable:** M-Pesa sandbox payments auto-capture and reflect on dashboard. Bank webhooks process. Tenants receive SMS/email.

---

### Day 6 — Dashboard, Charts & Reports (Tue Apr 14)

**Goal:** Complete dashboard with KPIs, charts, alerts. All 6 report types + PDF export functional.

**Morning (4h) — Dashboard Backend + KPI Cards**

| # | Task | Owner | Priority |
|---|---|---|---|
| 6.1 | Dashboard summary API (single call: KPIs, trends, recent, alerts) | Barclay | HIGH |
| 6.2 | KPI cards component (Total / Occupied / Vacant / Arrears) | William | HIGH |
| 6.3 | Monthly collection progress bar | William | HIGH |
| 6.4 | Recent payments feed (last 10 transactions) | William | HIGH |
| 6.5 | Alerts panel (overdue, partial, upcoming move-outs) | William | HIGH |

**Afternoon (4h) — Charts + Reports Backend**

| # | Task | Owner | Priority |
|---|---|---|---|
| 6.6 | 12-month income trend line chart (Chart.js) | William | HIGH |
| 6.7 | Portfolio occupancy doughnut chart | William | HIGH |
| 6.8 | Stacked bar (Occupied/Partial/Vacant) | William | HIGH |
| 6.9 | Monthly collection report API + PDF | Barclay | HIGH |
| 6.10 | Annual income summary API | Barclay | HIGH |
| 6.11 | Arrears report API + PDF | Barclay | HIGH |
| 6.12 | Per-tenant payment history API | Barclay | HIGH |
| 6.13 | Occupancy history + move-in/out log APIs | Barclay | MEDIUM |

**Evening (3h) — Reports UI + Mobile + Polish**

| # | Task | Owner | Priority |
|---|---|---|---|
| 6.14 | Reports page with tab/accordion navigation | William | HIGH |
| 6.15 | Per-tenant payment bar chart (green/amber/red + expected rent line) | William | HIGH |
| 6.16 | PDF download triggers wired in frontend | William | HIGH |
| 6.17 | Quick-action buttons (Add Tenant / Record Payment / Reports) | William | MEDIUM |
| 6.18 | TanStack Query auto-refresh (30s on dashboard) | William | MEDIUM |
| 6.19 | Mobile responsive pass on dashboard + reports | William | HIGH |
| 6.20 | Settings page (login audit viewer + account info) | William | MEDIUM |

**Deliverable:** Dashboard complete with charts + alerts. All 6 reports functional with PDF export. Mobile-responsive.

---

### Day 7 — Polish, Testing & Production Deployment (Wed Apr 15)

**Goal:** Production-ready. Secure. Tested. Live with real data.

**Morning (4h) — E2E Testing + Audits**

| # | Task | Owner | Priority |
|---|---|---|---|
| 7.1 | Playwright E2E tests — 5 critical journeys (login, register tenant, record payment, M-Pesa flow, generate report) | William | HIGH |
| 7.2 | Cross-browser testing (Chrome, Firefox, Safari, Edge) | William | HIGH |
| 7.3 | Mobile responsiveness audit + fixes | William | HIGH |
| 7.4 | Security audit: CORS, CSP, rate limiting, input validation | Barclay | HIGH |
| 7.5 | Performance audit: API response times, bundle size | Both | MEDIUM |

**Afternoon (4h) — Production Setup**

| # | Task | Owner | Priority |
|---|---|---|---|
| 7.6 | Sentry setup (backend + frontend) | Barclay | HIGH |
| 7.7 | Production env vars on Render + Vercel | Barclay | HIGH |
| 7.8 | Custom domain + SSL configuration | Barclay | HIGH |
| 7.9 | Verify automated PostgreSQL backups (Render) | Barclay | HIGH |
| 7.10 | Register M-Pesa production C2B URLs | Barclay | HIGH |
| 7.11 | Performance optimizations (lazy loading, code splitting) | William | MEDIUM |

**Evening (3h) — Go Live + Handover**

| # | Task | Owner | Priority |
|---|---|---|---|
| 7.12 | Merge `develop` → `main`, verify auto-deploy | Both | HIGH |
| 7.13 | Create admin account in production | Barclay | HIGH |
| 7.14 | Seed production with real building + unit data | Both | HIGH |
| 7.15 | Smoke test full production flow (login → record payment → report) | Both | HIGH |
| 7.16 | Deployment runbook + handover documentation | William | MEDIUM |
| 7.17 | Stage environment prepared for penetration testing | Barclay | MEDIUM |

**Deliverable:** System live in production. Real M-Pesa payments flowing. Owner managing full portfolio.

---

### 16.1 Critical Path & Risk Notes

- **Day 1 must finish auth + CI/CD** — every subsequent day depends on a working pipeline. If Day 1 slips, compress Day 5 notification work first.
- **Day 5 (M-Pesa)** is the highest external-dependency risk. Daraja sandbox quirks are unpredictable. If integration debugging exceeds the day, fall back to manual payment entry on Day 7 launch and finish M-Pesa post-launch.
- **MEDIUM/LOW items are deferrable** — if any HIGH item slips, drop the same-day MEDIUM tasks first (rate limiting, seed data, monthly auto-email, settings page).
- **Parallelism is mandatory** — William (frontend) and Barclay (backend) work the same day's tasks concurrently, syncing at end-of-block. Solo work on this plan is not feasible in 7 days.
- **Daily standup at start of Morning block** (15 min): blockers from previous day, today's task split, integration touchpoints.
- **Daily integration check at end of Evening block** (30 min): merge feature branches to `develop`, verify staging deploy green, file blockers for next day.

---

## 17. Risk Register & Mitigations

| # | Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|---|
| R1 | M-Pesa Daraja sandbox differs from production behavior | HIGH | MEDIUM | Test extensively in sandbox. Budget 1 week for production integration debugging |
| R2 | Bank does not support webhooks | MEDIUM | HIGH | Polling fallback already designed (Celery Beat hourly). Manual entry as backup |
| R3 | Tenant enters wrong account reference on M-Pesa | MEDIUM | HIGH | Validation endpoint rejects unknown references. Admin manual override for mismatches |
| R4 | Payment recorded twice (callback replay) | HIGH | MEDIUM | Idempotency via unique `reference_code` constraint. TransID dedup check |
| R5 | S3 bucket misconfigured (public access) | CRITICAL | LOW | All objects private. Access via pre-signed URLs only. S3 Block Public Access enabled |
| R6 | JWT secret key leaked | CRITICAL | LOW | Stored in Render env vars. Never in code. Rotate immediately if suspected |
| R7 | Database grows large over time (permanent retention) | LOW | HIGH | PostgreSQL handles this well at 500-unit scale. Add archival strategy at 10K+ payments |
| R8 | Render free tier limitations | MEDIUM | MEDIUM | Use paid Starter plan for production. Free tier for staging only |
| R9 | SendGrid/Africa's Talking API downtime | LOW | LOW | Celery retry with exponential backoff (3 retries). Non-blocking — payment still recorded |
| R10 | WeasyPrint difficult to install on Render | MEDIUM | MEDIUM | Alternative: use reportlab (pure Python) or pre-built Docker image with WeasyPrint deps |

---

## 18. Post-Deployment Checklist

### Security Verification

- [ ] `DEBUG=False` in production
- [ ] `ALLOWED_HOSTS` restricted to production domain
- [ ] `CORS_ALLOWED_ORIGINS` restricted to production frontend URL
- [ ] `SECRET_KEY` is unique, random, 50+ characters
- [ ] All API keys in environment variables, not in code
- [ ] HTTPS enforced (HTTP → HTTPS redirect)
- [ ] Security headers present (HSTS, X-Frame-Options, CSP, X-Content-Type-Options)
- [ ] Rate limiting active on login and API endpoints
- [ ] bcrypt password hashing confirmed (not Django default PBKDF2)
- [ ] JWT httpOnly cookie confirmed (not localStorage)
- [ ] S3 bucket is private, Block Public Access enabled
- [ ] M-Pesa callback URL IP whitelist active
- [ ] No sensitive data in error responses (generic 500 messages)
- [ ] Login audit log capturing all attempts

### Functional Verification

- [ ] Admin can log in and see dashboard
- [ ] KPI cards show correct numbers
- [ ] Charts render with real data
- [ ] Can add a building and units
- [ ] Can register a tenant with document upload
- [ ] Can record a manual (cash) payment
- [ ] Unit status updates correctly after payment
- [ ] Progress bars display correct percentages
- [ ] Can process a move-out
- [ ] Past tenant data accessible
- [ ] Reports generate correctly
- [ ] PDF export works
- [ ] M-Pesa sandbox test payment flows through
- [ ] SMS notifications delivered
- [ ] Email notifications delivered
- [ ] Password reset flow works end-to-end
- [ ] Account lockout triggers after 5 failed attempts
- [ ] Mobile layout is usable on phone screen

### Monitoring

- [ ] Sentry configured and receiving test error
- [ ] Render health checks passing
- [ ] Database backups confirmed running
- [ ] Celery worker processing tasks
- [ ] Celery Beat scheduler running nightly jobs

---

## 19. Penetration Testing Preparation

### 19.1 Staging Environment

Before pen testing, provision a separate staging environment on Render that mirrors production:

- Same code, same configuration, different database (seeded with test data)
- Separate M-Pesa sandbox credentials
- Separate S3 bucket (or folder prefix)

### 19.2 Testing Accounts

Provide the pen tester with:

- Admin credentials (valid login)
- API documentation (endpoint inventory from Section 7.1)
- Architecture diagram
- Known security controls (for grey-box testing)

### 19.3 Pre-Test Self-Assessment

Before engaging the pen tester, run these automated scans:

| Tool | Purpose |
|---|---|
| `safety check` (Python) | Known CVEs in Python packages |
| `npm audit` (Node.js) | Known CVEs in npm packages |
| OWASP ZAP (automated scan) | Common web vulnerabilities |
| `django-check --deploy` | Django deployment security checklist |
| Mozilla Observatory | HTTP security headers audit |

### 19.4 Pen Test Scope Alignment

Ensure the pen tester covers all items from Section 13 of the concept brief:

- OWASP Top 10 (2021) — all 10 categories
- Business logic attacks on payment processing
- IDOR on UUID-based endpoints
- File upload security
- Rate limiting bypass attempts
- M-Pesa callback replay and manipulation

---

## 20. Appendices

### Appendix A: Key Design Decisions Log

| Decision | Options Considered | Chosen | Rationale |
|---|---|---|---|
| Primary keys | Auto-increment vs UUID | UUID | IDOR prevention, no sequential enumeration |
| JWT storage | localStorage vs httpOnly cookie | httpOnly cookie | XSS-proof token storage |
| Task queue | Celery vs Django-Q vs Huey | Celery | Most mature, best Django ecosystem support |
| PDF generation | WeasyPrint vs reportlab vs client-side | WeasyPrint | HTML/CSS templates = easier to maintain |
| State management | Redux vs Zustand vs TanStack Query | TanStack Query | Server-state focused, minimal boilerplate |
| Form library | Formik vs React Hook Form | React Hook Form | Better performance, smaller bundle |
| Charts | Chart.js vs Recharts vs Nivo | Chart.js | Spec requirement, lightweight, well-documented |
| Monorepo vs separate repos | Separate repos vs monorepo | Monorepo | Simpler CI, atomic commits, shared docs |

### Appendix B: Useful Commands Reference

```bash
# Backend
python manage.py makemigrations          # Generate new migration files
python manage.py migrate                 # Apply migrations
python manage.py createsuperuser         # Create admin account
python manage.py seed_dev_data           # Seed development data
python manage.py recalculate_statuses    # Force status recalculation
python manage.py shell_plus              # Enhanced Django shell
pytest --cov=apps -v                     # Run tests with coverage
ruff check . --fix                       # Lint and auto-fix

# Frontend
npm run dev                              # Start dev server
npm run build                            # Production build
npm run lint                             # ESLint
npm run typecheck                        # TypeScript check
npm run test                             # Vitest
npx playwright test                      # E2E tests

# Celery
celery -A celery_app worker -l info      # Start worker
celery -A celery_app beat -l info        # Start scheduler
celery -A celery_app flower              # Monitoring UI (optional)

# Deployment
git push origin develop                  # Push to develop (CI runs)
git checkout main && git merge develop   # Merge to main (auto-deploys)
```

### Appendix C: API Response Format Convention

All API responses follow a consistent format:

```json
// Success (single object)
{
  "id": "uuid",
  "field": "value",
  ...
}

// Success (list with pagination)
{
  "count": 42,
  "next": "https://api.example.com/items/?page=2",
  "previous": null,
  "results": [...]
}

// Error
{
  "detail": "Human-readable error message",
  "code": "error_code"
}

// Validation Error
{
  "field_name": ["Error message for this field"],
  "non_field_errors": ["Error not tied to a specific field"]
}
```

### Appendix D: Colour System

| Status | Hex | Tailwind Class | Usage |
|---|---|---|---|
| Paid / Green | `#16A34A` | `bg-green-600` | Fully paid units, 100% progress bars |
| Partial / Amber | `#D97706` | `bg-amber-600` | Partial payments, 1-99% progress bars |
| Unpaid / Red | `#DC2626` | `bg-red-600` | Unpaid units, 0% progress bars, arrears |
| Vacant / Grey | `#6B7280` | `bg-gray-500` | Vacant units |
| Notice / Blue | `#2563EB` | `bg-blue-600` | Notice given |
| Maintenance / Dark Blue | `#1E40AF` | `bg-blue-800` | Under maintenance |
| Credit / Teal | `#0D9488` | `bg-teal-600` | Overpayment credit indicators |

---

> **Document End**
>
> This plan is a living document. Update it as decisions change, scope adjusts, or new information surfaces during development. Each sprint should begin with a review of the relevant plan sections and end with a retrospective noting any deviations.
