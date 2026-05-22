import datetime as dt
from http import HTTPStatus
from unittest.mock import Mock, patch

import pook
from bravado.exception import HTTPError, HTTPForbidden

from django.utils.timezone import now

from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo
from allianceauth.eveonline.providers import ObjectNotFound
from app_utils.django import app_labels
from app_utils.testing import NoSocketsTestCase, generate_invalid_pk

from freight.models import Contract, EveEntity, Location, Pricing
from freight.tests.helpers import TestCaseWithClearCache
from freight.tests.testdata.factories_2 import (
    EveEntityCharacterFactory,
    LocationStationFactory,
    LocationStructureFactory,
    PositionFactory,
    PricingFactory,
    TokenFactory2,
    make_esi_url,
)
from freight.tests.testdata.helpers import (
    create_contract_handler_w_contracts,
    create_locations,
)

MANAGERS_PATH = "freight.managers"
MODELS_PATH = "freight.models"


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
        with self.assertRaises(ObjectNotFound):
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
        pook.get(
            make_esi_url(f"universe/structures/{location_id}"),
            reply=HTTPStatus.FORBIDDEN,
            response_json={"error": "some error"},
        )

        # when/then
        with self.assertRaises(HTTPForbidden):
            Location.objects.update_or_create_esi(
                token=token, location_id=location_id, add_unknown=False
            )

    @pook.on
    def test_should_raise_error_on_other_http_errors_for_structures(self):
        # given
        token = TokenFactory2(scopes=["esi-universe.read_structures.v1"])
        location_id = 1_000_000_000_001
        pook.get(
            make_esi_url(f"universe/structures/{location_id}"),
            reply=HTTPStatus.INTERNAL_SERVER_ERROR,
        )

        # when/then
        with self.assertRaises(HTTPError):
            Location.objects.update_or_create_esi(
                token=token, location_id=location_id, add_unknown=False
            )


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
        pook.get(
            make_esi_url(f"universe/stations/{location_id}"),
            reply=HTTPStatus.INTERNAL_SERVER_ERROR,
        )

        # when/then
        with self.assertRaises(HTTPError):
            Location.objects.update_or_create_esi(
                token=None, location_id=location_id, add_unknown=False
            )


class TestContractQuerySet(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.handler, cls.user = create_contract_handler_w_contracts(
            [149409016, 149409061, 149409062, 149409063, 149409064, 149409006]
        )

    def test_pending_count(self):
        result = Contract.objects.all().pending_count()
        self.assertEqual(result, 6)


class TestContractManager(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.handler, cls.user = create_contract_handler_w_contracts(
            [
                149409016,
                149409061,
                149409062,
                149409063,
                149409064,
                149409006,
                149409318,
            ]
        )

    def test_issued_by_user(self):
        # when
        qs = Contract.objects.all().issued_by_user(user=self.user)
        # then
        self.assertSetEqual(
            set(qs.values_list("contract_id", flat=True)),
            {149409016, 149409061, 149409062, 149409063, 149409064},
        )

    def test_can_update_pricing_for_bidirectional(self):
        # given
        jita = Location.objects.get(id=60003760)
        amamake = Location.objects.get(id=1022167642188)
        amarr = Location.objects.get(id=60008494)
        pricing_1 = PricingFactory(
            start_location=jita,
            end_location=amamake,
            price_base=500000000,
            is_bidirectional=True,
        )
        pricing_3 = PricingFactory(
            start_location=amarr,
            end_location=amamake,
            price_base=250000000,
            is_bidirectional=True,
        )
        # when
        result = Contract.objects.update_pricing()
        # then
        self.assertEqual(result, 7)
        contract_1 = Contract.objects.get(contract_id=149409016)
        self.assertEqual(contract_1.pricing, pricing_1)
        contract_2 = Contract.objects.get(contract_id=149409061)
        self.assertEqual(contract_2.pricing, pricing_1)
        contract_3 = Contract.objects.get(contract_id=149409062)
        self.assertEqual(contract_3.pricing, pricing_3)

    def test_can_update_pricing_for_unidirectional(self):
        # given
        jita = Location.objects.get(id=60003760)
        amamake = Location.objects.get(id=1022167642188)
        amarr = Location.objects.get(id=60008494)
        pricing_1 = PricingFactory(
            start_location=jita,
            end_location=amamake,
            price_base=500000000,
            is_bidirectional=False,
        )
        pricing_2 = PricingFactory(
            start_location=amamake,
            end_location=jita,
            price_base=350000000,
            is_bidirectional=False,
        )
        pricing_3 = PricingFactory(
            start_location=amarr,
            end_location=amamake,
            price_base=250000000,
            is_bidirectional=True,
        )
        # when
        Contract.objects.update_pricing()
        # then
        contract_1 = Contract.objects.get(contract_id=149409016)
        self.assertEqual(contract_1.pricing, pricing_1)
        contract_2 = Contract.objects.get(contract_id=149409061)
        self.assertEqual(contract_2.pricing, pricing_2)
        contract_3 = Contract.objects.get(contract_id=149409062)
        self.assertEqual(contract_3.pricing, pricing_3)
        contract_4 = Contract.objects.get(contract_id=149409063)
        self.assertEqual(contract_4.pricing, pricing_3)
        contract_5 = Contract.objects.get(contract_id=149409064)
        self.assertIsNone(contract_5.pricing)


class TestContractManager_CreateFromDict(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.handler, cls.user = create_contract_handler_w_contracts(
            [149409016, 149409061, 149409062, 149409063, 149409064]
        )

    def test_can_create_outstanding(self):
        contract_dict = {
            "acceptor_id": 0,
            "assignee_id": 93000001,
            "availability": "personal",
            "buyout": None,
            "collateral": 50000000.0,
            "contract_id": 149409014,
            "date_accepted": None,
            "date_completed": None,
            "date_expired": dt.datetime(2019, 10, 30, 23, tzinfo=dt.timezone.utc),
            "date_issued": dt.datetime(2019, 10, 2, 23, tzinfo=dt.timezone.utc),
            "days_to_complete": 3,
            "end_location_id": 1022167642188,
            "for_corporation": False,
            "issuer_corporation_id": 92000002,
            "issuer_id": 90000003,
            "price": 0.0,
            "reward": 25000000.0,
            "start_location_id": 60003760,
            "status": "outstanding",
            "title": "demo contract",
            "type": "courier",
            "volume": 115000.0,
        }
        obj, created = Contract.objects.update_or_create_from_dict(
            self.handler, contract_dict, Mock()
        )
        self.assertTrue(created)
        self.assertEqual(obj.contract_id, 149409014)
        self.assertIsNone(obj.acceptor)
        self.assertIsNone(obj.acceptor_corporation)
        self.assertEqual(obj.collateral, 50000000)
        self.assertIsNone(obj.date_accepted)
        self.assertIsNone(obj.date_completed)
        self.assertEqual(
            obj.date_expired, dt.datetime(2019, 10, 30, 23, tzinfo=dt.timezone.utc)
        )
        self.assertEqual(
            obj.date_issued, dt.datetime(2019, 10, 2, 23, tzinfo=dt.timezone.utc)
        )
        self.assertEqual(obj.days_to_complete, 3)
        self.assertEqual(obj.end_location_id, 1022167642188)
        self.assertFalse(obj.for_corporation)
        self.assertEqual(
            obj.issuer_corporation,
            EveCorporationInfo.objects.get(corporation_id=92000002),
        )
        self.assertEqual(obj.issuer, EveCharacter.objects.get(character_id=90000003))
        self.assertEqual(obj.reward, 25000000)
        self.assertEqual(obj.start_location_id, 60003760)
        self.assertEqual(obj.status, Contract.Status.OUTSTANDING)
        self.assertEqual(obj.title, "demo contract")
        self.assertEqual(obj.volume, 115000)
        self.assertIsNone(obj.pricing)
        self.assertIsNone(obj.issues)

    def test_can_create_in_progress(self):
        contract_dict = {
            "acceptor_id": 90000003,
            "assignee_id": 90000003,
            "availability": "personal",
            "buyout": None,
            "collateral": 50000000.0,
            "contract_id": 149409014,
            "date_accepted": dt.datetime(2019, 10, 3, 23, tzinfo=dt.timezone.utc),
            "date_completed": None,
            "date_expired": dt.datetime(2019, 10, 30, 23, tzinfo=dt.timezone.utc),
            "date_issued": dt.datetime(2019, 10, 2, 23, tzinfo=dt.timezone.utc),
            "days_to_complete": 3,
            "end_location_id": 1022167642188,
            "for_corporation": False,
            "issuer_corporation_id": 92000002,
            "issuer_id": 90000003,
            "price": 0.0,
            "reward": 25000000.0,
            "start_location_id": 60003760,
            "status": "in_progress",
            "title": "demo contract",
            "type": "courier",
            "volume": 115000.0,
        }
        obj, created = Contract.objects.update_or_create_from_dict(
            self.handler, contract_dict, Mock()
        )
        self.assertTrue(created)
        self.assertEqual(obj.contract_id, 149409014)
        self.assertEqual(obj.acceptor, EveCharacter.objects.get(character_id=90000003))
        self.assertEqual(
            obj.acceptor_corporation,
            EveCorporationInfo.objects.get(corporation_id=92000002),
        )
        self.assertEqual(obj.collateral, 50000000)
        self.assertEqual(
            obj.date_accepted, dt.datetime(2019, 10, 3, 23, tzinfo=dt.timezone.utc)
        )
        self.assertIsNone(obj.date_completed)
        self.assertEqual(
            obj.date_issued, dt.datetime(2019, 10, 2, 23, tzinfo=dt.timezone.utc)
        )
        self.assertEqual(
            obj.date_expired, dt.datetime(2019, 10, 30, 23, tzinfo=dt.timezone.utc)
        )
        self.assertEqual(obj.days_to_complete, 3)
        self.assertEqual(obj.end_location_id, 1022167642188)
        self.assertFalse(obj.for_corporation)
        self.assertEqual(
            obj.issuer_corporation,
            EveCorporationInfo.objects.get(corporation_id=92000002),
        )
        self.assertEqual(obj.issuer, EveCharacter.objects.get(character_id=90000003))
        self.assertEqual(obj.reward, 25000000)
        self.assertEqual(obj.start_location_id, 60003760)
        self.assertEqual(obj.status, Contract.Status.IN_PROGRESS)
        self.assertEqual(obj.title, "demo contract")
        self.assertEqual(obj.volume, 115000)
        self.assertIsNone(obj.pricing)
        self.assertIsNone(obj.issues)

    def test_can_create_finished(self):
        contract_dict = {
            "acceptor_id": 90000003,
            "assignee_id": 90000003,
            "availability": "personal",
            "buyout": None,
            "collateral": 50000000.0,
            "contract_id": 149409014,
            "date_accepted": dt.datetime(2019, 10, 3, 23, tzinfo=dt.timezone.utc),
            "date_completed": dt.datetime(2019, 10, 4, 23, tzinfo=dt.timezone.utc),
            "date_expired": dt.datetime(2019, 10, 30, 23, tzinfo=dt.timezone.utc),
            "date_issued": dt.datetime(2019, 10, 2, 23, tzinfo=dt.timezone.utc),
            "days_to_complete": 3,
            "end_location_id": 1022167642188,
            "for_corporation": False,
            "issuer_corporation_id": 92000002,
            "issuer_id": 90000003,
            "price": 0.0,
            "reward": 25000000.0,
            "start_location_id": 60003760,
            "status": "finished",
            "title": "demo contract",
            "type": "courier",
            "volume": 115000.0,
        }
        obj, created = Contract.objects.update_or_create_from_dict(
            self.handler, contract_dict, Mock()
        )
        self.assertTrue(created)
        self.assertEqual(obj.contract_id, 149409014)
        self.assertEqual(obj.acceptor, EveCharacter.objects.get(character_id=90000003))
        self.assertEqual(
            obj.acceptor_corporation,
            EveCorporationInfo.objects.get(corporation_id=92000002),
        )
        self.assertEqual(obj.collateral, 50000000)
        self.assertEqual(
            obj.date_accepted, dt.datetime(2019, 10, 3, 23, tzinfo=dt.timezone.utc)
        )
        self.assertEqual(
            obj.date_completed, dt.datetime(2019, 10, 4, 23, tzinfo=dt.timezone.utc)
        )
        self.assertEqual(
            obj.date_issued, dt.datetime(2019, 10, 2, 23, tzinfo=dt.timezone.utc)
        )
        self.assertEqual(
            obj.date_expired, dt.datetime(2019, 10, 30, 23, tzinfo=dt.timezone.utc)
        )
        self.assertEqual(obj.days_to_complete, 3)
        self.assertEqual(obj.end_location_id, 1022167642188)
        self.assertFalse(obj.for_corporation)
        self.assertEqual(
            obj.issuer_corporation,
            EveCorporationInfo.objects.get(corporation_id=92000002),
        )
        self.assertEqual(obj.issuer, EveCharacter.objects.get(character_id=90000003))
        self.assertEqual(obj.reward, 25000000)
        self.assertEqual(obj.start_location_id, 60003760)
        self.assertEqual(obj.status, Contract.Status.FINISHED)
        self.assertEqual(obj.title, "demo contract")
        self.assertEqual(obj.volume, 115000)
        self.assertIsNone(obj.pricing)
        self.assertIsNone(obj.issues)

    def test_raises_exception_on_wrong_date_types(self):
        contract_dict = {
            "acceptor_id": 90000003,
            "assignee_id": 90000003,
            "availability": "personal",
            "buyout": None,
            "collateral": 50000000.0,
            "contract_id": 149409014,
            "date_accepted": "2019-10-03T23:00:00Z",
            "date_completed": "2019-10-04T23:00:00Z",
            "date_expired": "2019-10-30T23:00:00Z",
            "date_issued": "2019-10-02T23:00:00Z",
            "days_to_complete": 3,
            "end_location_id": 1022167642188,
            "for_corporation": False,
            "issuer_corporation_id": 92000002,
            "issuer_id": 90000003,
            "price": 0.0,
            "reward": 25000000.0,
            "start_location_id": 60003760,
            "status": "finished",
            "title": "demo contract",
            "type": "courier",
            "volume": 115000.0,
        }
        with self.assertRaises(TypeError):
            Contract.objects.update_or_create_from_dict(
                self.handler, contract_dict, Mock()
            )

    @patch(MANAGERS_PATH + ".EveCharacter.objects.create_character")
    def test_can_create_in_progress_and_creates_acceptor_char(
        self, mock_create_character
    ):
        def create_character(character_id):
            return EveCharacter.objects.create(
                character_id=90000987,
                character_name="Dummy",
                corporation_id=92000002,
                corporation_name="The Planet",
            )

        mock_create_character.side_effect = create_character
        EveEntity.objects.create(
            id=90000987, name="Dummy", category=EveEntity.CATEGORY_CHARACTER
        )
        contract_dict = {
            "acceptor_id": 90000987,
            "assignee_id": 90000987,
            "availability": "personal",
            "buyout": None,
            "collateral": 50000000.0,
            "contract_id": 149409014,
            "date_accepted": dt.datetime(2019, 10, 3, 23, tzinfo=dt.timezone.utc),
            "date_completed": None,
            "date_expired": dt.datetime(2019, 10, 30, 23, tzinfo=dt.timezone.utc),
            "date_issued": dt.datetime(2019, 10, 2, 23, tzinfo=dt.timezone.utc),
            "days_to_complete": 3,
            "end_location_id": 1022167642188,
            "for_corporation": False,
            "issuer_corporation_id": 92000002,
            "issuer_id": 90000003,
            "price": 0.0,
            "reward": 25000000.0,
            "start_location_id": 60003760,
            "status": "in_progress",
            "title": "demo contract",
            "type": "courier",
            "volume": 115000.0,
        }
        obj, created = Contract.objects.update_or_create_from_dict(
            self.handler, contract_dict, Mock()
        )
        self.assertTrue(created)
        self.assertEqual(obj.contract_id, 149409014)
        self.assertEqual(obj.acceptor, EveCharacter.objects.get(character_id=90000987))
        self.assertEqual(
            obj.acceptor_corporation,
            EveCorporationInfo.objects.get(corporation_id=92000002),
        )

    @patch(MANAGERS_PATH + ".EveEntityManager.get_or_create_esi")
    def test_sets_acceptor_to_none_if_it_cant_be_created(self, mock_get_or_create_esi):
        # given
        mock_get_or_create_esi.side_effect = OSError
        contract_dict = {
            "acceptor_id": 666,
            "assignee_id": 90000987,
            "availability": "personal",
            "buyout": None,
            "collateral": 50000000.0,
            "contract_id": 149409014,
            "date_accepted": dt.datetime(2019, 10, 3, 23, tzinfo=dt.timezone.utc),
            "date_completed": None,
            "date_expired": dt.datetime(2019, 10, 30, 23, tzinfo=dt.timezone.utc),
            "date_issued": dt.datetime(2019, 10, 2, 23, tzinfo=dt.timezone.utc),
            "days_to_complete": 3,
            "end_location_id": 1022167642188,
            "for_corporation": False,
            "issuer_corporation_id": 92000002,
            "issuer_id": 90000003,
            "price": 0.0,
            "reward": 25000000.0,
            "start_location_id": 60003760,
            "status": "in_progress",
            "title": "demo contract",
            "type": "courier",
            "volume": 115000.0,
        }
        # when
        obj, created = Contract.objects.update_or_create_from_dict(
            self.handler, contract_dict, Mock()
        )
        # then
        self.assertTrue(created)
        self.assertEqual(obj.contract_id, 149409014)
        self.assertIsNone(obj.acceptor)
        self.assertIsNone(obj.acceptor_corporation)


if "discord" in app_labels():

    @patch(MODELS_PATH + ".contracts.FREIGHT_HOURS_UNTIL_STALE_STATUS", 48)
    @patch(MODELS_PATH + ".contracts.dhooks_lite.Webhook.execute", autospec=True)
    class TestContractManager_Notifications(NoSocketsTestCase):
        @classmethod
        def setUpClass(cls):
            super().setUpClass()
            cls.handler, _ = create_contract_handler_w_contracts()
            jita = Location.objects.get(id=60003760)
            amamake = Location.objects.get(id=1022167642188)
            PricingFactory(
                start_location=jita, end_location=amamake, price_base=500000000
            )
            Contract.objects.update_pricing()

        @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_WEBHOOK_URL", "url")
        @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", None)
        @patch(MANAGERS_PATH + ".FREIGHT_NOTIFY_ALL_CONTRACTS", False)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_WEBHOOK_URL", "url")
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", None)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORDPROXY_ENABLED", False)
        def test_send_pilot_notifications_normal(self, mock_webhook_execute):
            Contract.objects.send_notifications(rate_limited=False)
            self.assertEqual(mock_webhook_execute.call_count, 8)

        @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_WEBHOOK_URL", "url")
        @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", None)
        @patch(MANAGERS_PATH + ".FREIGHT_NOTIFY_ALL_CONTRACTS", True)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_WEBHOOK_URL", "url")
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", None)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORDPROXY_ENABLED", False)
        def test_send_pilot_notifications_if_invalid_route_set_but_global_option_enabled(
            self, mock_webhook_execute
        ):
            x = Contract.objects.filter(status=Contract.Status.OUTSTANDING).first()
            Contract.objects.all().exclude(pk=x.pk).delete()
            x.end_location_id = 60008494
            x.save()
            Contract.objects.update_pricing()
            Contract.objects.send_notifications(rate_limited=False)
            self.assertEqual(mock_webhook_execute.call_count, 1)

        @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_WEBHOOK_URL", "url")
        @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", None)
        @patch(MANAGERS_PATH + ".FREIGHT_NOTIFY_ALL_CONTRACTS", False)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_WEBHOOK_URL", "url")
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", None)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORDPROXY_ENABLED", False)
        def test_send_pilot_notifications_if_invalid_route_set_and_global_option_disabled(
            self, mock_webhook_execute
        ):
            x = Contract.objects.filter(status=Contract.Status.OUTSTANDING).first()
            Contract.objects.all().exclude(pk=x.pk).delete()
            x.end_location_id = 60008494
            x.save()
            Contract.objects.update_pricing()
            Contract.objects.send_notifications(rate_limited=False)
            self.assertEqual(mock_webhook_execute.call_count, 0)

        @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_WEBHOOK_URL", "url")
        @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", None)
        @patch(MANAGERS_PATH + ".FREIGHT_NOTIFY_ALL_CONTRACTS", False)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_WEBHOOK_URL", "url")
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", None)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORDPROXY_ENABLED", False)
        def test_dont_send_pilot_notifications_for_expired_contracts(
            self, mock_webhook_execute
        ):
            x = Contract.objects.filter(status=Contract.Status.OUTSTANDING).first()
            Contract.objects.all().exclude(pk=x.pk).delete()
            x.date_expired = now() - dt.timedelta(hours=1)
            x.save()
            Contract.objects.send_notifications(rate_limited=False)
            self.assertEqual(mock_webhook_execute.call_count, 0)

        @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_WEBHOOK_URL", "url")
        @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", None)
        @patch(MANAGERS_PATH + ".FREIGHT_NOTIFY_ALL_CONTRACTS", False)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_WEBHOOK_URL", "url")
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", None)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORDPROXY_ENABLED", False)
        def test_send_pilot_notifications_only_once(self, mock_webhook_execute):
            x = Contract.objects.filter(status=Contract.Status.OUTSTANDING).first()
            Contract.objects.all().exclude(pk=x.pk).delete()

            # round #1
            Contract.objects.send_notifications(rate_limited=False)
            self.assertEqual(mock_webhook_execute.call_count, 1)

            # round #2
            Contract.objects.send_notifications(rate_limited=False)
            self.assertEqual(mock_webhook_execute.call_count, 1)

        @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_WEBHOOK_URL", None)
        @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", None)
        @patch(MANAGERS_PATH + ".FREIGHT_NOTIFY_ALL_CONTRACTS", False)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_WEBHOOK_URL", None)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", None)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORDPROXY_ENABLED", False)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORDPROXY_ENABLED", False)
        def test_dont_send_any_notifications_when_no_url_if_set(
            self, mock_webhook_execute
        ):
            Contract.objects.send_notifications(rate_limited=False)
            self.assertEqual(mock_webhook_execute.call_count, 0)

        @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_WEBHOOK_URL", None)
        @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", "url")
        @patch(MANAGERS_PATH + ".FREIGHT_NOTIFY_ALL_CONTRACTS", False)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_WEBHOOK_URL", None)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", "url")
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORDPROXY_ENABLED", False)
        def test_send_customer_notifications_normal(self, mock_webhook_execute):
            Contract.objects.send_notifications(rate_limited=False)
            self.assertEqual(mock_webhook_execute.call_count, 12)

        @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_WEBHOOK_URL", None)
        @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", "url")
        @patch(MANAGERS_PATH + ".FREIGHT_NOTIFY_ALL_CONTRACTS", False)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_WEBHOOK_URL", None)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", "url")
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORDPROXY_ENABLED", False)
        def test_dont_send_customer_notifications_for_expired_contracts(
            self, mock_webhook_execute
        ):
            x = Contract.objects.filter(status=Contract.Status.OUTSTANDING).first()
            Contract.objects.all().exclude(pk=x.pk).delete()
            x.date_expired = now() - dt.timedelta(hours=1)
            x.save()
            Contract.objects.send_notifications(rate_limited=False)
            self.assertEqual(mock_webhook_execute.call_count, 0)

        @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_WEBHOOK_URL", None)
        @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", "url")
        @patch(MANAGERS_PATH + ".FREIGHT_NOTIFY_ALL_CONTRACTS", False)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_WEBHOOK_URL", None)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", "url")
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORDPROXY_ENABLED", False)
        def test_send_customer_notifications_only_once_per_state(
            self, mock_webhook_execute
        ):
            x = Contract.objects.filter(status=Contract.Status.OUTSTANDING).first()
            Contract.objects.all().exclude(pk=x.pk).delete()

            # round #1
            Contract.objects.send_notifications(rate_limited=False)
            self.assertEqual(mock_webhook_execute.call_count, 1)

            # round #2
            Contract.objects.send_notifications(rate_limited=False)
            self.assertEqual(mock_webhook_execute.call_count, 1)

        @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_WEBHOOK_URL", "url")
        @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", None)
        @patch(MANAGERS_PATH + ".FREIGHT_NOTIFY_ALL_CONTRACTS", True)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_WEBHOOK_URL", "url")
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", None)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORDPROXY_ENABLED", False)
        def test_send_customer_notification_if_invalid_route_set_but_global_option_enabled(
            self, mock_webhook_execute
        ):
            x = Contract.objects.filter(status=Contract.Status.OUTSTANDING).first()
            Contract.objects.all().exclude(pk=x.pk).delete()
            x.end_location_id = 60008494
            x.save()
            Contract.objects.update_pricing()
            Contract.objects.send_notifications(rate_limited=False)
            self.assertEqual(mock_webhook_execute.call_count, 1)

        @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_WEBHOOK_URL", "url")
        @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", None)
        @patch(MANAGERS_PATH + ".FREIGHT_NOTIFY_ALL_CONTRACTS", False)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_WEBHOOK_URL", "url")
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", None)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORDPROXY_ENABLED", False)
        def test_send_customer_notification_if_invalid_route_set_and_global_option_disabled(
            self, mock_webhook_execute
        ):
            x = Contract.objects.filter(status=Contract.Status.OUTSTANDING).first()
            Contract.objects.all().exclude(pk=x.pk).delete()
            x.end_location_id = 60008494
            x.save()
            Contract.objects.update_pricing()
            Contract.objects.send_notifications(rate_limited=False)
            self.assertEqual(mock_webhook_execute.call_count, 0)


class TestPricingManager(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.jita, cls.amamake, cls.amarr = create_locations()
        cls.p1 = PricingFactory(
            start_location=cls.jita,
            end_location=cls.amamake,
            price_base=50000000,
            is_default=True,
        )
        cls.p2 = PricingFactory(
            start_location=cls.jita, end_location=cls.amarr, price_base=10000000
        )

    def test_default_pricing_no_default_defined(self):
        Pricing.objects.all().delete()
        p = PricingFactory(
            start_location=self.jita,
            end_location=self.amamake,
            price_base=50000000,
            is_default=True,
        )
        expected = p
        self.assertEqual(Pricing.objects.get_default(), expected)

    def test_default_and_default_defined(self):
        expected = self.p1
        self.assertEqual(Pricing.objects.get_default(), expected)

    def test_default_with_no_pricing_defined(self):
        Pricing.objects.all().delete()
        expected = None
        self.assertEqual(Pricing.objects.get_default(), expected)

    def test_get_or_default_normal(self):
        expected = self.p1
        self.assertEqual(Pricing.objects.get_or_default(self.p1.pk), expected)

    def test_get_or_default_not_found(self):
        expected = self.p1
        invalid_pk = generate_invalid_pk(Pricing)
        self.assertEqual(Pricing.objects.get_or_default(invalid_pk), expected)

    def test_get_or_default_with_none(self):
        expected = self.p1
        self.assertEqual(Pricing.objects.get_or_default(None), expected)
