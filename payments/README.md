# `payments/` — M-Pesa STK Push, done properly

This app lets **any other app** charge a customer through M-Pesa (Safaricom's mobile money) without knowing how M-Pesa works.
`school` uses it for course fees, `blogs` for memberships and tips.

| File | What it does |
|------|--------------|
| `models.py` | The single `Payment` table |
| `mpesa.py` | A thin HTTP client for Safaricom's **Daraja** API (no database code) |
| `services.py` | The payment lifecycle: start, apply result exactly once, reconcile |
| `views.py` / `urls.py` | The public callback (webhook) and the "my payments" API |
| `serializers.py` | What the front end sees, including friendly messages |
| `signals.py` | `payment_finished`, the event other apps listen to |
| `admin.py` | Read-only financial record, plus a "re-check with Safaricom" action |
| `management/commands/mpesa_reconcile.py` | Cron-job command that settles stuck payments |
| `tests.py` | 35 tests, all offline |

---

## 1. How an STK Push payment works

```
Browser            Our API                    Safaricom Daraja              Customer's phone
   │ POST enroll     │                               │                              │
   ├────────────────►│ create Payment(pending)       │                              │
   │                 ├──── stk_push ────────────────►│ ───── PIN prompt ───────────►│
   │◄── 202 + payment│◄──── CheckoutRequestID ───────┤                              │
   │                 │                               │◄──── customer enters PIN ────┤
   │                 │◄── POST /mpesa/callback/<secret>/ (result) ──┤                │
   │                 │ apply_result → status=success → signal        │               │
   │ GET /payments/1 │                                                              │
   ├────────────────►│ (if callback is late: ask Daraja "what happened?")           │
   │◄── status: paid │                                                              │
```

Key idea: **the HTTP request that starts the payment does not know the result.** The result arrives later in a
separate request from Safaricom (a *webhook* / *callback*). The front end therefore polls
`GET /api/payments/<id>/` until `pending` becomes `false`.

## 2. The `Payment` model

* `status`: `pending → success | failed | cancelled | review`. `review` means money moved but the amount did not
  match what we expected — a human must look.
* `purpose`: `enrollment`, `membership` or `tip`. `account_reference` is a short code such as `ENR-12`, `MEM-3`, `TIP-9`
  that identifies *what was bought* (Daraja limits it to 12 characters).
* Daraja identifiers: `merchant_request_id`, `checkout_request_id` (**unique**, how callbacks find the row),
  `mpesa_receipt`, `result_code`, `result_desc`, and the raw `callback_payload` (JSON) kept for audit.
* Timestamps: `created_at`, `updated_at`, `paid_at`, and `checked_at` (last time we asked Daraja).
* `Meta.indexes` on `(user, purpose, status)` speeds the duplicate check; `amount_display` formats `500.00` as `500`.

## 3. `mpesa.py` — the Daraja client

No database access; only HTTP and string handling, which makes it easy to test with mocks.

* `env()` — reads `MPESA_ENV`; **refuses** `simulate` unless `DEBUG` is on (so a demo mode can never reach production).
* `normalize_phone()` — turns `0712 345 678`, `+254712345678`, `712345678` into `254712345678`, or raises `ValueError`.
* `access_token()` — OAuth token from Daraja, **cached** for just under an hour so we do not fetch one per payment.
* `_password()` — Daraja's password is `base64(shortcode + passkey + timestamp)`.
* `stk_push()` — sends the prompt. In `simulate` mode it returns fake ids and never touches the network.
* `stk_query()` — asks "what happened to this prompt?"; returns `None` while Daraja says it is still processing.
* Every request has a `timeout`, and network problems become a friendly `MpesaError`.

## 4. `services.py` — the lifecycle

### `initiate_stk(...)`
1. Normalise the phone, require a **whole number** of shillings ≥ 1.
2. **Idempotency:** if the same user already has a pending payment with the same reference created in the last 60 seconds,
   return it instead of sending a second prompt to the phone.
3. Build the callback URL (`callback_url()`): needs `MPESA_CALLBACK_SECRET`, and an **HTTPS** public address
   (use ngrok locally). The secret is part of the URL path.
4. Save a `pending` `Payment` *first*, then call Daraja. If Daraja rejects it, mark the payment `failed` and raise
   `PaymentError` with a customer-friendly message.

### `apply_result(...)` — "exactly once"
Safaricom may retry a callback, and our own reconciliation may race it. So:

```python
with transaction.atomic():
    payment = Payment.objects.select_for_update().get(checkout_request_id=...)   # lock the row
    if payment.status != PENDING:  return payment                                # already settled → do nothing
    ...set status from result_code (0=success, 1032=cancelled, else failed)...
    if amount differs → REVIEW
    payment.save()
    transaction.on_commit(lambda: payment_finished.send(...))                    # only after the DB commit
```

* `select_for_update()` locks the row so two workers cannot settle it twice.
* `on_commit` guarantees listeners only run once the data is really saved.
* A late duplicate callback can still back-fill a missing `mpesa_receipt`.

### `handle_callback(data)`
Parses Daraja's JSON (`Body.stkCallback...`) and calls `apply_result`. A malformed body raises `ValueError`.

### `reconcile(payment)`
For when the callback never arrives (phone off, our server down…):

* Skip payments younger than 15 s (give the callback a head start) and rate-limit to one query per 10 s.
* Ask Daraja via `stk_query`. If still processing and older than **10 minutes**, treat it as timed out.
* In `simulate` mode, complete the payment after `MPESA_SIMULATE_DELAY` seconds (a phone number ending in `999` simulates a cancelled prompt).

## 5. Views

* **`MpesaCallbackView`** (`POST /api/payments/mpesa/callback/<secret>/`)
  * `authentication_classes = []`, `AllowAny`, `throttle_classes = []`: Safaricom has no JWT and must never be rate-limited.
  * The gate is the **secret in the URL**, compared with `hmac.compare_digest` (constant-time, avoids timing attacks).
    A wrong secret gives a plain `404`.
  * Always replies `{"ResultCode": 0, "ResultDesc": "Accepted"}` to well-formed bodies, even unknown ids, so Safaricom stops retrying.
* **`PaymentViewSet`** (read-only): `get_queryset` returns only **your** payments (others get `404`).
  `retrieve` calls `services.reconcile(payment)`, so merely polling heals a lost callback.

## 6. The signal

`signals.py` declares one `Signal`, `payment_finished`. `services.apply_result` sends it; `blogs.receivers` and `school.receivers`
listen and act only on their own `payment.purpose`. This keeps `payments` generic.

## 7. Operations

* **Admin**: payments are fully read-only (a financial record: no add, edit or delete). The action *Re-check selected pending payments with Safaricom* calls `reconcile(force=True)`.
* **Cron / scheduled job**: `python manage.py mpesa_reconcile` every few minutes settles any pending payment whose callback was lost. It also calls
  `services.expire_orphans()`, which marks as `failed` any payment that was saved but **never sent to Safaricom** (no `checkout_request_id`) for more than
  10 minutes — for example after a server crash between "save" and "send". Nothing was charged, and without this a course seat would stay reserved forever.

## 8. Tests worth reading

`PhoneTests`, `DarajaClientTests` (mocked `requests`), `InitiateTests`, `CallbackApiTests` (idempotent retries, wrong secret, amount
mismatch, malformed body), `PaymentApiTests` (privacy, polling), `SimulatorTests`.

---

## 9. Remaining design notes (good discussion topics)

* Tokens and throttle counters use the Django cache. The default is per-process memory; set `REDIS_URL` so several workers share one cache.
* There is no automatic refund flow and no B2C payouts; tips are collected by the platform, not forwarded.
* Orphaned `pending` rows (saved but never sent) are now cleaned up by `expire_orphans()`; see `ExpireOrphansTests`.

## 10. Exercises

1. Run with `MPESA_ENV=simulate` and `DEBUG=True`, enroll in a paid course, and watch the status change via `GET /api/payments/<id>/`.
2. Use phone number `0700000999` to see a cancelled prompt.
3. Add a new `purpose` called `donation` and write a receiver in a new app that reacts to it.
4. Add a `refunded` status and an admin action that marks it (design the rules first).
