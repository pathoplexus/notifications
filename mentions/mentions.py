import json
import os

import requests

# Europe PMC fully indexes bioRxiv and medRxiv preprint text and exposes a
# keyword search API, so it is used here to find preprints that *mention*
# Pathoplexus (the official bioRxiv/medRxiv API only supports date/DOI lookups,
# not full-text search).
EUROPEPMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

# bioRxiv and medRxiv are both published by Cold Spring Harbor Laboratory under
# the 10.1101 DOI prefix. Restricting SRC:PPR (preprint) results to this prefix
# keeps just those two servers and drops other preprint servers.
CSHL_DOI_PREFIX = "10.1101/"

SEARCH_TERM = "pathoplexus"
# SRC:PPR limits to preprints; the DOI-prefix filter below narrows to bioRxiv/medRxiv.
QUERY = f'{SEARCH_TERM} AND (SRC:PPR)'

slack_webhook_url = os.environ["SLACK_WEBHOOK_URL"]

notified_file = "already_notified/notified_preprints.txt"
if os.path.exists(notified_file):
    with open(notified_file, "r") as f:
        notified = {line.strip() for line in f if line.strip()}
else:
    notified = set()


def fetch_all_hits():
    """Fetch every Europe PMC hit for the query, following cursorMark pagination."""
    results = []
    cursor = "*"
    while True:
        params = {
            "query": QUERY,
            "format": "json",
            "resultType": "core",
            "pageSize": 100,
            "cursorMark": cursor,
        }
        resp = requests.get(EUROPEPMC_SEARCH_URL, params=params)
        resp.raise_for_status()
        payload = resp.json()
        page = payload.get("resultList", {}).get("result", [])
        results.extend(page)
        next_cursor = payload.get("nextCursorMark")
        # Stop when the cursor stops advancing or a page comes back empty.
        if not page or not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
    return results


def preprint_server(result):
    """Best-effort label of which server a 10.1101 preprint came from."""
    urls = result.get("fullTextUrlList", {}).get("fullTextUrl", [])
    for entry in urls:
        url = (entry.get("url") or "").lower()
        if "medrxiv.org" in url:
            return "medRxiv"
        if "biorxiv.org" in url:
            return "bioRxiv"
    return "bioRxiv/medRxiv"


def result_key(result):
    """Stable identifier for deduplication across runs."""
    doi = result.get("doi")
    if doi:
        return doi.lower()
    return f"{result.get('source', 'PPR')}:{result.get('id')}"


all_hits = fetch_all_hits()
print(f"Europe PMC returned {len(all_hits)} preprint hit(s) for '{SEARCH_TERM}'")

# Keep only bioRxiv/medRxiv (Cold Spring Harbor Laboratory) preprints.
preprints = [h for h in all_hits if (h.get("doi") or "").startswith(CSHL_DOI_PREFIX)]
print(f"{len(preprints)} of those are bioRxiv/medRxiv preprints")

new_preprints = [p for p in preprints if result_key(p) not in notified]

if not new_preprints:
    print("No new Pathoplexus mentions on bioRxiv/medRxiv")
    raise SystemExit(0)

# Newest first.
new_preprints.sort(key=lambda p: p.get("firstPublicationDate", ""), reverse=True)

header = (
    f"{len(new_preprints)} new bioRxiv/medRxiv preprint(s) mentioning Pathoplexus 📄"
)

lines = []
for p in new_preprints[:10]:
    server = preprint_server(p)
    doi = p.get("doi", "")
    doi_url = f"https://doi.org/{doi}" if doi else ""
    lines.append(
        json.dumps(
            {
                "server": server,
                "title": p.get("title"),
                "authors": p.get("authorString"),
                "firstPublicationDate": p.get("firstPublicationDate"),
                "doi": doi,
                "url": doi_url,
            },
            indent=2,
        )
    )

message_intro = "Details of up to 10 new preprints (Slack can't handle more):\n"
message = message_intro + "\n\n".join(lines)

filter_url = (
    "https://europepmc.org/search?query="
    + requests.utils.quote(QUERY)
)

print(f"Sending notification for {len(new_preprints)} new mention(s)")
res = requests.post(
    slack_webhook_url,
    json={"text": message, "header": header, "filterUrl": filter_url},
)
if res.status_code != 200:
    print("Failed to send notification")
    print(res.text)
    raise SystemExit(1)

print(f"Notification successfully sent: {res.text}")
with open(notified_file, "a") as f:
    for p in new_preprints:
        f.write(result_key(p) + "\n")
