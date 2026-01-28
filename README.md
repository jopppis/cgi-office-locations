# cgi-office-locations
CGI Finland office location finder

Geocoding via CGI Navici.

Scrape CGI office locations from https://www.cgi.com/fi/fi/toimipisteet using the page layout at 2026-01-28.

## Usage

Running the tool requires `uv`. [Install it](https://docs.astral.sh/uv/getting-started/installation/) and then run:

```bash
uv venv
uv pip install -r requirements.in
source .venv/bin/activate
python get-locations.py --navici-api-key APIKEY > offices.geojson
```
