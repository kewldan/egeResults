from __future__ import annotations

from ege_notifier.models.student import ResultItem, Student
from ege_notifier.models.subscription import Subscription
from ege_notifier.models.user import User

ALL_DOCUMENTS = [User, Student, Subscription]

__all__ = ["User", "Student", "ResultItem", "Subscription", "ALL_DOCUMENTS"]
