from app_utils.testing import NoSocketsTestCase

from freight.models import ContractHandler

from .factories_2 import (
    ContractFactory,
    ContractHandlerFactory,
    EveEntityCorporationFactory,
    PricingFactory,
)


class TestPricingFactory(NoSocketsTestCase):
    def test_should_handle_update_constracts(self):
        p = PricingFactory(price_base=500_000)
        self.assertTrue(p)


class TestContractHandlerFactory(NoSocketsTestCase):
    def test_should_create_for_my_alliance_by_default(self):
        handler = ContractHandlerFactory()
        self.assertEqual(handler.operation_mode, ContractHandler.Mode.MY_ALLIANCE)


class TestContractFactory(NoSocketsTestCase):
    def test_should_create_for_my_corporation(self):
        handler = ContractHandlerFactory(
            operation_mode=ContractHandler.Mode.MY_CORPORATION
        )
        contract = ContractFactory(handler=handler)
        self.assertEqual(
            contract.issuer_corporation.corporation_id, handler.organization.id
        )

    def test_should_create_for_my_alliance(self):
        handler = ContractHandlerFactory(
            operation_mode=ContractHandler.Mode.MY_ALLIANCE
        )
        contract = ContractFactory(handler=handler)
        self.assertEqual(
            contract.issuer_corporation.alliance.alliance_id, handler.organization.id
        )


class TestEveEntityCorporationFactory(NoSocketsTestCase):
    def test_create(self):
        a = EveEntityCorporationFactory()
        b = EveEntityCorporationFactory(id=a.id)
        self.assertEqual(a, b)
