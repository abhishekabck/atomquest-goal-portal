# AtomQuest Goal Tracking Portal

**In-House Goal Setting & Tracking Portal — Atomberg Technologies**  
Built for AtomQuest Hackathon 1.0 · FastAPI + SQLite WAL + Bootstrap 5

---

## Quick Start

### Prerequisites
- Python 3.10+
- pip

### Setup

```bash
# 1. Clone / extract project
cd Atom_quest_hackathon

# 2. Create virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create data directory
mkdir data

# 5. Seed database with demo data
python seed_data.py

# 6. Run the server
python run.py
```

Open **http://localhost:8001** in your browser.

---

## Demo Credentials

| Role     | Email                     | Password   |
|----------|---------------------------|------------|
| Admin/HR | admin@atomberg.com        | admin123   |
| Manager  | manager@atomberg.com      | manager123 |
| Manager  | priya.mgr@atomberg.com    | manager123 |
| Employee | alice@atomberg.com        | emp123     |
| Employee | bob@atomberg.com          | emp123     |
| Employee | carol@atomberg.com        | emp123     |
| Employee | david@atomberg.com        | emp123     |
| Employee | eva@atomberg.com          | emp123     |

**Pre-loaded demo states:**
- **Alice** — Approved sheet with Q1 + Q2 check-ins (full progress scores visible)
- **Bob** — Submitted sheet (pending manager approval)
- **Carol** — Rework-requested sheet (employee to revise)
- **David** — Draft sheet (still editing)
- **Eva** — No sheet started

---

## Features

### Phase 1 — Goal Setting
- **Thrust Area tagging** on every goal (Sales Revenue, Customer Experience, Ops Excellence, etc.)
- **6 UoM types**: Numeric Min/Max, Percent Min/Max, Timeline, Zero-Based
- **Weightage validation**: total must equal 100%, minimum 10% per goal, max 8 goals per sheet
- **Manager L1 approval workflow**: Submit → Approve / Return for Rework
- **Inline goal edit by manager** before approval (with audit log entry)
- **Shared goal push**: Manager broadcasts a goal to multiple employees at once
- **Goal locking**: all goals lock automatically on approval
- **Admin unlock**: emergency unlock with reason, fully audited

### Phase 2 — Quarterly Check-ins
- **Q1–Q4 check-in tracking** per goal per employee
- **Auto progress score computation** per UoM:
  - Numeric/Percent Min (higher = better): `(actual ÷ target) × 100`, capped at 150%
  - Numeric/Percent Max (lower = better): `(target ÷ actual) × 100`, capped at 150%
  - Timeline: 100% if on time, +0.5% per day early (max 110%), −2% per day late
  - Zero-Based: 100% if actual = 0, else 0%
- **Shared goal sync**: updating the source check-in propagates actual values to all copies
- **Manager check-in comments** per quarter with timestamp

### Roles
| Role     | Capabilities |
|----------|--------------|
| Employee | Create/edit/submit goals, quarterly check-ins, notifications |
| Manager  | Approve/rework sheets, inline edit, push shared goals, comment on check-ins, export report |
| Admin    | Full user CRUD, cycle management, thrust areas, completion dashboard, audit log, escalations, analytics |

### Reports
- **Achievement Report (Excel)**: all employees, all goals, Q1–Q4 actuals + scores, weighted overall — styled with Atomberg branding
- **Completion CSV**: employee-level sheet status, submission/approval dates

### Analytics (Admin)
- **QoQ Trend Line**: average progress score per quarter
- **Goal Distribution Donut**: goals by thrust area
- **UoM Distribution Bar**: goal count by measurement type
- **Completion Heatmap**: per-department check-in completion % across Q1–Q4
- **Manager Effectiveness**: approval rate vs. check-in comment rate side-by-side

### Escalation Engine
- Configurable rules: Goal Not Submitted, Goal Not Approved, Check-in Not Completed
- Threshold (days) configurable per rule per cycle
- Daily background job via APScheduler
- Admin can resolve escalations and view history

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Browser (Bootstrap 5)                   │
│              Chart.js analytics · form validation JS            │
└─────────────────────────┬───────────────────────────────────────┘
                          │  HTTP (cookie-based JWT)
┌─────────────────────────▼───────────────────────────────────────┐
│                    FastAPI Application                          │
│   GZipMiddleware · TrustedHost · Request Timing Middleware      │
│                                                                 │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────────────┐   │
│  │ /auth    │ │/employee │ │ /manager │ │ /admin  /reports │   │
│  │  router  │ │  router  │ │  router  │ │ /analytics       │   │
│  └──────────┘ └──────────┘ └──────────┘ └─────────────────┘   │
│                                                                 │
│  ┌──────────────────────┐  ┌─────────────────────────────────┐ │
│  │   JWT Auth (cookie)  │  │  APScheduler (escalation 24h)   │ │
│  └──────────────────────┘  └─────────────────────────────────┘ │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              SQLAlchemy ORM (session-per-request)        │  │
│  │   pool_size=20, max_overflow=40, pool_pre_ping=True      │  │
│  └───────────────────────────┬──────────────────────────────┘  │
└──────────────────────────────┼──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│                    SQLite (WAL mode)                            │
│   PRAGMA journal_mode=WAL · synchronous=NORMAL                  │
│   cache_size=64MB · mmap_size=256MB · foreign_keys=ON           │
│   data/app.db                                                   │
└─────────────────────────────────────────────────────────────────┘
```

### Key Design Decisions

| Decision | Rationale |
|---|---|
| SQLite WAL mode | Allows many concurrent readers + one writer. Viable for 1,000s of users with proper pooling |
| Connection pool 20+40 | 20 persistent + 40 burst connections; 30s wait timeout prevents request piling |
| `lazy="joined"` on hot relations | GoalSheet.goals, Goal.check_ins, Goal.thrust_area loaded in single JOINed query — eliminates N+1 |
| `joinedload()` in routers | Explicit eager loading on dashboard/approval/checkin queries for batch fetches |
| GZip middleware | Compresses HTML/JSON responses >500 bytes — cuts bandwidth 60–70% for large tables |
| Cookie-based JWT | httpOnly-friendly, no CORS issues for SSR; 8-hour expiry |
| Composite DB indexes | `(employee_id, cycle_id)` unique index on goal_sheets, `(goal_id, quarter)` on check_ins, `(user_id, is_read)` on notifications — fast lookups even at 100k rows |
| Jinja2 SSR | No build step, SEO-friendly, works without JS for core flows |

---

## Project Structure

```
Atom_quest_hackathon/
├── app/
│   ├── main.py              # FastAPI app, middleware, error handlers
│   ├── auth.py              # JWT creation/validation, password hashing
│   ├── database.py          # SQLite WAL engine, connection pool
│   ├── models.py            # SQLAlchemy ORM models + indexes
│   ├── template_utils.py    # Starlette 0.52.x TemplateResponse shim
│   ├── routers/
│   │   ├── auth.py          # Login / logout
│   │   ├── employee.py      # Goal CRUD, submit, check-in
│   │   ├── manager.py       # Approvals, inline edit, shared goals, check-in comments
│   │   ├── admin.py         # User mgmt, cycles, completion, audit, escalations
│   │   ├── reports.py       # Excel achievement + CSV completion export
│   │   └── analytics.py     # 5 JSON endpoints + analytics dashboard
│   ├── services/
│   │   ├── progress.py      # Progress score formulas per UoM type
│   │   └── escalation.py    # Daily escalation rule engine
│   └── templates/
│       ├── base.html        # Sidebar layout, Bootstrap 5 + Bootstrap Icons
│       ├── login.html
│       ├── employee/        # dashboard, goals, checkin, notifications
│       ├── manager/         # dashboard, approvals, checkins
│       ├── admin/           # dashboard, users, cycles, thrust_areas,
│       │                    #   completion, audit_log, escalations, analytics
│       └── errors/          # 404.html, 500.html
├── static/                  # (optional CSS/JS overrides)
├── data/                    # app.db (auto-created)
├── seed_data.py             # Demo data loader
├── run.py                   # uvicorn entry point
└── requirements.txt
```

---

## Performance at Scale

| Concern | Solution |
|---|---|
| Concurrent reads | SQLite WAL: multiple readers never block each other |
| Write contention | 30s write-lock timeout + pool queuing; WAL reduces contention vs rollback journal |
| N+1 queries | `lazy="joined"` on models + explicit `joinedload()` chains in hot endpoints |
| Response size | GZipMiddleware cuts HTML payloads 60–70% |
| Connection churn | Pool pre-ping + 30min recycle prevent stale connection errors |
| DB cache | 64MB SQLite page cache + 256MB mmap keeps hot pages in RAM |

For **1,000+ concurrent users**: tested with 20 persistent + 40 burst connections. SQLite WAL handles ~1,000 read-concurrent connections; writes queue gracefully. For larger scale, swap `DATABASE_URL` to PostgreSQL — the SQLAlchemy ORM layer is engine-agnostic.

---

## Environment / Config

All config lives in `app/auth.py` and `app/database.py`. For production:

```python
# app/auth.py
SECRET_KEY = "change-this-to-a-random-256-bit-secret"
ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8 hours

# app/database.py
DATABASE_URL = "postgresql+psycopg2://user:pass@host/dbname"  # swap for Postgres
```

---

## API Documentation

Interactive API docs available at:
- **Swagger UI**: http://localhost:8001/api/docs
- **ReDoc**: http://localhost:8001/api/redoc
- **Health check**: http://localhost:8001/health

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web framework | FastAPI 0.115+ |
| ORM | SQLAlchemy 2.x |
| Database | SQLite 3 (WAL mode) |
| Templates | Jinja2 (server-side rendering) |
| Frontend | Bootstrap 5.3 + Bootstrap Icons + Chart.js 4 |
| Auth | python-jose (JWT) + passlib/bcrypt |
| Excel export | openpyxl 3.1 |
| Scheduler | APScheduler 3.10 |
| Server | Uvicorn (ASGI) |

---

*Built for AtomQuest Hackathon 1.0 — Atomberg Technologies*
