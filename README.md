# BauCu – Django Voting System

A production-grade web application for vote counting with full audit trail, double-entry verification, and real-time dashboard.

---

## Features

| Feature | Description |
|---|---|
| **Ballot Entry** | Single entry + bulk import (CSV upload or paste) |
| **Double-Entry Verification** | Two operators must confirm each ballot before finalization |
| **Admin Dashboard** | Real-time vote percentages, Chart.js charts, auto-refresh |
| **Audit Trail** | Every create/update/verify/reject logged with before/after JSON |
| **Role-Based Access** | ADMIN, OPERATOR, VIEWER roles with enforced permissions |
| **Concurrency Safety** | `transaction.atomic()`, `SELECT ... FOR UPDATE`, optimistic locking |
| **Bulk Processing** | Chunked bulk inserts (500/batch), Celery for async processing |
| **Caching** | Redis-backed cache for dashboard aggregations |
| **Responsive UI** | Bootstrap 5, works on desktop/tablet/mobile |

---

## Architecture

```
┌─────────────┐     ┌────────────┐     ┌────────────┐
│  Bootstrap 5 │────▶│  Django    │────▶│ PostgreSQL │
│  Frontend    │     │  Backend   │     │  Database  │
└─────────────┘     └─────┬──────┘     └────────────┘
                          │
                    ┌─────▼──────┐
                    │   Redis    │
                    │ Cache+Queue│
                    └─────┬──────┘
                          │
                    ┌─────▼──────┐
                    │   Celery   │
                    │  Workers   │
                    └────────────┘
```

---

## Quick Start

### Option 1: Docker Compose (Recommended)

```bash
docker-compose up --build
docker-compose exec web python manage.py seed_data --ballots 500
```

Open http://localhost:8000

### Option 2: Local Development

```bash
# 1. Create virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/Mac

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure database
# Make sure PostgreSQL is running, then create the database:
#   CREATE DATABASE baucu_db;

# 4. Copy environment variables
copy .env.example .env       # Windows
# cp .env.example .env       # Linux/Mac

# 5. Run migrations
python manage.py migrate

# 6. Seed sample data
python manage.py seed_data --ballots 500

# 7. Start development server
python manage.py runserver
```

Open http://localhost:8000

---

## Default Users

| Username | Password | Role |
|---|---|---|
| `admin` | `admin123` | Administrator |
| `operator1` | `operator123` | Data Operator |
| `operator2` | `operator123` | Data Operator |
| `viewer` | `viewer123` | Viewer |

---

## URL Structure

| URL | Purpose |
|---|---|
| `/` | Redirect to election list |
| `/voting/` | Election list |
| `/voting/create/` | Create election (Admin) |
| `/voting/<id>/` | Election detail |
| `/voting/<id>/ballot/add/` | Enter single ballot |
| `/voting/<id>/ballot/bulk/` | Bulk import (CSV/paste) |
| `/voting/<id>/ballots/` | List all ballots (filterable) |
| `/voting/<id>/verify/` | Pending verification list |
| `/voting/<id>/dashboard/` | Admin dashboard |
| `/voting/<id>/audit/` | Audit log |
| `/voting/api/<id>/dashboard/` | JSON API for dashboard data |
| `/admin/` | Django admin interface |

---

## Data Integrity

- **Atomic Transactions**: All ballot operations wrapped in `transaction.atomic()`
- **Row-Level Locking**: `SELECT ... FOR UPDATE` during ballot verification
- **Optimistic Concurrency**: Version field on ballots prevents lost updates
- **Double-Entry Verification**: Operator cannot verify own entries
- **Audit Logs**: Immutable, tracks before/after for every change

---

## Performance

- **Bulk Inserts**: Chunked at 500 rows per batch
- **Materialized Summaries**: `VoteSummary` table avoids COUNT(*) on dashboard
- **Database Indexes**: On candidate, ballot code, election, verification status
- **Redis Cache**: Dashboard data cached for 30 seconds
- **Connection Pooling**: CONN_MAX_AGE=600 (use PgBouncer in production)

---

## Running Tests

```bash
python manage.py test voting
```

---

## Production Deployment

1. Set `DJANGO_DEBUG=False`
2. Set a strong `DJANGO_SECRET_KEY`
3. Configure a real PostgreSQL server
4. Use PgBouncer for connection pooling
5. Run behind a reverse proxy (Nginx)
6. Use `gunicorn` with multiple workers
7. Start Celery workers for async tasks
