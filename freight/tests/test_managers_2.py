from app_utils.testing import NoSocketsTestCase

from .testdata.factories_2 import ContractFactory


class TestContractManagerNotifications2(NoSocketsTestCase):
    def test_should_notify_when_there_are_new_contracts(self):
        # given

        contract = ContractFactory()
