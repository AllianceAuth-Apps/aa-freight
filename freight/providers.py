"""ESI client provider for Freight."""

from pathlib import Path

from esi.openapi_clients import ESIClientProvider

from freight import __version__

spec_file = Path(__file__).parent / "openapi_2025-12-16.json"
esi = ESIClientProvider(
    compatibility_date="2025-12-16",
    ua_appname="aa-freight",
    ua_version=__version__,
    operations=[
        "GetCorporationsCorporationIdContracts",
        "GetUniverseStationsStationId",
        "GetUniverseStructuresStructureId",
        "PostUniverseNames",
    ],
    spec_file=spec_file,
)
