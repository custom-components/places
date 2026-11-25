"""Tests for the Nominatim probe developer tool."""

from collections.abc import Callable, Mapping
import json
from typing import Any
from urllib.error import URLError

import pytest

from tools.nominatim_probe import NominatimClient, ProbeError, format_city_mapping, main

ISSUE_550_ADDRESS = {
    "road": "Square's Quay",
    "city": "South Hams",
    "county": "Devon",
}
ISSUE_550_CHAIN = [
    {"rank_address": 27, "isaddress": True, "localname": "Square's Quay", "type": "residential"},
    {"rank_address": 16, "isaddress": False, "localname": "Kingsbridge", "type": "administrative"},
    {"rank_address": 16, "isaddress": True, "localname": "South Hams", "type": "administrative"},
]


def _fetch_from(routes: Mapping[str, Any]) -> Callable[[str], bytes]:
    """Build a fetch function that answers by endpoint path.

    Args:
        routes (Mapping[str, Any]):
            Endpoint path (such as ``/reverse``) to JSON body, or an exception to raise.

    Returns:
        Callable[[str], bytes]:
            Fetch function for ``NominatimClient``.
    """

    def fetch(url: str) -> bytes:
        """Return or raise the configured response for ``url``.

        Args:
            url (str):
                Requested URL.

        Returns:
            bytes:
                Encoded JSON body.

        Raises:
            OSError:
                The configured network or timeout error for the route.
        """
        path = url.split("?", maxsplit=1)[0].removeprefix("https://nominatim.openstreetmap.org")
        response = routes[path]
        if isinstance(response, OSError):
            raise OSError(response.errno, str(response)) from response
        return response if isinstance(response, bytes) else json.dumps(response).encode()

    return fetch


def _client(routes: Mapping[str, Any]) -> NominatimClient:
    """Build a client that answers from ``routes`` without waiting.

    Args:
        routes (Mapping[str, Any]):
            Responses by endpoint path.

    Returns:
        NominatimClient:
            Client with no real network or sleeping.
    """
    return NominatimClient(fetch=_fetch_from(routes), sleep=lambda _seconds: None)


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        pytest.param(
            ISSUE_550_ADDRESS,
            ["'South Hams' from address.city", "(empty)", "(empty)"],
            id="issue-550-parish-dropped",
        ),
        pytest.param(
            {**ISSUE_550_ADDRESS, "town": "Kingsbridge", "suburb": "Westville"},
            [
                "'South Hams' from address.city",
                "'Kingsbridge' from address.town",
                "'Westville' from address.suburb",
            ],
            id="healthy-parish-as-town",
        ),
    ],
)
def test_format_city_mapping(address: dict[str, str], expected: list[str]) -> None:
    """Report the address key Places would use for each city field.

    Args:
        address (dict[str, str]):
            Nominatim address mapping.
        expected (list[str]):
            Expected value text for city, postal town, and neighbourhood.
    """
    lines = format_city_mapping(address)

    assert [line.split(maxsplit=1)[1] for line in lines] == expected


def test_client_spaces_consecutive_requests() -> None:
    """Wait out the remaining spacing before a second request."""
    now = [100.0]
    sleeps: list[float] = []
    client = NominatimClient(
        fetch=lambda _url: b"{}",
        spacing=1.2,
        clock=lambda: now[0],
        sleep=sleeps.append,
    )

    client.get("/details", {})
    now[0] += 0.2
    client.get("/details", {})

    assert sleeps == [pytest.approx(1.0)]


@pytest.mark.parametrize(
    "response",
    [
        pytest.param(URLError("unreachable"), id="network"),
        pytest.param(TimeoutError("timed out"), id="timeout"),
        pytest.param(b"<html>busy</html>", id="not-json"),
        pytest.param({"error": "Unable to geocode"}, id="nominatim-error"),
    ],
)
def test_client_raises_probe_error(response: object) -> None:
    """Turn request, decode, and Nominatim errors into ``ProbeError``.

    Args:
        response (object):
            Exception or body returned for the request.
    """
    with pytest.raises(ProbeError, match="/reverse"):
        _client({"/reverse": response}).get("/reverse", {})


def test_main_reports_point_and_continues_after_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Print the mapping and address chain, and keep probing after a failed request.

    Args:
        capsys (pytest.CaptureFixture[str]):
            Captured stdout.
    """
    client = _client(
        {
            "/reverse": {
                "display_name": "Square's Quay",
                "osm_type": "way",
                "osm_id": 78058089,
                "address": ISSUE_550_ADDRESS,
            },
            "/details": {"localname": "Square's Quay", "address": ISSUE_550_CHAIN},
        }
    )
    failing_details = _fetch_from({"/details": TimeoutError("timed out")})

    first = main(["--point", "50.2818,-3.7770"], client=client)
    client._fetch = failing_details
    second = main(["--relation", "3544003", "--relation", "3600281"], client=client)

    out = capsys.readouterr().out
    assert first == 0
    assert "postal_town    (empty)" in out
    assert "16 no  'Kingsbridge' administrative" in out
    assert second == 1
    assert out.count("ERROR") == 2
