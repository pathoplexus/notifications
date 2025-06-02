import json
import os
from time import sleep

import requests

organisms = ["ebola-sudan", "ebola-zaire", "mpox", "west-nile", "cchf", "rsv-a", "rsv-b", "hmpv"]
slack_webhook_url = os.environ["SLACK_WEBHOOK_URL"]

params = {
    "dataFormat": "json",
    "downloadAsFile": "false",
    "fields": ",".join(
        [
            "accessionVersion",
            "version",
            "authorAffiliations",
            "dataUseTerms",
            "geoLocCountry",
            "groupName",
            "groupId",
            "sampleCollectionDate",
            "releasedAtTimestamp",
        ]
    ),
}

for organism in organisms:
    base_url = f"https://lapis.pathoplexus.org/{organism}"
    url = f"{base_url}/sample/details"
    data = requests.get(url, params=params).json()["data"]

    notified_file = f"already_notified/notified_{organism}.txt"
    if os.path.exists(notified_file):
        with open(notified_file, "r") as f:
            notified = {line.strip() for line in f if line.strip()}
    else:
        notified = set()

    new_sequences = [seq for seq in data if seq["accessionVersion"] not in notified]

    if not new_sequences:
        print(f"No new sequences for {organism}")
        continue

    # Check if there are non-groupId=1 sequences and add alert to header
    direct_submission_count = len(
        [seq for seq in new_sequences if seq["groupId"] != 1 and seq["version"] == 1]
    )
    direct_submission_alert = (
        f"⚠️ SubmissionAlert: {direct_submission_count} new direct Pathoplexus submissions! 🎉"
        if direct_submission_count > 0
        else ""
    )
    header_base = f"{len(new_sequences)} new releases for {organism}"
    thread_header = header_base + "\n" + direct_submission_alert

    # Minimum and maximum releasedAtTimestamps of new sequences
    min_time = min(seq["releasedAtTimestamp"] for seq in new_sequences)
    max_time = max(seq["releasedAtTimestamp"] for seq in new_sequences)
    filter_url = (
        f"https://pathoplexus.org/{organism}/search?visibility_releasedAtTimestamp=true" +
        f"&releasedAtTimestampFrom={min_time - 1}&releasedAtTimestampTo={max_time + 1}"
    )

    message = (
        "Details of up to 10 new sequences (Slack can't handle more):\n"
        + "\n\n".join(json.dumps(seq, indent=2) for seq in new_sequences[:10])
    )

    print(f"Sending notification for {organism}")
    res = requests.post(
        slack_webhook_url,
        json={"text": message, "header": thread_header, "filterUrl": filter_url},
    )
    if res.status_code != 200:
        print(f"Failed to send notification for {organism}")
        print(res.text)
        continue
    print(f"Notification successfully sent for {organism}: {res.text}")
    with open(notified_file, "a") as f:
        for seq in new_sequences:
            f.write(seq["accessionVersion"] + "\n")
    sleep(5)
