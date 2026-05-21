import datetime as dt
from typing import Generic, TypeVar

import factory
import factory.fuzzy

from django.utils import timezone

from app_utils.testdata_factories import (
    EveCharacterFactory,
    EveCorporationInfoFactory,
    UserMainFactory,
)

from freight.models import Contract, ContractHandler, EveEntity, Location, Pricing
from freight.models.routes import post_save

T = TypeVar("T")


class BaseMetaFactory(Generic[T], factory.base.FactoryMetaClass):
    def __call__(cls, *args, **kwargs) -> T:
        return super().__call__(*args, **kwargs)


class EveEntityAllianceFactory(
    factory.django.DjangoModelFactory, metaclass=BaseMetaFactory[EveEntity]
):
    class Meta:
        model = EveEntity

    id = factory.Sequence(lambda n: 99_900_001 + n)
    name = factory.LazyAttribute(lambda o: f"alliance_{o.id}")
    category = EveEntity.CATEGORY_ALLIANCE


class EveEntityCharacterFactory(
    factory.django.DjangoModelFactory, metaclass=BaseMetaFactory[EveEntity]
):
    class Meta:
        model = EveEntity

    id = factory.Sequence(lambda n: 90_900_001 + n)
    category = EveEntity.CATEGORY_CHARACTER
    name = factory.LazyAttribute(lambda o: f"character_{o.id}")


class EveEntityCorporationFactory(
    factory.django.DjangoModelFactory, metaclass=BaseMetaFactory[EveEntity]
):
    class Meta:
        model = EveEntity

    id = factory.Sequence(lambda n: 98_900_001 + n)
    name = factory.LazyAttribute(lambda o: f"corporation_{o.id}")
    category = EveEntity.CATEGORY_CORPORATION


class LocationFactory(
    factory.django.DjangoModelFactory, metaclass=BaseMetaFactory[Location]
):
    class Meta:
        model = Location

    id = factory.Sequence(lambda n: 60_900_000 + n)
    category_id = Location.Category.STATION_ID
    name = factory.faker.Faker("city")


class UserMainDefaultFactory(UserMainFactory):
    main_character__scopes = [
        "esi-universe.read_structures.v1",
        "esi-contracts.read_corporation_contracts.v1",
        "esi-universe.read_structures.v1",
    ]
    permissions__ = [
        "freight.basic_access",
        "freight.use_calculator",
    ]


class UserMainManagerFactory(UserMainDefaultFactory):
    main_character__scopes = [
        "esi-universe.read_structures.v1",
        "esi-contracts.read_corporation_contracts.v1",
        "esi-universe.read_structures.v1",
    ]
    permissions__ = [
        "freight.basic_access",
        # "freight.add_location",
        "freight.setup_contract_handler",
        "freight.use_calculator",
        "freight.view_contracts",
        "freight.view_statistics",
    ]


class ContractHandlerFactory(
    factory.django.DjangoModelFactory, metaclass=BaseMetaFactory[ContractHandler]
):
    class Meta:
        model = ContractHandler

    organization = factory.SubFactory(EveEntityAllianceFactory)


class ContractFactory(
    factory.django.DjangoModelFactory, metaclass=BaseMetaFactory[Contract]
):
    class Meta:
        model = Contract

    contract_id = factory.Sequence(lambda n: 10_000_000 + n)
    collateral = factory.fuzzy.FuzzyFloat(100_000_000, 1_000_000_000)
    days_to_complete = 3
    date_completed = None
    date_issued = factory.fuzzy.FuzzyDateTime(
        timezone.now() - dt.timedelta(days=7), timezone.now() - dt.timedelta(hours=12)
    )
    date_expired = factory.LazyAttribute(
        lambda o: o.date_issued + dt.timedelta(days=o.days_to_complete)
    )
    end_location = factory.SubFactory(LocationFactory)
    for_corporation = False
    handler = factory.SubFactory(ContractHandlerFactory)
    issuer = factory.SubFactory(EveCharacterFactory)
    reward = factory.fuzzy.FuzzyFloat(50_000_000, 100_000_000)
    status = Contract.Status.OUTSTANDING
    start_location = factory.SubFactory(LocationFactory)
    title = factory.faker.Faker("sentence")
    volume = factory.fuzzy.FuzzyInteger(1_000, 100_000_000)

    @factory.lazy_attribute
    def issuer_corporation(self):
        return EveCorporationInfoFactory(corporation_id=self.issuer.corporation_id)

    class Params:
        accepted = factory.Trait(
            status=Contract.Status.IN_PROGRESS,
            date_accepted=factory.LazyAttribute(
                lambda o: o.date_issued + dt.timedelta(hours=3)
            ),
            acceptor=factory.SubFactory(EveCharacterFactory),
            acceptor_corporation=factory.LazyAttribute(
                lambda o: EveCorporationInfoFactory(
                    corporation_id=o.acceptor.corporation_id
                )
            ),
        )
        completed = factory.Trait(
            status=Contract.Status.FINISHED,
            date_accepted=factory.LazyAttribute(
                lambda o: o.date_issued + dt.timedelta(hours=3)
            ),
            date_completed=factory.LazyAttribute(
                lambda o: o.date_issued + dt.timedelta(hours=6)
            ),
            acceptor=factory.SubFactory(EveCharacterFactory),
            acceptor_corporation=factory.LazyAttribute(
                lambda o: EveCorporationInfoFactory(
                    corporation_id=o.acceptor.corporation_id
                )
            ),
        )


@factory.django.mute_signals(post_save)
class PricingFactory(
    factory.django.DjangoModelFactory, metaclass=BaseMetaFactory[Pricing]
):
    class Meta:
        model = Pricing

    start_location = factory.SubFactory(LocationFactory)
    end_location = factory.SubFactory(LocationFactory)

    @factory.post_generation
    def update_contracts(self: Pricing, create, extracted, **kwargs):
        if not create or extracted is False:
            return

        from freight.tasks import update_contracts_pricing

        update_contracts_pricing()
