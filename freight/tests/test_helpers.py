from unittest.mock import patch

from app_utils.testdata_factories import (
    EveAllianceInfoFactory,
    EveCharacterFactory,
    EveCorporationInfoFactory,
)
from app_utils.testing import NoSocketsTestCase

from freight.helpers import (
    get_or_create_eve_character,
    get_or_create_eve_corporation_info,
    update_or_create_eve_entity_from_evecharacter,
)
from freight.models import EveEntity

MODULE_PATH = "freight.helpers"


class TestCreateEveEntityFromEveCharacter(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.character = EveCharacterFactory(
            character_id=90000001,
            corporation__corporation_id=92000001,
            corporation__alliance=EveAllianceInfoFactory(alliance_id=93000001),
        )

    def test_can_create_corporation_from_evecharacter(self):
        corporation, _ = update_or_create_eve_entity_from_evecharacter(
            self.character, category=EveEntity.CATEGORY_CORPORATION
        )
        self.assertEqual(int(corporation.id), 92000001)

    def test_can_create_alliance_from_evecharacter(self):
        alliance, _ = update_or_create_eve_entity_from_evecharacter(
            self.character, category=EveEntity.CATEGORY_ALLIANCE
        )
        self.assertEqual(int(alliance.id), 93000001)

    def test_can_create_character_alliance_from_evecharacter(self):
        char2, _ = update_or_create_eve_entity_from_evecharacter(
            self.character, category=EveEntity.CATEGORY_CHARACTER
        )
        self.assertEqual(int(char2.id), 90000001)

    def test_raises_exception_when_trying_to_create_alliance_from_non_member(self):
        character = EveCharacterFactory(corporation__create_alliance=False)
        with self.assertRaises(ValueError):
            update_or_create_eve_entity_from_evecharacter(
                character, category=EveEntity.CATEGORY_ALLIANCE
            )

    def test_raises_exception_when_trying_to_create_invalid_category_from_evechar(self):
        with self.assertRaises(ValueError):
            update_or_create_eve_entity_from_evecharacter(
                self.character, category="xxx"
            )


class TestGetOrCreateEveCharacter(NoSocketsTestCase):
    def test_should_return_character_when_it_exists(self):
        # given
        character = EveCharacterFactory(character_id=1001)

        # when
        got, created = get_or_create_eve_character(1001)

        # then
        self.assertFalse(created)
        self.assertEqual(got, character)

    def test_should_create_character_when_it_does_not_exist(self):
        # when
        with patch(MODULE_PATH + ".EveCharacter.objects.create_character") as m:
            m.side_effect = lambda character_id: EveCharacterFactory(
                character_id=character_id
            )
            got, created = get_or_create_eve_character(1001)

        # then
        self.assertTrue(created)
        self.assertEqual(got.character_id, 1001)


class TestGetOrCreateEveCorporationInfo(NoSocketsTestCase):
    def test_should_return_character_when_it_exists(self):
        # given
        character = EveCorporationInfoFactory(corporation_id=2001)

        # when
        got, created = get_or_create_eve_corporation_info(2001)

        # then
        self.assertFalse(created)
        self.assertEqual(got, character)

    def test_should_create_character_when_it_does_not_exist(self):
        # when
        with patch(MODULE_PATH + ".EveCorporationInfo.objects.create_corporation") as m:
            m.side_effect = lambda corp_id: EveCorporationInfoFactory(
                corporation_id=corp_id
            )
            got, created = get_or_create_eve_corporation_info(2001)

        # then
        self.assertTrue(created)
        self.assertEqual(got.corporation_id, 2001)
