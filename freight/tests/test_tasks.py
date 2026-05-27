from unittest.mock import patch

from django.test import override_settings

from app_utils.testing import NoSocketsTestCase

from freight import tasks
from freight.tests.testdata.factories_2 import (
    ContractFactory,
    ContractHandlerFactory,
    LocationStationFactory,
    LocationStructureFactory,
)

MODULE_PATH = "freight.tasks"


class TestUpdateContractsEsi(NoSocketsTestCase):
    def test_exception_when_no_contract_handler(self):
        with self.assertRaises(RuntimeError):
            tasks.update_contracts_esi()

    def test_minimal_run(self):
        ContractHandlerFactory()
        with patch(MODULE_PATH + ".ContractHandler.update_contracts_esi") as m:
            tasks.update_contracts_esi()
            self.assertTrue(m.called)


class TestSendContractNotifications(NoSocketsTestCase):
    def test_normal_run(self):
        with patch(MODULE_PATH + ".Contract.objects.send_notifications") as m:
            tasks.send_contract_notifications()
            self.assertTrue(m.called)


@override_settings(CELERY_ALWAYS_EAGER=True, CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestRunContractsSync(NoSocketsTestCase):
    @patch(MODULE_PATH + ".update_contracts_esi")
    @patch(MODULE_PATH + ".send_contract_notifications")
    def test_normal_run(
        self, mock_send_contract_notifications, mock_update_contracts_esi
    ):
        tasks.run_contracts_sync()
        self.assertTrue(mock_update_contracts_esi.si.called)
        self.assertTrue(mock_send_contract_notifications.si.called)


class TestUpdateContractsPricing(NoSocketsTestCase):
    def test_normal_run(self):
        # given
        ContractFactory()
        # when
        result = tasks.update_contracts_pricing()
        # then
        self.assertEqual(result, 1)


@override_settings(CELERY_ALWAYS_EAGER=True, CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
@patch(MODULE_PATH + ".ContractHandler.token")
@patch(MODULE_PATH + ".Location.objects.update_or_create_esi")
class TestUpdateLocation(NoSocketsTestCase):
    def test_normal_run(self, mock_update_or_create_from_esi, mock_token):
        ContractHandlerFactory()
        LocationStructureFactory(id=1022167642188)
        tasks.update_location(1022167642188)
        self.assertTrue(mock_token.called)
        self.assertTrue(mock_update_or_create_from_esi.called)

    def test_update_locations(self, mock_update_or_create_from_esi, mock_token):
        ContractHandlerFactory()
        LocationStructureFactory(id=1022167642188)
        LocationStationFactory(id=60003760)
        tasks.update_locations([1022167642188, 60003760])
        self.assertEqual(mock_update_or_create_from_esi.call_count, 2)
        call_args_1, call_args_2 = mock_update_or_create_from_esi.call_args_list
        _, kwargs_1 = call_args_1
        _, kwargs_2 = call_args_2
        self.assertEqual(kwargs_1["location_id"], 1022167642188)
        self.assertEqual(kwargs_2["location_id"], 60003760)
