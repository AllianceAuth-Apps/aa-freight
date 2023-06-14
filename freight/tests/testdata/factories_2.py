import datetime as dt

import factory
import factory.fuzzy

from django.utils import timezone
from eveuniverse.tests.testdata.factories import create_eve_entity

from allianceauth.eveonline.models import EveCorporationInfo
from app_utils.testdata_factories import UserMainFactory

from freight.models import Contract, ContractHandler


class DefaultUserMainFactory(UserMainFactory):
    ...


class ContractHandlerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ContractHandler

    organization = factory.LazyAttribute(lambda o: create_eve_entity())


class ContractFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Contract

    collateral = factory.fuzzy.FuzzyFloat(100_000_000, 1_000_000_000)
    days_to_complete = 3
    date_issued = factory.fuzzy.FuzzyDateTime(timezone.now() - dt.timedelta(days=7))
    date_expired = factory.LazyAttribute(
        lambda o: o.date_issued + dt.timedelta(days=o.days_to_complete)
    )
    for_corporation = False
    issuer_corporation = factory.LazyAttribute(
        lambda o: EveCorporationInfo.objects.get(corporation_id=o.issuer.corporation_id)
    )
    reward = factory.fuzzy.FuzzyFloat(50_000_000, 100_000_000)
    status = factory.fuzzy.FuzzyChoice(
        [
            Contract.Status.OUTSTANDING,
            Contract.Status.OUTSTANDING,
            Contract.Status.IN_PROGRESS,
            Contract.Status.FINISHED,
            Contract.Status.FINISHED,
            Contract.Status.FINISHED,
            Contract.Status.FINISHED,
        ]
    )
    title = factory.faker.Faker("sentence")
    volume = factory.fuzzy.FuzzyInteger(1_000, 100_000_000)

    @factory.lazy_attribute
    def contract_id(self):
        contract_ids = Contract.objects.values_list("contract_id", flat=True)
        fuzzer = factory.fuzzy.FuzzyInteger(10_000_000, 99_000_000)
        new_contract_id = fuzzer.fuzz()
        while True:
            if new_contract_id not in contract_ids:
                return new_contract_id

    @factory.lazy_attribute
    def date_accepted(self):
        if self.status == Contract.Status.OUTSTANDING or not self.acceptor:
            return None
        return factory.fuzzy.FuzzyDateTime(
            start_dt=self.date_issued,
            end_dt=min(self.date_issued + dt.timedelta(days=2), timezone.now()),
        ).fuzz()

    @factory.lazy_attribute
    def date_completed(self):
        if (
            self.status in {Contract.Status.OUTSTANDING, Contract.Status.IN_PROGRESS}
            or not self.acceptor
        ):
            return None
        return factory.fuzzy.FuzzyDateTime(
            start_dt=self.date_accepted,
            end_dt=min(
                self.date_accepted + dt.timedelta(days=self.days_to_complete),
                timezone.now(),
            ),
        ).fuzz()

    @factory.lazy_attribute
    def acceptor_corporation(self):
        if not self.acceptor:
            return None
        return EveCorporationInfo.objects.get(
            corporation_id=self.acceptor.corporation_id
        )

    @classmethod
    def _adjust_kwargs(cls, **kwargs):
        if kwargs["status"] == Contract.Status.OUTSTANDING:
            kwargs["acceptor"] = None
            kwargs["acceptor_corporation"] = None
        return kwargs
