"""Finite, shared regular-attendance retry policy; not a school rate-limit claim."""
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
