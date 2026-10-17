# `mpesa/` — the Location API (and where the first M-Pesa lesson went)

This app now contains one thing: a **location API** that stores places and fills in missing details with Google's Geocoding API.

The original lesson-1 M-Pesa code (`/api/pay/` and `/api/pay/callback/`) was **retired from the live API** during the code review because it
could not work safely, and it was superseded by [`payments/`](../payments/README.md). It is preserved, with the reasons, in
[`docs/lessons/mpesa_first_version.md`](../docs/lessons/mpesa_first_version.md) as a **before/after study**: read that page, then read
`payments/mpesa.py` and `payments/services.py`.

| File | What it does |
|------|--------------|
| `views.py` | The Location views and the Google geocoding helpers |
| `models.py` | `Location` |
| `serializers.py` | `LocationSerializer` |
| `throttles.py` | `GeocodingThrottle`: a per-user limit on writes (which may call Google) |
| `urls.py` | `/api/locations/` and `/api/locations/<id>/` |
| `tests.py` | 14 tests with Google mocked (no network) |

---

## 1. The `Location` API

`Location` stores `address`, `latitude`, `longitude`, `town`, `county`, `country`.

| Request | Who | What happens |
|---------|-----|--------------|
| `GET /api/locations/` | any signed-in user | A **paginated** list (10 per page), ordered by id |
| `GET /api/locations/<id>/` | any signed-in user | One location. Reading **never** writes to the database or calls Google |
| `POST /api/locations/` | editor, admin | Create from an address *or* from coordinates; missing details are filled in by Google |
| `PUT /api/locations/<id>/` | editor, admin | Re-geocode from a new address or new coordinates |
| `DELETE /api/locations/<id>/` | editor, admin | Remove |

How `POST` decides what to do:

* **Coordinates supplied** → validated as numbers inside −90..90 / −180..180 (zero is valid). If the address, town, county or country is missing,
  Google **reverse geocoding** (`latlng=`) supplies it. Values the caller sent are never overwritten.
* **Address only** → Google **forward geocoding** (`address=`) returns the coordinates and address components.
* The result is saved through `LocationSerializer`, which does the final validation.

Google reports `status: "OK"`, and each result's `address_components` contain `locality` (town), `administrative_area_level_1` (county) and `country`.
`_components_from()` extracts them in one place (the code used to be copied three times).

## 2. Concepts shown

* Function-based views with `@api_view`, plus `@permission_classes` and `@throttle_classes`.
* Calling an external API safely with `requests`: a **timeout** (a slow Google must not freeze a worker), `try/except`, and **logging** instead of `print`.
* Reusing an existing permission class (`ReadOnlyOrEditor`): signed-in users read, only editors/admins write.
* A **custom throttle** (`GeocodingThrottle`, scope `geocoding`, 60/hour) that skips plain reads, because only writes cost Google money.
* Manual pagination in a function view with `PageNumberPagination`.
* Keeping a **backwards-compatible alias**: the original detail URL had no trailing slash (`/api/locations/3`). It still works, and `blog_api/schema.py` hides it from the docs.
* **Mocking** in tests: `mock.patch('mpesa.views.requests.get')` lets every test run offline and lets one assert that a forbidden request never reaches Google.

## 3. Behaviour changes from the code review

* The broken M-Pesa routes and the unused `mpesa.Payment` model were removed (migration `0003_delete_unused_payment`; the table was empty).
* Write access is limited to editors and admins and is throttled (before, any signed-in reader could create/delete locations and spend the Google quota).
* `GET` no longer repairs missing coordinates by calling Google and saving (a read must not have side effects).
* Timeouts, logging, `django.conf.settings` instead of importing the settings module, no star imports, no unused imports, trailing-slash URL, pagination.
* The app now has tests (it had none).

## 4. Exercises

1. Rewrite `location_list_create_api_view` as a `ModelViewSet` with a router and compare the line counts.
2. Port `Location` onto `blog_api.location.LocationMixin` (the fields differ: `FloatField` vs `DecimalField`). Write the migration carefully.
3. Cache geocoding results for an address for 24 hours using Django's cache.
4. Read the lesson-1 page in `docs/lessons/`, list five problems in it, and find where `payments/` solves each.
