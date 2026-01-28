import argparse
import json
import sys
import time
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup


def get_offices(
    url: str = "https://www.cgi.com/fi/fi/toimipisteet",
) -> List[Dict[str, Optional[str]]]:
    """
    Scrapes the CGI offices page and returns a list of office dictionaries.
    """
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Error fetching {url}: {e}", file=sys.stderr)
        sys.exit(1)

    soup = BeautifulSoup(response.content, "html.parser")
    offices = []

    # Office listings are wrapped in .vcard-wrapper
    for wrapper in soup.select(".vcard-wrapper"):
        vcard = wrapper.select_one(".vcard")
        if not vcard:
            continue

        # Extract name (e.g., "Helsinki - Karvaamokuja")
        # Often inside an h4 within .adr, or the .locality h4 if generic
        # Based on inspection:
        # <div class="adr">
        #   <h4>Helsinki - Karvaamokuja</h4> ...
        name_tag = vcard.select_one(".adr h4")
        locality_tag = vcard.select_one(".locality")

        name = name_tag.get_text(strip=True) if name_tag else None
        if not name and locality_tag:
            name = locality_tag.get_text(strip=True)

        if not name:
            continue

        # Extract address details
        street_tag = vcard.select_one(".thoroughfare")
        postal_tag = vcard.select_one(".postal-code")
        city_tag = vcard.select_one(
            ".adr .locality"
        )  # Prefer locality inside adr if exists

        if not city_tag:
            city_tag = locality_tag

        street = street_tag.get_text(strip=True) if street_tag else ""
        postal_code = postal_tag.get_text(strip=True) if postal_tag else ""
        city = city_tag.get_text(strip=True) if city_tag else ""

        full_address = f"{street}, {postal_code} {city}".strip().strip(",")

        # Fallback if street is missing (some might only have city)
        if not street:
            # If no street address, maybe skip or just use city
            # Based on inspection, most have street addresses.
            # If "Hämeenlinna" only has a phone number in the headers in the markdown view,
            # but let's check the HTML.
            # In the HTML view:
            # Hämeenlinna has <span class="postal-code">13100</span> but NO thoroughfare exposed in the snippet I saw?
            # Wait, looking at line 1000 in the view_file output:
            # It just has <span class="postal-code">13100</span> and phone.
            # No street address for Hämeenlinna?
            # If so, geocoding might fail or return city center.
            # We will try to geocode what we have.
            pass

        offices.append(
            {
                "name": name,
                "street": street,
                "postal_code": postal_code,
                "city": city,
                "full_address": full_address,
            }
        )

    return offices


def geocode_address(address: str, api_key: str) -> Optional[Any]:
    """
    Geocodes an address string using the Navici API.
    """
    url = "https://mapservices.navici.com/geocoding/geocode"
    params = {
        "address": address,
        "crs": "EPSG:3067",
        "lang": "fi",
        "source": "digiroadAddress|vrkAddress",
        "limit": 1,
        "apikey": api_key,
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"Error geocoding '{address}': {e}", file=sys.stderr)
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Generate GeoJSON of CGI Finland offices."
    )
    parser.add_argument(
        "--navici-api-key", required=True, help="API key for Navici Geocoding service"
    )
    args = parser.parse_args()

    offices = get_offices()
    print(f"Found {len(offices)} offices.", file=sys.stderr)

    features = []

    for office in offices:
        address = office["full_address"]
        if not address:
            print(f"Skipping {office['name']} (no address found)", file=sys.stderr)
            continue

        print(f"Geocoding: {office['name']} ({address})...", file=sys.stderr)

        # Add a small delay to be polite
        time.sleep(0.2)

        result = geocode_address(address, args.navici_api_key)

        if not result:
            continue

        # Inspect result structure to find coordinates
        # Assuming result is a list of features or a FeatureCollection
        # If it's a list, we take the first item.
        # If it's a dict check for 'features' key.

        match = None
        if isinstance(result, list) and len(result) > 0:
            match = result[0]
        elif isinstance(result, dict) and "features" in result:
            if len(result["features"]) > 0:
                match = result["features"][0]

        if match:
            # We construct our own Feature to ensure clean output structure
            # But if Navici returns a GeoJSON Feature, we can just use it or enrich it.
            # Let's create a new feature with our properties.

            # Helper to get geometry
            geometry = match.get("geometry")
            if not geometry:
                # Check if top level has lat/lon
                if "latitude" in match and "longitude" in match:
                    geometry = {
                        "type": "Point",
                        "coordinates": [
                            float(match["longitude"]),
                            float(match["latitude"]),
                        ],
                    }

            if geometry:
                feature = {
                    "type": "Feature",
                    "geometry": geometry,
                    "properties": {
                        "city": office["city"],
                    },
                }
                features.append(feature)
            else:
                print(f"No geometry in response for {address}", file=sys.stderr)
        else:
            print(f"No match found for {address}", file=sys.stderr)

    geojson = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:3067"}},
        "features": features,
    }

    print(json.dumps(geojson, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
