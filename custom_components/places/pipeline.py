"""Update orchestration pipeline for Places entity refreshes."""

from __future__ import annotations

from collections.abc import MutableMapping
from datetime import datetime
import logging
from typing import TYPE_CHECKING, Any

from .const import ATTR_LAST_PLACE_NAME, CONF_NAME, UpdateStatus

if TYPE_CHECKING:
    from .update_sensor import PlacesUpdater

_LOGGER = logging.getLogger(__name__)


class PlacesUpdatePipeline:
    """Run the Places updater through its ordered update phases."""

    def __init__(self, updater: PlacesUpdater) -> None:
        """Create a pipeline instance for a single updater.

        Args:
            updater: Active updater coordinating all update phases.
        """
        self.updater = updater

    async def run(self, reason: str, previous_attr: MutableMapping[str, Any]) -> None:
        """Execute a full update in the legacy phase order.

        Args:
            reason: Human-readable update reason.
            previous_attr: Snapshot of attributes captured before the update start.
        """
        await self.updater.log_update_start(reason)
        now: datetime = await self.updater.get_current_time()

        await self.updater.update_entity_name_and_cleanup()
        await self.updater.update_client_sensor_name()
        await self.updater.update_previous_state()
        await self.updater.update_old_coordinates()
        prev_last_place_name = self.updater.sensor.get_attr_safe_str(ATTR_LAST_PLACE_NAME)

        proceed_with_update: UpdateStatus = (
            await self.updater.check_device_tracker_and_update_coords()
        )
        if proceed_with_update == UpdateStatus.PROCEED:
            proceed_with_update = await self.updater.determine_update_criteria()

        if proceed_with_update == UpdateStatus.PROCEED:
            await self.updater.process_osm_update(now=now)

            if await self.updater.should_update_state(now=now):
                await self.updater.handle_state_update(
                    now=now, prev_last_place_name=prev_last_place_name
                )
            else:
                _LOGGER.info(
                    "(%s) No entity update needed, Previous State = New State",
                    self.updater.sensor.get_attr(CONF_NAME),
                )
                await self.updater.rollback_update(previous_attr, now, proceed_with_update)
        else:
            await self.updater.rollback_update(previous_attr, now, proceed_with_update)

        await self.updater.finish_update(now=now)
