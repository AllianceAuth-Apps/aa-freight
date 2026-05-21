from app_utils.testing import NoSocketsTestCase

from .factories_2 import PricingFactory


class TestPricingFactory(NoSocketsTestCase):
    def test_should_handle_update_constracts(self):
        p = PricingFactory(price_base=500_000)
        self.assertTrue(p)
