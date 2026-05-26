import datetime as dt
from unittest.mock import patch

from dhooks_lite import Embed

from django.utils.timezone import now

from app_utils.testing import NoSocketsTestCase

from freight.models import Contract
from freight.tests.testdata.factories_2 import (
    ContractCustomerNotificationFactory,
    ContractFactory,
    LocationStationFactory,
)

MODULE_PATH = "freight.models.contracts"
PATCH_FREIGHT_OPERATION_MODE = MODULE_PATH + ".FREIGHT_OPERATION_MODE"


class TestContract(NoSocketsTestCase):
    def test_str(self):
        contract = ContractFactory(
            contract_id=42,
            start_location=LocationStationFactory(name="Jita"),
            end_location=LocationStationFactory(name="Amamake"),
        )
        got = str(contract)
        want = "42: Jita -> Amamake"
        self.assertEqual(got, want)

    def test_get_issues_list(self):
        contract: Contract = ContractFactory.build(issues='["one", "two"]')
        self.assertListEqual(contract.get_issue_list(), ["one", "two"])


class TestContract_DateLatest(NoSocketsTestCase):
    def test_should_return_date_issues_for_new_contract(self):
        date_issued = now()
        contract = ContractFactory(
            date_issued=date_issued,
        )
        got = contract.date_latest
        self.assertEqual(got, date_issued)

    def test_should_return_date_accepted_when_accepted(self):
        date_accepted = now() - dt.timedelta(hours=1)
        contract = ContractFactory(accepted=True, date_accepted=date_accepted)
        got = contract.date_latest
        self.assertEqual(got, date_accepted)

    def test_should_return_date_completed_when_completed(self):
        date_completed = now() - dt.timedelta(hours=1)
        contract = ContractFactory(
            finished=True,
            date_completed=date_completed,
        )
        got = contract.date_latest
        self.assertEqual(got, date_completed)


class TestContract_IsStale(NoSocketsTestCase):
    def test_should_return_stale(self):
        hours = 12
        contract = ContractFactory(
            date_issued=now() - dt.timedelta(hours=hours, seconds=1),
        )
        with patch(MODULE_PATH + ".FREIGHT_HOURS_UNTIL_STALE_STATUS", hours):
            self.assertTrue(contract.has_stale_status)

    def test_should_return_not_stale(self):
        hours = 12
        contract = ContractFactory(
            date_issued=now() - dt.timedelta(hours=1),
        )
        with patch(MODULE_PATH + ".FREIGHT_HOURS_UNTIL_STALE_STATUS", hours):
            self.assertFalse(contract.has_stale_status)


class TestContract_AcceptorName(NoSocketsTestCase):
    def test_outstanding_contract(self):
        contract = ContractFactory()
        self.assertIsNone(contract.acceptor_name)

    def test_accepted_contract(self):
        contract = ContractFactory(accepted=True)
        self.assertTrue(contract.acceptor_name)


class TestContract_GenerateEmbed(NoSocketsTestCase):
    def test_generate_embed_w_pricing(self):
        contract = ContractFactory(create_pricing=True)
        x = contract._generate_embed()
        self.assertIsInstance(x, Embed)
        self.assertEqual(x.color, Contract.EMBED_COLOR_PASSED)

    def test_generate_embed_w_pricing_issues(self):
        contract = ContractFactory(create_pricing=True, issues='["we have issues"]')
        x = contract._generate_embed()
        self.assertIsInstance(x, Embed)
        self.assertEqual(x.color, Contract.EMBED_COLOR_FAILED)

    def test_generate_embed_wo_pricing(self):
        contract = ContractFactory(create_pricing=False)
        contract.pricing = None
        x = contract._generate_embed()
        self.assertIsInstance(x, Embed)


@patch(MODULE_PATH + ".dhooks_lite.Webhook.execute", spec=True)
class TestContractSendPilotNotification(NoSocketsTestCase):
    @patch(MODULE_PATH + ".FREIGHT_DISCORD_WEBHOOK_URL", None)
    def test_aborts_without_webhook_url(self, mock_webhook_execute):
        # given
        mock_webhook_execute.return_value.status_ok = True
        contract = ContractFactory()

        # when
        contract.send_pilot_notification()

        # then
        self.assertEqual(mock_webhook_execute.call_count, 0)

    @patch(MODULE_PATH + ".FREIGHT_DISCORD_WEBHOOK_URL", "url")
    @patch(MODULE_PATH + ".FREIGHT_DISCORD_DISABLE_BRANDING", False)
    @patch(MODULE_PATH + ".FREIGHT_DISCORD_MENTIONS", None)
    def test_with_branding_and_wo_mentions(self, mock_webhook_execute):
        # given
        mock_webhook_execute.return_value.status_ok = True
        contract = ContractFactory()

        # when
        contract.send_pilot_notification()

        # then
        self.assertEqual(mock_webhook_execute.call_count, 1)

    @patch(MODULE_PATH + ".FREIGHT_DISCORD_WEBHOOK_URL", "url")
    @patch(MODULE_PATH + ".FREIGHT_DISCORD_DISABLE_BRANDING", True)
    @patch(MODULE_PATH + ".FREIGHT_DISCORD_MENTIONS", None)
    def test_wo_branding_and_wo_mentions(self, mock_webhook_execute):
        # given
        mock_webhook_execute.return_value.status_ok = True
        contract = ContractFactory()

        # when
        contract.send_pilot_notification()

        # then
        self.assertEqual(mock_webhook_execute.call_count, 1)

    @patch(MODULE_PATH + ".FREIGHT_DISCORD_WEBHOOK_URL", "url")
    @patch(MODULE_PATH + ".FREIGHT_DISCORD_DISABLE_BRANDING", True)
    @patch(MODULE_PATH + ".FREIGHT_DISCORD_MENTIONS", "@here")
    def test_with_branding_and_with_mentions(self, mock_webhook_execute):
        # given
        mock_webhook_execute.return_value.status_ok = True
        contract = ContractFactory()

        # when
        contract.send_pilot_notification()

        # then
        self.assertEqual(mock_webhook_execute.call_count, 1)

    @patch(MODULE_PATH + ".FREIGHT_DISCORD_WEBHOOK_URL", "url")
    @patch(MODULE_PATH + ".FREIGHT_DISCORD_DISABLE_BRANDING", True)
    @patch(MODULE_PATH + ".FREIGHT_DISCORD_MENTIONS", True)
    def test_wo_branding_and_with_mentions(self, mock_webhook_execute):
        # given
        mock_webhook_execute.return_value.status_ok = True
        contract = ContractFactory()

        # when
        contract.send_pilot_notification()

        # then
        self.assertEqual(mock_webhook_execute.call_count, 1)

    @patch(MODULE_PATH + ".FREIGHT_DISCORD_WEBHOOK_URL", "url")
    def test_log_error_from_execute(self, mock_webhook_execute):
        # given
        mock_webhook_execute.return_value.status_ok = False
        mock_webhook_execute.return_value.status_code = 404
        contract = ContractFactory()

        # when
        contract.send_pilot_notification()

        # then
        self.assertEqual(mock_webhook_execute.call_count, 1)


class TestContractCustomerNotification(NoSocketsTestCase):
    def test_str(self):
        contract = ContractFactory(create_pricing=True, accepted=True)
        notif = ContractCustomerNotificationFactory(contract=contract)
        expected = f"{contract.contract_id} - in_progress"
        self.assertEqual(str(notif), expected)
