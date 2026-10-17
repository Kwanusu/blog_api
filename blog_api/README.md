# `blog_api/` — the project package

This is the folder `django-admin startproject` created. It holds the settings, the root URL table, and two small
reusable helpers that several apps share. Nothing here is "business logic": it is the wiring that lets the apps
(`accounts`, `blogs`, `school`, `payments`, `mpesa`) work together.

| File | Role |
|------|------|
| `settings.py` | All configuration. Secrets come from `.env` through `python-decouple` |
| `urls.py` | The root URL table: sends `/admin/` and `/api/...` to the right app |
| `location.py` | `LocationMixin` (model fields) and `LocationSerializerMixin` (validation) for anything with a map pin |
| `serializer_fields.py` | `CloudinaryImageField`: accept an upload, return a URL |
| `settings_test.py` | Settings for the automated tests only (fast password hasher) |
| `schema.py` | A small hook that tidies the generated API documentation |
| `tests.py` | Project guard-rails: migrations in sync, one primary-key type, API docs generate |
| `wsgi.py` / `asgi.py` | Entry points for production servers (generated; unchanged) |

---

## 1. `settings.py`, section by section

### 1.1 Reading configuration with `decouple`

```python
SECRET_KEY = config('SECRET_KEY')                       # no default → the app refuses to start without it
DEBUG = config('DEBUG', default=False, cast=bool)      # safe default: production mode
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1,[::1]', cast=lambda v: [...])
```

*Why:* the [Twelve-Factor App](https://12factor.net/config) rule — configuration that changes between machines
lives in the environment, not in code. `cast=` converts the text in `.env` into the right Python type.
Notice the **safe defaults**: `DEBUG` is `False` unless you say otherwise, and `SECRET_KEY` has *no* default so
you can never accidentally run with a published key.

### 1.2 `INSTALLED_APPS` and `MIDDLEWARE`

* Our five apps are listed, plus `rest_framework`, `rest_framework_simplejwt` (JWT login),
  `rest_framework_simplejwt.token_blacklist` (lets us revoke refresh tokens) and `corsheaders`.
* `CorsMiddleware` is placed **above** `CommonMiddleware`. Order matters: CORS headers must be added before
  anything can short-circuit the response.
* `CORS_ALLOWED_ORIGINS` lists the front-end origins (for example the Vite dev server on `localhost:5173`) that
  a browser may call this API from.

### 1.3 `AUTH_USER_MODEL = 'accounts.User'`

We replaced Django's default user with our own (email as the login, plus a `role`). This **must** be set before
the first migration of a project; changing it later is painful (the project folder even keeps a
`db.sqlite3.bak-pre-custom-user` file from when this switch was made). See `accounts/README.md`.

### 1.4 `REST_FRAMEWORK` — the API-wide defaults

| Key | Value | Meaning |
|-----|-------|---------|
| `DEFAULT_PERMISSION_CLASSES` | `IsAuthenticated` | **Deny by default.** A view is public only if it says `AllowAny` |
| `DEFAULT_AUTHENTICATION_CLASSES` | `JWTAuthentication` | Reads `Authorization: Bearer <token>` |
| `DEFAULT_PAGINATION_CLASS` / `PAGE_SIZE` | `PageNumberPagination` / `10` | Lists return `{count, next, previous, results}` |
| `DEFAULT_THROTTLE_CLASSES` | `UserRateThrottle`, `AnonRateThrottle` | Rate limits for everyone |
| `DEFAULT_THROTTLE_RATES` | `user`, `anon` + named scopes | `login: 10/min`, `password_reset: 5/hour`, `social_login: 20/hour`, `payments: 20/hour`, `geocoding: 60/hour` |
| `DEFAULT_SCHEMA_CLASS` | `drf_spectacular` | Generates the OpenAPI schema behind `/api/docs/` |

The **named scopes** (`login`, `payments`, …) are used by `ScopedRateThrottle` on individual views. They protect
the endpoints that are expensive (they send an M-Pesa prompt or an email) or sensitive (they check passwords).

### 1.5 Database, primary keys and cache

The database is chosen from `.env`, not by editing code:

| `.env` | Result |
|--------|--------|
| `DB_BACKEND=sqlite` (default) | A local `db.sqlite3` file: perfect for learning, no installation |
| `DB_BACKEND=postgres` + `DATABASE_URL=postgresql://user:pass@host:5432/name` | PostgreSQL (install `psycopg[binary]`); connections are reused (`DB_CONN_MAX_AGE`) |

It is an **explicit switch** on purpose: a leftover `DATABASE_URL` in someone's `.env` must never silently point a
classroom machine at a remote database.

`DEFAULT_AUTO_FIELD = BigAutoField` gives every model the same primary-key type. Before it was set, migrations written by
different Django versions disagreed (`AutoField` vs `BigAutoField`) and `makemigrations` always found "changes".

`CACHES`: throttle counters and the cached M-Pesa token live in the cache. The default is per-process memory, which is fine
locally; set `REDIS_URL` to share one cache between several server processes in production.

### 1.6 Time zone

`TIME_ZONE = 'Africa/Nairobi'` with `USE_TZ = True`: Django stores UTC in the database and converts to Nairobi
time for display. M-Pesa timestamps are generated with `timezone.localtime()` for that reason.

### 1.7 Email

If `EMAIL_HOST` is empty, `EMAIL_BACKEND` is the **console** backend, so while developing, "sent" emails
(for example password-reset links) are printed in the terminal. Set the SMTP variables to send for real.

### 1.8 Cloudinary and image size

`cloudinary.config(...)` is called once at start-up. `MAX_IMAGE_UPLOAD_SIZE = 5 MB` is enforced by
`CloudinaryImageField` *before* anything is sent to Cloudinary.

### 1.9 JWT settings

```python
SIMPLE_JWT = {
  'ACCESS_TOKEN_LIFETIME': timedelta(minutes=15),   # short: a stolen access token expires quickly
  'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
  'ROTATE_REFRESH_TOKENS': True,                    # every refresh returns a NEW refresh token…
  'BLACKLIST_AFTER_ROTATION': True,                 # …and the old one is blacklisted (cannot be replayed)
  'UPDATE_LAST_LOGIN': True,
}
```

### 1.10 Production hardening

Everything inside `if not DEBUG:` switches on only in production: secure cookies, `nosniff`, optional HTTPS
redirect and HSTS (`SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS`) and the proxy header
(`BEHIND_PROXY`). They are opt-in via `.env` so you can enable them *after* HTTPS works.
Run `python manage.py check --deploy` to see what Django still recommends.

### 1.11 M-Pesa, Google Maps and school details

Grouped at the bottom, each from `.env`. Two points worth remembering:

* `MPESA_ENV='simulate'` never touches the network and auto-completes payments, so the whole payment flow can be
  demoed with no Safaricom account. It is **refused** when `DEBUG` is off (see `payments/mpesa.py::env`).
* `GOOGLE_MAPS_API_KEY` is a *browser* key. It is meant to be public; protect it by restricting the HTTP referrer in
  Google Cloud, not by hiding it.

---

## 2. `urls.py`

```python
path('admin/', admin.site.urls),
path('api/schema/', SpectacularAPIView.as_view(), name='schema'),          # OpenAPI file
path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema')),      # interactive docs
path('api/', include('accounts.urls')),
path('api/', include('blogs.urls')),
path('api/', include('school.urls')),
path('api/', include('mpesa.urls')),
path('api/payments/', include('payments.urls')),
```

Each app owns its URLs (`include`) and the root file only chooses a prefix. Django tries them top to bottom and
takes the first match, so keep prefixes distinct. `payments` gets its own sub-prefix because its router registers
an empty prefix (`r''`). The docs pages are open while `DEBUG=True` and staff-only otherwise
(`SPECTACULAR_SETTINGS['SERVE_PERMISSIONS']`).

## 3. `location.py` — a reusable model mix-in

Teachers, students and courses all need an address with a map pin. Instead of copying four fields three times we
wrote an **abstract model**:

```python
class LocationMixin(models.Model):
    address, latitude, longitude, place_id
    class Meta:
        abstract = True          # no table of its own; fields are copied into each child model
```

* Latitude/longitude are `DecimalField(max_digits=9, decimal_places=6)` with min/max validators (−90..90, −180..180).
  `Decimal` is used rather than `float` so values round-trip exactly.
* `has_location` is a small convenience property.
* `LOCATION_FIELDS` is the list of field names so serializers can write `*LOCATION_FIELDS` instead of repeating them.
* `LocationSerializerMixin.validate()` enforces one rule: **a pin needs both coordinates** (both or neither).
  It looks at the incoming data first and falls back to the saved instance, so a `PATCH` that sends only
  `latitude` is checked against the stored `longitude`.

> Concepts shown: abstract base classes, DRY, multiple inheritance with `super().validate(attrs)`, cooperative mix-ins.

## 4. `serializer_fields.py` — a custom serializer field

`CloudinaryImageField` extends DRF's `ImageField`:

1. **Writing** (`to_internal_value`): DRF/Pillow already checks that the file really is an image; we additionally
   reject files larger than `MAX_IMAGE_UPLOAD_SIZE` with a clear message.
2. **Reading** (`to_representation`): return `value.url` (or `None`), so clients see a plain URL string.

The uploaded file is handed to the model's `CloudinaryField`, which uploads it when the object is saved.
Used by `Blog.image` and `Course.thumbnail`. The tests in `blogs/tests.py` mock the upload so no network call is made.

---

## 5. Added in the code review

* **Static files:** `STATIC_ROOT = BASE_DIR / 'staticfiles'` plus **WhiteNoise** middleware (only when `DEBUG` is off) so
  `collectstatic` works and the admin keeps its styling in production without a separate web server.
* **Logging:** a console `LOGGING` configuration (`LOG_LEVEL` in `.env`). Use `logger = logging.getLogger(__name__)` in a
  module instead of `print()`; the module name tells you where a message came from.
* **`django-filter`** is enabled (`'django_filters'` in `INSTALLED_APPS`), giving `?field=value` filters on list endpoints.
* **API documentation:** `drf-spectacular` builds `/api/docs/` from your serializers and views. `schema.py` hides the old
  slash-less location URL so each operation appears once.
* **`settings_test.py`:** `python manage.py test --settings=blog_api.settings_test` replaces the slow PBKDF2 hasher with a fast
  one (the 193 tests run in about 2 seconds instead of about a minute) and silences expected log noise. **Never** use it on a server.
* **`tests.py`:** fails if a model change has no migration (`makemigrations --check`), checks every app uses `BigAutoField`
  and that the OpenAPI schema builds.

## 6. Exercises

1. Turn on `DEBUG=False` locally and run `python manage.py check --deploy`. Which warnings appear and why?
2. Change `PAGE_SIZE` to 5 and call `GET /api/v1/blogs/`. What changes in the JSON?
3. Add a new throttle scope called `uploads` and apply it to the blog create action.
4. Create a second abstract mix-in `TimeStampedModel` (`created_at`, `updated_at`) and use it in one model.
5. Open `/api/docs/`, authorise with a JWT, and call an endpoint from the browser. Which serializer field produced each part of the response?
6. Set `DB_BACKEND=postgres` against a local PostgreSQL and re-run `migrate` and the tests.
