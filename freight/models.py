import hashlib
import json
from datetime import timedelta
from urllib.parse import urljoin

import dhooks_lite

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.urls import reverse
from django.utils.functional import classproperty
from django.utils.timezone import now
from esi.models import Token
from eveuniverse.models import EveEntity

from allianceauth.authentication.models import CharacterOwnership, User
from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo
from allianceauth.services.hooks import get_extension_logger
from app_utils.datetime import DATETIME_FORMAT
from app_utils.django import app_labels
from app_utils.helpers import humanize_number
from app_utils.logging import LoggerAddTag
from app_utils.urls import site_absolute_url

from . import __title__
from .app_settings import (
    FREIGHT_APP_NAME,
    FREIGHT_CONTRACT_SYNC_GRACE_MINUTES,
    FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL,
    FREIGHT_DISCORD_DISABLE_BRANDING,
    FREIGHT_DISCORD_MENTIONS,
    FREIGHT_DISCORD_WEBHOOK_URL,
    FREIGHT_DISCORDPROXY_ENABLED,
    FREIGHT_DISCORDPROXY_PORT,
    FREIGHT_FULL_ROUTE_NAMES,
    FREIGHT_HOURS_UNTIL_STALE_STATUS,
    FREIGHT_OPERATION_MODE,
    FREIGHT_OPERATION_MODE_CORP_IN_ALLIANCE,
    FREIGHT_OPERATION_MODE_CORP_PUBLIC,
    FREIGHT_OPERATION_MODE_MY_ALLIANCE,
    FREIGHT_OPERATION_MODE_MY_CORPORATION,
    FREIGHT_OPERATION_MODES,
)
from .constants import AVATAR_SIZE
from .managers import ContractManager, LocationManager, PricingManager
from .providers import esi

if "discord" in app_labels():
    from allianceauth.services.modules.discord.models import DiscordUser
else:
    DiscordUser = None

try:
    from discordproxy.client import DiscordClient
    from discordproxy.discord_api_pb2 import Embed
    from discordproxy.exceptions import DiscordProxyException
    from google.protobuf import json_format
except ImportError:
    DiscordClient = None

logger = LoggerAddTag(get_extension_logger(__name__), __title__)


class Freight(models.Model):
    """Meta model for global app permissions"""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = (
            ("add_location", "Can add / update locations"),
            ("basic_access", "Can access this app"),
            ("setup_contract_handler", "Can setup contract handler"),
            ("use_calculator", "Can use the calculator"),
            ("view_contracts", "Can view the contracts list"),
            ("view_statistics", "Can view freight statistics"),
        )

    @classmethod
    def operation_mode_friendly(cls, operation_mode) -> str:
        """returns user friendly description of operation mode"""
        msg = [(x, y) for x, y in FREIGHT_OPERATION_MODES if x == operation_mode]
        if len(msg) != 1:
            raise ValueError("Undefined mode")
        return msg[0][1]

    @staticmethod
    def category_for_operation_mode(mode: str) -> str:
        """Eve Entity category for given operation mode."""
        if mode == FREIGHT_OPERATION_MODE_MY_ALLIANCE:
            return EveEntity.CATEGORY_ALLIANCE
        return EveEntity.CATEGORY_CORPORATION


class Location(models.Model):
    """An Eve Online courier contract location: station or Upwell structure"""

    class Category(models.IntegerChoices):
        STATION_ID = 3, "station"
        STRUCTURE_ID = 65, "structure"
        UNKNOWN_ID = 0, "(unknown)"

    id = models.BigIntegerField(
        primary_key=True,
        validators=[MinValueValidator(0)],
        help_text="Eve Online location ID, "
        "either item ID for stations or structure ID for structures",
    )

    category_id = models.PositiveIntegerField(
        choices=Category.choices,
        default=Category.UNKNOWN_ID,
        help_text="Eve Online category ID",
    )
    name = models.CharField(
        max_length=100,
        db_index=True,
        help_text="In-game name of this station or structure",
    )
    solar_system_id = models.PositiveIntegerField(
        default=None, null=True, blank=True, help_text="Eve Online solar system ID"
    )
    type_id = models.PositiveIntegerField(
        default=None, null=True, blank=True, help_text="Eve Online type ID"
    )

    objects = LocationManager()

    def __str__(self):
        return self.name

    def __repr__(self) -> str:
        return "{}(pk={}, name='{}')".format(
            self.__class__.__name__, self.pk, self.name
        )

    @property
    def category(self):
        return self.category_id

    @property
    def solar_system_name(self):
        return self.name.split(" ", 1)[0]

    @property
    def location_name(self):
        return self.name.rsplit("-", 1)[1].strip()

    @classmethod
    def get_esi_scopes(cls):
        return ["esi-universe.read_structures.v1"]


class Pricing(models.Model):
    """Pricing for a courier route"""

    start_location = models.ForeignKey(
        Location,
        on_delete=models.CASCADE,
        related_name="+",
        help_text="Starting station or structure for courier route",
    )
    end_location = models.ForeignKey(
        Location,
        on_delete=models.CASCADE,
        related_name="+",
        help_text="Destination station or structure for courier route",
    )

    collateral_min = models.BigIntegerField(
        default=None,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Minimum required collateral in ISK",
    )
    collateral_max = models.BigIntegerField(
        default=None,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Maximum allowed collateral in ISK",
    )
    days_to_expire = models.PositiveIntegerField(
        default=None,
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text="Recommended days for contracts to expire",
    )
    days_to_complete = models.PositiveIntegerField(
        default=None,
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text="Recommended days for contract completion",
    )
    details = models.TextField(
        default=None,
        null=True,
        blank=True,
        help_text="Text with additional instructions for using this pricing",
    )
    is_active = models.BooleanField(
        default=True, help_text="Non active pricings will not be used or shown"
    )
    is_default = models.BooleanField(
        default=False,
        help_text=(
            "The default pricing will be preselected in the calculator. "
            "Please make sure to only mark one pricing as default."
        ),
    )
    is_bidirectional = models.BooleanField(
        default=True,
        help_text="Whether this pricing is valid for contracts "
        "in either direction or only the one specified",
    )
    price_base = models.FloatField(
        default=None,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Base price in ISK",
    )
    price_min = models.FloatField(
        default=None,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Minimum total price in ISK",
    )
    price_per_volume = models.FloatField(
        default=None,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Add-on price per m3 volume in ISK",
    )
    price_per_collateral_percent = models.FloatField(
        default=None,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Add-on price in % of collateral",
    )
    volume_max = models.FloatField(
        default=None,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Maximum allowed volume in m3",
    )
    volume_min = models.FloatField(
        default=None,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Minimum allowed volume in m3",
    )
    use_price_per_volume_modifier = models.BooleanField(
        default=False, help_text="Whether the global price per volume modifier is used"
    )

    objects = PricingManager()

    class Meta:
        unique_together = (("start_location", "end_location"),)

    def save(self, update_contracts=True, *args, **kwargs) -> None:
        super().save(*args, **kwargs)
        if update_contracts:
            self._update_contracts()

    def _update_contracts(self):
        from .tasks import update_contracts_pricing

        update_contracts_pricing.delay()

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return "{}(pk={}, name='{}')".format(
            self.__class__.__name__, self.pk, self.name_full
        )

    def clean(self):
        if (
            self.price_base is None
            and self.price_min is None
            and self.price_per_volume is None
            and self.price_per_collateral_percent is None
        ):
            raise ValidationError("You must specify at least one price component")

        if self.start_location_id and self.end_location_id:
            if (
                Pricing.objects.filter(
                    start_location=self.end_location,
                    end_location=self.start_location,
                    is_bidirectional=True,
                ).exists()
                and self.is_bidirectional
            ):
                raise ValidationError(
                    "There already exists a bidirectional pricing for this route. "
                    "Please set this pricing to non-bidirectional to save it. "
                    "And after you must also set the other pricing to "
                    "non-bidirectional."
                )

            if (
                Pricing.objects.filter(
                    start_location=self.end_location,
                    end_location=self.start_location,
                    is_bidirectional=False,
                ).exists()
                and self.is_bidirectional
            ):
                raise ValidationError(
                    "There already exists a non bidirectional pricing for "
                    "this route. You need to mark this pricing as "
                    "non-bidirectional too to continue."
                )

    @property
    def name(self) -> str:
        return self._name(FREIGHT_FULL_ROUTE_NAMES)

    @property
    def name_full(self) -> str:
        return self._name(full_name=True)

    @property
    def name_short(self) -> str:
        return self._name(full_name=False)

    def _name(self, full_name: bool) -> str:
        if full_name:
            start_name = self.start_location.name
            end_name = self.end_location.name
        else:
            start_name = self.start_location.solar_system_name
            end_name = self.end_location.solar_system_name

        route_name = "{} {} {}".format(
            start_name, "<->" if self.is_bidirectional else "->", end_name
        )
        return route_name

    def price_per_volume_modifier(self):
        """returns the effective price per volume modifier or None"""
        if not self.use_price_per_volume_modifier:
            modifier = None

        else:
            handler = ContractHandler.objects.first()
            if handler:
                modifier = handler.price_per_volume_modifier

            else:
                modifier = None

        return modifier

    def price_per_volume_eff(self):
        """ "returns price per volume incl. potential modifier or None"""
        if not self.price_per_volume:
            price_per_volume = None
        else:
            price_per_volume = self.price_per_volume
            modifier = self.price_per_volume_modifier()
            if modifier:
                price_per_volume = max(
                    0, price_per_volume + (price_per_volume * modifier / 100)
                )

        return price_per_volume

    def requires_volume(self) -> bool:
        """whether this pricing required volume to be specified"""
        return (self.price_per_volume is not None and self.price_per_volume != 0) or (
            self.volume_min is not None and self.volume_min != 0
        )

    def requires_collateral(self) -> bool:
        """whether this pricing required collateral to be specified"""
        return (
            self.price_per_collateral_percent is not None
            and self.price_per_collateral_percent != 0
        ) or (self.collateral_min is not None and self.collateral_min != 0)

    def is_fix_price(self) -> bool:
        """whether this pricing is a fix price"""
        return (
            self.price_base is not None
            and self.price_min is None
            and self.price_per_volume is None
            and self.price_per_collateral_percent is None
        )

    def get_calculated_price(self, volume: float, collateral: float) -> float:
        """returns the calculated price for the given parameters"""

        if not volume:
            volume = 0

        if not collateral:
            collateral = 0

        if volume < 0:
            raise ValueError("volume can not be negative")
        if collateral < 0:
            raise ValueError("collateral can not be negative")

        volume = float(volume)
        collateral = float(collateral)

        price_base = 0 if not self.price_base else self.price_base
        price_min = 0 if not self.price_min else self.price_min

        price_per_volume_eff = self.price_per_volume_eff()
        if not price_per_volume_eff:
            price_per_volume = 0
        else:
            price_per_volume = price_per_volume_eff

        price_per_collateral_percent = (
            0
            if not self.price_per_collateral_percent
            else self.price_per_collateral_percent
        )

        return max(
            price_min,
            (
                price_base
                + volume * price_per_volume
                + collateral * (price_per_collateral_percent / 100)
            ),
        )

    def get_contract_price_check_issues(
        self, volume: float, collateral: float, reward: float = None
    ) -> list:
        """returns list of validation error messages or none if ok"""
        if volume and volume < 0:
            raise ValueError("volume can not be negative")
        if collateral and collateral < 0:
            raise ValueError("collateral can not be negative")
        if reward and reward < 0:
            raise ValueError("reward can not be negative")
        issues = list()
        if volume is not None and self.volume_min and volume < self.volume_min:
            issues.append(
                "below the minimum required volume of {:,.0f} m3".format(
                    self.volume_min
                )
            )
        if volume is not None and self.volume_max and volume > self.volume_max:
            issues.append(
                "exceeds the maximum allowed volume of {:,.0f} m3".format(
                    self.volume_max
                )
            )
        if (
            collateral is not None
            and self.collateral_max
            and collateral > self.collateral_max
        ):
            issues.append(
                "exceeds the maximum allowed collateral of {:,.0f} ISK".format(
                    self.collateral_max
                )
            )
        if (
            collateral is not None
            and self.collateral_min
            and collateral < self.collateral_min
        ):
            issues.append(
                "below the minimum required collateral of {:,.0f} ISK".format(
                    self.collateral_min
                )
            )
        if reward is not None:
            calculated_price = self.get_calculated_price(volume, collateral)
            if reward < calculated_price:
                issues.append(
                    "reward is below the calculated price of {:,.0f} ISK".format(
                        calculated_price
                    )
                )
        if len(issues) == 0:
            return None
        return issues


class ContractHandler(models.Model):
    """Handler for syncing of contracts belonging to an alliance or corporation"""

    # errors
    ERROR_NONE = 0
    ERROR_TOKEN_INVALID = 1
    ERROR_TOKEN_EXPIRED = 2
    ERROR_INSUFFICIENT_PERMISSIONS = 3
    ERROR_NO_CHARACTER = 4
    ERROR_ESI_UNAVAILABLE = 5
    ERROR_OPERATION_MODE_MISMATCH = 6
    ERROR_UNKNOWN = 99

    ERRORS_LIST = [
        (ERROR_NONE, "No error"),
        (ERROR_TOKEN_INVALID, "Invalid token"),
        (ERROR_TOKEN_EXPIRED, "Expired token"),
        (ERROR_INSUFFICIENT_PERMISSIONS, "Insufficient permissions"),
        (ERROR_NO_CHARACTER, "No character set for fetching alliance contacts"),
        (ERROR_ESI_UNAVAILABLE, "ESI API is currently unavailable"),
        (
            ERROR_OPERATION_MODE_MISMATCH,
            "Operation mode does not match with current setting",
        ),
        (ERROR_UNKNOWN, "Unknown error"),
    ]

    organization = models.OneToOneField(
        EveEntity, on_delete=models.CASCADE, primary_key=True
    )
    character = models.ForeignKey(
        CharacterOwnership,
        on_delete=models.SET_DEFAULT,
        default=None,
        null=True,
        related_name="+",
        help_text="character used for syncing contracts",
    )
    operation_mode = models.CharField(
        max_length=32,
        default=FREIGHT_OPERATION_MODE_MY_ALLIANCE,
        help_text="defines what kind of contracts are synced",
    )
    price_per_volume_modifier = models.FloatField(
        default=None,
        null=True,
        blank=True,
        help_text="global modifier for price per volume in percent, e.g. 2.5 = +2.5%",
    )
    version_hash = models.CharField(
        max_length=32,
        null=True,
        default=None,
        blank=True,
        help_text="hash to identify changes to contracts",
    )
    last_sync = models.DateTimeField(
        null=True, default=None, blank=True, help_text="when the last sync happened"
    )
    last_error = models.IntegerField(
        choices=ERRORS_LIST,
        default=ERROR_NONE,
        help_text="error that occurred at the last sync attempt (if any)",
    )  # no longer used

    def __str__(self):
        return str(self.organization.name)

    def __repr__(self) -> str:
        return "{}(pk={}, organization='{}')".format(
            self.__class__.__name__, self.pk, str(self.organization.name)
        )

    @property
    def operation_mode_friendly(self) -> str:
        """returns user friendly description of operation mode"""
        return Freight.operation_mode_friendly(self.operation_mode)

    @property
    def last_error_message_friendly(self) -> str:
        msg = [(x, y) for x, y in self.ERRORS_LIST if x == self.last_error]
        return msg[0][1] if len(msg) > 0 else "Undefined error"

    @classmethod
    def get_esi_scopes(cls) -> list:
        return [
            "esi-contracts.read_corporation_contracts.v1",
            "esi-universe.read_structures.v1",
        ]

    @property
    def is_sync_ok(self) -> bool:
        """Evaluate if sync has problems."""
        return self.last_sync is not None and self.last_sync > (
            now() - timedelta(minutes=FREIGHT_CONTRACT_SYNC_GRACE_MINUTES)
        )

    class Meta:
        verbose_name_plural = verbose_name = "Contract Handler"

    def get_availability_text_for_contracts(self) -> str:
        """returns a text detailing the availability choice for this setup"""

        if self.operation_mode == FREIGHT_OPERATION_MODE_MY_ALLIANCE:
            extra_text = "[My Alliance]"

        elif self.operation_mode == FREIGHT_OPERATION_MODE_MY_CORPORATION:
            extra_text = "[My Corporation]"

        else:
            extra_text = ""

        return "Private ({}) {}".format(self.organization.name, extra_text)

    def valid_token(self) -> Token:
        """Fetch a valid esi token for the contract handler."""
        token = (
            Token.objects.filter(
                user=self.character.user,
                character_id=self.character.character.character_id,
            )
            .require_scopes(self.get_esi_scopes())
            .require_valid()
            .first()
        )
        if not token:
            raise ObjectDoesNotExist(f"{self}: No valid token found")
        return token

    def update_contracts_esi(self, force_sync=False) -> None:
        self._validate_update_readiness()
        contracts = self._fetch_contracts_from_esi()
        self._process_contracts_from_esi(contracts_all=contracts, force_sync=force_sync)

    def _validate_update_readiness(self):
        """Check preconditions for contracts update and raise exception when not met."""
        if self.operation_mode != FREIGHT_OPERATION_MODE:
            raise RuntimeError(
                f"{self}: Current operation mode not matching the handler"
            )
        if self.character is None:
            raise RuntimeError(f"{self}: No character configured to sync")
        if not self.character.user.has_perm("freight.setup_contract_handler"):
            raise RuntimeError(
                f"{self}: Character does not have sufficient permission to sync contracts"
            )

    def _fetch_contracts_from_esi(self):
        token = self.valid_token()
        contracts = esi.client.Contracts.get_corporations_corporation_id_contracts(
            token=token.valid_access_token(),
            corporation_id=self.character.character.corporation_id,
        ).results()
        if settings.DEBUG:
            self._save_contract_to_file(contracts)
        return contracts

    def _save_contract_to_file(self, contracts):
        """saves raw contracts to file for debugging"""
        with open("contracts_raw.json", "w", encoding="utf-8") as f:
            json.dump(contracts, f, cls=DjangoJSONEncoder, sort_keys=True, indent=4)

    def _process_contracts_from_esi(self, contracts_all: list, force_sync: bool):
        # 1st filter: reduce to courier contracts assigned to handler org
        contracts_courier = [
            x
            for x in contracts_all
            if x["type"] == "courier"
            and int(x["assignee_id"]) == int(self.organization.id)
        ]

        # 2nd filter: remove contracts not in scope due to operation mode
        contracts = list()
        for contract in contracts_courier:
            try:
                issuer = EveCharacter.objects.get(character_id=contract["issuer_id"])
            except EveCharacter.DoesNotExist:
                issuer = EveCharacter.objects.create_character(
                    character_id=contract["issuer_id"]
                )
            assignee_id = int(contract["assignee_id"])
            issuer_corporation_id = int(issuer.corporation_id)
            issuer_alliance_id = int(issuer.alliance_id) if issuer.alliance_id else None
            if self.operation_mode == FREIGHT_OPERATION_MODE_MY_ALLIANCE:
                in_scope = issuer_alliance_id == assignee_id
            elif self.operation_mode == FREIGHT_OPERATION_MODE_MY_CORPORATION:
                in_scope = assignee_id == issuer_corporation_id
            elif self.operation_mode == FREIGHT_OPERATION_MODE_CORP_IN_ALLIANCE:
                in_scope = issuer_alliance_id == int(
                    self.character.character.alliance_id
                )
            elif self.operation_mode == FREIGHT_OPERATION_MODE_CORP_PUBLIC:
                in_scope = True
            else:
                raise NotImplementedError(
                    "Unsupported operation mode: {}".format(self.operation_mode)
                )
            if in_scope:
                contracts.append(contract)

        # determine if contracts have changed by comparing their hashes
        new_version_hash = hashlib.md5(
            json.dumps(contracts, cls=DjangoJSONEncoder).encode("utf-8")
        ).hexdigest()
        if force_sync or new_version_hash != self.version_hash:
            self._store_contracts_from_esi(contracts, new_version_hash)
        else:
            logger.info("%s: Contracts are unchanged.", self)
        self.last_sync = now()
        self.save()

    def _store_contracts_from_esi(self, contracts: list, new_version_hash: str) -> None:
        logger.info("%s: Storing update with %d contracts", self, len(contracts))
        token = self.valid_token()
        with transaction.atomic():
            for contract in contracts:
                Contract.objects.update_or_create_from_dict(
                    handler=self, contract=contract, token=token
                )
            self.version_hash = new_version_hash
            self.save()
        Contract.objects.update_pricing()


class Contract(models.Model):
    """An Eve Online courier contract with additional meta data"""

    class Status(models.TextChoices):
        OUTSTANDING = "outstanding", "outstanding"
        IN_PROGRESS = "in_progress", "in progress"
        FINISHED_ISSUER = "finished_issuer", "finished issuer"
        FINISHED_CONTRACTOR = "finished_contractor", "finished contractor"
        FINISHED = "finished", "finished"
        CANCELED = "canceled", "canceled"
        REJECTED = "rejected", "rejected"
        FAILED = "failed", "failed"
        DELETED = "deleted", "deleted"
        REVERSED = "reversed", "reversed"

        @classproperty
        def completed(cls) -> set:
            """Status representing a completed contract."""
            return {
                cls.FINISHED_ISSUER,
                cls.FINISHED_CONTRACTOR,
                cls.FINISHED_ISSUER,
                cls.CANCELED,
                cls.REJECTED,
                cls.DELETED,
                cls.FINISHED,
                cls.FAILED,
            }

        @classproperty
        def for_customer_notification(cls) -> set:
            return {cls.OUTSTANDING, cls.IN_PROGRESS, cls.FINISHED, cls.FAILED}

    EMBED_COLOR_PASSED = 0x008000
    EMBED_COLOR_FAILED = 0xFF0000

    handler = models.ForeignKey(
        ContractHandler, on_delete=models.CASCADE, related_name="contracts"
    )
    contract_id = models.IntegerField()

    acceptor = models.ForeignKey(
        EveCharacter,
        on_delete=models.CASCADE,
        default=None,
        null=True,
        blank=True,
        related_name="contracts_acceptor",
        help_text="character of acceptor or None if accepted by corp",
    )
    acceptor_corporation = models.ForeignKey(
        EveCorporationInfo,
        on_delete=models.CASCADE,
        default=None,
        null=True,
        blank=True,
        related_name="contracts_acceptor_corporation",
        help_text="corporation of acceptor",
    )
    collateral = models.FloatField()
    date_accepted = models.DateTimeField(default=None, null=True, blank=True)
    date_completed = models.DateTimeField(default=None, null=True, blank=True)
    date_expired = models.DateTimeField()
    date_issued = models.DateTimeField()
    date_notified = models.DateTimeField(
        default=None,
        null=True,
        blank=True,
        db_index=True,
        help_text="datetime of latest notification, None = none has been sent",
    )
    days_to_complete = models.IntegerField()
    end_location = models.ForeignKey(
        Location, on_delete=models.CASCADE, related_name="contracts_end_location"
    )
    for_corporation = models.BooleanField()
    issuer_corporation = models.ForeignKey(
        EveCorporationInfo,
        on_delete=models.CASCADE,
        related_name="contracts_issuer_corporation",
    )
    issuer = models.ForeignKey(
        EveCharacter, on_delete=models.CASCADE, related_name="contracts_issuer"
    )
    issues = models.TextField(
        default=None,
        null=True,
        blank=True,
        help_text="List or price check issues as JSON array of strings or None",
    )
    pricing = models.ForeignKey(
        Pricing,
        on_delete=models.SET_DEFAULT,
        default=None,
        null=True,
        blank=True,
        related_name="contracts",
    )
    reward = models.FloatField()
    start_location = models.ForeignKey(
        Location, on_delete=models.CASCADE, related_name="contracts_start_location"
    )
    status = models.CharField(max_length=32, choices=Status.choices, db_index=True)
    title = models.CharField(max_length=100, default=None, null=True, blank=True)
    volume = models.FloatField()

    objects = ContractManager()

    class Meta:
        unique_together = (("handler", "contract_id"),)
        indexes = [
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return "{}: {} -> {}".format(
            self.contract_id,
            self.start_location.solar_system_name,
            self.end_location.solar_system_name,
        )

    def __repr__(self) -> str:
        return "{}(contract_id={}, start_location={}, end_location={})".format(
            self.__class__.__name__,
            self.contract_id,
            self.start_location.solar_system_name,
            self.end_location.solar_system_name,
        )

    @property
    def is_completed(self) -> bool:
        """whether this contract is completed or active"""
        return self.status in self.Status.completed

    @property
    def is_in_progress(self) -> bool:
        return self.status == self.Status.IN_PROGRESS

    @property
    def is_failed(self) -> bool:
        return self.status == self.Status.FAILED

    @property
    def has_expired(self) -> bool:
        """returns true if this contract is expired"""
        return self.date_expired < now()

    @property
    def has_pricing(self) -> bool:
        return bool(self.pricing)

    @property
    def has_pricing_errors(self) -> bool:
        return bool(self.issues)

    @property
    def hours_issued_2_completed(self) -> float:
        if self.date_completed:
            td = self.date_completed - self.date_issued
            return td.days * 24 + (td.seconds / 3600)
        else:
            return None

    @property
    def date_latest(self) -> bool:
        """latest status related date of this contract"""
        if self.date_completed:
            date = self.date_completed
        elif self.date_accepted:
            date = self.date_accepted
        else:
            date = self.date_issued

        return date

    @property
    def has_stale_status(self) -> bool:
        """whether the status of this contract has become stale"""
        return self.date_latest < now() - timedelta(
            hours=FREIGHT_HOURS_UNTIL_STALE_STATUS
        )

    @property
    def acceptor_name(self) -> str:
        "returns the name of the acceptor character or corporation or None"

        if self.acceptor:
            name = self.acceptor.character_name
        elif self.acceptor_corporation:
            name = self.acceptor_corporation.corporation_name
        else:
            name = None

        return name

    def get_price_check_issues(self, pricing: Pricing) -> list:
        return pricing.get_contract_price_check_issues(
            self.volume, self.collateral, self.reward
        )

    def get_issue_list(self) -> list:
        """returns current pricing issues as list of strings"""
        if self.issues:
            return json.loads(self.issues)
        else:
            return []

    def _generate_embed_description(self) -> object:
        """generates a Discord embed for this contract"""
        desc = (
            f"**From**: {self.start_location}\n"
            f"**To**: {self.end_location}\n"
            f"**Volume**: {self.volume:,.0f} m3\n"
            f"**Reward**: {humanize_number(self.reward)} ISK\n"
            f"**Collateral**: {humanize_number(self.collateral)} ISK\n"
            f"**Status**: {self.status}\n"
        )
        if self.pricing:
            if not self.has_pricing_errors:
                check_text = "passed"
                color = self.EMBED_COLOR_PASSED
            else:
                check_text = "FAILED"
                color = self.EMBED_COLOR_FAILED
        else:
            check_text = "N/A"
            color = None
        desc += (
            f"**Contract Check**: {check_text}\n"
            f"**Issued on**: {self.date_issued.strftime(DATETIME_FORMAT)}\n"
            f"**Issued by**: {self.issuer}\n"
            f"**Expires on**: {self.date_expired.strftime(DATETIME_FORMAT)}\n"
        )
        if self.acceptor_name:
            desc += f"**Accepted by**: {self.acceptor_name}\n"
        if self.date_accepted:
            desc += f"**Accepted on**: {self.date_accepted.strftime(DATETIME_FORMAT)}\n"
        desc += f"**Contract ID**: {self.contract_id}\n"
        return {"desc": desc, "color": color}

    def _generate_embed(self, for_issuer=False) -> dhooks_lite.Embed:
        embed_desc = self._generate_embed_description()
        if for_issuer:
            url = urljoin(site_absolute_url(), reverse("freight:contract_list_user"))
        else:
            url = urljoin(site_absolute_url(), reverse("freight:contract_list_all"))
        return dhooks_lite.Embed(
            author=dhooks_lite.Author(
                name=self.issuer.character_name, icon_url=self.issuer.portrait_url()
            ),
            title=(
                f"{self.start_location.solar_system_name} >> "
                f"{self.end_location.solar_system_name} "
                f"| {self.volume:,.0f} m3 | {self.status.upper()}"
            ),
            url=url,
            description=embed_desc["desc"],
            color=embed_desc["color"],
        )

    def send_pilot_notification(self):
        """sends pilot notification about this contract to the DISCORD webhook"""
        if FREIGHT_DISCORD_WEBHOOK_URL:
            if FREIGHT_DISCORD_DISABLE_BRANDING:
                username = None
                avatar_url = None
            else:
                username = FREIGHT_APP_NAME
                avatar_url = self.handler.organization.icon_url(size=AVATAR_SIZE)

            hook = dhooks_lite.Webhook(
                FREIGHT_DISCORD_WEBHOOK_URL, username=username, avatar_url=avatar_url
            )
            with transaction.atomic():
                logger.info(
                    "%s: Trying to sent pilot notification about contract %s to %s",
                    self,
                    self.contract_id,
                    FREIGHT_DISCORD_WEBHOOK_URL,
                )
                if FREIGHT_DISCORD_MENTIONS:
                    contents = str(FREIGHT_DISCORD_MENTIONS) + " "
                else:
                    contents = ""

                contract_list_url = urljoin(
                    site_absolute_url(), reverse("freight:contract_list_all")
                )
                contents += (
                    "There is a new courier contract from {} "
                    "looking to be picked up "
                    "[[show]({})]:"
                ).format(self.issuer, contract_list_url)

                embed = self._generate_embed()
                response = hook.execute(
                    content=contents, embeds=[embed], wait_for_response=True
                )
                if response.status_ok:
                    self.date_notified = now()
                    self.save()
                else:
                    logger.warn(
                        "%s: Failed to send message. HTTP code: %s",
                        self,
                        response.status_code,
                    )
        else:
            logger.debug("%s: FREIGHT_DISCORD_WEBHOOK_URL not configured", self)

    def send_customer_notification(self, force_sent=False):
        """sends customer notification about this contract to Discord
        force_sent: send notification even if one has already been sent
        """
        if (
            FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL or FREIGHT_DISCORDPROXY_ENABLED
        ) and DiscordUser:
            status_to_report = None
            for status in self.Status.for_customer_notification:
                if self.status == status and (
                    force_sent or not self.customer_notifications.filter(status=status)
                ):
                    status_to_report = status
                    break

            if status_to_report:
                self._report_to_customer(status_to_report)
        else:
            logger.debug(
                "%s: FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL not configured or "
                "Discord services not installed or Discord Proxy not enabled",
                self,
            )

    def _report_to_customer(self, status_to_report):
        issuer_user = User.objects.filter(
            character_ownerships__character=self.issuer
        ).first()
        if not issuer_user:
            logger.info(
                "%s: Could not find matching user for issuer: %s", self, self.issuer
            )
            return
        try:
            discord_user_id = DiscordUser.objects.get(user=issuer_user).uid
        except DiscordUser.DoesNotExist:
            logger.warning(
                "%s: Could not find Discord user for issuer: %s", self, issuer_user
            )
            return

        if FREIGHT_DISCORDPROXY_ENABLED:
            self._send_to_customer_via_discordproxy(status_to_report, discord_user_id)

        elif FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL:
            self._send_to_customer_via_webhook(status_to_report, discord_user_id)

    def _send_to_customer_via_webhook(self, status_to_report, discord_user_id):
        if FREIGHT_DISCORD_DISABLE_BRANDING:
            username = None
            avatar_url = None
        else:
            username = FREIGHT_APP_NAME
            avatar_url = self.handler.organization.icon_url(size=AVATAR_SIZE)

        hook = dhooks_lite.Webhook(
            FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL,
            username=username,
            avatar_url=avatar_url,
        )
        logger.info(
            "%s: Trying to send customer notification"
            " about contract %s on status %s to %s",
            self,
            self.contract_id,
            status_to_report,
            FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL,
        )
        embed = self._generate_embed(for_issuer=True)
        contents = self._generate_contents(discord_user_id, status_to_report)
        response = hook.execute(
            content=contents, embeds=[embed], wait_for_response=True
        )
        if response.status_ok:
            ContractCustomerNotification.objects.update_or_create(
                contract=self,
                status=status_to_report,
                defaults={"date_notified": now()},
            )
        else:
            logger.warn(
                "%s: Failed to send message. HTTP code: %s",
                self,
                response.status_code,
            )

    def _send_to_customer_via_discordproxy(self, status_to_report, discord_user_id):
        logger.info(
            "%s: Trying to send customer notification "
            "about contract %s on status %s to discord dm",
            self,
            self.contract_id,
            status_to_report,
        )
        embed_dct = self._generate_embed(for_issuer=True).asdict()
        embed = json_format.ParseDict(embed_dct, Embed())
        contents = self._generate_contents(
            discord_user_id, status_to_report, include_mention=False
        )
        client = DiscordClient(target=f"localhost:{FREIGHT_DISCORDPROXY_PORT}")
        try:
            client.create_direct_message(
                user_id=discord_user_id, content=contents, embed=embed
            )
        except DiscordProxyException as ex:
            logger.error("Failed to send message to Discord: %s", ex)
        else:
            ContractCustomerNotification.objects.update_or_create(
                contract=self,
                status=status_to_report,
                defaults={"date_notified": now()},
            )

    def _generate_contents(
        self, discord_user_id, status_to_report, include_mention=True
    ):
        contents = "<@{}>\n".format(discord_user_id) if include_mention else ""
        if self.acceptor_name:
            acceptor_text = "by {} ".format(self.acceptor_name)
        else:
            acceptor_text = ""
        if status_to_report == self.Status.OUTSTANDING:
            contents += "We have received your contract"
            if self.has_pricing_errors:
                issues = self.get_issue_list()
                contents += (
                    ", but we found some issues.\n"
                    "Please create a new courier contract "
                    "and correct the following issues:\n"
                )
                for issue in issues:
                    contents += "• {}\n".format(issue)
            else:
                contents += " and it will be picked up by " "one of our pilots shortly."
        elif status_to_report == self.Status.IN_PROGRESS:
            contents += (
                "Your contract has been picked up {}"
                "and will be delivered to you shortly.".format(acceptor_text)
            )
        elif status_to_report == self.Status.FINISHED:
            contents += (
                "Your contract has been **delivered**.\n"
                "Thank you for using our freight service."
            )
        elif status_to_report == self.Status.FAILED:
            contents += (
                "Your contract has been **failed** {}"
                "Thank you for using our freight service.".format(acceptor_text)
            )
        else:
            raise NotImplementedError()
        return contents


class ContractCustomerNotification(models.Model):
    """record of contract notification to customer about state"""

    contract = models.ForeignKey(
        Contract, on_delete=models.CASCADE, related_name="customer_notifications"
    )
    status = models.CharField(
        max_length=32, choices=Contract.Status.choices, db_index=True
    )
    date_notified = models.DateTimeField(help_text="datetime of notification")

    class Meta:
        unique_together = (("contract", "status"),)

    def __str__(self):
        return "{} - {}".format(self.contract.contract_id, self.status)

    def __repr__(self) -> str:
        return "{}(pk={}, contract_id={}, status={})".format(
            self.__class__.__name__, self.pk, self.contract.contract_id, self.status
        )
