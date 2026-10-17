# `school/` — departments, teachers, students, courses and enrollments

A relational-data app with **role-based access**, **self-service enrollment with M-Pesa payment**, and **map pins**.

| File | What it does |
|------|--------------|
| `models.py` | `Department`, `Teacher`, `Student`, `Course`, `Enrollment` |
| `serializers.py` | One serializer per model, privacy rules and profile/enroll payloads |
| `views.py` | Five `ModelViewSet`s plus profile, school-info and map views |
| `permissions.py` | `SchoolRolePermission` and `EnrollmentPermission` |
| `services.py` | Provision a teacher login; start, pay for and cancel an enrollment |
| `receivers.py` | Activates an enrollment when its payment succeeds |
| `admin.py` | Admin screens (course list shows an annotated "Enrolled" count) |
| `management/commands/seed_school.py` | Demo data and demo logins |
| `tests.py`, `test_enroll_maps.py`, `test_review_fixes.py` | 57 tests describing every rule |

---

## 1. The data model

```
Department 1─N Teacher          Department 1─N Course
Course N─M Teacher  (ManyToMany)
Student 1─N Enrollment N─1 Course     (Enrollment = the "through" table, with extra data)
User 1─1 Teacher    User 1─1 Student  (optional logins)
Enrollment N─1 Payment
```

* **`on_delete=PROTECT`** for `Teacher.department` and `Course.department`: you cannot delete a department that is still in
  use. The API turns Django's `ProtectedError` into a friendly **409 Conflict** (see `ProtectedDeleteMixin`) instead of a 500.
* **`Teacher`, `Student`, `Course` all inherit `LocationMixin`** (`blog_api/location.py`) to get address/latitude/longitude/place_id for free.
* **`Enrollment` is an explicit join model** because the link carries data: `grade`, `status`, `payment`, `amount_paid`, `paid_at`,
  `enrolled_on`. A `UniqueConstraint(student, course)` makes double enrollment impossible at the **database** level.
* **`Enrollment.status`**: `pending` (waiting for payment) → `active` → or `cancelled`. Staff-created enrollments are active immediately.
* **`Enrollment.grade`** is limited to the choices `A`–`E` (`Enrollment.Grade`) or blank for "not graded yet", so typos like `a+` are rejected.
* **`Course`** extras: `fee` (whole KES, `0` = free), `capacity` (empty = unlimited), `start_date`, `venue_name`, `thumbnail` (Cloudinary).
  Computed helpers `taken_seats`, `seats_left`, `is_full`, `is_free` are properties.
* **`Student.for_user(user)`** is a *get-or-create-or-claim* classmethod: it returns the user's student profile; if staff earlier
  entered a student with the same email and no login, the profile is **claimed** by that user; otherwise a new profile is created
  with a generated admission number (`WEB-000123`).
* `Student.admission_number` and `email` are unique; `Teacher.email` is unique.

## 2. Permissions: a declarative role table

Instead of writing a permission class per view, `SchoolRolePermission` reads three attributes **from the view**:

```python
class CourseViewSet(viewsets.ModelViewSet):
    permission_classes = [SchoolRolePermission]
    read_roles   = ALL_ROLES        # GET / HEAD / OPTIONS
    write_roles  = MANAGER_ROLES    # POST / PUT / PATCH   (admin, editor)
    delete_roles = ADMIN_ONLY       # DELETE
```

You can read the access policy of every endpoint at a glance. Summary:

| Endpoint | read | write | delete |
|----------|------|-------|--------|
| departments, courses | all roles | admin, editor | admin |
| teachers | admin, editor, teacher | admin, editor | admin |
| students | admin, editor, teacher, student (own only) | admin, editor | admin |
| enrollments | admin, editor, teacher, student | admin, editor, teacher (**grade only**) | admin |

`EnrollmentPermission` adds: teachers cannot `POST` new enrollments, and a teacher may update an enrollment only if they teach
that course (`has_object_permission`).

### Row-level filtering with `get_queryset()`
Permissions decide *whether* you may call an endpoint; the queryset decides *which rows* you can see:

* `StudentViewSet`: a student only gets their own record.
* `EnrollmentViewSet`: managers see all; teachers see enrollments in **their** courses (`.distinct()` avoids duplicates from the join);
  everyone else sees only their own. Another student's enrollment returns **404**, not 403 — it does not even reveal that it exists.

## 3. Serializers

* **`TeacherSerializer`** — `department_name` is read-only (`source="department.name"`). `validate_email` rejects emails that already belong to
  a non-teacher login. `create()` runs inside `transaction.atomic()`, saves the teacher, then calls `provision_teacher_account`; if that raises
  `ValueError`, it becomes a normal validation error and the transaction rolls back. `update()` keeps the linked login's email in step with
  the teacher's email (and refuses an address another account already uses, rolling everything back).
* **`StudentSerializer`** — **privacy in `to_representation`**: `address`, `latitude`, `longitude`, `place_id`, `date_of_birth` and `phone` are removed
  unless the viewer is an admin/editor or the student themself. Teachers still get name, admission number and email, which is what they need.
* **`CourseSerializer`** — computed `seats_left`, `is_full`, `teacher_names`, and `my_enrollment` (`{id, status}` for the signed-in user, supplied
  by the view through `context`). `taken` comes from a database annotation so listing courses does not run one query per course (tested in
  `test_listing_courses_does_not_query_per_course` asserts fewer than 12 queries however many courses exist; we measured 4).
* **`EnrollmentSerializer`** — `status`, `payment`, `amount_paid`, `paid_at`, `enrolled_on` are read-only so clients cannot mark themselves paid.
  A teacher who tries to change anything except `grade` gets a 400.
* **`StudentProfileSerializer`** — what a person may edit about themselves (name, phone, location); email is read-only; the phone is normalised
  to `2547…` with the same helper `payments` uses.

## 4. Views worth studying

* **Filtering and search** (`LIST_FILTER_BACKENDS`): `?search=`, `?ordering=` and exact filters such as `?department=2`, `?course=5`, `?status=active`.
  Each view whitelists its own fields; students are searchable by name and admission number only, so phone/date of birth cannot be probed.
* **`CourseViewSet`**
  * `queryset` uses `select_related("department")`, `prefetch_related("teachers")` and `annotate(taken=Count(..., filter=Q(status=active)))`:
    three techniques to keep SQL queries constant.
  * `get_serializer_context()` adds `my_enrollments`, fetched with **one** query for the signed-in user.
  * `@action enroll`: free course → `201` and active at once; paid course → `202 Accepted` with the enrollment and the payment, and the front end polls
    `/api/payments/<id>/`. Errors: `EnrollmentError` → 409, `PaymentError` → 400, missing phone → 400.
* **`EnrollmentViewSet.cancel`** — a student may cancel their **own unpaid** enrollment; managers can cancel anyone's.
* **`StudentProfileView`** — `GET /api/me/student/` returns an *unsaved* blank profile if none exists (no side effects on GET);
  `PATCH` creates/claims the profile with `Student.for_user`.
* **`SchoolInfoView`** — school name, address, pin and the Google Maps browser key for the front end.
* **`TeacherMapView`** — pins for teachers who **opted in** (`show_on_map`) and have coordinates; no emails exposed.
* **`StudentMapView`** — managers only, because a student's address is personal data.

## 5. Business rules in `services.py`

* **`provision_teacher_account(teacher)`** — when an admin adds a teacher, create (or attach) a `User(role=teacher)` with an **unusable password** and
  e-mail a one-time "choose your password" link. The e-mail is queued with `transaction.on_commit` so it is only sent if the database transaction succeeds.
  The Django admin calls the same function (`TeacherAdmin.save_model`), so both entry points behave identically.
* **`start_enrollment(user, course)`** — get the student profile; refuse if already active; then, inside one transaction, **lock the course row**
  (`select_for_update()`), refuse if no seat is left, `get_or_create` the enrollment under `select_for_update()`; re-open a cancelled one; **promote a `reader` to `student`**; activate immediately when the course is free.
* **`seats_in_use(course)`** — seats that are unavailable to a new applicant: **active enrollments plus enrollments whose M-Pesa prompt is still live**
  (a pending payment younger than `SEAT_HOLD`, 10 minutes). The hold means two people can no longer both be told "pay now" for the last seat. It is released
  automatically when the payment is cancelled, fails or expires. On SQLite row locks are ignored; on PostgreSQL they serialise concurrent applicants.
* **`pay_for_enrollment(enrollment, phone)`** — ask `payments` for an STK prompt with reference `ENR-<id>`, link the payment, and remember the phone number on
  the student profile for next time.
* **`cancel_enrollment`** — not allowed if active or if a payment prompt is in flight.

**`receivers.py`** closes the loop: on a successful `ENROLLMENT` payment it finds the enrollment from `ENR-<id>` and calls `enrollment.activate(payment)`,
which copies the amount and paid time onto the enrollment.

## 6. Admin and seed data

* `CourseAdmin` annotates an `_enrolled` count so the "Enrolled" column is sortable without extra queries.
* `EnrollmentAdmin` uses `raw_id_fields` (a text box instead of a giant drop-down) and makes `payment`, `amount_paid`, `paid_at` read-only.
* `python manage.py seed_school [--no-users] [--password …]` creates 4 departments, 5 teachers, 10 students, 7 courses, their enrollments and demo logins.
  It uses `get_or_create` everywhere so it is **safe to re-run**.

## 7. Tests worth reading

`SchoolRBACTests` (the role matrix), `ProtectedDeleteTests` (409 not 500), `TeacherSetupEmailTests`, `EnrollTests` (free, paid, cancelled prompt,
full course, rate limit), `CancelAndVisibilityTests`, `CourseApiTests` (query counts), `StudentProfileTests`, `PrivacyAndMapsTests`.

---

## 8. Behaviour changes from the code review

* **Seat race fixed** with a course row lock and seat holds (above); tests in `test_review_fixes.py::SeatHoldTests`.
* **Student privacy**: teachers no longer receive date of birth or phone number.
* **Grades** restricted to `A`–`E`; **search/filter/ordering** added to the list endpoints; **teacher email** changes now update the login.
* Remaining discussion topic: the capacity check is only as strong as the database's row locking, so test concurrency on PostgreSQL before relying on it.

## 9. Exercises

1. Add a `?teacher=` filter to enrollments (hint: `course__teachers`), using a `FilterSet`.
2. Read `SeatHoldTests` and add a test for a course with two seats and three applicants.
3. Change `SEAT_HOLD` to 5 minutes. Which tests need to change, and why?
4. Add a `GET /api/me/enrollments/` endpoint for the signed-in student.
