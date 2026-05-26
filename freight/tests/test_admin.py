from http import HTTPStatus
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.test import TestCase

from app_utils.testdata_factories import UserFactory

from freight.admin import ContractAdmin
from freight.models import Contract
from freight.tests.testdata.factories_2 import (
    ContractFactory,
    ContractHandlerFactory,
    PricingFactory,
)

MODULE_PATH = "freight.admin"


class MockRequest(object):
    def __init__(self, user=None):
        self.user = user


class TestContractAdmin(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.modeladmin = ContractAdmin(model=Contract, admin_site=AdminSite())
        cls.user = UserFactory(is_superuser=True, is_staff=True)
        cls.handler = ContractHandlerFactory()

    @patch(MODULE_PATH + ".ContractAdmin.message_user", spec=True)
    @patch(MODULE_PATH + ".Contract.send_pilot_notification")
    def test_should_send_pilots_notification(
        self, mock_send_pilot_notification, mock_message_user
    ):
        # given
        ContractFactory(handler=self.handler)
        obj_qs = Contract.objects.all()
        # when
        self.modeladmin.send_pilots_notification(MockRequest(self.user), obj_qs)
        # then
        self.assertEqual(mock_send_pilot_notification.call_count, 1)
        self.assertTrue(mock_message_user.called)

    @patch(MODULE_PATH + ".ContractAdmin.message_user", spec=True)
    @patch(MODULE_PATH + ".Contract.send_customer_notification")
    def test_should_send_customer_notification(
        self, mock_send_customer_notification, mock_message_user
    ):
        # given
        ContractFactory(handler=self.handler)
        obj_qs = Contract.objects.all()
        # when
        self.modeladmin.send_customer_notification(MockRequest(self.user), obj_qs)
        # then
        self.assertEqual(mock_send_customer_notification.call_count, 1)
        self.assertTrue(mock_message_user.called)

    def test_should_open_list(self):
        # given
        ContractFactory(handler=self.handler)
        self.client.force_login(self.user)
        # when
        response = self.client.get("/admin/freight/contract/")
        # then
        self.assertEqual(response.status_code, HTTPStatus.OK)


class TestPricingAdmin(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = UserFactory(is_superuser=True, is_staff=True)
        PricingFactory()

    def test_should_open_list(self):
        # given
        PricingFactory()
        self.client.force_login(self.user)
        # when
        response = self.client.get("/admin/freight/pricing/")
        # then
        self.assertEqual(response.status_code, HTTPStatus.OK)
