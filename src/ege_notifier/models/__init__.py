from __future__ import annotations

from ege_notifier.models.share_token import ShareToken
from ege_notifier.models.student import ResultItem, Student
from ege_notifier.models.subscription import Subscription
from ege_notifier.models.user import User

ALL_DOCUMENTS = [User, Student, Subscription, ShareToken]

__all__ = [
    "User",
    "Student",
    "ResultItem",
    "Subscription",
    "ShareToken",
    "ALL_DOCUMENTS",
]
