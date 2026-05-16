"""Client helpers for OpenStreetMap lookup requests used by Places."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, MutableMapping
import json
import logging
from urllib.parse import urlencode

import aiohttp
from homeassistant.const import __version__ as ha_version
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, OSM_CACHE, OSM_THROTTLE, OSM_THROTTLE_INTERVAL_SECONDS, VERSION

_LOGGER = logging.getLogger(__name__)


class OSMClient:
    """Client for shared OSM request building and lookup behavior."""

    def __init__(self, hass: HomeAssistant, sensor_name: str) -> None:
        """Create an OSM client bound to a sensor for logging and HA context.

        Args:
            hass: Home Assistant instance.
            sensor_name: Sensor name used in log messages.
        """
        self._hass: HomeAssistant = hass
        self._sensor_name: str = sensor_name

    @staticmethod
    def reverse_url(
        latitude: object, longitude: object, language: str | None, email: str | None
    ) -> str:
        """Build the Nominatim reverse-geocode URL for the supplied coordinates.

        Args:
            latitude: Latitude for the reverse lookup.
            longitude: Longitude for the reverse lookup.
            language: Accept-Language value to request localized results.
            email: Nominatim contact email value.

        Returns:
            Fully encoded reverse geocode URL.
        """
        base_url = "https://nominatim.openstreetmap.org/reverse?format=json"
        params = {
            "lat": latitude,
            "lon": longitude,
            "accept-language": language or "",
            "addressdetails": "1",
            "namedetails": "1",
            "zoom": "18",
            "limit": "1",
            "email": email or "",
        }
        return f"{base_url}&{urlencode(params)}"

    @staticmethod
    def details_url(
        osm_type_abbr: str, osm_id: object, language: str | None, email: str | None
    ) -> str:
        """Build the Nominatim lookup URL for a typed OSM feature.

        Args:
            osm_type_abbr: One-letter OSM type prefix (N/W/R).
            osm_id: Object identifier for the feature.
            language: Accept-Language value to request localized details.
            email: Nominatim contact email value.

        Returns:
            Fully encoded OSM lookup URL.
        """
        return (
            "https://nominatim.openstreetmap.org/lookup?osm_ids="
            f"{osm_type_abbr}{osm_id}"
            "&format=json&addressdetails=1&extratags=1&namedetails=1"
            f"&email={email or ''}&accept-language={language or ''}"
        )

    @staticmethod
    def wikidata_url(wikidata_id: object) -> str:
        """Build the wikidata entity URL used by OSM extras lookup."""
        return f"https://www.wikidata.org/wiki/Special:EntityData/{wikidata_id}.json"

    async def get_json(self, url: str, name: str) -> MutableMapping[str, object] | None:
        """Fetch JSON from a URL with OSM cache and throttle behavior.

        Args:
            url: Absolute URL to query.
            name: Friendly label for log output.

        Returns:
            Parsed JSON mapping (or a list-item flattened to mapping), or
            ``None`` when the request or parse fails.
        """
        osm_cache: dict[str, object] = self._hass.data[DOMAIN][OSM_CACHE]
        if url in osm_cache:
            _LOGGER.debug(
                "(%s) %s data loaded from cache (Cache size: %s)",
                self._sensor_name,
                name,
                len(osm_cache),
            )
            cached_data = osm_cache[url]
            if isinstance(cached_data, Mapping):
                return dict(cached_data)
            return {}

        throttle = self._hass.data[DOMAIN][OSM_THROTTLE]
        async with throttle["lock"]:
            now = asyncio.get_running_loop().time()
            wait_time = max(0, OSM_THROTTLE_INTERVAL_SECONDS - (now - throttle["last_query"]))
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            throttle["last_query"] = asyncio.get_running_loop().time()

            _LOGGER.info("(%s) Requesting data for %s", self._sensor_name, name)
            _LOGGER.debug("(%s) %s URL: %s", self._sensor_name, name, url)

            get_dict: object | None = None
            user_agent = (
                f"Mozilla/5.0 (Home Assistant/{ha_version}) "
                f"{DOMAIN}/{VERSION} (+https://github.com/custom-components/places)"
            )
            headers: dict[str, str] = {"user-agent": user_agent}

            try:
                session = async_get_clientsession(self._hass)
                async with session.get(
                    url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    get_json_input = await response.text()
                    _LOGGER.debug(
                        "(%s) %s Response: %s",
                        self._sensor_name,
                        name,
                        get_json_input,
                    )
                    try:
                        get_dict = json.loads(get_json_input)
                    except json.decoder.JSONDecodeError as exc:
                        _LOGGER.warning(
                            "(%s) JSON Decode Error with %s info [%s: %s]: %s",
                            self._sensor_name,
                            name,
                            type(exc).__name__,
                            exc,
                            get_json_input,
                        )
                        return None
            except (
                TimeoutError,
                aiohttp.ClientError,
                aiohttp.ContentTypeError,
                OSError,
                RuntimeError,
            ) as exc:
                _LOGGER.warning(
                    "(%s) Error connecting to %s [%s: %s]: %s",
                    self._sensor_name,
                    name,
                    type(exc).__name__,
                    exc,
                    url,
                )
                return None

            if get_dict is None:
                return None

            if (
                isinstance(get_dict, list)
                and len(get_dict) == 1
                and isinstance(get_dict[0], Mapping)
            ):
                get_dict = get_dict[0]
                osm_cache[url] = get_dict
                return dict(get_dict) if isinstance(get_dict, MutableMapping) else None
            if not isinstance(get_dict, MutableMapping):
                return None

            if "error_message" in get_dict:
                _LOGGER.warning(
                    "(%s) An error occurred contacting the web service for %s: %s",
                    self._sensor_name,
                    name,
                    get_dict.get("error_message"),
                )
                return None

            osm_cache[url] = get_dict
            return get_dict
