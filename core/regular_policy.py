"""Finite, shared regular-attendance retry policy; not a school rate-limit claim."""
import time

REGULAR_REFRESH_SECONDS = 1800
READ_RETRY_DELAYS = (90, 180, 1800)


def regular_read_failed(account, retry_after=0):
    """Schedule a new read, with a long pause after three consecutive failures."""
    failures = getattr(account, "regular_read_failures", 0)
    delay = READ_RETRY_DELAYS[failures % len(READ_RETRY_DELAYS)]
    account.regular_read_failures = failures + 1
    account.regular_background_retry_at = time.monotonic() + max(delay, retry_after)


def regular_read_succeeded(account):
    account.regular_read_failures = 0
    account.regular_background_retry_at = 0


MAX_POSTS = 6
BURST_POSTS = 3
SHORT_DELAY = 30
PRECLASS_GROUP_DELAY = 60
INCLASS_GROUP_DELAY = 300


def minimum_retry_delay(attempts, before_start=False):
    if attempts <= 0:
        return 0
    if attempts % BURST_POSTS == 0:
        return PRECLASS_GROUP_DELAY if before_start else INCLASS_GROUP_DELAY
    return SHORT_DELAY
