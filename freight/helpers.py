"""Helpers for Freight."""

from __future__ import annotations

from typing import TYPE_CHECKING, Tuple

from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo

if TYPE_CHECKING:
    from freight.models import EveEntity


def update_or_create_eveentity_from_character(
    character: EveCharacter, category: str
) -> Tuple[EveEntity, bool]:
    """Update or create an EVE Entity from an EveCharacter."""
    from .models import EveEntity

    match category:
        case EveEntity.CATEGORY_ALLIANCE:
            if not character.alliance_id:
                raise ValueError("character is not an alliance member")
            return EveEntity.objects.update_or_create(
                id=character.alliance_id,
                defaults={
                    "name": character.alliance_name,
                    "category": EveEntity.CATEGORY_ALLIANCE,
                },
            )

        case EveEntity.CATEGORY_CORPORATION:
            return EveEntity.objects.update_or_create(
                id=character.corporation_id,
                defaults={
                    "name": character.corporation_name,
                    "category": EveEntity.CATEGORY_CORPORATION,
                },
            )

        case EveEntity.CATEGORY_CHARACTER:
            return EveEntity.objects.update_or_create(
                id=character.character_id,
                defaults={
                    "name": character.character_name,
                    "category": EveEntity.CATEGORY_CHARACTER,
                },
            )

    raise ValueError(f"Invalid category: f{category}")


def get_or_create_eve_character(character_id: int) -> Tuple[EveCharacter, bool]:
    """Get or create an EVE character from ESI."""
    try:
        return EveCharacter.objects.get(character_id=character_id), False
    except EveCharacter.DoesNotExist:
        return EveCharacter.objects.create_character(character_id=character_id), True


def get_or_create_eve_corporation_info(
    corporation_id: int,
) -> Tuple[EveCorporationInfo, bool]:
    """Get or create an EVE corporation from ESI."""
    try:
        return (EveCorporationInfo.objects.get(corporation_id=corporation_id), False)
    except EveCorporationInfo.DoesNotExist:
        return (
            EveCorporationInfo.objects.create_corporation(corp_id=corporation_id),
            True,
        )
