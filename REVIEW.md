# Project Review — completeness and efficiency

*Prepared for the instructor. Review date: 17 Oct 2026. Scope: every Python file in `accounts`, `blogs`, `school`,
`payments`, `mpesa` and `blog_api`, `requirements.txt`, `.gitignore` and git history. The `.env` contents were not read
(only the variable names were listed); the front end, a real Safaricom sandbox and PostgreSQL were not part of this review.*

*The review below describes the project **as it was before the fixes**. See the Resolution section for what was done.*

## Resolution (17 Oct 2026): all items fixed

Every item below was fixed in a second pass. The test suite grew from 143 to **193 tests, all passing**
(`python manage.py test --settings=blog_api.settings_test`, about 2 seconds). Each change in the code has a comment starting with
**"Review fix"** and the item letter, so `Review fix A2` finds the drafts change. The migrations were rehearsed on a database
created by the *old* code (mixed-case email, 25 unpublished posts, one location): they applied cleanly and nothing was lost.

| Item | Status | What was done | Protected by |
|------|--------|---------------|--------------|
| A1 backup in git | **Done — you must finish two steps** | `.gitignore` now covers `db.sqlite3*`, `*.bak*`, `*.sqlite3`; the file was removed from git's index (kept on disk). | — |
| A2 drafts | Done | `get_queryset()` hides drafts by role; `is_published` is exposed and writable; default `True`; migration `0007` publishes existing posts | `blogs/test_drafts_and_search.py` |
| A3 search leak | Done | `text` removed from `search_fields`; `?is_premium=` and `?author=` filters added | same |
| A4 legacy M-Pesa / locations | Done | Broken pay + callback routes removed (code kept in `docs/lessons/`); writes limited to editor/admin; throttle; timeouts; no GET side effects; unused model dropped | `mpesa/tests.py` |
| A5 migration drift | Done | `DEFAULT_AUTO_FIELD` + app configs; one clean migration per app; test fails on future drift | `blog_api/tests.py` |
| B1 dependencies | Done | Removed `google`, `beautifulsoup4`, `soupsieve`; `django-filter` and `whitenoise` are now used; `drf-spectacular` added | CI install, schema test |
| B2 email case | Done | Lower-cased on save, case-insensitive login/lookup, DB constraint, data migration `0004` | `accounts/test_review_fixes.py` |
| B3 seat race | Done | Course row lock + seat holds for live payment prompts | `SeatHoldTests` |
| B4 slow tests | Done | `blog_api/settings_test.py` (52 s → 2 s) | — |
| B5 student privacy | Done | Teachers no longer receive date of birth or phone; search cannot probe them | `StudentPrivacyTests` |
| B6 production gaps | Done | `STATIC_ROOT` + WhiteNoise, `LOGGING`, `DB_BACKEND`/`DATABASE_URL` switch, optional `REDIS_URL` cache | `check --deploy`, `collectstatic` run |
| B7 `mpesa/` quality | Done | Refactored (see A4); now has 14 tests | `mpesa/tests.py` |
| C: README, API docs, `.env.example`, ordering/index, grade choices, search/filter, logout ownership, commented code, `IsWriter`, atomic block, idempotency comment, CI, coverage, Python version | Done | README files, `/api/docs/`, `.env.example`, `Author` ordering + `published_date` index, `Enrollment.Grade`, filters on school endpoints, logout checks token owner, old `APIView` code moved to `docs/lessons/`, `IsWriter` moved to `accounts/permissions.py`, redundant `atomic` removed, comment added, `ci/github-actions-ci.yml`, Python 3.12+ stated | respective tests |
| Limitations noted in READMEs: teacher email not syncing, orphaned pending payments | Done | `TeacherSerializer.update` syncs the login; `payments.services.expire_orphans()` runs from `mpesa_reconcile` | `TeacherEmailSyncTests`, `ExpireOrphansTests` |

### Behaviour changes your front end should know about

* `POST /api/pay/` and `POST /api/pay/callback/` no longer exist (they could not work). Use course/membership/tip endpoints and `/api/payments/`.
* `GET /api/locations/` is now **paginated** (`{count, next, previous, results}`); writes need the editor or admin role; `/api/locations/<id>` also works with a trailing slash.
* Blog posts that are drafts are hidden from readers; a new post is published unless `"is_published": false` is sent.
* Teachers no longer see a student's date of birth or phone; `?search=` on blogs no longer matches body text.
* Emails are lower-case everywhere; `Enrollment.grade` accepts only `A`–`E` (or empty).
* An unpaid course enrollment with a live M-Pesa prompt now **reserves a seat for 10 minutes**.

### What you still need to do yourself

1. **A1:** check whether `github.com/Kwanusu/blog_api` is public. The backup was removed from the index only; it is still in git *history*.
   Change the password of the account in that backup, and if the repo is public purge the file from history (`git filter-repo --path db.sqlite3.bak-pre-custom-user --invert-paths`, then force-push). I did not rewrite history or commit anything.
2. Run `pip install -r requirements.txt` and `python manage.py migrate` (new migrations: accounts 0004–0005, blogs 0006–0007, school 0006, mpesa 0003).
3. Move `ci/github-actions-ci.yml` to `.github/workflows/ci.yml` (the tool I used cannot write to `.github`).
4. Optional clean-up of `.env`: the keys `NAME`, `USER`, `PASSWORD`, `HOST`, `PORT` are not read by the project. `DATABASE_URL` is only used if you set `DB_BACKEND=postgres`.
5. Review the changes with `git diff` and commit them. Note: files I did not touch may show as modified only because of Windows line endings.

---

## How this was checked

* Read all the source (about 5 700 lines, 143 tests).
* Installed the pinned `requirements.txt` into a fresh Python 3.13 environment and ran `manage.py check`,
  `makemigrations --check`, `check --deploy` and the **full test suite** with `MPESA_ENV=simulate`.
* Wrote a throw-away probe test (not saved in your project) to confirm behaviours and count SQL queries.

## Verdict

For a teaching project this is **unusually complete and well engineered**: deny-by-default permissions, JWT with rotation and
blacklisting, a real payment lifecycle (idempotent, exactly-once, reconciled), clean separation through services and signals,
and a test suite that reads like a specification. **143 / 143 tests pass.** `manage.py check` reports no issues.
Query counts are good (see "Efficiency"). The items below are the gaps, ordered by importance.

---

## A. Fix first

| # | Finding | Evidence | Suggested fix |
|---|---------|----------|---------------|
| A1 | **A database backup is committed to git.** `db.sqlite3.bak-pre-custom-user` was added in the first commit and is tracked; the remote is `github.com/Kwanusu/blog_api`. It contains one user row (email, PBKDF2 password hash) and session data. `.gitignore` covers `db.sqlite3` but not this name. | `git ls-files`; `git log --all -- db.sqlite3.bak-pre-custom-user` | Check whether the repo is public. `git rm --cached` the file, add `db.sqlite3*` and `*.bak*` to `.gitignore`, **change that account's password**, and purge history (`git filter-repo`) if the repo is public. `.env` and `db.sqlite3` were never committed (verified). |
| A2 | **Drafts are visible to every signed-in user.** `Blog.is_published` is never used by the API: it is not in the serializer and `BlogViewSet` does not filter on it. | Probe: a reader's `GET /api/v1/blogs/` listed an unpublished post | Filter in `get_queryset()` (readers: published only; authors: published + own; editors/admins: all) and add the field to the serializer with the same rule as `is_premium`. |
| A3 | **Paywall can be probed through search.** `search_fields` includes `text`, so `?search=word` matches inside premium text a non-member cannot read. | Probe: a non-member's `?search=secret-word` returned 20 hits for premium-only text | Remove `text` from `search_fields`, or search only `title`/author. |
| A4 | **Legacy `mpesa` callback can never work, and its Location API is open to any signed-in user.** `/api/pay/callback/` uses the default `IsAuthenticated`, so Safaricom receives `401`. Any `reader` can create and delete `Location` rows (and trigger billable Google Geocoding calls). | Probe: anonymous POST → 401; reader POST → 201; reader DELETE → 204 | Either remove the `mpesa` payment views (the `payments` app replaces them) or label the app "lesson 1 only". Add `permission_classes` and a throttle scope to the location views. |
| A5 | **Migration drift.** `makemigrations --check` wants new migrations `blogs/0006` and `school/0006` (`AutoField` ⇄ `BigAutoField`). Existing migrations `0005` were generated by Django **5.2.8** while `requirements.txt` pins Django **6.1.2**. | `python manage.py makemigrations --check --dry-run` | Set `DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'` in settings (and `default_auto_field` in the two missing `apps.py`), generate the migration once, commit it. Pin one Django version for everyone. Important before moving to PostgreSQL. |

## B. Should fix

| # | Finding | Suggested fix |
|---|---------|---------------|
| B1 | **`requirements.txt` lists unused packages.** `google==3.0.0` (a web-scraping package, unrelated to `google-auth`) pulled in `beautifulsoup4` and `soupsieve`; `django-filter` and `whitenoise` are installed but never imported or configured. | Remove `google`, `beautifulsoup4`, `soupsieve`. Either use `django-filter` / `whitenoise` (with `STATIC_ROOT`) or drop them. Consider `requirements.in` + a compiled lock file. |
| B2 | **Emails are case-sensitive in the database.** `Dup@x.com` and `dup@x.com` both register (201 and 201), yet Google login and forgot-password search with `iexact`. | Lower-case in the manager/serializer and add `UniqueConstraint(Lower('email'))`. |
| B3 | **Seat overbooking is possible** (`school/services.py`): `is_full` counts only `active` enrollments, is checked without a lock, and pending enrollments hold no seat. | `select_for_update()` on the `Course` row inside `start_enrollment`, and count recent pending enrollments. Add a concurrency test. |
| B4 | **No test settings.** The suite takes ~52 s mostly hashing passwords with PBKDF2. With a fast hasher it takes **1.2 s** (same 143 tests, measured). | Add `blog_api/settings_test.py` (`PASSWORD_HASHERS = [MD5PasswordHasher]`) and run `manage.py test --settings=blog_api.settings_test`. |
| B5 | **Students' personal data is broadly visible.** Any teacher/editor listing `/api/students/` gets date of birth, phone and email (only address is hidden). | Decide intent; if not needed, remove `date_of_birth`/`phone` for teachers like `PRIVATE` does for the address. |
| B6 | **Production readiness gaps in `settings.py`:** no `STATIC_ROOT` (so `collectstatic` fails), no `LOGGING`, SQLite active while the PostgreSQL block reads `DB_NAME…` but `.env` has `NAME/USER/…` (stale keys), per-process `LocMemCache` used for throttling and the M-Pesa token. | Use `DATABASE_URL` (e.g. `dj-database-url`) and delete the stale keys; add `LOGGING`; configure a shared cache (Redis/DB) before running more than one worker. |
| B7 | **`mpesa/` code-quality problems** (useful as a teaching "refactor me"): `print()` for logging, `requests` calls without `timeout`, `from blog_api.settings import …`, `from .models import *`, unused imports, route `locations/<int:pk>` missing the trailing slash, `GET` that writes to the DB, unused `Payment` model, no tests, duplicate of `LocationMixin`. | Port to `ModelViewSet` + `LocationMixin`, or retire the app. |

## C. Nice to have

* No project `README` or API documentation existed (the READMEs added now cover the first). Add OpenAPI docs with `drf-spectacular` so students can explore endpoints in a browser.
* Add `.env.example` (variable names only) so new students know what to set.
* `Author` has no default ordering (page order not guaranteed); `Blog.published_date` is used for default ordering but is not indexed.
* `grade` is free text; use choices. School list endpoints have no search/filter/ordering (blogs do).
* `LogoutView` blacklists any valid refresh token, not necessarily the caller's.
* `blogs/views.py` carries ~50 lines of commented-out `APIView` code, `IsWriter` lives in `views.py` rather than `accounts/permissions.py`, and `start_membership` wraps one `create()` in `transaction.atomic()`. The commented code is a good teaching reference; consider moving it to a `docs/` snippet.
* Two layers of idempotency (60 s window in `blogs.services` *and* in `payments.services`) both exist; fine, but worth a comment.
* No CI. A GitHub Action running `python manage.py test` and `makemigrations --check` would have caught A5.
* Add coverage for `mpesa/` (zero tests) and for search/ordering on blogs.
* Python 3.14 is used locally (`.venv`); Django 6.1 needs 3.12+. State the supported Python version in the README.

## D. What is already good (worth pointing out to students)

* Secrets only from `.env` (ignored by git); `SECRET_KEY` has no default; `DEBUG` defaults to off; `simulate` payments refused when `DEBUG` is off.
* Deny-by-default DRF permissions with an **allow-list test** that fails if a new endpoint becomes public.
* The role is never accepted from the client (register, Google login, enrollment promotion are all server-decided).
* Password reset does not reveal whether an email exists; tokens are single-use and expire; login/reset/payments are throttled.
* Payments: exactly-once settlement with `select_for_update` + `on_commit`, amount-mismatch → `review`, constant-time callback secret check, reconciliation command, read-only admin.
* Decoupling through the `payment_finished` signal; business rules in `services.py`.
* Privacy by design: teacher map is opt-in, student addresses managers-only, tippers shown by first name only.
* Seed commands are idempotent.

## Efficiency measurements

| Endpoint (probe data) | SQL queries | Comment |
|-----------------------|-------------|---------|
| `GET /api/v1/blogs/` (20 premium posts, reader) | **3** | `select_related` + annotated tip totals + one membership lookup |
| `GET /api/courses/` (15 courses × 3 teachers) | **4** | `prefetch_related` + annotated seat count + one "my enrollments" query |
| `GET /api/enrollments/` (10 rows, manager) | **2** | `select_related('student', 'course')` |
| `GET /api/v1/users/` | 2 | count + page |
| Test suite | 52 s → **1.2 s** | with a fast password hasher (B4) |

There is no N+1 problem on the list endpoints. Remaining efficiency ideas: an index on `Blog.published_date`; `icontains` search on `Blog.text`
is a full scan (fine for a classroom, use full-text search at scale); move expensive geocoding calls out of request/response cycles.

## Suggested order of work

1. A1 (remove the committed backup, rotate that password), A5 (one clean migration).
2. A2 and A3 (drafts and search), with tests first — a good live-coding lesson on writing a failing test.
3. B1 and B4 (dependencies and fast tests).
4. A4/B7 — decide whether `mpesa/` is retired or refactored as a class exercise.
5. B2, B3, B5, B6, then the "nice to have" list.

I can apply any of these if you want. Say which, and I will do them one at a time with tests.
