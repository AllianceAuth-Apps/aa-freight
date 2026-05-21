from django.test import TestCase

from .factories_2 import PricingFactory


class TestPricingFactory(TestCase):
    def test_should_handle_update_constracts(self):
        p = PricingFactory(update_contracts=True)
        self.assertTrue(p)
