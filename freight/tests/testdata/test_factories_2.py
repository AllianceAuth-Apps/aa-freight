from app_utils.testdata_factories import UserMainFactory
from app_utils.testing import NoSocketsTestCase

from freight.models import ContractHandler

from .factories_2 import (
    ContractFactory,
    ContractHandlerFactory,
    EveEntityCorporationFactory,
    PricingFactory,
)


class TestPricingFactory_UpdateContracts(NoSocketsTestCase):
    def test_should_update_contracts_by_defauult_and_without_tasks(self):
        contract = ContractFactory()
        pricing = PricingFactory(contract=contract)
        contract.refresh_from_db()
        self.assertEqual(contract.pricing, pricing)

    def test_should_not_update_contracts_when_requested(self):
        contract = ContractFactory()
        PricingFactory(contract=contract, update_contracts=False)
        contract.refresh_from_db()
        self.assertIsNone(contract.pricing)


class TestPricingFactory_DefaultPrice(NoSocketsTestCase):
    def test_should_set_base_price_as_default(self):
        p = PricingFactory()
        self.assertIsNotNone(p.price_base)

    def test_should_not_overwrite_custom_base_price(self):
        price_base = 100
        p = PricingFactory(price_base=price_base)
        self.assertEqual(p.price_base, price_base)

    def test_should_not_set_base_price_when_other_pricing_set(self):
        p = PricingFactory(price_per_volume=100)
        self.assertIsNone(p.price_base)


class TestPricingFactory_Contract(NoSocketsTestCase):
    def test_should_use_locations_from_contract(self):
        contract = ContractFactory()
        pricing = PricingFactory(contract=contract)
        self.assertEqual(pricing.start_location, contract.start_location)
        self.assertEqual(pricing.end_location, contract.end_location)

    def test_should_generate_random_locations_when_no_contract_given(self):
        pricing = PricingFactory()
        self.assertIsNotNone(pricing.start_location)
        self.assertIsNotNone(pricing.end_location)


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


class TestContractFactory_CreatePricing(NoSocketsTestCase):
    def test_should_create_pricing_when_requested(self):
        contract = ContractFactory(create_pricing=True)
        self.assertEqual(contract.pricing.start_location, contract.start_location)
        self.assertEqual(contract.pricing.end_location, contract.end_location)

    def test_should_not_create_pricing_by_default(self):
        contract = ContractFactory()
        self.assertIsNone(contract.pricing)


class TestEveEntityCorporationFactory(NoSocketsTestCase):
    def test_create(self):
        a = EveEntityCorporationFactory()
        b = EveEntityCorporationFactory(id=a.id)
        self.assertEqual(a, b)


class TestUserMainFactory(NoSocketsTestCase):
    def test_basic(self):
        # related to a bug because there are two permission
        # with name "add_location" in freight.
        user = UserMainFactory(
            main_character__scopes=[
                "esi-universe.read_structures.v1",
            ],
            permissions__=[
                "freight.basic_access",
                "freight.add_location",
            ],
        )
        self.assertTrue(user)
