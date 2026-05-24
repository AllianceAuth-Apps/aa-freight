import datetime as dt
import urllib.parse
from typing import Generic, TypeVar

import factory
import factory.fuzzy

from django.utils.timezone import now
from esi.tests.factories_2 import ScopeFactory
from esi.tests.factories_2 import TokenFactory as _TokenFactory

from app_utils.django import app_labels
from app_utils.testdata_factories import (
    EveCharacterFactory,
    EveCorporationInfoFactory,
    UserMainFactory,
)

from freight.models import Contract, ContractHandler, EveEntity, Location, Pricing
from freight.models.routes import post_save

if "discord" in app_labels():
    from allianceauth.services.modules.discord.models import DiscordUser
else:
    DiscordUser = None  # pylint: disable=invalid-name

T = TypeVar("T")
_BASE_URL = "https://esi.evetech.net/"
_POSITION_MIN = -100_000_000_000_000_000
_POSITION_MAX = 100_000_000_000_000_000


def make_esi_url(path: str) -> str:
    if path.startswith("/"):
        raise ValueError("path can not start with a slash")
    if path.endswith("/"):
        raise ValueError("path can not end with a slash")

    url = urllib.parse.urljoin(_BASE_URL, "/latest/" + path + "/")
    return url


class BaseMetaFactory(Generic[T], factory.base.FactoryMetaClass):
    def __call__(cls, *args, **kwargs) -> T:
        return super().__call__(*args, **kwargs)


class PositionFactory(factory.DictFactory, metaclass=BaseMetaFactory[dict]):
    x = factory.fuzzy.FuzzyFloat(_POSITION_MIN, _POSITION_MAX)
    y = factory.fuzzy.FuzzyFloat(_POSITION_MIN, _POSITION_MAX)
    z = factory.fuzzy.FuzzyFloat(_POSITION_MIN, _POSITION_MAX)


class TokenFactory2(_TokenFactory):
    """Token factory that does not trigger the character ownership update
    in Alliance Auth.
    """

    @classmethod
    def _generate(cls, strategy, params):
        with factory.django.mute_signals(post_save):
            return super()._generate(strategy, params)

    @factory.post_generation
    def scopes(self, create, extracted, **kwargs):
        if not create or not extracted:
            return

        for name in extracted:
            self.scopes.add(ScopeFactory(name=name))


class _EveEntityFactory(
    factory.django.DjangoModelFactory, metaclass=BaseMetaFactory[EveEntity]
):
    class Meta:
        model = EveEntity
        django_get_or_create = ("id",)

    name = factory.LazyAttribute(lambda o: f"{o.category.title()} #{o.id}")


class EveEntityAllianceFactory(_EveEntityFactory):
    id = factory.Sequence(lambda n: 99_900_001 + n)
    category = EveEntity.CATEGORY_ALLIANCE


class EveEntityCharacterFactory(_EveEntityFactory):
    id = factory.Sequence(lambda n: 90_900_001 + n)
    category = EveEntity.CATEGORY_CHARACTER


class EveEntityCorporationFactory(_EveEntityFactory):
    id = factory.Sequence(lambda n: 98_900_001 + n)
    category = EveEntity.CATEGORY_CORPORATION


class LocationStationFactory(
    factory.django.DjangoModelFactory, metaclass=BaseMetaFactory[Location]
):
    class Meta:
        model = Location
        django_get_or_create = ("id",)

    id = factory.Sequence(lambda n: 60_900_000 + n)
    category_id = Location.Category.STATION
    name = factory.LazyAttribute(lambda o: f"Station #{o.id}")


class LocationStructureFactory(
    factory.django.DjangoModelFactory, metaclass=BaseMetaFactory[Location]
):
    class Meta:
        model = Location
        django_get_or_create = ("id",)

    id = factory.Sequence(lambda n: 1_000_900_000_001 + n)
    category_id = Location.Category.STRUCTURE
    name = factory.LazyAttribute(lambda o: f"Structure #{o.id}")


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

    class Params:
        user = None

    operation_mode = ContractHandler.Mode.MY_ALLIANCE

    @factory.lazy_attribute
    def character(self):
        user = self.user or UserMainManagerFactory()
        return user.profile.main_character.character_ownership

    @factory.lazy_attribute
    def organization(self):
        match self.operation_mode:
            case ContractHandler.Mode.MY_ALLIANCE:
                if self.character:
                    return EveEntityAllianceFactory(
                        id=self.character.character.alliance_id,
                        name=self.character.character.alliance_name,
                    )
                return EveEntityAllianceFactory()

            case (
                ContractHandler.Mode.CORP_IN_ALLIANCE
                | ContractHandler.Mode.CORP_PUBLIC
                | ContractHandler.Mode.MY_CORPORATION
            ):
                if self.character:
                    return EveEntityCorporationFactory(
                        id=self.character.character.corporation_id,
                        name=self.character.character.corporation_name,
                    )
                return EveEntityCorporationFactory()

        raise ValueError(f"Unexpected operation mode: {self.operation_mode}")


class ContractFactory(
    factory.django.DjangoModelFactory, metaclass=BaseMetaFactory[Contract]
):
    class Meta:
        model = Contract

    class Params:
        user = None
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
        finished = factory.Trait(
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

    contract_id = factory.Sequence(lambda n: 10_000_000 + n)
    collateral = factory.fuzzy.FuzzyFloat(100_000_000, 1_000_000_000)
    days_to_complete = 3
    date_completed = None
    date_issued = factory.fuzzy.FuzzyDateTime(
        now() - dt.timedelta(hours=12), now() - dt.timedelta(hours=1)
    )
    date_expired = factory.fuzzy.FuzzyDateTime(
        now() + dt.timedelta(hours=1), now() + dt.timedelta(days=7)
    )
    end_location = factory.SubFactory(LocationStationFactory)
    for_corporation = False
    handler = factory.SubFactory(ContractHandlerFactory)
    reward = factory.fuzzy.FuzzyFloat(50_000_000, 100_000_000)
    status = Contract.Status.OUTSTANDING
    start_location = factory.SubFactory(LocationStationFactory)
    title = factory.faker.Faker("sentence")
    volume = factory.fuzzy.FuzzyInteger(1_000, 100_000_000)

    @factory.lazy_attribute
    def issuer(self):
        if self.user:
            return self.user.profile.main_character

        match self.handler.operation_mode:
            case ContractHandler.Mode.MY_ALLIANCE:
                corporation = EveCorporationInfoFactory(
                    alliance=self.handler.character.character.corporation.alliance
                )
                return EveCharacterFactory(corporation=corporation)

            case ContractHandler.Mode.MY_CORPORATION:
                return EveCharacterFactory(
                    corporation=self.handler.character.character.corporation
                )

        raise ValueError("Unexpected input")

    @factory.lazy_attribute
    def issuer_corporation(self):
        return EveCorporationInfoFactory(corporation_id=self.issuer.corporation_id)

    @factory.post_generation
    def eve_entities(self, create, extracted, **kwargs):
        if not create or extracted is False:
            return

        if self.acceptor:
            EveEntityCharacterFactory(
                id=self.acceptor.character_id, name=self.acceptor.character_name
            )

    @factory.post_generation
    def create_pricing(self, create, extracted, **kwargs):
        if not create or extracted is not True:
            return

        self.pricing = PricingFactory(contract=self)
        self.save()


class PricingFactory(
    factory.django.DjangoModelFactory, metaclass=BaseMetaFactory[Pricing]
):
    class Meta:
        model = Pricing

    class Params:
        contract = None

    is_default = False
    is_active = True
    is_bidirectional = True

    @classmethod
    def _generate(cls, strategy, params):
        with factory.django.mute_signals(post_save):
            return super()._generate(strategy, params)

    @factory.lazy_attribute
    def start_location(self):
        if self.contract:
            return self.contract.start_location

        return LocationStationFactory()

    @factory.lazy_attribute
    def end_location(self):
        if self.contract:
            return self.contract.end_location

        return LocationStationFactory()

    @classmethod
    def _adjust_kwargs(cls, **kwargs):
        """Set a base price as default when no pricing field defined."""
        price_fields = {
            "price_base",
            "price_per_volume",
            "price_per_collateral_percent",
            "use_price_per_volume_modifier",
        }
        fields_provided = set(kwargs.keys())
        if not price_fields.intersection(fields_provided):
            kwargs["price_base"] = factory.fuzzy.FuzzyInteger(
                100_000, 10_000_000
            ).fuzz()

        return kwargs

    @factory.post_generation
    def update_contracts(self: Pricing, create, extracted, **kwargs):
        if not create or extracted is False:
            return

        from freight.tasks import update_contracts_pricing

        update_contracts_pricing()


if "discord" in app_labels():

    class DiscordUserFactory(
        factory.django.DjangoModelFactory, metaclass=BaseMetaFactory[DiscordUser]
    ):
        class Meta:
            model = DiscordUser

        activated = factory.fuzzy.FuzzyDateTime(now() - dt.timedelta(days=30), now())
        uid = factory.Sequence(lambda n: 1_000_000_001 + n)
        user = factory.SubFactory(UserMainDefaultFactory)
        username = factory.LazyAttribute(lambda o: o.user.username)
