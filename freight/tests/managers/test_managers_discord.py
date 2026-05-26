import datetime as dt
from unittest.mock import MagicMock, patch

from django.utils.timezone import now

from app_utils.django import app_labels
from app_utils.testing import NoSocketsTestCase

if "discord" in app_labels():

    from freight.models import Contract
    from freight.tests.managers.test_managers import MANAGERS_PATH, MODELS_PATH
    from freight.tests.testdata.factories_2 import (
        ContractFactory,
        DiscordUserFactory,
        UserMainDefaultFactory,
    )

    # TODO: Try to consolidate URL mocks to one module

    @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", None)
    @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", None)
    @patch(MODELS_PATH + ".contracts.FREIGHT_HOURS_UNTIL_STALE_STATUS", 48)
    @patch(MODELS_PATH + ".contracts.dhooks_lite.Webhook.execute", autospec=True)
    @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORDPROXY_ENABLED", False)
    class TestContractManager_SendNotifications_Pilot(NoSocketsTestCase):
        @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_WEBHOOK_URL", "url")
        @patch(MANAGERS_PATH + ".FREIGHT_NOTIFY_ALL_CONTRACTS", False)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_WEBHOOK_URL", "url")
        def test_should_send_pilot_notifications_for_matching_contracts_only(
            self, mock_webhook_execute: MagicMock
        ):
            ContractFactory(create_pricing=True)
            ContractFactory()
            Contract.objects.send_notifications(rate_limited=False)
            self.assertEqual(mock_webhook_execute.call_count, 1)

        @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_WEBHOOK_URL", "url")
        @patch(MANAGERS_PATH + ".FREIGHT_NOTIFY_ALL_CONTRACTS", True)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_WEBHOOK_URL", "url")
        def test_should_send_pilot_notification_for_any_contracts_when_requested(
            self, mock_webhook_execute: MagicMock
        ):
            ContractFactory(create_pricing=True)
            ContractFactory()
            Contract.objects.send_notifications(rate_limited=False)
            self.assertEqual(mock_webhook_execute.call_count, 2)

        @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_WEBHOOK_URL", "url")
        @patch(MANAGERS_PATH + ".FREIGHT_NOTIFY_ALL_CONTRACTS", False)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_WEBHOOK_URL", "url")
        def test_should_not_send_pilot_notifications_for_expired_contracts(
            self, mock_webhook_execute: MagicMock
        ):
            ContractFactory(date_expired=now() - dt.timedelta(seconds=1))
            Contract.objects.send_notifications(rate_limited=False)
            self.assertEqual(mock_webhook_execute.call_count, 0)

        @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_WEBHOOK_URL", "url")
        @patch(MANAGERS_PATH + ".FREIGHT_NOTIFY_ALL_CONTRACTS", False)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_WEBHOOK_URL", "url")
        def test_should_send_pilot_notifications_once_only(
            self, mock_webhook_execute: MagicMock
        ):
            ContractFactory(create_pricing=True)

            # round #1
            Contract.objects.send_notifications(rate_limited=False)
            self.assertEqual(mock_webhook_execute.call_count, 1)

            # round #2
            mock_webhook_execute.reset_mock()
            Contract.objects.send_notifications(rate_limited=False)
            self.assertEqual(mock_webhook_execute.call_count, 0)

        @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_WEBHOOK_URL", None)
        @patch(MANAGERS_PATH + ".FREIGHT_NOTIFY_ALL_CONTRACTS", False)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_WEBHOOK_URL", None)
        def test_should_not_send_any_notifications_when_no_url_set(
            self, mock_webhook_execute: MagicMock
        ):
            ContractFactory(create_pricing=True)
            Contract.objects.send_notifications(rate_limited=False)
            self.assertEqual(mock_webhook_execute.call_count, 0)

    @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_WEBHOOK_URL", None)
    @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_WEBHOOK_URL", None)
    @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORDPROXY_ENABLED", False)
    @patch(MODELS_PATH + ".contracts.FREIGHT_HOURS_UNTIL_STALE_STATUS", 48)
    @patch(MODELS_PATH + ".contracts.dhooks_lite.Webhook.execute", autospec=True)
    class TestContractManager_SendNotifications_Customer(NoSocketsTestCase):
        @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", "url")
        @patch(MANAGERS_PATH + ".FREIGHT_NOTIFY_ALL_CONTRACTS", False)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", "url")
        def test_should_send_customer_notification_for_valid_contracts(
            self, mock_webhook_execute: MagicMock
        ):
            # given
            user = UserMainDefaultFactory()
            DiscordUserFactory(user=user)
            ContractFactory(user=user, accepted=True, create_pricing=True)
            ContractFactory(user=user, accepted=True, create_pricing=False)  # ignore

            # when
            Contract.objects.send_notifications(rate_limited=False)

            # then
            self.assertEqual(mock_webhook_execute.call_count, 1)

        @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", "url")
        @patch(MANAGERS_PATH + ".FREIGHT_NOTIFY_ALL_CONTRACTS", False)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", "url")
        def test_should_not_send_customer_notifications_for_expired_contracts(
            self, mock_webhook_execute: MagicMock
        ):
            # given
            user = UserMainDefaultFactory()
            DiscordUserFactory(user=user)
            ContractFactory(
                user=user,
                accepted=True,
                create_pricing=True,
                date_expired=now() - dt.timedelta(hours=1),
            )

            # when
            Contract.objects.send_notifications(rate_limited=False)

            # then
            self.assertEqual(mock_webhook_execute.call_count, 0)

        @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", "url")
        @patch(MANAGERS_PATH + ".FREIGHT_NOTIFY_ALL_CONTRACTS", False)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", "url")
        def test_should_send_customer_notifications_only_once_per_state(
            self, mock_webhook_execute: MagicMock
        ):
            # given
            user = UserMainDefaultFactory()
            DiscordUserFactory(user=user)
            ContractFactory(user=user, accepted=True, create_pricing=True)

            # round #1
            Contract.objects.send_notifications(rate_limited=False)
            self.assertEqual(mock_webhook_execute.call_count, 1)

            # round #2
            mock_webhook_execute.reset_mock()
            Contract.objects.send_notifications(rate_limited=False)
            self.assertEqual(mock_webhook_execute.call_count, 0)

        @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", "url")
        @patch(MANAGERS_PATH + ".FREIGHT_NOTIFY_ALL_CONTRACTS", True)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", "url")
        def test_should_send_customer_notification_for_any_contract_when_requested(
            self, mock_webhook_execute: MagicMock
        ):
            # given
            user = UserMainDefaultFactory()
            DiscordUserFactory(user=user)
            ContractFactory(user=user, accepted=True, create_pricing=False)

            # when
            Contract.objects.send_notifications(rate_limited=False)

            # then
            self.assertEqual(mock_webhook_execute.call_count, 1)

        @patch(MANAGERS_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", None)
        @patch(MANAGERS_PATH + ".FREIGHT_NOTIFY_ALL_CONTRACTS", False)
        @patch(MODELS_PATH + ".contracts.FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", None)
        def test_should_not_send_notification_when_url_not_configured(
            self, mock_webhook_execute: MagicMock
        ):
            # given
            user = UserMainDefaultFactory()
            DiscordUserFactory(user=user)
            ContractFactory(user=user, accepted=True, create_pricing=True)

            # when
            Contract.objects.send_notifications(rate_limited=False)

            # then
            self.assertEqual(mock_webhook_execute.call_count, 0)
