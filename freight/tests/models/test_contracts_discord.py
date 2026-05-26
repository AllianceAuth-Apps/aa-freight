import datetime as dt
from typing import NamedTuple
from unittest.mock import MagicMock, patch

from django.utils.timezone import now

from app_utils.django import app_labels
from app_utils.testing import NoSocketsTestCase

if "discord" in app_labels():
    from allianceauth.services.modules.discord.models import DiscordUser

    from freight.models import Contract
    from freight.tests.models.test_contracts import MODULE_PATH
    from freight.tests.testdata.factories_2 import (
        ContractFactory,
        ContractHandlerFactory,
        DiscordUserFactory,
        UserMainDefaultFactory,
    )

else:
    DiscordUser = None

try:
    from discordproxy.client import DiscordClient
    from discordproxy.exceptions import to_discord_proxy_exception
    from discordproxy.tests.factories import create_rpc_error

except ImportError:
    DiscordClient = None

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
