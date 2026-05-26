from http import HTTPStatus
from unittest.mock import patch

from django.test import RequestFactory, tag
from django.urls import reverse

from allianceauth.tests.auth_utils import AuthUtils
from app_utils.testdata_factories import EveCharacterFactory, UserMainFactory
from app_utils.testing import NoSocketsTestCase, json_response_to_python

from freight import constants, views
from freight.app_settings import FREIGHT_OPERATION_MODE_MY_ALLIANCE
from freight.models import Contract, ContractHandler, Location
from freight.tests.testdata.factories_2 import (
    ContractFactory,
    ContractHandlerFactory,
    PricingFactory,
    UserMainDefaultFactory,
)
from freight.tests.testdata.helpers import create_contract_handler_w_contracts

MODULE_PATH = "freight.views"


def json_response_to_python_dict(response) -> dict:
    return {x["id"]: x for x in json_response_to_python(response)["data"]}


class TestCalculator(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = UserMainDefaultFactory()
        cls.factory = RequestFactory()

    def test_index(self):
        # given
        ContractHandlerFactory(user=self.user)
        request = self.factory.get(reverse("freight:index"))
        request.user = self.user

        # when
        response = views.index(request)

        # then
        self.assertEqual(response.status_code, HTTPStatus.FOUND)
        self.assertEqual(response.url, reverse("freight:calculator"))

    def test_calculator_access_with_permission(self):
        # given
        ContractHandlerFactory(user=self.user)
        request = self.factory.get(reverse("freight:calculator"))
        request.user = self.user

        # when
        response = views.calculator(request)

        # then
        self.assertEqual(response.status_code, HTTPStatus.OK)

    def test_calculator_no_access_without_permission(self):
        # given
        ContractHandlerFactory(user=self.user)
        request = self.factory.get(reverse("freight:calculator"))
        request.user = UserMainFactory()
        # when
        response = views.calculator(request)

        # then
        self.assertNotEqual(response.status_code, HTTPStatus.OK)

    def test_can_render_calculator_without_handler(self):
        # given
        request = self.factory.get(reverse("freight:calculator"))
        request.user = self.user
        # when
        response = views.calculator(request)
        # then
        self.assertEqual(response.status_code, HTTPStatus.OK)


class TestContractListData_Access(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.factory = RequestFactory()
        cls.user_1 = UserMainFactory(
            permissions__=[
                "freight.basic_access",
                "freight.view_contracts",
                "freight.use_calculator",
            ]
        )
        cls.handler = ContractHandlerFactory(user=cls.user_1)
        cls.user_2 = UserMainFactory(
            main_character__character=EveCharacterFactory(
                corporation=cls.user_1.profile.main_character.corporation
            ),
            permissions__=["freight.basic_access"],
        )

    def test_should_open_all_contracts_page(self):
        # given
        request = self.factory.get(reverse("freight:contract_list_all"))
        request.user = self.user_1
        # when
        response = views.contract_list_all(request)
        # then
        self.assertEqual(response.status_code, HTTPStatus.OK)

    def test_all_no_access_without_permission(self):
        request = self.factory.get(reverse("freight:contract_list_all"))
        request.user = self.user_2
        response = views.contract_list_all(request)
        self.assertNotEqual(response.status_code, HTTPStatus.OK)

    # TODO
    """ issue with setting permission
    def test_active_access_with_permission(self):
        request = self.factory.get(reverse('freight:contract_list_active'))
        request.user = self.user_1

        response = views.contract_list_active(request)
        self.assertEqual(response.status_code, HTTPStatus.OK)
    """

    def test_user_no_access_without_permission(self):
        request = self.factory.get(reverse("freight:contract_list_user"))
        request.user = self.user_2
        response = views.contract_list_user(request)
        self.assertNotEqual(response.status_code, HTTPStatus.OK)

    def test_user_access_with_permission(self):
        request = self.factory.get(reverse("freight:contract_list_user"))
        request.user = self.user_1

        response = views.contract_list_user(request)
        self.assertEqual(response.status_code, HTTPStatus.OK)

    def test_user_access_with_permission_and_no_main(self):
        # given
        user = AuthUtils.create_user("John Doe")
        user = AuthUtils.add_permission_to_user_by_name("freight.basic_access", user)
        user = AuthUtils.add_permission_to_user_by_name("freight.use_calculator", user)
        request = self.factory.get(reverse("freight:contract_list_user"))
        request.user = user
        # when
        response = views.contract_list_user(request)
        # then
        self.assertEqual(response.status_code, HTTPStatus.OK)

    def test_data_user_no_access_without_permission_1(self):
        request = self.factory.get(
            reverse("freight:contract_list_data", args={constants.CONTRACT_LIST_USER})
        )
        request.user = self.user_2
        response = views.contract_list_data(request, constants.CONTRACT_LIST_USER)
        data = json_response_to_python(response)["data"]
        self.assertListEqual(data, [])

    def test_data_user_no_access_without_permission_2(self):
        request = self.factory.get(
            reverse("freight:contract_list_data", args={constants.CONTRACT_LIST_ACTIVE})
        )
        request.user = self.user_2
        response = views.contract_list_data(request, constants.CONTRACT_LIST_ACTIVE)
        data = json_response_to_python(response)["data"]
        self.assertListEqual(data, [])

    def test_data_user_no_access_without_permission_3(self):
        request = self.factory.get(
            reverse("freight:contract_list_data", args={constants.CONTRACT_LIST_ALL})
        )
        request.user = self.user_2
        response = views.contract_list_data(request, constants.CONTRACT_LIST_ALL)
        data = json_response_to_python(response)["data"]
        self.assertListEqual(data, [])


class TestContractListData_Categories(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.factory = RequestFactory()
        cls.user_1 = UserMainFactory(
            permissions__=[
                "freight.basic_access",
                "freight.view_contracts",
                "freight.use_calculator",
            ]
        )
        cls.handler = ContractHandlerFactory(user=cls.user_1)
        cls.contract_accepted = ContractFactory(handler=cls.handler, accepted=True)
        cls.contract_canceled = ContractFactory(handler=cls.handler, canceled=True)
        cls.contract_failed = ContractFactory(handler=cls.handler, failed=True)
        cls.contract_finished = ContractFactory(handler=cls.handler, finished=True)
        cls.contract_oustanding = ContractFactory(handler=cls.handler)
        cls.user_2 = UserMainFactory(
            permissions__=["freight.basic_access", "freight.use_calculator"]
        )
        cls.contract_accepted_user = ContractFactory(
            handler=cls.handler, user=cls.user_2, accepted=True
        )
        cls.contract_canceled_user = ContractFactory(
            handler=cls.handler, user=cls.user_2, canceled=True
        )
        cls.contract_failed_user = ContractFactory(
            handler=cls.handler, user=cls.user_2, failed=True
        )
        cls.contract_finished_user = ContractFactory(
            handler=cls.handler, user=cls.user_2, finished=True
        )
        cls.contract_oustanding_user = ContractFactory(
            handler=cls.handler, user=cls.user_2
        )

    def test_should_return_all_contracts(self):
        # given
        request = self.factory.get(
            reverse("freight:contract_list_data", args={constants.CONTRACT_LIST_ALL})
        )
        request.user = self.user_1

        # when
        response = views.contract_list_data(request, constants.CONTRACT_LIST_ALL)

        # then
        got = {obj["contract_id"] for obj in json_response_to_python(response)["data"]}
        want = {
            self.contract_oustanding.contract_id,
            self.contract_accepted.contract_id,
            self.contract_finished.contract_id,
            self.contract_failed.contract_id,
            self.contract_canceled.contract_id,
            self.contract_oustanding_user.contract_id,
            self.contract_accepted_user.contract_id,
            self.contract_finished_user.contract_id,
            self.contract_failed_user.contract_id,
            self.contract_canceled_user.contract_id,
        }
        self.assertSetEqual(got, want)

    def test_should_return_active_contracts(self):
        # given
        request = self.factory.get(
            reverse("freight:contract_list_data", args={constants.CONTRACT_LIST_ACTIVE})
        )
        request.user = self.user_1

        # when
        response = views.contract_list_data(request, constants.CONTRACT_LIST_ACTIVE)

        # then
        # then
        got = {obj["contract_id"] for obj in json_response_to_python(response)["data"]}
        want = {
            self.contract_oustanding.contract_id,
            self.contract_accepted.contract_id,
            self.contract_oustanding_user.contract_id,
            self.contract_accepted_user.contract_id,
        }
        self.assertSetEqual(got, want)

    def test_should_return_contracts_issued_by_user(self):
        # given
        request = self.factory.get(
            reverse("freight:contract_list_data", args={constants.CONTRACT_LIST_USER})
        )
        request.user = self.user_2

        # when
        response = views.contract_list_data(request, constants.CONTRACT_LIST_USER)

        # then
        self.assertEqual(response.status_code, HTTPStatus.OK)
        got = {obj["contract_id"] for obj in json_response_to_python(response)["data"]}
        want = {
            self.contract_oustanding_user.contract_id,
            self.contract_accepted_user.contract_id,
            self.contract_finished_user.contract_id,
            self.contract_failed_user.contract_id,
        }
        self.assertSetEqual(got, want)

    def test_should_not_return_user_contracts_when_user_is_missing_permission(self):
        # given
        user = UserMainFactory(permissions__=["freight.basic_access"])
        ContractFactory(handler=self.handler, user=user)
        request = self.factory.get(
            reverse("freight:contract_list_data", args={constants.CONTRACT_LIST_USER})
        )
        request.user = user

        # when
        response = views.contract_list_data(request, constants.CONTRACT_LIST_USER)

        # then
        self.assertEqual(response.status_code, HTTPStatus.OK)
        got = {obj["contract_id"] for obj in json_response_to_python(response)["data"]}
        self.assertFalse(got)

    def test_data_invalid_category(self):
        request = self.factory.get(
            reverse("freight:contract_list_data", args={"this_is_not_valid"})
        )
        request.user = self.user_1

        with self.assertRaises(ValueError):
            views.contract_list_data(request, "this_is_not_valid")


class TestContractListData_ResponseDetails(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.factory = RequestFactory()
        cls.user = UserMainFactory(
            permissions__=["freight.basic_access", "freight.view_contracts"]
        )
        cls.handler = ContractHandlerFactory(user=cls.user)

    def test_should_return_contract(self):
        # given
        contract = ContractFactory(handler=self.handler, accepted=True)
        request = self.factory.get(
            reverse("freight:contract_list_data", args={constants.CONTRACT_LIST_ALL})
        )
        request.user = self.user

        # when
        response = views.contract_list_data(request, constants.CONTRACT_LIST_ALL)

        # then
        self.assertEqual(response.status_code, HTTPStatus.OK)
        data = json_response_to_python(response)["data"]
        obj = data[0]
        self.assertEqual(obj["contract_id"], contract.contract_id)
        self.assertEqual(obj["status"], "in_progress")


@patch(MODULE_PATH + ".messages", autospec=True)
@patch(MODULE_PATH + ".tasks.run_contracts_sync", autospec=True)
class TestSetupContractHandler(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.factory = RequestFactory()

    def test_can_setup_for_alliance(self, mock_run_contracts_sync, mock_message):
        # given
        user = UserMainFactory(
            permissions__=[
                "freight.basic_access",
                "freight.setup_contract_handler",
            ]
        )
        token = user.token_set.first()
        token.character_id = user.profile.main_character.character_id
        request = self.factory.post(
            reverse("freight:setup_contract_handler"), data={"_token": token.pk}
        )
        request.user = user
        request.token = token

        # when
        with patch(
            MODULE_PATH + ".FREIGHT_OPERATION_MODE", FREIGHT_OPERATION_MODE_MY_ALLIANCE
        ):
            orig_view = views.setup_contract_handler.__wrapped__.__wrapped__.__wrapped__

        # then
        response = orig_view(request, token)
        self.assertEqual(mock_run_contracts_sync.delay.call_count, 1)
        self.assertEqual(response.status_code, HTTPStatus.FOUND)
        self.assertEqual(response.url, reverse("freight:index"))

    @tag("tox_disabled")  # FIXME: Test does not work in tox
    def test_should_return_error_when_user_is_not_in_an_alliance(
        self, mock_run_contracts_sync, mock_message
    ):
        # given
        user = UserMainFactory(
            permissions__=[
                "freight.basic_access",
                "freight.setup_contract_handler",
            ],
            main_character__character=EveCharacterFactory(
                corporation__create_alliance=False
            ),
        )
        token = user.token_set.first()
        token.character_id = user.profile.main_character.character_id
        request = self.factory.post(
            reverse("freight:setup_contract_handler"), data={"_token": token.pk}
        )
        request.user = user
        request.token = token

        # when
        with patch(
            MODULE_PATH + ".FREIGHT_OPERATION_MODE", FREIGHT_OPERATION_MODE_MY_ALLIANCE
        ):
            orig_view = views.setup_contract_handler.__wrapped__.__wrapped__.__wrapped__

        # then
        response = orig_view(request, token)
        self.assertEqual(mock_message.error.call_count, 1)
        self.assertEqual(mock_run_contracts_sync.delay.call_count, 0)
        self.assertEqual(response.status_code, HTTPStatus.FOUND)
        self.assertEqual(response.url, reverse("freight:index"))

    def test_should_show_error_when_existing_handler_has_different_operation_mode(
        self, mock_run_contracts_sync, mock_message
    ):
        # given
        user = UserMainFactory(
            permissions__=[
                "freight.basic_access",
                "freight.setup_contract_handler",
            ]
        )
        ContractHandlerFactory(
            user=user, operation_mode=ContractHandler.Mode.MY_CORPORATION
        )
        token = user.token_set.first()
        token.character_id = user.profile.main_character.character_id
        request = self.factory.post(
            reverse("freight:setup_contract_handler"), data={"_token": token.pk}
        )
        request.user = user
        request.token = token

        # when
        with patch(
            MODULE_PATH + ".FREIGHT_OPERATION_MODE", FREIGHT_OPERATION_MODE_MY_ALLIANCE
        ):
            orig_view = views.setup_contract_handler.__wrapped__.__wrapped__.__wrapped__

        # then
        response = orig_view(request, token)
        self.assertEqual(mock_message.error.call_count, 1)
        self.assertEqual(response.status_code, HTTPStatus.FOUND)
        self.assertEqual(response.url, reverse("freight:index"))
        self.assertEqual(mock_run_contracts_sync.delay.call_count, 0)


class TestStatistics(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _, cls.user = create_contract_handler_w_contracts()
        # expected contracts to load: 149409118, 149409218, 149409318
        cls.user = AuthUtils.add_permission_to_user_by_name(
            "freight.basic_access", cls.user
        )
        cls.user = AuthUtils.add_permission_to_user_by_name(
            "freight.view_statistics", cls.user
        )
        jita = Location.objects.get(id=60003760)
        amamake = Location.objects.get(id=1022167642188)
        cls.pricing = PricingFactory(
            start_location=jita, end_location=amamake, price_base=500000000
        )
        Contract.objects.update_pricing()
        cls.factory = RequestFactory()

    def test_should_open_statistics_page(self):
        # given
        request = self.factory.get(reverse("freight:statistics"))
        request.user = self.user
        # when
        response = views.statistics(request)
        # then
        self.assertEqual(response.status_code, HTTPStatus.OK)

    def test_statistics_routes_data(self):
        request = self.factory.get(reverse("freight:statistics_routes_data"))
        request.user = self.user

        response = views.statistics_routes_data(request)
        self.assertEqual(response.status_code, HTTPStatus.OK)

        data = json_response_to_python(response)["data"]
        self.assertListEqual(
            data,
            [
                {
                    "contracts": 3,
                    "rewards": 300000000,
                    "collaterals": 3000000000,
                    "volume": 345000.0,
                    "pilots": 1,
                    "name": "Jita <-> Amamake",
                    "customers": 1,
                }
            ],
        )

    def test_statistics_pilots_data(self):
        request = self.factory.get(reverse("freight:statistics_pilots_data"))
        request.user = self.user

        response = views.statistics_pilots_data(request)
        self.assertEqual(response.status_code, HTTPStatus.OK)

        data = json_response_to_python(response)["data"]

        self.assertListEqual(
            data,
            [
                {
                    "rewards": 300000000,
                    "collaterals": 3000000000,
                    "volume": 345000.0,
                    "corporation": "Wayne Enterprise",
                    "contracts": 3,
                    "name": "Bruce Wayne",
                }
            ],
        )

    def test_statistics_pilot_corporations_data(self):
        request = self.factory.get(
            reverse("freight:statistics_pilot_corporations_data")
        )
        request.user = self.user

        response = views.statistics_pilot_corporations_data(request)
        self.assertEqual(response.status_code, HTTPStatus.OK)

        data = json_response_to_python(response)["data"]

        self.assertListEqual(
            data,
            [
                {
                    "name": "Wayne Enterprise",
                    "rewards": 300000000,
                    "collaterals": 3000000000,
                    "volume": 345000.0,
                    "alliance": "",
                    "contracts": 3,
                }
            ],
        )

    def test_statistics_customer_data(self):
        request = self.factory.get(reverse("freight:statistics_customer_data"))
        request.user = self.user

        response = views.statistics_customer_data(request)
        self.assertEqual(response.status_code, HTTPStatus.OK)

        data = json_response_to_python(response)["data"]

        self.assertListEqual(
            data,
            [
                {
                    "rewards": 300000000,
                    "collaterals": 3000000000,
                    "volume": 345000.0,
                    "corporation": "Wayne Enterprise",
                    "contracts": 3,
                    "name": "Robin",
                }
            ],
        )
