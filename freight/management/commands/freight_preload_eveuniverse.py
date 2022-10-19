from django.core.management.base import BaseCommand, CommandError
from eveuniverse.models import EveEntity

from allianceauth.services.hooks import get_extension_logger
from app_utils.esi import fetch_esi_status
from app_utils.logging import LoggerAddTag

from ... import __title__
from ...models import ContractHandler

logger = LoggerAddTag(get_extension_logger(__name__), __title__)


class Command(BaseCommand):
    help = (
        "Preload missing eveuniverse objects in preparation "
        "for migrating to eveuniverse with release 2."
    )

    def handle(self, *args, **options):
        if not fetch_esi_status().is_ok:
            raise CommandError("ESI currently not available. Aborting.")
        logger.info("Running command for preloading eveuniverse objects.")
        models_map = [(ContractHandler, "organization", EveEntity)]
        for (FreightModel, freight_field, EveuniverseModel) in models_map:
            ids_target = {
                value
                for value in FreightModel.objects.values_list(
                    f"{freight_field}_id", flat=True
                )
                if value is not None
            }
            ids_current = set(EveuniverseModel.objects.values_list("id", flat=True))
            ids_diff = ids_target.difference(ids_current)
            if ids_diff:
                logger.info("%s: Missing IDs: %s", FreightModel.__name__, ids_diff)
                self.stdout.write(
                    f"{FreightModel.__name__}: Need to fetch {len(ids_diff)} "
                    "missing object(s) from ESI."
                )
            else:
                logger.info("%s: No missing IDs", FreightModel.__name__)
                self.stdout.write(f"{FreightModel.__name__}: OK")
            EveuniverseModel.objects.bulk_get_or_create_esi(ids=ids_target)
        logger.info("Preloading eveuniverse objects completed")
        self.stdout.write(self.style.SUCCESS("DONE"))
