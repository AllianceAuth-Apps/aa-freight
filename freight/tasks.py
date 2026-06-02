"""Tasks for Freight."""

from celery import chain, shared_task

from esi.decorators import rate_limit_retry_task

from allianceauth.services.hooks import get_extension_logger
from allianceauth.services.tasks import QueueOnce

from .models import Contract, ContractHandler, Location

logger = get_extension_logger(__name__)


@shared_task(base=QueueOnce, bind=True)
@rate_limit_retry_task
def update_contracts_esi(_self, force_sync=False) -> None:
    """start syncing contracts"""
    _contract_handler().update_contracts_esi(force_sync)


@shared_task(base=QueueOnce)
def send_contract_notifications(force_sent=False, rate_limited=True) -> None:
    """Send notification about outstanding contracts that have pricing"""
    Contract.objects.send_notifications(force_sent, rate_limited)


@shared_task
def run_contracts_sync(force_sync=False) -> None:
    """main task coordinating contract sync"""
    my_chain = chain(
        update_contracts_esi.si(force_sync), send_contract_notifications.si()
    )
    my_chain.delay()


@shared_task
def update_contracts_pricing() -> int:
    """Updates pricing for all contracts"""
    update_count = Contract.objects.filter_not_completed().update_pricing()
    logger.info("Updated pricing for %s contracts", update_count)
    return update_count


@shared_task(base=QueueOnce, bind=True)
@rate_limit_retry_task
def update_location(_self, location_id: int) -> None:
    """Updates the location from ESI"""
    Location.objects.get(id=location_id)
    token = _contract_handler().token()
    Location.objects.update_or_create_esi(location_id=location_id, token=token)


@shared_task
def update_locations(location_ids: list) -> None:
    """Updates the locations from ESI"""
    for location_id in location_ids:
        update_location.delay(location_id)


def _contract_handler() -> ContractHandler:
    """Return the contract handler if it exists or raise an error."""
    handler = ContractHandler.objects.first()
    if not handler:
        raise RuntimeError("No contract handler was found.")
    return handler
