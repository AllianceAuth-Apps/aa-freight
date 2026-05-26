import datetime as dt
from http import HTTPStatus
from typing import NamedTuple, Set
from unittest.mock import patch

import pook

from django.core.cache import cache
from django.test import TransactionTestCase
from django.utils.timezone import now
from esi.exceptions import HTTPServerError

from app_utils.testdata_factories import (
    EveAllianceInfoFactory,
    EveCharacterFactory,
    EveCorporationInfoFactory,
)
from app_utils.testing import NoSocketsTestCase

from freight.app_settings import (
    FREIGHT_OPERATION_MODE_CORP_IN_ALLIANCE,
    FREIGHT_OPERATION_MODE_CORP_PUBLIC,
    FREIGHT_OPERATION_MODE_MY_ALLIANCE,
    FREIGHT_OPERATION_MODE_MY_CORPORATION,
    FREIGHT_OPERATION_MODES,
)
from freight.models import Contract, ContractHandler, EveEntity, Freight
from freight.tests.helpers import extract
from freight.tests.testdata.factories_2 import (
    ContractFactory,
    ContractHandlerFactory,
    EveEntityAllianceFactory,
    EveEntityCharacterFactory,
    EveEntityCorporationFactory,
    LocationStationFactory,
    UserMainManagerFactory,
    make_esi_url,
)

MODULE_PATH = "freight.models.contract_handlers"
MANAGERS_PATH = "freight.managers"


class TestContractHandler(NoSocketsTestCase):
    def test_str(self):
        user = UserMainManagerFactory(
            main_character__character=EveCharacterFactory(
                corporation__corporation_name="Justice League"
            )
        )
        handler = ContractHandlerFactory(
            user=user, operation_mode=ContractHandler.Mode.MY_CORPORATION
        )
        self.assertEqual(str(handler), "Justice League")

    def test_get_availability_text_for_contracts(self):
        class Case(NamedTuple):
            operation_mode: ContractHandler.Mode
            want: str

        cases = [
            Case(
                ContractHandler.Mode.MY_ALLIANCE,
                "Private (Justice World) [My Alliance]",
            ),
            Case(
                ContractHandler.Mode.MY_CORPORATION,
                "Private (Justice League) [My Corporation]",
            ),
            Case(
                ContractHandler.Mode.CORP_IN_ALLIANCE,
                "Private (Justice League)",
            ),
            Case(
                ContractHandler.Mode.CORP_PUBLIC,
                "Private (Justice League)",
            ),
        ]

        alliance = EveAllianceInfoFactory(alliance_name="Justice World")
        corporation = EveCorporationInfoFactory(
            alliance=alliance, corporation_name="Justice League"
        )
        my_character = EveCharacterFactory(corporation=corporation)
        user = UserMainManagerFactory(main_character__character=my_character)

        for tc in cases:
            with self.subTest(mode=tc.operation_mode):
                handler = ContractHandlerFactory(
                    user=user, operation_mode=tc.operation_mode
                )
                got = handler.get_availability_text_for_contracts()
                self.assertEqual(got, tc.want)

                ContractHandler.objects.all().delete()

    @patch(MODULE_PATH + ".FREIGHT_CONTRACT_SYNC_GRACE_MINUTES", 30)
    def test_is_sync_ok(self):
        # recent sync
        handler = ContractHandler(last_sync=now())
        self.assertTrue(handler.is_sync_ok)

        # sync within grace period
        handler = ContractHandler(last_sync=now() - dt.timedelta(minutes=29))
        self.assertTrue(handler.is_sync_ok)

        # no sync within grace period
        handler = ContractHandler(last_sync=now() - dt.timedelta(minutes=31))
        self.assertFalse(handler.is_sync_ok)


class TestContractHandler_OperationModeFriendly(NoSocketsTestCase):
    def test_should_return_friendly_text_for_known_modes(self):
        cases = [
            (ContractHandler.Mode.MY_ALLIANCE, FREIGHT_OPERATION_MODES[0][1]),
            (ContractHandler.Mode.MY_CORPORATION, FREIGHT_OPERATION_MODES[1][1]),
            (ContractHandler.Mode.CORP_IN_ALLIANCE, FREIGHT_OPERATION_MODES[2][1]),
            (ContractHandler.Mode.CORP_PUBLIC, FREIGHT_OPERATION_MODES[3][1]),
        ]
        for mode, want in cases:
            with patch(MODULE_PATH + ".FREIGHT_OPERATION_MODE", mode):
                handler = ContractHandlerFactory(operation_mode=mode)
                self.assertEqual(handler.operation_mode_friendly, want)

    def test_should_raise_exception_for_unknown_mode(self):
        handler = ContractHandlerFactory()
        handler.operation_mode = "invalid"
        with self.assertRaises(ValueError):
            handler.operation_mode_friendly


class TestContractHandler_UpdateContractsEsi(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cache.clear()

    @patch(
        MODULE_PATH + ".FREIGHT_OPERATION_MODE", FREIGHT_OPERATION_MODE_MY_CORPORATION
    )
    @pook.on
    def test_can_create_new_contract_from_esi(self):
        # given
        handler = ContractHandlerFactory(
            operation_mode=ContractHandler.Mode.MY_CORPORATION
        )
        corporation = handler.character.character.corporation
        contract_id = 42
        end_location = LocationStationFactory()
        issuer = EveCharacterFactory(corporation=corporation)
        reward = 1234.56
        collateral = 91234.56
        days_to_complete = 3
        start_location = LocationStationFactory()
        date_issued = now() - dt.timedelta(hours=3)
        date_expired = date_issued + dt.timedelta(days=3)
        title = "title"
        volume = 100_000
        pook.get(
            make_esi_url(f"corporations/{handler.organization.id}/contracts"),
            reply=HTTPStatus.OK,
            response_headers={"X-Pages": "1"},
            response_json=[
                {
                    "acceptor_id": 0,
                    "assignee_id": handler.organization.id,
                    "availability": "corporation",
                    "collateral": collateral,
                    "contract_id": contract_id,
                    "date_expired": date_expired.isoformat(),
                    "date_issued": date_issued.isoformat(),
                    "days_to_complete": days_to_complete,
                    "end_location_id": end_location.id,
                    "for_corporation": False,
                    "issuer_corporation_id": corporation.corporation_id,
                    "issuer_id": issuer.character_id,
                    "reward": reward,
                    "start_location_id": start_location.id,
                    "status": "outstanding",
                    "title": title,
                    "type": "courier",
                    "volume": volume,
                }
            ],
        )

        # when
        handler.update_contracts_esi()

        # then
        self.assertEqual(handler.contracts.count(), 1)
        obj: Contract = handler.contracts.first()

        self.assertIsNone(obj.acceptor)
        self.assertIsNone(obj.acceptor_corporation)
        self.assertEqual(obj.contract_id, contract_id)
        self.assertEqual(obj.collateral, collateral)
        self.assertIsNone(obj.date_accepted)
        self.assertIsNone(obj.date_completed)
        self.assertEqual(obj.date_expired, date_expired)
        self.assertEqual(obj.date_issued, date_issued)
        self.assertEqual(obj.days_to_complete, days_to_complete)
        self.assertEqual(obj.end_location, end_location)
        self.assertFalse(obj.for_corporation)
        self.assertEqual(obj.issuer_corporation, corporation)
        self.assertEqual(obj.issuer, issuer)
        self.assertEqual(obj.reward, reward)
        self.assertEqual(obj.start_location, start_location)
        self.assertEqual(obj.status, Contract.Status.OUTSTANDING)
        self.assertEqual(obj.title, title)
        self.assertEqual(obj.volume, volume)

        # # should only contain the right contracts
        # contract_ids = [
        #     x["contract_id"]
        #     for x in Contract.objects.filter(
        #         status__exact=Contract.Status.OUTSTANDING
        #     ).values("contract_id")
        # ]
        # self.assertCountEqual(
        #     contract_ids, [149409005, 149409014, 149409006, 149409015]
        # )

        # # 2nd run should not update anything, but reset last_sync
        # Contract.objects.all().delete()
        # handler.last_sync = None
        # handler.save()
        # handler.update_contracts_esi()
        # self.assertEqual(Contract.objects.count(), 0)
        # handler.refresh_from_db()
        # self.assertIsNotNone(handler.last_sync)

    @patch(
        MODULE_PATH + ".FREIGHT_OPERATION_MODE", FREIGHT_OPERATION_MODE_MY_CORPORATION
    )
    @pook.on
    def test_can_update_contract_from_esi(self):
        # given
        handler = ContractHandlerFactory(
            operation_mode=ContractHandler.Mode.MY_CORPORATION
        )
        contract = ContractFactory(handler=handler)
        acceptor = EveCharacterFactory()
        EveEntityCharacterFactory(
            id=acceptor.character_id, name=acceptor.character_name
        )  # needed for internal check
        date_accepted = contract.date_issued + dt.timedelta(hours=1)
        date_completed = contract.date_issued + dt.timedelta(hours=1)
        pook.get(
            make_esi_url(f"corporations/{handler.organization.id}/contracts"),
            reply=HTTPStatus.OK,
            response_headers={"X-Pages": "1"},
            response_json=[
                {
                    "acceptor_id": acceptor.character_id,
                    "assignee_id": handler.organization.id,
                    "availability": "corporation",
                    "collateral": contract.collateral,
                    "contract_id": contract.contract_id,
                    "date_accepted": date_accepted.isoformat(),
                    "date_completed": date_completed.isoformat(),
                    "date_expired": contract.date_expired.isoformat(),
                    "date_issued": contract.date_issued.isoformat(),
                    "days_to_complete": contract.days_to_complete,
                    "end_location_id": contract.end_location.id,
                    "for_corporation": False,
                    "issuer_corporation_id": contract.issuer_corporation.corporation_id,
                    "issuer_id": contract.issuer.character_id,
                    "reward": contract.reward,
                    "start_location_id": contract.start_location.id,
                    "status": "finished",
                    "title": contract.title,
                    "type": "courier",
                    "volume": contract.volume,
                }
            ],
        )

        # when
        handler.update_contracts_esi()

        # then
        self.assertEqual(handler.contracts.count(), 1)
        obj: Contract = handler.contracts.first()

        self.assertEqual(obj.date_accepted, date_accepted)
        self.assertEqual(obj.date_completed, date_completed)
        self.assertEqual(obj.acceptor, acceptor)
        self.assertEqual(obj.acceptor_corporation, acceptor.corporation)
        self.assertEqual(obj.status, Contract.Status.FINISHED)

    @pook.on
    def test_can_sync_operation_modes(self):
        # given
        _reward = 1234.56
        _collateral = 91234.56
        _days_to_complete = 3
        _start_location = LocationStationFactory()
        _end_location = LocationStationFactory()
        _date_issued = now() - dt.timedelta(hours=3)
        _date_expired = _date_issued + dt.timedelta(days=3)
        _volume = 100_000

        my_alliance = EveAllianceInfoFactory()
        my_corporation = EveCorporationInfoFactory(alliance=my_alliance)
        my_character = EveCharacterFactory(corporation=my_corporation)
        user = UserMainManagerFactory(main_character__character=my_character)
        issuer_my_corporation = EveCharacterFactory(corporation=my_corporation)
        issuer_corporation_in_alliance = EveCharacterFactory(
            corporation=EveCorporationInfoFactory(alliance=my_alliance)
        )
        issuer_other_corporation = EveCharacterFactory()
        pook.get(
            make_esi_url(f"corporations/{my_corporation.corporation_id}/contracts"),
            reply=HTTPStatus.OK,
            response_headers={"X-Pages": "1"},
            response_json=[
                {
                    "acceptor_id": 0,
                    "assignee_id": my_corporation.corporation_id,
                    "availability": "corporation",
                    "collateral": _collateral,
                    "contract_id": 101,
                    "date_expired": _date_expired.isoformat(),
                    "date_issued": _date_issued.isoformat(),
                    "days_to_complete": _days_to_complete,
                    "end_location_id": _end_location.id,
                    "for_corporation": False,
                    "issuer_corporation_id": issuer_my_corporation.corporation_id,
                    "issuer_id": issuer_my_corporation.character_id,
                    "reward": _reward,
                    "start_location_id": _start_location.id,
                    "status": "outstanding",
                    "title": "corporation contract from corporation member",
                    "type": "courier",
                    "volume": _volume,
                },
                {
                    "acceptor_id": 0,
                    "assignee_id": my_alliance.alliance_id,
                    "availability": "alliance",
                    "collateral": _collateral,
                    "contract_id": 102,
                    "date_expired": _date_expired.isoformat(),
                    "date_issued": _date_issued.isoformat(),
                    "days_to_complete": _days_to_complete,
                    "end_location_id": _end_location.id,
                    "for_corporation": False,
                    "issuer_corporation_id": issuer_my_corporation.corporation_id,
                    "issuer_id": issuer_my_corporation.character_id,
                    "reward": _reward,
                    "start_location_id": _start_location.id,
                    "status": "outstanding",
                    "title": "alliance contract from corporation member",
                    "type": "courier",
                    "volume": _volume,
                },
                {
                    "acceptor_id": 0,
                    "assignee_id": my_alliance.alliance_id,
                    "availability": "alliance",
                    "collateral": _collateral,
                    "contract_id": 105,
                    "date_expired": _date_expired.isoformat(),
                    "date_issued": _date_issued.isoformat(),
                    "days_to_complete": _days_to_complete,
                    "end_location_id": _end_location.id,
                    "for_corporation": False,
                    "issuer_corporation_id": issuer_corporation_in_alliance.corporation_id,
                    "issuer_id": issuer_corporation_in_alliance.character_id,
                    "reward": _reward,
                    "start_location_id": _start_location.id,
                    "status": "outstanding",
                    "title": "alliance contract from alliance member outside the corporation",
                    "type": "courier",
                    "volume": _volume,
                },
                {
                    "acceptor_id": 0,
                    "assignee_id": my_corporation.corporation_id,
                    "availability": "corporation",
                    "collateral": _collateral,
                    "contract_id": 103,
                    "date_expired": _date_expired.isoformat(),
                    "date_issued": _date_issued.isoformat(),
                    "days_to_complete": _days_to_complete,
                    "end_location_id": _end_location.id,
                    "for_corporation": False,
                    "issuer_corporation_id": issuer_corporation_in_alliance.corporation_id,
                    "issuer_id": issuer_corporation_in_alliance.character_id,
                    "reward": _reward,
                    "start_location_id": _start_location.id,
                    "status": "outstanding",
                    "title": "corporation contract from alliance member in different corporation",
                    "type": "courier",
                    "volume": _volume,
                },
                {
                    "acceptor_id": 0,
                    "assignee_id": my_corporation.corporation_id,
                    "availability": "corporation",
                    "collateral": _collateral,
                    "contract_id": 104,
                    "date_expired": _date_expired.isoformat(),
                    "date_issued": _date_issued.isoformat(),
                    "days_to_complete": _days_to_complete,
                    "end_location_id": _end_location.id,
                    "for_corporation": False,
                    "issuer_corporation_id": issuer_other_corporation.corporation_id,
                    "issuer_id": issuer_other_corporation.character_id,
                    "reward": _reward,
                    "start_location_id": _start_location.id,
                    "status": "outstanding",
                    "title": "corporation contract from non-aligned character",
                    "type": "courier",
                    "volume": _volume,
                },
                # below contracts should not be picked up by any mode
                {
                    "acceptor_id": 0,
                    "assignee_id": 0,
                    "availability": "public",
                    "collateral": _collateral,
                    "contract_id": 901,
                    "date_expired": _date_expired.isoformat(),
                    "date_issued": _date_issued.isoformat(),
                    "days_to_complete": _days_to_complete,
                    "end_location_id": _end_location.id,
                    "for_corporation": False,
                    "issuer_corporation_id": issuer_my_corporation.corporation_id,
                    "issuer_id": issuer_my_corporation.character_id,
                    "reward": _reward,
                    "start_location_id": _start_location.id,
                    "status": "outstanding",
                    "title": "public contract from corp member",
                    "type": "courier",
                    "volume": _volume,
                },
                {
                    "acceptor_id": 0,
                    "assignee_id": my_character.character_id,
                    "availability": "personal",
                    "collateral": _collateral,
                    "contract_id": 902,
                    "date_expired": _date_expired.isoformat(),
                    "date_issued": _date_issued.isoformat(),
                    "days_to_complete": _days_to_complete,
                    "end_location_id": _end_location.id,
                    "for_corporation": False,
                    "issuer_corporation_id": issuer_my_corporation.corporation_id,
                    "issuer_id": issuer_my_corporation.character_id,
                    "reward": _reward,
                    "start_location_id": _start_location.id,
                    "status": "outstanding",
                    "title": "personal contract to me from corp member",
                    "type": "courier",
                    "volume": _volume,
                },
            ],
            persist=True,
        )

        class Case(NamedTuple):
            operation_mode: ContractHandler.Mode
            contract_ids: Set[int]

        cases = [
            Case(ContractHandler.Mode.CORP_IN_ALLIANCE, {101, 103}),
            Case(ContractHandler.Mode.CORP_PUBLIC, {101, 103, 104}),
            Case(ContractHandler.Mode.MY_ALLIANCE, {102, 105}),
            Case(ContractHandler.Mode.MY_CORPORATION, {101}),
        ]

        for tc in cases:
            with self.subTest(mode=tc.operation_mode):
                # given
                ContractHandler.objects.all().delete()
                handler = ContractHandlerFactory(
                    operation_mode=tc.operation_mode, user=user
                )

                # when
                with patch(MODULE_PATH + ".FREIGHT_OPERATION_MODE", tc.operation_mode):
                    handler.update_contracts_esi()

                # then
                self.assertSetEqual(
                    extract(handler.contracts, "contract_id"), tc.contract_ids
                )

    @patch(
        MODULE_PATH + ".FREIGHT_OPERATION_MODE", FREIGHT_OPERATION_MODE_MY_CORPORATION
    )
    @pook.on
    def test_should_continue_when_storing_a_contract_failed(self):
        # given
        handler = ContractHandlerFactory(
            operation_mode=ContractHandler.Mode.MY_CORPORATION
        )
        corporation = handler.character.character.corporation
        contract_id = 42
        end_location = LocationStationFactory()
        issuer = EveCharacterFactory(corporation=corporation)
        reward = 1234.56
        collateral = 91234.56
        days_to_complete = 3
        start_location = LocationStationFactory()
        date_issued = now() - dt.timedelta(hours=3)
        date_expired = date_issued + dt.timedelta(days=3)
        title = "title"
        volume = 100_000
        pook.get(
            make_esi_url(f"corporations/{handler.organization.id}/contracts"),
            reply=HTTPStatus.OK,
            response_headers={"X-Pages": "1"},
            response_json=[
                {
                    "acceptor_id": 0,
                    "assignee_id": handler.organization.id,
                    "availability": "corporation",
                    "collateral": collateral,
                    "contract_id": contract_id,
                    "date_expired": date_expired.isoformat(),
                    "date_issued": date_issued.isoformat(),
                    "days_to_complete": days_to_complete,
                    "end_location_id": end_location.id,
                    "for_corporation": False,
                    "issuer_corporation_id": corporation.corporation_id,
                    "issuer_id": issuer.character_id,
                    "reward": reward,
                    "start_location_id": start_location.id,
                    "status": "outstanding",
                    "title": title,
                    "type": "courier",
                    "volume": volume,
                }
            ],
        )
        exception = HTTPServerError(
            status_code=500, headers={}, data="Internal Server Error"
        )

        # when
        with patch(MANAGERS_PATH + ".ContractManager.update_or_create_from_dict") as m:
            m.side_effect = exception
            handler.update_contracts_esi()

        # then
        self.assertEqual(handler.contracts.count(), 0)

    @pook.on
    def test_abort_when_operation_mode_does_not_match(self):
        # given
        handler = ContractHandlerFactory(
            operation_mode=ContractHandler.Mode.MY_ALLIANCE
        )
        # when/then
        with self.assertRaises(ValueError):
            with patch(
                MODULE_PATH + ".FREIGHT_OPERATION_MODE",
                FREIGHT_OPERATION_MODE_MY_CORPORATION,
            ):
                handler.update_contracts_esi()

    @pook.on
    def test_abort_when_no_sync_char(self):
        # given
        handler = ContractHandlerFactory(
            operation_mode=ContractHandler.Mode.MY_ALLIANCE, character=None
        )
        # when/Then
        with self.assertRaises(ValueError):
            with patch(
                MODULE_PATH + ".FREIGHT_OPERATION_MODE",
                FREIGHT_OPERATION_MODE_MY_ALLIANCE,
            ):
                handler.update_contracts_esi()


class TestEveEntity(NoSocketsTestCase):
    def test_str(self):
        obj = EveEntityCharacterFactory(name="Bruce Wayne")
        self.assertEqual(str(obj), "Bruce Wayne")

    def test_icon_url(self):
        cases = [
            (
                "alliance",
                EveEntityAllianceFactory(id=93000001),
                "https://images.evetech.net/alliances/93000001/logo?size=128",
            ),
            (
                "character",
                EveEntityCharacterFactory(id=90000001),
                "https://images.evetech.net/characters/90000001/portrait?size=128",
            ),
            (
                "corporation",
                EveEntityCorporationFactory(id=92000001),
                "https://images.evetech.net/corporations/92000001/logo?size=128",
            ),
        ]
        for tc in cases:
            with self.subTest(name=tc[0]):
                self.assertEqual(tc[1].icon_url(), tc[2])


class TestEveEntity_IdentifyCategory(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.character = EveEntityCharacterFactory()
        cls.corporation = EveEntityCorporationFactory()
        cls.alliance = EveEntityAllianceFactory()

    def test_is_alliance(self):
        self.assertFalse(self.character.is_alliance)
        self.assertFalse(self.corporation.is_alliance)
        self.assertTrue(self.alliance.is_alliance)

    def test_is_corporation(self):
        self.assertFalse(self.character.is_corporation)
        self.assertTrue(self.corporation.is_corporation)
        self.assertFalse(self.alliance.is_corporation)

    def test_is_character(self):
        self.assertTrue(self.character.is_character)
        self.assertFalse(self.corporation.is_character)
        self.assertFalse(self.alliance.is_character)


class TestFreight(NoSocketsTestCase):
    def test_get_category_for_operation_mode_1(self):
        self.assertEqual(
            Freight.category_for_operation_mode(FREIGHT_OPERATION_MODE_MY_ALLIANCE),
            EveEntity.CATEGORY_ALLIANCE,
        )
        self.assertEqual(
            Freight.category_for_operation_mode(FREIGHT_OPERATION_MODE_MY_CORPORATION),
            EveEntity.CATEGORY_CORPORATION,
        )
        self.assertEqual(
            Freight.category_for_operation_mode(
                FREIGHT_OPERATION_MODE_CORP_IN_ALLIANCE
            ),
            EveEntity.CATEGORY_CORPORATION,
        )
        self.assertEqual(
            Freight.category_for_operation_mode(FREIGHT_OPERATION_MODE_CORP_PUBLIC),
            EveEntity.CATEGORY_CORPORATION,
        )
