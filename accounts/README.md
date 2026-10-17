# `accounts/` — users, roles, login and permissions

Everything about **who you are** and **what you may do** lives here. Every other app imports from it.

| File | What it does |
|------|--------------|
| `models.py` | Custom `User` (email login + `role`) and its `UserManager` |
| `serializers.py` | Register, role update, forgot/reset/change password, Google login payloads |
| `views.py` | Register, me, users admin, login/refresh/logout, password flows, Google sign-in |
| `urls.py` | Routes for all of the above |
| `permissions.py` | Role helpers and permission classes used across the whole project |
| `emails.py` | Password-reset and teacher-invitation emails |
| `google.py` | Verifies a Google ID token |
| `admin.py` | Django admin screen for the custom user |
| `tests.py`, `test_review_fixes.py` | 39 tests: roles, password flows, Google login, token lifecycle, throttling, email case, logout ownership |

---

## 1. The custom user model (`models.py`)

Django's built-in `User` logs in with a *username*. Modern apps log in with an **email**, and we also need a
**role**. So we subclassed `AbstractUser`:

```python
class User(AbstractUser):
    class Role(models.TextChoices):      # ADMIN, EDITOR, AUTHOR, TEACHER, STUDENT, READER
        ...
    username = None                      # remove the username column
    email = models.EmailField(unique=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.READER)
    USERNAME_FIELD = 'email'             # what you type to log in
    REQUIRED_FIELDS = []                 # extra prompts for createsuperuser (email+password are enough)
    objects = UserManager()
```

Points to understand:

* **`TextChoices`** gives you readable constants (`User.Role.ADMIN`) that are stored as short strings
  (`'admin'`) and checked by serializers and the admin.
* **A custom manager is mandatory** once `username` is removed, because the default `create_user()` expects a
  username. `UserManager._create_user` normalises the email, hashes the password with `set_password()`, and saves.
  `create_superuser` insists on `is_staff=True` and `is_superuser=True`.
* **`save()` override:** a superuser is always `admin`, so `createsuperuser` can never produce a superuser with the
  wrong role.
* **Convenience properties** (`is_admin_role`, …) keep role comparisons readable.
* **Emails are stored lower-case** (`_create_user` and `User.save()`), and a `UniqueConstraint(Lower('email'))` makes the
  database itself refuse `Ann@x.com` when `ann@x.com` exists. `get_by_natural_key()` looks users up with `__iexact`, so a person
  who types `ANN@X.com` at login still gets in. Migration `0004_lowercase_emails` converts existing rows first and stops with a
  clear message if two accounts differ only by case; `0005` then adds the constraint.
* The default role is `READER`. Higher roles are **only** granted by an admin (or by a business rule such as
  "enrolling in a course makes a reader a student").

Migrations `0001`–`0003` show the history: initial model, then the role choices, then switching to the custom
manager and removing `username`.

## 2. Registration and profile

* `RegisterSerializer` accepts `email, first_name, last_name, password`. `role` is **read-only**, and `create()`
  hard-codes `Role.READER`. A client sending `"role": "admin"` is silently ignored (test: `test_register_ignores_role`).
  This is an example of **never trusting client input for privileged fields** (mass-assignment protection).
* `validate_email` rejects an address that already exists in **any** letter case, so the user gets a friendly 400 instead of a database error.
* `password` is `write_only` (never returned) and run through Django's `validate_password` (length, common
  passwords, numeric-only, similarity).
* `UserSerializer` (used by `/auth/me/` and the admin user list) exposes `id, email, first_name, last_name, role`, all read-only.

## 3. Login with JWT

* `POST /api/token/` → `LoginView(TokenObtainPairView)` returns `{access, refresh}`.
  `throttle_scope = 'login'` (10 per minute) slows password guessing.
* The client sends `Authorization: Bearer <access>` on every request. Access tokens last 15 minutes.
* `POST /api/token/refresh/` exchanges a refresh token for a new access token. Because
  `ROTATE_REFRESH_TOKENS` and `BLACKLIST_AFTER_ROTATION` are on, the old refresh token dies immediately.
* `POST /api/auth/logout/` takes `{"refresh": "..."}` and **blacklists** it, so logging out really ends the session
  (JWTs are otherwise stateless and cannot be "deleted"). The view also checks that the token's `user_id` belongs to the
  signed-in caller, so nobody can log another person out with a stolen refresh token.

> JWT in one sentence: the server signs a small JSON payload (user id, expiry); anyone holding it is that user until it expires.

## 4. Password flows

| Endpoint | Behaviour | Security idea |
|----------|-----------|----------------|
| `POST /auth/password/forgot/` | Always answers 200 with the same message | **No account enumeration**: an attacker cannot learn which emails exist |
| `POST /auth/password/reset/` | Takes `uid`, `token`, `new_password` | Uses Django's `default_token_generator`; the token is **single-use** (it hashes the old password) and expires after `PASSWORD_RESET_TIMEOUT` |
| `POST /auth/password/change/` | Signed-in users send `old_password` + `new_password` | Checks the old password before accepting a new one |

`emails.py` builds the link to the **front-end** page (`PASSWORD_RESET_URL?uid=…&token=…`). Email errors are
logged but never shown to the caller, to keep responses uniform. `send_teacher_setup_email` re-uses the same
token mechanism to invite a new teacher to choose a password (see `school/`).

## 5. Google sign-in

1. The front end uses Google Identity Services and obtains an **ID token**.
2. It posts `{"id_token": "..."}` to `/api/auth/google/`.
3. `google.py` verifies signature, expiry and audience (`GOOGLE_CLIENT_ID`) and requires `email_verified`.
4. If the email already exists → log in (role unchanged). Otherwise create a `reader` with an **unusable password**.
5. Return our own JWT pair plus `created: true/false`.

The role is never taken from Google or the client.

## 6. Permissions (`permissions.py`) — the heart of the project

```python
def has_role(user, *roles): return bool(user and user.is_authenticated and user.role in roles)
```

| Class | Rule |
|-------|------|
| `IsAdminRole` | admin only |
| `IsEditorOrAdmin` | admin or editor |
| `ReadOnlyOrEditor` | any signed-in user may read; only editor/admin may write |
| `IsWriter` | admin, editor or author (used by the earnings endpoint; moved here from `blogs/views.py`) |
| `BlogPermission` | reader: read · author: create + edit **own** · editor: edit any · admin: delete |

DRF checks permissions in two steps:

1. `has_permission(request, view)` — *may this user use this endpoint at all?*
2. `has_object_permission(request, view, obj)` — *may they touch this particular object?*
   `BlogPermission` uses it so an author can edit only blogs where `obj.author.user_id == user.id`.

`UserViewSet` (admin only, `GET`/`PATCH` only via `http_method_names`) lets an admin change a role with
`PATCH /api/v1/users/<id>/ {"role": "editor"}`.

## 7. What the tests teach

Read `tests.py` as a specification. Highlights: `RBACTests` (every role against blogs/authors),
`PasswordFlowTests` (token reuse, expiry, throttling), `GoogleLoginTests` (all failure modes, using mocks so no
network is needed), `ApiProtectionTests` (an **allow-list test** that fails if someone accidentally makes a new
endpoint public) and token blacklisting.

---

## 8. Remaining design notes (good discussion topics)

* Roles are a single string. Real systems often need several roles per user or Django `Group`s.
* The old limitations (case-sensitive emails and unrestricted logout) were fixed in the code review; the tests in
  `test_review_fixes.py` describe the new behaviour.

## 9. Exercises

1. Add a `phone` field to `User`, migrate, and expose it in `UserSerializer`.
2. Write a test proving that an `editor` cannot promote someone to `admin` (hint: change `UserViewSet` permission or add validation).
3. Add a `GET /api/auth/sessions/` endpoint that lists a user's outstanding refresh tokens (look at `OutstandingToken`).
4. Read `test_review_fixes.py` and explain why `test_the_database_itself_refuses_case_duplicates` bypasses the serializer on purpose.
