from typing import Set

from django.core.cache import cache
from django.db.models import QuerySet
from django.test import TestCase


class TestCaseWithClearCache(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cache.clear()


def extract(qs: QuerySet, field: str) -> Set[int]:
    """Return the extracted fields from the items of a query set."""
    return set(qs.values_list(field, flat=True))
