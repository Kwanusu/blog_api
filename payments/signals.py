from django.dispatch import Signal

# Sent once, after commit, when a payment leaves "pending" (success, failed, cancelled or review).
# Domain apps (school, blogs) connect to this and act only on their own `payment.purpose`.
payment_finished = Signal()
