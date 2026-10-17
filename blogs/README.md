# `blogs/` — authors, blogs, paywall, memberships and tips

This was the first app of the course (a simple blog API) and it grew into a small publishing business:
readers can **subscribe** to unlock premium posts and can **tip** authors, both paid with M-Pesa.

| File | What it does |
|------|--------------|
| `models.py` | `Author`, `Blog`, `MembershipPlan`, `Membership`, `Tip` |
| `serializers.py` | Blog/author serializers, the paywall logic, plan/membership/tip payloads |
| `views.py` | `BlogViewSet`, `AuthorViewSet`, plans, membership status, earnings |
| `urls.py` | A `DefaultRouter` plus two plain routes, all under `/api/v1/` |
| `services.py` | Business rules for buying a membership / sending a tip |
| `receivers.py` | Listens to `payment_finished` and activates memberships / marks tips paid |
| `apps.py` | `ready()` imports `receivers` so the listener is connected at start-up |
| `admin.py` | Admin screens (memberships and tips are read-only: they come from payments) |
| `management/commands/seed_data.py` | Creates 5 authors and 25 posts |
| `tests.py`, `test_membership_tips.py`, `test_drafts_and_search.py` | Image upload; paywall, purchase and tip; drafts, search and filter tests |

---

## 1. Models

```
User ─1:1─ Author ─1:N─ Blog
User ─1:N─ Membership ─N:1─ MembershipPlan          Membership ─1:1─ Payment
Blog ─1:N─ Tip ◄── Author, tipper(User)              Tip ─1:1─ Payment
```

* **`Author`** is a *profile*, not a login. The optional `user` one-to-one link says "this login owns this author
  profile" — that link powers *"authors may edit only their own posts"*.
  `on_delete=SET_NULL` keeps the profile if the login is deleted.
* **`Blog`**: `title`, `text`, `author` (FK, `CASCADE`: deleting an author deletes their blogs),
  `published_date` (indexed: it is the default sort), `created_at` (`auto_now_add`), `is_published`, `image` (a `CloudinaryField`) and
  `is_premium`. **`is_published` controls visibility**: it defaults to `True`, and a draft is created with `"is_published": false`.
  `Author` has a default `Meta.ordering` so paginated author lists are stable.
* **`MembershipPlan`**: a thing for sale — `price` in **whole Kenya shillings** (`decimal_places=0`, because M-Pesa has no cents),
  `duration_days`, `is_active`, `sort_order`. `Meta.ordering` makes lists come out in display order.
* **`Membership`**: one purchase of a plan. Status is `pending` until the payment succeeds, then `active`.
  Two methods hold the rules:
  * `current_for(user)` — the active membership that ends last (or `None`).
  * `activate()` — starts **now**, or when the current period ends if the user renews early, so paid days are never wasted.
* **`Tip`**: a one-off payment from a reader to an author for one post. `blog`/`author`/`tipper` use `SET_NULL`
  so financial history survives deletions.
* Note `payment = OneToOneField('payments.Payment', ...)` uses a **string reference** to avoid a circular import
  between apps.

## 2. Serializers and the paywall (`serializers.py`)

`BlogSerializer` shows several DRF techniques:

* **`StringRelatedField`** for `author_name` (read-only, uses `Author.__str__`).
* **`CloudinaryImageField`** from `blog_api/serializer_fields.py` for the image.
* **`SerializerMethodField`** for computed values: `locked`, `tips_total`, `tips_count`.
* **`to_representation` override** — the paywall. If the post is premium and the viewer is not entitled, the
  `text` is cut to a 300-character teaser ending with "…". The viewer is entitled when they are the post's author,
  an editor/admin/superuser, or have a current membership.
* **One membership query per request**: `_viewer_is_member()` caches its answer in `self.context`, so a page of
  10 posts does one lookup, not ten (there is a test for this: `test_membership_is_looked_up_once_per_request_not_per_post`).
* **Field-level and object-level validation**: `validate_author` stops an `author`-role user from posting under someone
  else's profile; `validate` stops anyone but editors/admins from flipping `is_premium`.

Other serializers: `AuthorSerializer` (all fields), `MembershipPlanSerializer` (price as an integer),
`MembershipSerializer` (read-only), and two plain `Serializer`s for request bodies (`PhoneRequestSerializer`,
`TipRequestSerializer` with `min_value=10`, `max_value=70000`).

## 3. Views (`views.py`)

### `BlogViewSet` — a full CRUD API in about 20 lines

A `ModelViewSet` gives list/create/retrieve/update/partial-update/destroy. We add:

* `permission_classes = [BlogPermission]` (see `accounts/README.md`).
* `filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]`: `?search=django` searches **title and author name**;
  `?is_premium=true` / `?author=3` filter; `?ordering=-created_at` sorts. Default order is newest `published_date` first.
  The body `text` is deliberately **not searchable**: matching a word inside a hidden premium post would reveal that the word is there.
* **`get_queryset()` hides drafts**: editors/admins see everything, authors see published posts plus their own drafts, everyone
  else sees published posts only. Because `get_object()` uses the same queryset, a hidden draft is also a 404 on retrieve, update, delete and tip.
* **An annotated queryset** — the efficiency lesson:

  ```python
  Blog.objects.select_related('author').annotate(
      tips_total=money_sum('tips__amount', filter=Q(tips__status='paid')),
      tips_count=Count('tips', filter=Q(tips__status='paid')),
  )
  ```
  `select_related('author')` fetches each author in the same SQL JOIN (avoids the **N+1 query problem**), and
  `annotate` computes the tip totals in the database for the whole page at once. The serializer reads the
  annotation (`getattr(blog, 'tips_total')`) and only falls back to a query for a single object created in code.
  Measured: a list of posts costs **3 queries** regardless of how many posts are on the page.
* `@action(detail=True, methods=['post']) def tip(...)` adds `POST /blogs/{id}/tip/`. It is throttled with the
  `payments` scope (20/hour), calls `services.start_tip`, and answers **202 Accepted** with the payment.
  Why 202? The payment is not finished; the front end must poll `/api/payments/<id>/`.

### Other views

* `AuthorViewSet` — `ReadOnlyOrEditor`: everyone signed in can read, editors write.
* `MembershipPlanViewSet` — list/retrieve of active plans (`pagination_class = None` because there are only a few) and
  `POST /plans/{id}/subscribe/`.
* `MembershipView` (`APIView`) — "am I a member, and until when?" plus the last 5 memberships.
* `EarningsView` (permission `IsWriter`, now in `accounts/permissions.py`) — totals, top 10 posts and 10 recent tips. Authors see their own, editors/admins see all. Tippers are
  shown by **first name only** (privacy). `money_sum` is a helper that wraps `Sum` in `Coalesce` so "no rows" gives `0` instead of `None`.

### The old `APIView` code

The hand-written `APIView` classes (`BlogListCreateAPIView`, …) used to sit as comments at the bottom of this file. They moved to
[`docs/lessons/blogs_apiview_reference.md`](../docs/lessons/blogs_apiview_reference.md) so the module stays clean. Read them as a reference of
**how the course started**, then compare them with the `ModelViewSet` to see how much boilerplate DRF removes.

## 4. URLs

```python
router = DefaultRouter()
router.register('blogs', BlogViewSet, basename='blog')
router.register('authors', AuthorViewSet, basename='author')
router.register('plans', MembershipPlanViewSet, basename='plan')
```

The router generates `/blogs/`, `/blogs/{id}/`, `/blogs/{id}/tip/`, etc. The two `APIView`s are added with `path()`.
Everything sits under `/api/v1/` — the `v1` lets you release a `v2` later without breaking existing clients.

## 5. Services and the payment signal

**`services.py`** keeps the rules out of the views:

* Two layers of double-click protection exist on purpose: `services.py` prevents a second *purchase record*, `payments` prevents a second *M-Pesa prompt*.
* `start_membership(user, plan, phone)` — refuse inactive plans; **if the same user sent the same request in the last
  60 seconds and it is still pending, return that payment** (double-click protection); otherwise create a pending
  `Membership`, ask `payments` to send the STK prompt (`reference='MEM-<id>'`) and link the payment. If sending fails,
  delete the membership so no orphan is left.
* `start_tip(...)` — same pattern with `TIP-<id>`, plus: you cannot tip yourself; 10 ≤ amount ≤ 70 000.
* `PurchaseError` is a plain exception whose message is safe to show; the view turns it into a **409 Conflict**.

**`receivers.py`** is the other half. When `payments` finishes a payment it sends the `payment_finished` signal.
Here we react:

* successful `MEMBERSHIP` payment → find the membership from the reference `MEM-<id>` → `activate()`;
* successful `TIP` payment → find the tip from `TIP-<id>` → mark it `paid`.

We look the object up by **reference string**, not by the payment link, because Safaricom's callback can arrive a
fraction of a second before our own code has saved that link (test: `test_callback_before_the_link_is_saved_still_activates`).
`apps.py::ready()` imports the module — without that import the receiver would never be connected.

> Design lesson: `payments` knows nothing about blogs. The blogs app plugs in through a signal (the **observer pattern**).

## 6. Seed data

`python manage.py seed_data` creates five authors with five posts each. It uses `get_or_create`, so running it twice
does not duplicate anything (it is **idempotent**), and it is wrapped in `@transaction.atomic` so a failure leaves nothing half-done.

## 7. Tests worth reading

* `CloudinaryImageTests` — uploads with the Cloudinary call **mocked** (`mock.patch`), so tests run offline.
* `PaywallTests` — teaser vs full text, expired/pending memberships, author/editor bypass, one-query-per-request.
* `MembershipPurchaseTests`, `TipTests`, `EarningsTests` — the whole purchase flow using the simulator.
* `NoDuplicatesOrOrphansTests` — double clicks, invalid phone, Daraja outage.

---

## 8. Behaviour changes from the code review

* Drafts are now enforced (see above). Migration `0007_publish_existing_posts` marks every existing post as published, because until
  now the flag was ignored and all posts were visible.
* In the serializer `is_published` has an explicit `default=True`. This matters for multipart/form requests (such as image uploads): DRF
  reads a *missing* boolean in a form as `False`, which would otherwise turn every upload into a draft.
* Search no longer looks inside `text`; filters and ordering were added; `Author` and `published_date` got an ordering/index.
* `transaction.atomic()` around a single `create()` was removed (a single insert is already atomic).

## 9. Exercises

1. Read `test_drafts_and_search.py`. Which test would fail if `get_queryset` filtered only the list and not the detail route?
2. Add a `Comment` model (`blog`, `user`, `text`) with a nested route `/blogs/{id}/comments/`.
3. Add `?published_date__gte=` filtering with a `FilterSet` class.
4. Add a `"Scheduled"` state: a post whose `published_date` is in the future stays hidden from readers until that day.
