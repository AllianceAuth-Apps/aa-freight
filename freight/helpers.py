"""Helpers for Freight."""

from typing import Tuple

from allianceauth.eveonline.models import EveCharacter

from .models import EveEntity


def update_or_create_eve_entity_from_evecharacter(
    character: EveCharacter, category: str
) -> Tuple[EveEntity, bool]:
    """Updates or create an EveEntity object from an EveCharacter object."""

    if category == EveEntity.CATEGORY_ALLIANCE:
        if not character.alliance_id:
            raise ValueError("character is not an alliance member")
        return EveEntity.objects.update_or_create(
            id=character.alliance_id,
            defaults={
                "name": character.alliance_name,
                "category": EveEntity.CATEGORY_ALLIANCE,
            },
        )

    if category == EveEntity.CATEGORY_CORPORATION:
        return EveEntity.objects.update_or_create(
            id=character.corporation_id,
            defaults={
                "name": character.corporation_name,
                "category": EveEntity.CATEGORY_CORPORATION,
            },
        )

    if category == EveEntity.CATEGORY_CHARACTER:
        return EveEntity.objects.update_or_create(
            id=character.character_id,
            defaults={
                "name": character.character_name,
                "category": EveEntity.CATEGORY_CHARACTER,
            },
        )

    raise ValueError(f"Invalid category: f{category}")
