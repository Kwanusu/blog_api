# blog_api — Course Project Overview

A Django 6 + Django REST Framework (DRF) back end that grew lesson by lesson into a small but realistic
platform: a **blog** with a members-only paywall, a **school** (departments, teachers, students, courses,
enrollments), and **M-Pesa** mobile-money payments that tie them together.

Every app folder has its own `README.md` that explains *what was built and why*. Read them in the order below.

| # | Folder | What you learn there |
|---|--------|----------------------|
| 0 | [`blog_api/`](blog_api/README.md) | The project package: settings, URLs, reusable mix-ins and serializer fields |
| 1 | [`accounts/`](accounts/README.md) | Custom user model, roles, JWT login, Google sign-in, password reset, permissions |
| 2 | [`blogs/`](blogs/README.md) | Authors and blogs, ViewSets and routers, image upload, paywall, memberships and tips |
| 3 | [`school/`](school/README.md) | A relational model (departments → courses ← teachers, students ↔ enrollments), role-based access, maps |
| 4 | [`payments/`](payments/README.md) | A production-style M-Pesa STK Push integration: idempotency, callbacks, reconciliation, signals |
| 5 | [`mpesa/`](mpesa/README.md) | A Google-geocoded `Location` API. The *first* M-Pesa version now lives in [`docs/lessons/`](docs/lessons/mpesa_first_version.md) as a before/after study |

---

## 1. Big picture

```
                        ┌────────────────────────── React front end ───────────────────────────┐
                        │   (JWT in Authorization header, polls /api/payments/<id>/ after pay)  │
                        └──────────────────────────────────┬───────────────────────────────────┘
                                                           │  HTTP + JSON
                    ┌──────────────────────────────────────▼───────────────────────────────────┐
                    │                              blog_api (urls.py)                           │
                    │  /admin/  /api/ accounts  /api/ blogs  /api/ school  /api/ mpesa           │
                    │  /api/payments/ payments                                                  │
                    └───────┬──────────────┬───────────────┬──────────────┬─────────────────────┘
                            │              │               │              │
                       ┌────▼───┐     ┌────▼───┐      ┌────▼───┐     ┌────▼─────┐
                       │accounts│◄────│ blogs  │      │ school │     │ payments │──► Safaricom Daraja
                       │ User   │◄────┤ Author │      │ Student│     │ Payment  │◄── callback (webhook)
                       │ roles  │◄────┤ Blog   │      │ Course │     └────┬─────┘
                       └────────┘     │ Member │      │ Enroll │          │ signal: payment_finished
                                      │ Tip    │      └────▲───┘          │
                                      └────▲───┘           │              │
                                           └───────────────┴──────────────┘
                                         receivers.py in blogs and school react to the signal
```

Key design ideas (each is explained in the app that uses it):

* **One identity, many roles.** A single `User` model with a `role` field drives all permissions.
* **Deny by default.** `REST_FRAMEWORK` requires login on every endpoint; public endpoints opt in with `AllowAny`.
* **Thin views, fat services.** Business rules live in `services.py`; views translate HTTP ⇄ Python.
* **Apps don't import each other's internals for payments.** `payments` announces `payment_finished`;
  `blogs` and `school` listen. Adding a new thing to sell never requires editing `payments`.
* **Webhooks are untrusted and repeated.** The callback endpoint is idempotent and guarded by a secret in the URL.

---

## 2. Roles at a glance

| Role | Can do |
|------|--------|
| `reader` (default on sign-up) | Read blogs (premium posts are teasers unless a member), see courses/departments, subscribe, tip, enroll in a course |
| `student` | Everything a reader can, plus see **only their own** student record and enrollments (a reader becomes a student on first enrollment) |
| `author` | Create blogs and edit **their own** blogs; see their tip earnings |
| `teacher` | Read teachers/students/courses; see and **grade** enrollments in **their own** courses only |
| `editor` | Create/edit any blog, author, department, teacher, student, course, enrollment; cannot delete |
| `admin` | Everything, including deletes and changing other users' roles. Django superusers are forced to `admin` |

---

## 3. Endpoint map

| Area | Method + path | Who |
|------|---------------|-----|
| Auth | `POST /api/token/` (login), `POST /api/token/refresh/`, `POST /api/auth/logout/` | public / signed in |
| Auth | `POST /api/auth/register/`, `POST /api/auth/google/` | public |
| Auth | `GET /api/auth/me/`, `POST /api/auth/password/change/` | signed in |
| Auth | `POST /api/auth/password/forgot/`, `POST /api/auth/password/reset/` | public (throttled) |
| Users | `GET/PATCH /api/v1/users/` | admin only |
| Blogs | `/api/v1/blogs/` (CRUD, `?search=`, `?ordering=`), `POST /api/v1/blogs/{id}/tip/` | by role |
| Blogs | `/api/v1/authors/`, `/api/v1/plans/`, `POST /api/v1/plans/{id}/subscribe/` | by role |
| Blogs | `GET /api/v1/membership/`, `GET /api/v1/earnings/` | signed in / writers |
| School | `/api/departments/ teachers/ students/ courses/ enrollments/` | by role |
| School | `POST /api/courses/{id}/enroll/`, `POST /api/enrollments/{id}/cancel/` | signed in |
| School | `GET/PATCH /api/me/student/`, `GET /api/school/info/`, `GET /api/maps/teachers/ students/` | signed in / managers |
| Payments | `GET /api/payments/`, `GET /api/payments/{id}/` (also reconciles a late payment) | owner |
| Payments | `POST /api/payments/mpesa/callback/<secret>/` | Safaricom |
| Locations | `GET/POST /api/locations/`, `GET/PUT/DELETE /api/locations/{id}/` | read: signed in · write: editor, admin |
| Docs | `GET /api/docs/` (Swagger UI), `GET /api/schema/` (OpenAPI) | open when `DEBUG=True`, staff only otherwise |

> The old `POST /api/pay/` and `POST /api/pay/callback/` routes were **removed** in the code review; use the `payments` app.

---

## 4. Running it on Windows (PowerShell)

```powershell
cd C:\Users\Admin\Desktop\2607-Class\django_course\apis\blog_api

python -m venv .venv                 # Django 6.1 needs Python 3.12 or newer (3.13/3.14 work too)
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

copy .env.example .env               # then edit .env – at minimum set SECRET_KEY
python manage.py migrate
python manage.py seed_data           # 5 authors, 25 blogs
python manage.py seed_school         # departments, teachers, students, courses, demo logins
python manage.py createsuperuser     # email + password (role is forced to admin)
python manage.py runserver
```

Run the tests (193 at the time of writing):

```powershell
python manage.py test --settings=blog_api.settings_test    # ~2 seconds
python manage.py test                                      # same tests with real password hashing (~1 minute)
```

`blog_api/settings_test.py` swaps in a fast password hasher; it is for tests only. The suite also fails if a model
change is missing its migration, so always run `python manage.py makemigrations` after editing a model.

### Environment variables (`.env`, read with `python-decouple`)

Never commit `.env`; it is already in `.gitignore`.

| Name | Purpose |
|------|---------|
| `SECRET_KEY` | **Required.** Signs sessions, tokens and reset links |
| `DEBUG` | `True` locally. When `False`, secure-cookie and HTTPS settings switch on |
| `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS` | Comma-separated lists |
| `DB_BACKEND` (`sqlite` default / `postgres`), `DATABASE_URL`, `DB_CONN_MAX_AGE` | Database. `DATABASE_URL` is read **only** when `DB_BACKEND=postgres` |
| `REDIS_URL` | Optional shared cache so throttle counters work across several server processes |
| `LOG_LEVEL` | `INFO` by default; `DEBUG` while developing |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL` | SMTP. If `EMAIL_HOST` is empty, emails are printed to the console |
| `SITE_NAME`, `SITE_URL`, `PASSWORD_RESET_URL`, `TEACHER_SETUP_URL` | Used to build links inside emails |
| `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET` | Image uploads |
| `GOOGLE_CLIENT_ID` | Google sign-in |
| `GOOGLE_MAPS_API_KEY`, `GOOGLE_MAPS_MAP_ID`, `SCHOOL_*` | Maps and the "Visit us" card |
| `MPESA_ENV` (`sandbox` / `production` / `simulate`), `MPESA_CONSUMER_KEY`, `MPESA_CONSUMER_SECRET`, `MPESA_SHORTCODE`, `MPESA_PASSKEY`, `MPESA_CALLBACK_URL`, `MPESA_CALLBACK_SECRET` | M-Pesa. `simulate` works with no credentials and only when `DEBUG=True` |

---

## 5. How to study this project

1. Read `blog_api/README.md`, then open `settings.py` next to it.
2. Follow one request all the way through. Good first trace: `POST /api/token/` → `accounts/urls.py` →
   `LoginView` → SimpleJWT → response. Then `GET /api/v1/blogs/` → router → `BlogViewSet` →
   `BlogPermission` → queryset → `BlogSerializer` → paginated JSON.
3. Read the tests of each app *before* its code. The test names are a plain-English list of the rules.
4. Try the "Exercises" at the end of every app README.

---

## 6. What changed after the code review

Every finding in [`REVIEW.md`](REVIEW.md) has been fixed and is marked *Done* there, with the tests that protect it.
Changed code carries comments starting with **"Review fix …"** that explain *why* the change was made, so you can
search the project for `Review fix` to see them all. New things to know about:

* `.env.example` — the list of settings, safe to commit; copy it to `.env`.
* `docs/lessons/` — code from earlier lessons kept for study (the original `APIView` blog API and the first M-Pesa version).
* `ci/github-actions-ci.yml` — a ready-to-use GitHub Actions workflow (move it to `.github/workflows/`).
* `blog_api/settings_test.py`, `blog_api/schema.py`, `mpesa/throttles.py` — small new modules explained in the app READMEs.

> **Instructor note:** a review of the project (what is complete, what could be tighter, with evidence) is in
> [`REVIEW.md`](REVIEW.md). It is written for the teacher; share it with students when you are ready to
> discuss refactoring.
