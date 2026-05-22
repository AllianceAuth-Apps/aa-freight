from django.core.cache import cache
from django.test import TestCase


class TestCaseWithClearCache(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cache.clear()
