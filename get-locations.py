#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#   "requests",
#   "beautifulsoup4",
#   "pandas",
#   "geopy",
#   "folium",
# ]
# ///
"""Download CGI office locations."""

import re

import folium
import pandas as pd
import requests
from bs4 import BeautifulSoup
from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim


def scrape_cgi_locations():
    """
    Scrape CGI office locations using BeautifulSoup
    Returns a pandas DataFrame with structured location data
    """

    url = "https://www.cgi.com/en/about-us/locations"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.content, "html.parser")

    locations = parse_structured_content(soup)
    df = pd.DataFrame(locations)

    # Clean and standardize
    if not df.empty:
        for col in ["region", "country", "state_province", "city", "address"]:
            if col in df.columns and df[col].dtype == "object":
                df[col] = df[col].str.strip()

    return df


def parse_text_content(text):
    """Parse location data from raw text"""

    locations = []
    lines = [line.strip() for line in text.split("\n") if line.strip()]

    regions = ["Africa", "Asia Pacific", "Europe", "The Americas"]
    current_region = None
    current_country = None
    current_state = None

    i = 0
    while i < len(lines):
        line = lines[i]

        # Detect regions
        if line in regions:
            current_region = line
            i += 1
            continue

        # Skip separator lines
        if line == "-":
            i += 1
            continue

        # Check if this is a country (typically follows region)
        # Countries are usually capitalized and not addresses
        if current_region and not any(char.isdigit() for char in line):
            if len(line) < 50 and line[0].isupper():
                # Could be country or state
                if current_country is None or i > 0 and lines[i - 1] == "-":
                    current_country = line
                    current_state = None
                else:
                    current_state = line

        # Look for address patterns (contain numbers, postal codes)
        if re.search(r"\d", line) and i + 1 < len(lines):
            city = lines[i - 1] if i > 0 else None

            # Collect address lines
            address_parts = [line]
            j = i + 1
            while j < len(lines) and j < i + 4:
                next_line = lines[j]
                if next_line.startswith("[") or next_line == "-":
                    break
                if any(
                    keyword in next_line.lower()
                    for keyword in ["tel", "fax", "telephone"]
                ):
                    break
                address_parts.append(next_line)
                j += 1

            if city and current_region and current_country:
                locations.append(
                    {
                        "region": current_region,
                        "country": current_country,
                        "state_province": current_state,
                        "city": city,
                        "address": " ".join(address_parts),
                    }
                )

        i += 1

    return locations


def parse_structured_content(soup):
    """
    Parse structured HTML content using dt (region) -> h2 (country) -> h3 (state) -> div.adr (office) hierarchy
    """
    locations = []

    current_region = None
    current_country = None
    current_state = None

    # Valid regions to filter out non-location dt headers
    valid_regions = ["Africa", "Asia Pacific", "Europe", "The Americas"]

    # Find all relevant elements in order
    elements = soup.find_all(["dt", "h2", "h3", "div"])

    for elem in elements:
        tag = elem.name
        text = elem.get_text(strip=True)

        if tag == "dt":
            # Region level - only process valid geographic regions
            if text in valid_regions:
                current_region = text
                current_country = None
                current_state = None

        elif tag == "h2":
            # Country level - only process if we're in a valid region
            if current_region:
                current_country = text
                current_state = None

        elif tag == "h3":
            # State/Province level - only process if we're in a valid region and have a country
            if current_region and current_country:
                current_state = text

        elif tag == "div" and "adr" in elem.get("class", []):
            # Office location within div.adr
            if current_region and current_country:
                # Extract city/office name from h4 (if present) or locality
                h4 = elem.find("h4")
                locality = elem.find("span", class_="locality")

                if h4:
                    city = h4.get_text(strip=True)
                elif locality:
                    city = locality.get_text(strip=True)
                else:
                    # Skip if we can't determine the city
                    continue

                # Extract address components
                address_parts = []

                # Street address
                street_block = elem.find("span", class_="street-block")
                if street_block:
                    address_parts.append(street_block.get_text(strip=True))

                # Locality (city)
                locality = elem.find("span", class_="locality")
                if locality:
                    locality_text = locality.get_text(strip=True)
                    if locality_text:
                        address_parts.append(locality_text)

                # Postal code
                postal_code = elem.find("span", class_="postal-code")
                if postal_code:
                    postal_text = postal_code.get_text(strip=True)
                    if postal_text:
                        address_parts.append(postal_text)

                # Create location entry
                locations.append(
                    {
                        "region": current_region,
                        "country": current_country,
                        "state_province": current_state,
                        "city": city,
                        "address": ", ".join(address_parts) if address_parts else None,
                    }
                )

    return locations


def extract_location_from_div(div):
    """Extract location details from a div element"""
    try:
        # Extract city, address, phone, etc.
        city_elem = div.find(["h3", "h4", "h5"])
        address_elem = div.find("address") or div.find("div", class_="address")

        if city_elem:
            return {
                "city": city_elem.get_text(strip=True),
                "address": address_elem.get_text(strip=True) if address_elem else None,
            }
    except:
        pass
    return None


def geocode_addresses(df):
    """
    Add latitude and longitude using geocoding
    """
    geolocator = Nominatim(user_agent="cgi_location_analyzer")
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=2)

    df["full_address"] = df.apply(
        lambda x: f"{x['address']}, {x['city']}, {x['country']}"
        if pd.notna(x["address"])
        else f"{x['city']}, {x['country']}",
        axis=1,
    )

    df["location"] = df["full_address"].apply(geocode)
    df["latitude"] = df["location"].apply(lambda loc: loc.latitude if loc else None)
    df["longitude"] = df["location"].apply(lambda loc: loc.longitude if loc else None)

    return df


def analyze_locations(df):
    """Perform analysis on location data"""

    print("=== CGI Office Location Analysis ===\n")
    print(f"Total offices found: {len(df)}\n")

    # By region
    print("Offices by Region:")
    print(df["region"].value_counts().to_string())
    print()

    # By country
    print("\nTop 15 Countries:")
    print(df["country"].value_counts().head(15).to_string())
    print()

    # Countries per region
    print("\nCountries per Region:")
    print(df.groupby("region")["country"].nunique().to_string())

    return df


def create_visualization(df):
    """
    Create a map visualization of CGI offices
    Requires: pip install folium
    """
    try:
        # Center map on world
        m = folium.Map(location=[20, 0], zoom_start=2)

        # Add markers for each office
        for idx, row in df.iterrows():
            if pd.notna(row.get("latitude")) and pd.notna(row.get("longitude")):
                folium.Marker(
                    location=[row["latitude"], row["longitude"]],
                    popup=f"{row['city']}, {row['country']}",
                    tooltip=row["city"],
                ).add_to(m)

        m.save("cgi_offices_map.html")
        print("Map saved to cgi_offices_map.html")

    except ImportError:
        print("folium not installed. Run: pip install folium")


if __name__ == "__main__":
    print("Scraping CGI locations from website...")
    df = scrape_cgi_locations()

    if df.empty:
        print("No locations found. Check the website structure.")
    else:
        print(f"\nSuccessfully scraped {len(df)} locations!")
        print("\nSample data:")
        print(df.head(10))

        # Analyze
        analyze_locations(df)

        df = geocode_addresses(df)

        # Export
        df.to_csv("cgi_locations.csv", index=False)
        print("\n✓ Data exported to cgi_locations.csv")

        create_visualization(df)
