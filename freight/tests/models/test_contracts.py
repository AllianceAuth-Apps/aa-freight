import datetime as dt
from typing import NamedTuple
from unittest.mock import MagicMock, patch

from dhooks_lite import Embed

from django.utils.timezone import now

from app_utils.django import app_labels
from app_utils.testing import NoSocketsTestCase

from freight.models import Contract
from freight.tests.testdata.factories_2 import (
    ContractCustomerNotificationFactory,
    ContractFactory,
    ContractHandlerFactory,
    DiscordUserFactory,
    LocationStationFactory,
    UserMainDefaultFactory,
)

if "discord" in app_labels():
    from allianceauth.services.modules.discord.models import DiscordUser
else:
    DiscordUser = None

try:
    from discordproxy.client import DiscordClient
    from discordproxy.exceptions import to_discord_proxy_exception
    from discordproxy.tests.factories import create_rpc_error

except ImportError:
    DiscordClient = None


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


class TestContract_GetIssueList(NoSocketsTestCase):
    def test_get_issues_list(self):
        contract: Contract = ContractFactory.build(issues='["one", "two"]')
        self.assertListEqual(contract.get_issue_list(), ["one", "two"])

    # FIXME: Disabled test
    # def test_hours_issued_2_completed(self):
    #     self.contract.date_completed = self.contract.date_issued + dt.timedelta(hours=9)
    #     self.assertEqual(self.contract.hours_issued_2_completed, 9)
    #     self.contract.date_completed = None
    #     self.assertIsNone(self.contract.hours_issued_2_completed)


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


if DiscordUser:

    @patch(MODULE_PATH + ".FREIGHT_DISCORDPROXY_ENABLED", False)
    @patch(MODULE_PATH + ".dhooks_lite.Webhook.execute", spec=True)
    class TestContract_SendCustomerNotification_WebHook(NoSocketsTestCase):
        @classmethod
        def setUpClass(cls):
            super().setUpClass()
            cls.user = UserMainDefaultFactory()
            DiscordUserFactory(user=cls.user)
            cls.handler = ContractHandlerFactory(user=cls.user)

        @patch(MODULE_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", "url")
        def test_can_send_per_contract_status(self, mock_webhook_execute: MagicMock):
            # given
            mock_webhook_execute.return_value.status_ok = True

            class Case(NamedTuple):
                name: str
                params: dict
                want: Contract.Status

            cases = [
                Case("outstanding", {}, Contract.Status.OUTSTANDING),
                Case("in progress", {"accepted": True}, Contract.Status.IN_PROGRESS),
                Case("finished", {"finished": True}, Contract.Status.FINISHED),
                Case("failed", {"failed": True}, Contract.Status.FAILED),
            ]

            for tc in cases:
                with self.subTest(name=tc.name):
                    # when
                    contract = ContractFactory(
                        handler=self.handler,
                        user=self.user,
                        create_pricing=True,
                        **tc.params,
                    )
                    contract.send_customer_notification()

                    # then
                    self.assertEqual(mock_webhook_execute.call_count, 1)
                    obj: Contract
                    obj = contract.customer_notifications.get(status=tc.want)
                    self.assertAlmostEqual(
                        obj.date_notified, now(), delta=dt.timedelta(seconds=30)
                    )
                    mock_webhook_execute.reset_mock()

        @patch(MODULE_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", None)
        def test_aborts_without_webhook_url(self, mock_webhook_execute):
            # given
            mock_webhook_execute.return_value.status_ok = True
            contract = ContractFactory(
                handler=self.handler, user=self.user, create_pricing=True
            )

            # when
            contract.send_customer_notification()

            # then
            self.assertEqual(mock_webhook_execute.call_count, 0)

        @patch(MODULE_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", "url")
        @patch(MODULE_PATH + ".DiscordUser", None)
        def test_aborts_without_discord(self, mock_webhook_execute):
            # given
            mock_webhook_execute.return_value.status_ok = True
            contract = ContractFactory(
                handler=self.handler, user=self.user, create_pricing=True
            )

            # when
            contract.send_customer_notification()

            # then
            self.assertEqual(mock_webhook_execute.call_count, 0)

        @patch(MODULE_PATH + ".FREIGHT_DISCORD_DISABLE_BRANDING", True)
        @patch(MODULE_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", "url")
        def test_can_send_wo_branding(self, mock_webhook_execute):
            # given
            mock_webhook_execute.return_value.status_ok = True
            contract = ContractFactory(
                handler=self.handler, user=self.user, create_pricing=True
            )

            # when
            contract.send_customer_notification()

            # then
            self.assertEqual(mock_webhook_execute.call_count, 1)

        @patch(MODULE_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", "url")
        def test_log_error_from_execute(self, mock_webhook_execute):
            # given
            mock_webhook_execute.return_value.status_ok = False
            mock_webhook_execute.return_value.status_code = 404
            contract = ContractFactory(
                handler=self.handler, user=self.user, create_pricing=True
            )

            # when
            contract.send_customer_notification()

            # then
            self.assertEqual(mock_webhook_execute.call_count, 1)

        @patch(MODULE_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", "url")
        def test_aborts_without_Discord_user(self, mock_webhook_execute):
            # given
            mock_webhook_execute.return_value.status_ok = True
            contract = ContractFactory(create_pricing=True)

            # when
            contract.send_customer_notification()

            # then
            self.assertEqual(mock_webhook_execute.call_count, 0)


if DiscordUser and DiscordClient:

    @patch(MODULE_PATH + ".FREIGHT_DISCORDPROXY_ENABLED", True)
    @patch(MODULE_PATH + ".DiscordClient", spec=True)
    @patch(MODULE_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", None)
    class TestContract_SendCustomerNotification_DiscordProxy(NoSocketsTestCase):
        @classmethod
        def setUpClass(cls):
            super().setUpClass()
            cls.user = UserMainDefaultFactory()
            DiscordUserFactory(user=cls.user)
            cls.handler = ContractHandlerFactory(user=cls.user)

        def test_can_send_status_via_grpc(self, mock_DiscordClient):
            # given
            contract = ContractFactory(
                handler=self.handler, user=self.user, create_pricing=True
            )

            # when
            contract.send_customer_notification()

            # then
            self.assertTrue(
                mock_DiscordClient.return_value.create_direct_message.called
            )
            obj: Contract
            obj = contract.customer_notifications.get(
                status=Contract.Status.OUTSTANDING
            )
            self.assertAlmostEqual(
                obj.date_notified, now(), delta=dt.timedelta(seconds=30)
            )

        def test_can_handle_grpc_error(self, mock_DiscordClient):
            # given
            my_exception = to_discord_proxy_exception(create_rpc_error())
            my_exception.details = lambda: "{}"
            mock_DiscordClient.return_value.create_direct_message.side_effect = (
                my_exception
            )
            contract = ContractFactory(
                handler=self.handler, user=self.user, create_pricing=True
            )

            # when
            contract.send_customer_notification()

            # then
            self.assertTrue(
                mock_DiscordClient.return_value.create_direct_message.called
            )

        @patch(MODULE_PATH + ".DISCORDPROXY_HOST", "1.2.3.4")
        @patch(MODULE_PATH + ".DISCORDPROXY_PORT", 56789)
        def test_can_use_custom_config_for_discordproxy(self, mock_DiscordClient):
            contract = ContractFactory(
                handler=self.handler, user=self.user, create_pricing=True
            )

            # when
            contract.send_customer_notification()

            # then
            self.assertTrue(
                mock_DiscordClient.return_value.create_direct_message.called
            )
            _, kwargs = mock_DiscordClient.call_args
            self.assertEqual(kwargs["target"], "1.2.3.4:56789")
