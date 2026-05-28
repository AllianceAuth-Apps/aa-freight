import datetime as dt
from http import HTTPStatus
from unittest.mock import Mock

import pook

from django.utils.timezone import now
from esi.exceptions import HTTPError

from app_utils.testdata_factories import EveCharacterFactory, EveCorporationInfoFactory
from app_utils.testing import NoSocketsTestCase, generate_invalid_pk

from freight.models import Contract, EveEntity, Location, Pricing
from freight.tests.helpers import TestCaseWithClearCache
from freight.tests.testdata.factories_2 import (
    ContractFactory,
    ContractHandlerFactory,
    EveEntityCharacterFactory,
    LocationStationFactory,
    LocationStructureFactory,
    PositionFactory,
    PricingFactory,
    TokenFactory2,
    UserMainDefaultFactory,
    make_esi_url,
)

MANAGERS_PATH = "freight.managers"
MODELS_PATH = "freight.models"

# TODO: Add tests for sending notifications with discord notify


class TestEveEntityManager(TestCaseWithClearCache):
    @pook.on
    def test_can_create_new_from_esi_when_not_exists(self):
        # given
        entity_id = 1001
        name = "Alpha"
        category = EveEntity.CATEGORY_CHARACTER
        pook.post(
            make_esi_url("universe/names"),
            reply=200,
            response_json=[
                {"category": "character", "id": entity_id, "name": name},
            ],
        )

        # when
        obj: EveEntity
        obj, created = EveEntity.objects.get_or_create_esi(id=entity_id)

        # then
        self.assertTrue(created)
        self.assertEqual(obj.id, entity_id)
        self.assertEqual(obj.name, name)
        self.assertEqual(obj.category, category)

    @pook.on
    def test_should_return_existing_object_when_exists(self):
        # given
        obj = EveEntityCharacterFactory()

        # when
        obj_2: EveEntity
        obj_2, created = EveEntity.objects.get_or_create_esi(id=obj.id)

        # then
        self.assertFalse(created)
        self.assertEqual(obj, obj_2)

    @pook.on
    def test_can_update_existing(self):
        # given
        entity_id = 1001
        EveEntityCharacterFactory(id=entity_id, name="Alpha")
        name = "Alpha2"
        category = EveEntity.CATEGORY_ALLIANCE
        pook.post(
            make_esi_url("universe/names"),
            reply=HTTPStatus.OK,
            response_json=[
                {"category": "alliance", "id": entity_id, "name": name},
            ],
        )

        # when
        obj: EveEntity
        obj, created = EveEntity.objects.update_or_create_esi(id=entity_id)

        # then
        self.assertFalse(created)
        self.assertEqual(obj.id, entity_id)
        self.assertEqual(obj.name, name)
        self.assertEqual(obj.category, category)

    @pook.on
    def test_raise_exception_if_entity_can_not_be_created(self):
        # given
        pook.post(
            make_esi_url("universe/names"),
            reply=HTTPStatus.NOT_FOUND,
            response_json={"error": "not found"},
        )

        # when/then
        with self.assertRaises(HTTPError):
            EveEntity.objects.get_or_create_esi(id=666)


class TestLocationManager_GetOrCreate(TestCaseWithClearCache):
    @pook.on
    def test_should_get_existing_location(self):
        # given
        token = TokenFactory2(scopes=["esi-universe.read_structures.v1"])
        location = LocationStationFactory()

        # when
        got, created = Location.objects.get_or_create_esi(token, location.id)

        # then
        self.assertFalse(created)
        self.assertEqual(got, location)

    @pook.on
    def test_should_create_new_structure(self):
        # given
        token = TokenFactory2(scopes=["esi-universe.read_structures.v1"])
        name = "Alpha"
        structure_id = 1000000000001
        solar_system_id = 30004984  # Abune
        type_id = 35832  # Astrahus
        pook.get(
            make_esi_url(f"universe/structures/{structure_id}"),
            reply=HTTPStatus.OK,
            response_json={
                "owner_id": 666,
                "name": name,
                "position": PositionFactory(),
                "solar_system_id": solar_system_id,
                "type_id": type_id,
            },
        )

        # when
        obj: Location
        obj, created = Location.objects.get_or_create_esi(token, structure_id)

        # then
        self.assertTrue(created)
        self.assertEqual(obj.category, Location.Category.STRUCTURE)
        self.assertEqual(obj.id, structure_id)
        self.assertEqual(obj.name, name)
        self.assertEqual(obj.solar_system_id, solar_system_id)
        self.assertEqual(obj.type_id, type_id)


class TestLocationManager_Structure_UpdateOrCreate(TestCaseWithClearCache):
    @pook.on
    def test_should_create_structure(self):
        # given
        token = TokenFactory2(scopes=["esi-universe.read_structures.v1"])
        name = "Alpha"
        location_id = 1_000_000_000_001
        solar_system_id = 30004984  # Abune
        type_id = 35832  # Astrahus
        pook.get(
            make_esi_url(f"universe/structures/{location_id}"),
            reply=HTTPStatus.OK,
            response_json={
                "owner_id": 666,
                "name": name,
                "position": PositionFactory(),
                "solar_system_id": solar_system_id,
                "type_id": type_id,
            },
        )

        # when
        location: Location
        location, created = Location.objects.update_or_create_esi(
            token=token, location_id=location_id
        )

        # then
        self.assertTrue(created)
        self.assertEqual(location.category, Location.Category.STRUCTURE)
        self.assertEqual(location.id, location_id)
        self.assertEqual(location.name, name)
        self.assertEqual(location.solar_system_id, solar_system_id)
        self.assertEqual(location.type_id, type_id)

    @pook.on
    def test_should_update_structure(self):
        # given
        token = TokenFactory2(scopes=["esi-universe.read_structures.v1"])
        location_1 = LocationStructureFactory()
        name = "Alpha"
        solar_system_id = 30004984  # Abune
        type_id = 35832  # Astrahus
        pook.get(
            make_esi_url(f"universe/structures/{location_1.id}"),
            reply=HTTPStatus.OK,
            response_json={
                "owner_id": 666,
                "name": name,
                "position": PositionFactory(),
                "solar_system_id": solar_system_id,
                "type_id": type_id,
            },
        )

        # when
        location_2: Location
        location_2, created = Location.objects.update_or_create_esi(
            token=token, location_id=location_1.id
        )

        # then
        self.assertFalse(created)
        location_1.refresh_from_db()
        self.assertEqual(location_1.category, Location.Category.STRUCTURE)
        self.assertEqual(location_1.id, location_1.id)
        self.assertEqual(location_1.name, name)
        self.assertEqual(location_1.solar_system_id, solar_system_id)
        self.assertEqual(location_1.type_id, type_id)
        self.assertEqual(location_2, location_1)

    @pook.on
    def test_should_create_skeleton_structure_on_specific_http_errors(self):
        # given
        token = TokenFactory2(scopes=["esi-universe.read_structures.v1"])
        location_id = 1_000_000_000_001
        for status_code in [HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN]:
            with self.subTest(status_code=status_code):
                pook.get(
                    make_esi_url(f"universe/structures/{location_id}"),
                    reply=status_code,
                    response_json={"error": "some error"},
                )

                # when
                location: Location
                location, created = Location.objects.update_or_create_esi(
                    token=token, location_id=location_id
                )

                # then
                self.assertTrue(created)
                self.assertEqual(location.category, Location.Category.STRUCTURE)
                self.assertEqual(location.id, location.id)
                self.assertEqual(location.name, f"Unknown structure {location_id}")
                self.assertIsNone(location.solar_system_id)
                self.assertIsNone(location.type_id)

                Location.objects.filter(id=location_id).delete()

    @pook.on
    def test_should_raise_specific_http_errors_when_requested(self):
        # given
        token = TokenFactory2(scopes=["esi-universe.read_structures.v1"])
        location_id = 1_000_000_000_001
        status_code = HTTPStatus.FORBIDDEN
        pook.get(
            make_esi_url(f"universe/structures/{location_id}"),
            reply=status_code,
            response_json={"error": "some error"},
        )

        # when/then
        with self.assertRaises(HTTPError) as ex:
            Location.objects.update_or_create_esi(
                token=token, location_id=location_id, add_unknown=False
            )
            self.assertEqual(ex.status_code, status_code)

    @pook.on
    def test_should_raise_error_on_other_http_errors_for_structures(self):
        # given
        token = TokenFactory2(scopes=["esi-universe.read_structures.v1"])
        location_id = 1_000_000_000_001
        status_code = HTTPStatus.INTERNAL_SERVER_ERROR
        pook.get(
            make_esi_url(f"universe/structures/{location_id}"),
            reply=status_code,
            response_json={"error": "some error"},
        )

        # when/then
        with self.assertRaises(HTTPError) as ex:
            Location.objects.update_or_create_esi(
                token=token, location_id=location_id, add_unknown=False
            )
            self.assertEqual(ex.status_code, status_code)


class TestLocationManager_Station_UpdateOrCreate(TestCaseWithClearCache):
    @pook.on
    def test_should_create_station(self):
        # given
        name = "Alpha"
        location_id = 60_000_001
        solar_system_id = 30004984  # Abune
        type_id = 1529  # Caldari station
        pook.get(
            make_esi_url(f"universe/stations/{location_id}"),
            reply=200,
            response_json={
                "max_dockable_ship_volume": 50000000,
                "name": name,
                "office_rental_cost": 118744,
                "owner": 1000180,
                "position": PositionFactory(),
                "race_id": 1,
                "reprocessing_efficiency": 0.2,
                "reprocessing_stations_take": 0.025,
                "services": [
                    "bounty-missions",
                    "courier-missions",
                    "reprocessing-plant",
                    "market",
                    "repair-facilities",
                    "factory",
                    "fitting",
                    "news",
                    "insurance",
                    "docking",
                    "office-rental",
                    "loyalty-point-store",
                    "navy-offices",
                    "security-offices",
                ],
                "station_id": location_id,
                "system_id": solar_system_id,
                "type_id": type_id,
            },
        )

        # when
        location: Location
        location, created = Location.objects.update_or_create_esi(
            token=None, location_id=location_id
        )

        # then
        self.assertTrue(created)
        self.assertEqual(location.category, Location.Category.STATION)
        self.assertEqual(location.id, location_id)
        self.assertEqual(location.name, name)
        self.assertEqual(location.solar_system_id, solar_system_id)
        self.assertEqual(location.type_id, type_id)

    @pook.on
    def test_should_update_station(self):
        # given
        location_1 = LocationStationFactory()
        name = "Alpha"
        solar_system_id = 30004984  # Abune
        type_id = 1529  # Caldari station
        pook.get(
            make_esi_url(f"universe/stations/{location_1.id}"),
            reply=200,
            response_json={
                "max_dockable_ship_volume": 50000000,
                "name": name,
                "office_rental_cost": 118744,
                "owner": 1000180,
                "position": PositionFactory(),
                "race_id": 1,
                "reprocessing_efficiency": 0.2,
                "reprocessing_stations_take": 0.025,
                "services": [
                    "bounty-missions",
                    "courier-missions",
                    "reprocessing-plant",
                    "market",
                    "repair-facilities",
                    "factory",
                    "fitting",
                    "news",
                    "insurance",
                    "docking",
                    "office-rental",
                    "loyalty-point-store",
                    "navy-offices",
                    "security-offices",
                ],
                "station_id": location_1.id,
                "system_id": solar_system_id,
                "type_id": type_id,
            },
        )

        # when
        location_2: Location
        location_2, created = Location.objects.update_or_create_esi(
            token=None, location_id=location_1.id
        )

        # then
        self.assertFalse(created)
        location_1.refresh_from_db()
        self.assertEqual(location_1.category, Location.Category.STATION)
        self.assertEqual(location_1.id, location_1.id)
        self.assertEqual(location_1.name, name)
        self.assertEqual(location_1.solar_system_id, solar_system_id)
        self.assertEqual(location_1.type_id, type_id)
        self.assertEqual(location_2, location_1)

    @pook.on
    def test_should_raise_http_errors(self):
        # given
        location_id = 60_000_001
        status_code = HTTPStatus.BAD_REQUEST
        pook.get(
            make_esi_url(f"universe/stations/{location_id}"),
            reply=status_code,
            response_json={"error": "some error"},
        )

        # when/then
        with self.assertRaises(HTTPError) as ex:
            Location.objects.update_or_create_esi(
                token=None, location_id=location_id, add_unknown=False
            )
            self.assertEqual(ex.status_code, status_code)


class TestContractQuerySet(NoSocketsTestCase):
    def test_pending_count(self):
        # given
        handler = ContractHandlerFactory()
        ContractFactory(handler=handler, date_expired=now() + dt.timedelta(days=1))
        ContractFactory(
            handler=handler, date_expired=now() + dt.timedelta(hours=1), accepted=True
        )
        ContractFactory(
            handler=handler, date_expired=now() - dt.timedelta(hours=1), accepted=True
        )
        ContractFactory(
            handler=handler, date_expired=now() + dt.timedelta(days=1), finished=True
        )
        # when
        got = Contract.objects.all().pending_count()
        # then
        self.assertEqual(got, 1)


class TestContractManager_IssuedByUser(NoSocketsTestCase):
    def test_issued_by_user(self):
        # given
        user = UserMainDefaultFactory()
        handler = ContractHandlerFactory(user=user)
        contract = ContractFactory(handler=handler, issuer=user.profile.main_character)
        ContractFactory(handler=handler)

        # when
        qs = Contract.objects.all().issued_by_user(user=user)

        # then
        self.assertCountEqual(qs, [contract])


class TestContractManager_UpdatePricing(NoSocketsTestCase):
    def test_can_update_pricing_for_bidirectional(self):
        # given
        handler = ContractHandlerFactory()
        location_1 = LocationStationFactory()
        location_2 = LocationStationFactory()
        contract_1 = ContractFactory(
            handler=handler, start_location=location_1, end_location=location_2
        )
        contract_2 = ContractFactory(
            handler=handler, start_location=location_2, end_location=location_1
        )
        contract_3 = ContractFactory(handler=handler)
        pricing = PricingFactory(
            contract=contract_1, price_base=500000000, is_bidirectional=True
        )

        # when
        got = Contract.objects.update_pricing()

        # then
        self.assertEqual(got, 3)
        contract_1.refresh_from_db()
        self.assertEqual(contract_1.pricing, pricing)
        contract_2.refresh_from_db()
        self.assertEqual(contract_2.pricing, pricing)
        contract_3.refresh_from_db()
        self.assertIsNone(contract_3.pricing)

    def test_can_update_pricing_for_unidirectional(self):
        # given
        handler = ContractHandlerFactory()
        location_1 = LocationStationFactory()
        location_2 = LocationStationFactory()
        contract_1 = ContractFactory(
            handler=handler,
            start_location=location_1,
            end_location=location_2,
        )
        contract_2 = ContractFactory(
            handler=handler,
            start_location=location_2,
            end_location=location_1,
        )
        pricing = PricingFactory(
            start_location=location_1,
            end_location=location_2,
            is_bidirectional=False,
        )

        # when
        got = Contract.objects.update_pricing()

        # then
        self.assertEqual(got, 2)

        contract_1.refresh_from_db()
        self.assertEqual(contract_1.pricing, pricing)
        contract_2.refresh_from_db()
        self.assertIsNone(contract_2.pricing)


class TestContractManager_CreateFromDict(NoSocketsTestCase):
    def test_can_create_outstanding(self):
        # given
        handler = ContractHandlerFactory()
        start_location = LocationStationFactory()
        end_location = LocationStationFactory()
        assignee = EveCorporationInfoFactory()
        date_expired = now() + dt.timedelta(days=3)
        date_issued = now() - dt.timedelta(hours=3)
        contract_id = 149409014
        collaterial = 50000000.0
        days_to_complete = 3
        reward = 25000000.0
        volume = 115000.0
        issuer = EveCharacterFactory()
        title = "demo contract"
        contract_dict = {
            "acceptor_id": 0,
            "assignee_id": assignee.corporation_id,
            "availability": "personal",
            "buyout": None,
            "collateral": collaterial,
            "contract_id": contract_id,
            "date_accepted": None,
            "date_completed": None,
            "date_expired": date_expired,
            "date_issued": date_issued,
            "days_to_complete": days_to_complete,
            "end_location_id": end_location.id,
            "for_corporation": False,
            "issuer_corporation_id": issuer.corporation.corporation_id,
            "issuer_id": issuer.character_id,
            "reward": reward,
            "start_location_id": start_location.id,
            "status": "outstanding",
            "title": title,
            "type": "courier",
            "volume": volume,
        }

        # when
        obj: Contract
        obj, created = Contract.objects.update_or_create_from_dict(
            handler, contract_dict, token=Mock()
        )

        # then
        self.assertTrue(created)
        self.assertEqual(obj.collateral, collaterial)
        self.assertEqual(obj.contract_id, contract_id)
        self.assertEqual(obj.date_expired, date_expired)
        self.assertEqual(obj.date_issued, date_issued)
        self.assertEqual(obj.days_to_complete, days_to_complete)
        self.assertEqual(obj.end_location, end_location)
        self.assertEqual(obj.issuer_corporation, issuer.corporation)
        self.assertEqual(obj.issuer, issuer)
        self.assertEqual(obj.reward, reward)
        self.assertEqual(obj.start_location, start_location)
        self.assertEqual(obj.status, Contract.Status.OUTSTANDING)
        self.assertEqual(obj.title, title)
        self.assertEqual(obj.volume, volume)
        self.assertFalse(obj.for_corporation)
        self.assertIsNone(obj.acceptor_corporation)
        self.assertIsNone(obj.acceptor)
        self.assertIsNone(obj.date_accepted)
        self.assertIsNone(obj.date_completed)
        self.assertIsNone(obj.issues)
        self.assertIsNone(obj.pricing)

    def test_can_create_in_progress(self):
        # given
        handler = ContractHandlerFactory()
        start_location = LocationStationFactory()
        end_location = LocationStationFactory()
        assignee = EveCorporationInfoFactory()
        date_expired = now() + dt.timedelta(days=3)
        date_issued = now() - dt.timedelta(hours=3)
        date_accepted = now() - dt.timedelta(hours=2)
        contract_id = 149409014
        collaterial = 50000000.0
        days_to_complete = 3
        reward = 25000000.0
        volume = 115000.0
        issuer = EveCharacterFactory()
        acceptor = EveCharacterFactory()
        title = "demo contract"
        EveEntityCharacterFactory(
            id=acceptor.character_id, name=acceptor.character_name
        )  # needed for internal check
        contract_dict = {
            "acceptor_id": acceptor.character_id,
            "assignee_id": assignee.corporation_id,
            "availability": "personal",
            "buyout": None,
            "collateral": collaterial,
            "contract_id": contract_id,
            "date_accepted": date_accepted,
            "date_completed": None,
            "date_expired": date_expired,
            "date_issued": date_issued,
            "days_to_complete": days_to_complete,
            "end_location_id": end_location.id,
            "for_corporation": False,
            "issuer_corporation_id": issuer.corporation.corporation_id,
            "issuer_id": issuer.character_id,
            "reward": reward,
            "start_location_id": start_location.id,
            "status": "in_progress",
            "title": title,
            "type": "courier",
            "volume": volume,
        }

        # when
        obj: Contract
        obj, created = Contract.objects.update_or_create_from_dict(
            handler, contract_dict, token=Mock()
        )

        # then
        self.assertTrue(created)
        self.assertEqual(obj.acceptor_corporation, acceptor.corporation)
        self.assertEqual(obj.collateral, collaterial)
        self.assertEqual(obj.contract_id, contract_id)
        self.assertEqual(obj.date_accepted, date_accepted)
        self.assertEqual(obj.date_expired, date_expired)
        self.assertEqual(obj.date_issued, date_issued)
        self.assertEqual(obj.days_to_complete, days_to_complete)
        self.assertEqual(obj.end_location, end_location)
        self.assertEqual(obj.issuer_corporation, issuer.corporation)
        self.assertEqual(obj.issuer, issuer)
        self.assertEqual(obj.reward, reward)
        self.assertEqual(obj.start_location, start_location)
        self.assertEqual(obj.status, Contract.Status.IN_PROGRESS)
        self.assertEqual(obj.title, title)
        self.assertEqual(obj.volume, volume)
        self.assertFalse(obj.for_corporation)
        self.assertIsNone(obj.date_completed)
        self.assertIsNone(obj.issues)
        self.assertIsNone(obj.pricing)

    def test_can_create_finished(self):
        # given
        handler = ContractHandlerFactory()
        start_location = LocationStationFactory()
        end_location = LocationStationFactory()
        assignee = EveCorporationInfoFactory()
        date_expired = now() + dt.timedelta(days=3)
        date_issued = now() - dt.timedelta(hours=3)
        date_accepted = now() - dt.timedelta(hours=2)
        date_completed = now()
        contract_id = 149409014
        collaterial = 50000000.0
        days_to_complete = 3
        reward = 25000000.0
        volume = 115000.0
        issuer = EveCharacterFactory()
        acceptor = EveCharacterFactory()
        title = "demo contract"
        EveEntityCharacterFactory(
            id=acceptor.character_id, name=acceptor.character_name
        )  # needed for internal check
        contract_dict = {
            "acceptor_id": acceptor.character_id,
            "assignee_id": assignee.corporation_id,
            "availability": "personal",
            "buyout": None,
            "collateral": collaterial,
            "contract_id": contract_id,
            "date_accepted": date_accepted,
            "date_completed": date_completed,
            "date_expired": date_expired,
            "date_issued": date_issued,
            "days_to_complete": days_to_complete,
            "end_location_id": end_location.id,
            "for_corporation": False,
            "issuer_corporation_id": issuer.corporation.corporation_id,
            "issuer_id": issuer.character_id,
            "reward": reward,
            "start_location_id": start_location.id,
            "status": "finished",
            "title": title,
            "type": "courier",
            "volume": volume,
        }

        # when
        obj: Contract
        obj, created = Contract.objects.update_or_create_from_dict(
            handler, contract_dict, token=Mock()
        )

        # then
        self.assertTrue(created)
        self.assertEqual(obj.acceptor_corporation, acceptor.corporation)
        self.assertEqual(obj.collateral, collaterial)
        self.assertEqual(obj.contract_id, contract_id)
        self.assertEqual(obj.date_accepted, date_accepted)
        self.assertEqual(obj.date_expired, date_expired)
        self.assertEqual(obj.date_issued, date_issued)
        self.assertEqual(obj.date_completed, date_completed)
        self.assertEqual(obj.days_to_complete, days_to_complete)
        self.assertEqual(obj.end_location, end_location)
        self.assertEqual(obj.issuer_corporation, issuer.corporation)
        self.assertEqual(obj.issuer, issuer)
        self.assertEqual(obj.reward, reward)
        self.assertEqual(obj.start_location, start_location)
        self.assertEqual(obj.status, Contract.Status.FINISHED)
        self.assertEqual(obj.title, title)
        self.assertEqual(obj.volume, volume)
        self.assertFalse(obj.for_corporation)
        self.assertIsNone(obj.issues)
        self.assertIsNone(obj.pricing)


class TestPricingManager_GetDefault(NoSocketsTestCase):
    def test_should_return_default_pricing_when_exists(self):
        # given
        pricing = PricingFactory(is_default=True)
        PricingFactory()
        # when
        got = Pricing.objects.get_default()
        # then
        self.assertEqual(got, pricing)

    def test_should_return_any_pricing_when_no_default_defined(self):
        # given
        pricing = PricingFactory()
        # when
        got = Pricing.objects.get_default()
        # then
        self.assertEqual(got, pricing)

    def test_should_return_none_when_no_pricing_defined(self):
        # when
        got = Pricing.objects.get_default()
        # then
        self.assertIsNone(got)


class TestPricingManager_GetOrDefault(NoSocketsTestCase):
    def test_should_return_default_pricing_when_exists(self):
        # given
        pricing = PricingFactory(is_default=True)
        PricingFactory()
        # when
        got = Pricing.objects.get_or_default()
        # then
        self.assertEqual(got, pricing)

    def test_should_return_any_pricing_when_no_default_defined(self):
        # given
        pricing = PricingFactory()
        # when
        got = Pricing.objects.get_or_default()
        # then
        self.assertEqual(got, pricing)

    def test_should_return_none_when_no_pricing_defined(self):
        # when
        got = Pricing.objects.get_or_default()
        # then
        self.assertIsNone(got)

    def test_should_return_given_pricing_when_it_exists(self):
        # given
        PricingFactory(is_default=True)
        pricing = PricingFactory()
        # when
        got = Pricing.objects.get_or_default(pk=pricing.pk)
        # then
        self.assertEqual(got, pricing)

    def test_should_return_default_when_given_pricing_not_found(self):
        # given
        pricing = PricingFactory(is_default=True)
        PricingFactory()
        # when
        got = Pricing.objects.get_or_default(pk=generate_invalid_pk(Pricing))
        # then
        self.assertEqual(got, pricing)
