"""Probe Nominatim to explain the city, postal town, and neighbourhood a Place would get.

For each coordinate, the probe prints the reverse-geocoded ``address``, the keys Places
would pick for city, postal town, and neighbourhood (using the integration's own
``match_city_types``), and the Nominatim details address chain with ``rank_address`` and
``isaddress`` for each entry. For each OSM relation id, it prints the details rank
information and linked places.

Run from the repository root::

    ./.venv/bin/python -m tools.nominatim_probe --point 50.2818,-3.7770
    ./.venv/bin/python -m tools.nominatim_probe --relation 3544003 --relation 3600281

Requests carry a generic User-Agent, time out after ``REQUEST_TIMEOUT`` seconds, and are
spaced ``REQUEST_SPACING`` seconds apart to respect the Nominatim usage policy. Output is
flushed line by line so a background run shows progress.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
import json
import sys
import time
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from custom_components.places.parse_osm import match_city_types

NOMINATIM_URL = "https://nominatim.openstreetmap.org"
USER_AGENT = "places-nominatim-probe/1.0 (Home Assistant Places developer tool)"
REQUEST_TIMEOUT = 12.0
REQUEST_SPACING = 1.2

type Fetch = Callable[[str], bytes]


class ProbeError(Exception):
    """A Nominatim request failed or returned an unusable body."""


def _urlopen_fetch(url: str) -> bytes:
    """Fetch ``url`` with the probe User-Agent and timeout.

    Args:
        url (str):
            Fully built Nominatim URL; always under ``NOMINATIM_URL``.

    Returns:
        bytes:
            The raw response body.
    """
    request = Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310 - fixed https base
    with urlopen(request, timeout=REQUEST_TIMEOUT) as response:  # noqa: S310 - fixed https base
        body: bytes = response.read()
    return body


class NominatimClient:
    """Minimal Nominatim client that spaces requests and turns failures into ``ProbeError``."""

    def __init__(
        self,
        fetch: Fetch = _urlopen_fetch,
        spacing: float = REQUEST_SPACING,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Initialize the client.

        Args:
            fetch (Fetch):
                Callable returning the response body for a URL.
            spacing (float):
                Minimum seconds between the start of consecutive requests.
            clock (Callable[[], float]):
                Monotonic clock used to measure spacing.
            sleep (Callable[[float], None]):
                Sleep function used to wait out the spacing.
        """
        self._fetch = fetch
        self._spacing = spacing
        self._clock = clock
        self._sleep = sleep
        self._last_request: float | None = None

    def get(self, path: str, params: Mapping[str, str | int | float]) -> Any:
        """Request a Nominatim endpoint and decode its JSON body.

        Args:
            path (str):
                Endpoint path such as ``/reverse``.
            params (Mapping[str, str | int | float]):
                Query parameters.

        Returns:
            Any:
                The decoded JSON body.

        Raises:
            ProbeError:
                The request failed, timed out, or the body was not JSON, or Nominatim
                returned an ``error`` object.
        """
        if self._last_request is not None:
            wait = self._spacing - (self._clock() - self._last_request)
            if wait > 0:
                self._sleep(wait)
        url = f"{NOMINATIM_URL}{path}?{urlencode(params)}"
        self._last_request = self._clock()
        try:
            data = json.loads(self._fetch(url))
        except OSError as err:  # URLError and TimeoutError are OSErrors
            raise ProbeError(f"{url}: {err}") from err
        except ValueError as err:
            raise ProbeError(f"{url}: response is not JSON ({err})") from err
        if isinstance(data, dict) and "error" in data:
            raise ProbeError(f"{url}: {data['error']}")
        return data


def format_city_mapping(address: Mapping[str, Any]) -> list[str]:
    """Describe which ``address`` keys Places maps to city, postal town, and neighbourhood.

    Args:
        address (Mapping[str, Any]):
            Nominatim ``address`` mapping from a reverse response.

    Returns:
        list[str]:
            One line per field, naming the chosen key and value or ``(empty)``.
    """
    matched = match_city_types(address)
    lines = []
    for field, key in (
        ("city", matched.city),
        ("postal_town", matched.postal_town),
        ("neighbourhood", matched.neighbourhood),
    ):
        value = "(empty)" if key is None else f"{address[key]!r} from address.{key}"
        lines.append(f"  {field:<14} {value}")
    return lines


def format_details(details: Mapping[str, Any]) -> list[str]:
    """Summarize a Nominatim details response: ranks, index date, links, address chain.

    Args:
        details (Mapping[str, Any]):
            Body of ``/details`` requested with ``addressdetails`` and ``linkedplaces``.

    Returns:
        list[str]:
            Human-readable summary lines.
    """
    lines = [
        (
            f"  {details.get('localname')!r} {details.get('category')}={details.get('type')}"
            f" {details.get('osm_type')}{details.get('osm_id')}"
        ),
        (
            f"  admin_level={details.get('admin_level')}"
            f" rank_address={details.get('rank_address')}"
            f" rank_search={details.get('rank_search')}"
            f" indexed_date={details.get('indexed_date')}"
        ),
    ]
    lines.extend(
        f"  linked: {place.get('localname')!r} {place.get('class')}={place.get('type')}"
        f" {place.get('osm_type')}{place.get('osm_id')}"
        for place in details.get("linked_places") or []
    )
    address = details.get("address") or []
    if address:
        lines.append("  address chain (rank_address, isaddress, place_type/type, admin_level):")
        lines.extend(
            f"    {entry.get('rank_address'):>2} {'yes' if entry.get('isaddress') else 'no ':<3}"
            f" {entry.get('localname')!r} {entry.get('place_type') or entry.get('type')}"
            f" admin_level={entry.get('admin_level')}"
            f" {entry.get('osm_type') or ''}{entry.get('osm_id') or ''}"
            for entry in address
        )
    return lines


def _details(client: NominatimClient, osm_type: str, osm_id: int | str) -> Any:
    """Request ``/details`` for one OSM object with address and linked places.

    Args:
        client (NominatimClient):
            Client used for the request.
        osm_type (str):
            One-letter OSM type: ``N``, ``W``, or ``R``.
        osm_id (int | str):
            OSM object id.

    Returns:
        Any:
            The decoded details body.
    """
    return client.get(
        "/details",
        {
            "osmtype": osm_type,
            "osmid": osm_id,
            "addressdetails": 1,
            "linkedplaces": 1,
            "format": "json",
        },
    )


def probe_point(client: NominatimClient, lat: float, lon: float) -> list[str]:
    """Reverse-geocode a coordinate and explain the Places city fields.

    Args:
        client (NominatimClient):
            Client used for the requests.
        lat (float):
            Latitude.
        lon (float):
            Longitude.

    Returns:
        list[str]:
            Report lines for the coordinate.
    """
    reverse = client.get(
        "/reverse",
        {
            "format": "jsonv2",
            "lat": lat,
            "lon": lon,
            "addressdetails": 1,
            "namedetails": 1,
            "zoom": 18,
        },
    )
    address = reverse.get("address") or {}
    lines = [f"reverse {lat},{lon}: {reverse.get('display_name')!r}", "  address:"]
    lines.extend(f"    {key}: {value!r}" for key, value in address.items())
    lines.append("  Places mapping:")
    lines.extend(format_city_mapping(address))
    osm_type, osm_id = reverse.get("osm_type"), reverse.get("osm_id")
    if osm_type and osm_id:
        lines.append(f"details of reverse result {osm_type} {osm_id}:")
        lines.extend(format_details(_details(client, osm_type[0].upper(), osm_id)))
    return lines


def probe_relation(client: NominatimClient, relation_id: int) -> list[str]:
    """Explain the rank information Nominatim holds for an OSM relation.

    Args:
        client (NominatimClient):
            Client used for the request.
        relation_id (int):
            OSM relation id.

    Returns:
        list[str]:
            Report lines for the relation.
    """
    return [f"relation {relation_id}:", *format_details(_details(client, "R", relation_id))]


def _parse_point(value: str) -> tuple[float, float]:
    """Parse a ``LAT,LON`` command-line value.

    Args:
        value (str):
            Text in ``LAT,LON`` form.

    Returns:
        tuple[float, float]:
            Latitude and longitude.

    Raises:
        argparse.ArgumentTypeError:
            The value is not two comma-separated numbers.
    """
    try:
        lat, lon = (float(part) for part in value.split(","))
    except ValueError as err:
        raise argparse.ArgumentTypeError(f"expected LAT,LON, got {value!r}") from err
    return lat, lon


def main(argv: Sequence[str] | None = None, client: NominatimClient | None = None) -> int:
    """Run the probe for every requested coordinate and relation.

    Args:
        argv (Sequence[str] | None):
            Command-line arguments; defaults to ``sys.argv[1:]``.
        client (NominatimClient | None):
            Client to use; defaults to a live, throttled client.

    Returns:
        int:
            ``0`` when every probe succeeded, ``1`` when any failed.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--point", action="append", type=_parse_point, default=[])
    parser.add_argument("--relation", action="append", type=int, default=[])
    args = parser.parse_args(argv)
    if not args.point and not args.relation:
        parser.error("give at least one --point LAT,LON or --relation ID")

    client = client or NominatimClient()
    probes: list[Callable[[], list[str]]] = [
        *(lambda p=point: probe_point(client, *p) for point in args.point),
        *(lambda r=relation: probe_relation(client, r) for relation in args.relation),
    ]
    failed = False
    for probe in probes:
        try:
            lines = probe()
        except ProbeError as err:
            failed = True
            lines = [f"ERROR {err}"]
        for line in lines:
            print(line, flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
