import json
from datetime import datetime
from time import sleep
from typing import Tuple

from bravado.exception import HTTPForbidden, HTTPUnauthorized

from django.contrib.auth.models import User
from django.db import models, transaction
from django.utils.timezone import now
from esi.models import Token
from eveuniverse.models import EveEntity

from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo
from allianceauth.services.hooks import get_extension_logger
from app_utils.logging import LoggerAddTag

from . import __title__, constants
from .app_settings import (
    FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL,
    FREIGHT_DISCORD_WEBHOOK_URL,
    FREIGHT_DISCORDPROXY_ENABLED,
)
from .providers import esi

logger = LoggerAddTag(get_extension_logger(__name__), __title__)


class PricingManager(models.Manager):
    def get_queryset(self) -> models.QuerySet:
        return super().get_queryset().select_related("start_location", "end_location")

    def get_default(self):
        """return the default pricing if defined
        else the first pricing, which can be None if no pricing exists
        """
        pricing_qs = self.filter(is_active=True)
        pricing = pricing_qs.filter(is_default=True).first()
        if not pricing:
            return pricing_qs.first()
        return pricing

    def get_or_default(self, pk: int = None):
        """returns the pricing for given pk if found else default pricing"""
        if pk:
            try:
                return self.filter(is_active=True).get(pk=pk)
            except self.model.DoesNotExist:
                return self.get_default()
        return self.get_default()


class LocationManager(models.Manager):
    STATION_ID_START = 60000000
    STATION_ID_END = 69999999

    def get_or_create_esi(
        self, token: Token, location_id: int, add_unknown: bool = True
    ) -> Tuple[models.Model, bool]:
        """gets or creates location object with data fetched from ESI"""
        from .models import Location

        try:
            location = self.get(id=location_id)
            created = False
        except Location.DoesNotExist:
            location, created = self.update_or_create_esi(
                token=token, location_id=location_id, add_unknown=add_unknown
            )
        return location, created

    def update_or_create_esi(
        self, token: Token, location_id: int, add_unknown: bool = True
    ) -> Tuple[models.Model, bool]:
        """updates or creates location object with data fetched from ESI"""
        from .models import Location

        if location_id >= self.STATION_ID_START and location_id <= self.STATION_ID_END:
            logger.info("%s: Fetching station from ESI", location_id)
            station = esi.client.Universe.get_universe_stations_station_id(
                station_id=location_id
            ).results()
            return self.update_or_create(
                id=location_id,
                defaults={
                    "name": station["name"],
                    "solar_system_id": station["system_id"],
                    "type_id": station["type_id"],
                    "category_id": Location.Category.STATION_ID,
                },
            )
        try:
            structure = esi.client.Universe.get_universe_structures_structure_id(
                token=token.valid_access_token(), structure_id=location_id
            ).results()
        except (HTTPUnauthorized, HTTPForbidden) as ex:
            logger.warn("%s: No access to this structure: %s", location_id, ex)
            if add_unknown:
                return self.get_or_create(
                    id=location_id,
                    defaults={
                        "name": "Unknown structure {}".format(location_id),
                        "category_id": Location.Category.STRUCTURE_ID,
                    },
                )
            raise ex
        else:
            return self.update_or_create(
                id=location_id,
                defaults={
                    "name": structure["name"],
                    "solar_system_id": structure["solar_system_id"],
                    "type_id": structure["type_id"],
                    "category_id": Location.Category.STRUCTURE_ID,
                },
            )


class ContractQuerySet(models.QuerySet):
    def pending_count(self) -> int:
        """returns the number of pending contacts for this QS"""
        return (
            self.filter(status=self.model.Status.OUTSTANDING)
            .exclude(date_expired__lt=now())
            .count()
        )

    def filter_not_completed(self):
        return self.exclude(status__in=self.model.Status.completed)

    def issued_by_user(self, user: User) -> models.QuerySet:
        """returns QS of contracts issued by a character owned by given user"""
        return self.filter(
            issuer__in=EveCharacter.objects.filter(character_ownership__user=user)
        )

    def update_pricing(self) -> int:
        """Updates contracts with matching pricing"""
        from .models import Pricing

        def _make_key(location_id_1: int, location_id_2: int) -> str:
            return "{}x{}".format(int(location_id_1), int(location_id_2))

        pricings = dict()
        for obj in Pricing.objects.filter(is_active=True).order_by("-id"):
            pricings[_make_key(obj.start_location_id, obj.end_location_id)] = obj
            if obj.is_bidirectional:
                pricings[_make_key(obj.end_location_id, obj.start_location_id)] = obj

        update_count = 0
        for contract in self.all():
            with transaction.atomic():
                route_key = _make_key(
                    contract.start_location_id, contract.end_location_id
                )
                if route_key in pricings:
                    pricing = pricings[route_key]
                    issues_list = contract.get_price_check_issues(pricing)
                    if issues_list:
                        issues = json.dumps(issues_list)
                    else:
                        issues = None
                else:
                    pricing = None
                    issues = None
                contract.pricing = pricing
                contract.issues = issues
                contract.save()
                update_count += 1
        return update_count

    def sent_pilot_notifications(self, rate_limited: bool) -> None:
        """Send all pilot notifications for these contracts."""
        logger.info("Trying to send pilot notifications for %d contracts", self.count())
        for contract in self:
            if not contract.has_expired:
                contract.send_pilot_notification()
                if rate_limited:
                    sleep(1)
            else:
                logger.debug("contract %s has expired", contract.contract_id)

    def sent_customer_notifications(self, rate_limited: bool, force_sent: bool) -> None:
        """Send customer notifications for these contracts."""
        logger.debug(
            "Checking %d contracts if customer notifications need to be sent",
            self.count(),
        )
        for contract in self:
            if contract.has_expired:
                logger.debug("contract %d has expired", contract.contract_id)
            elif contract.has_stale_status:
                logger.debug("contract %d has stale status", contract.contract_id)
            else:
                contract.send_customer_notification(force_sent)
                if rate_limited:
                    sleep(1)

    def contract_list_filter(self, category: str, user: User) -> models.QuerySet:
        """Filter contracts by category and user permission for contract list view."""
        if category == constants.CONTRACT_LIST_ACTIVE:
            if not user.has_perm("freight.view_contracts"):
                return self.none()
            return self.filter(
                status__in=[
                    self.model.Status.OUTSTANDING,
                    self.model.Status.IN_PROGRESS,
                ]
            ).exclude(date_expired__lt=now())
        elif category == constants.CONTRACT_LIST_ALL:
            if not user.has_perm("freight.view_contracts"):
                return self.none()
            return self
        elif category == constants.CONTRACT_LIST_USER:
            if not user.has_perm("freight.use_calculator"):
                return self.none()
            return self.issued_by_user(user=user).filter(
                status__in=[
                    self.model.Status.OUTSTANDING,
                    self.model.Status.IN_PROGRESS,
                    self.model.Status.FINISHED,
                    self.model.Status.FAILED,
                ]
            )
        raise ValueError("Invalid category: {}".format(category))


class ContractManagerBase(models.Manager):
    def update_or_create_from_dict(
        self, handler: object, contract: dict, token: Token
    ) -> Tuple[models.Model, bool]:
        """updates or creates a contract from given dict"""
        # validate types
        self._ensure_datetime_type_or_none(contract, "date_accepted")
        self._ensure_datetime_type_or_none(contract, "date_completed")
        self._ensure_datetime_type_or_none(contract, "date_expired")
        self._ensure_datetime_type_or_none(contract, "date_issued")
        acceptor, acceptor_corporation = self._identify_contracts_acceptor(contract)
        issuer_corporation, issuer = self._identify_contracts_issuer(contract)
        date_accepted = (
            contract["date_accepted"] if "date_accepted" in contract else None
        )
        date_completed = (
            contract["date_completed"] if "date_completed" in contract else None
        )
        title = contract["title"] if "title" in contract else None
        start_location, end_location = self._identify_locations(contract, token)
        return self.update_or_create(
            handler=handler,
            contract_id=contract["contract_id"],
            defaults={
                "acceptor": acceptor,
                "acceptor_corporation": acceptor_corporation,
                "collateral": contract["collateral"],
                "date_accepted": date_accepted,
                "date_completed": date_completed,
                "date_expired": contract["date_expired"],
                "date_issued": contract["date_issued"],
                "days_to_complete": contract["days_to_complete"],
                "end_location": end_location,
                "for_corporation": contract["for_corporation"],
                "issuer_corporation": issuer_corporation,
                "issuer": issuer,
                "reward": contract["reward"],
                "start_location": start_location,
                "status": contract["status"],
                "title": title,
                "volume": contract["volume"],
                "pricing": None,
                "issues": None,
            },
        )

    @staticmethod
    def _ensure_datetime_type_or_none(contract: dict, property_name: str):
        if contract[property_name] and not isinstance(
            contract[property_name], datetime
        ):
            raise TypeError("%s must be of type datetime" % property_name)

    def _identify_locations(self, contract: dict, token: Token) -> tuple:
        from .models import Location

        start_location, _ = Location.objects.get_or_create_esi(
            token, contract["start_location_id"]
        )
        end_location, _ = Location.objects.get_or_create_esi(
            token, contract["end_location_id"]
        )
        return start_location, end_location

    def _identify_contracts_acceptor(self, contract: dict) -> tuple:
        if int(contract["acceptor_id"]) == 0:
            return None, None  # no acceptor
        entity, _ = EveEntity.objects.get_or_create_esi(id=contract["acceptor_id"])
        if entity.is_character:
            try:
                acceptor = EveCharacter.objects.get(character_id=entity.id)
            except EveCharacter.DoesNotExist:
                acceptor = EveCharacter.objects.create_character(character_id=entity.id)
            try:
                acceptor_corporation = EveCorporationInfo.objects.get(
                    corporation_id=acceptor.corporation_id
                )
            except EveCorporationInfo.DoesNotExist:
                acceptor_corporation = EveCorporationInfo.objects.create_corporation(
                    corp_id=acceptor.corporation_id
                )
        elif entity.is_corporation:
            acceptor = None
            try:
                acceptor_corporation = EveCorporationInfo.objects.get(
                    corporation_id=entity.id
                )
            except EveCorporationInfo.DoesNotExist:
                acceptor_corporation = EveCorporationInfo.objects.create_corporation(
                    corp_id=entity.id
                )
        else:
            raise ValueError(
                "Acceptor has invalid category: {}".format(entity.category)
            )
        return acceptor, acceptor_corporation

    def _identify_contracts_issuer(self, contract) -> tuple:
        try:
            issuer = EveCharacter.objects.get(character_id=contract["issuer_id"])
        except EveCharacter.DoesNotExist:
            issuer = EveCharacter.objects.create_character(
                character_id=contract["issuer_id"]
            )
        try:
            issuer_corporation = EveCorporationInfo.objects.get(
                corporation_id=contract["issuer_corporation_id"]
            )
        except EveCorporationInfo.DoesNotExist:
            issuer_corporation = EveCorporationInfo.objects.create_corporation(
                corp_id=contract["issuer_corporation_id"]
            )
        return issuer_corporation, issuer

    def send_notifications(
        self, force_sent: bool = False, rate_limited: bool = True
    ) -> None:
        """Send notifications for outstanding contracts that have pricing."""
        from .models import Pricing

        if (
            self.count() > 0
            and Pricing.objects.exists()
            and not self.filter(pricing__isnull=False).exists()
        ):
            logger.info(
                "There are no notifications to send, "
                "because none of the existing contracts have a valid pricing."
            )
            return
        self._sent_pilot_notifications(force_sent, rate_limited)
        self._sent_customer_notifications(force_sent, rate_limited)

    def _sent_pilot_notifications(self, force_sent: bool, rate_limited: bool) -> None:
        if FREIGHT_DISCORD_WEBHOOK_URL:
            contracts_qs = self.filter(
                status__exact=self.model.Status.OUTSTANDING
            ).exclude(pricing__exact=None)
            if not force_sent:
                contracts_qs = contracts_qs.filter(date_notified__exact=None)
            contracts_qs = contracts_qs.select_related()
            if contracts_qs.count() > 0:
                contracts_qs.sent_pilot_notifications(rate_limited)
            else:
                logger.debug("No new pilot notifications.")
        else:
            logger.debug("FREIGHT_DISCORD_WEBHOOK_URL not configured")

    def _sent_customer_notifications(
        self, force_sent: bool, rate_limited: bool
    ) -> None:
        if FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL or FREIGHT_DISCORDPROXY_ENABLED:
            contracts_qs = self.filter(
                status__in=self.model.Status.for_customer_notification
            ).exclude(pricing__exact=None)
            contracts_qs = contracts_qs.select_related()
            if contracts_qs.count() > 0:
                contracts_qs.sent_customer_notifications(
                    rate_limited=rate_limited, force_sent=force_sent
                )
            else:
                logger.debug("No new customer notifications.")
        else:
            logger.debug(
                "FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL not configured "
                "or FREIGHT_DISCORDPROXY_ENABLED not enabled"
            )


ContractManager = ContractManagerBase.from_queryset(ContractQuerySet)
