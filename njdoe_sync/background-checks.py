import datetime
import json
import os
import pathlib
import sys
import time
import traceback
from collections import deque

import njdoe
from google.cloud import storage

GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")
ADP_MODULE_PATH = os.getenv("ADP_MODULE_PATH")
ADP_CLIENT_ID = os.getenv("ADP_CLIENT_ID")
ADP_CLIENT_SECRET = os.getenv("ADP_CLIENT_SECRET")
ADP_CERT_FILEPATH = os.getenv("ADP_CERT_FILEPATH")
ADP_KEY_FILEPATH = os.getenv("ADP_KEY_FILEPATH")
TARGET_STAFF_FILE = os.getenv("TARGET_STAFF_FILE")
WAIT_TIME = int(os.getenv("WAIT_TIME"))

PROJECT_PATH = pathlib.Path(__file__).parent.absolute()
NOW_TIMESTAMP = datetime.datetime.now()
NOW_DATE_ISO = NOW_TIMESTAMP.date().isoformat()

sys.path.insert(0, ADP_MODULE_PATH)
import adp  # noqa: E402


def main():
    with open(TARGET_STAFF_FILE) as f:
        staff = json.load(f)

    file_dir = PROJECT_PATH / "data" / "background_check"
    if not file_dir.exists():
        file_dir.mkdir(parents=True)

    adp_client = adp.authorize(
        ADP_CLIENT_ID, ADP_CLIENT_SECRET, ADP_CERT_FILEPATH, ADP_KEY_FILEPATH
    )
    adp_client.headers["Accept"] = "application/json;masked=false"

    gcs_client = storage.Client()
    gcs_bucket = gcs_client.bucket(GCS_BUCKET_NAME)

    print("Downloading worker data from ADP...")
    querystring = {
        "$select": ",".join(
            [
                "worker/person/governmentIDs",
                "worker/person/birthDate",
            ]
        ),
    }

    adp_staff = [
        s
        | adp.get_record(
            adp_client, "/hr/v2/workers", querystring, id=s["associate_oid"]
        )[0]
        for s in staff
    ]

    for p in adp_staff:
        worker_id = p.get("workerID").get("idValue")
        govt_ids = p.get("person").get("governmentIDs")
        ssn = next(
            iter(
                [
                    gi.get("idValue")
                    for gi in govt_ids
                    if gi.get("nameCode").get("codeValue") == "SSN"
                ]
            ),
            None,
        )

        birth_date = p.get("person").get("birthDate")
        dob = deque(birth_date.split("-"))
        dob.rotate(-1)

        if not all([ssn, dob]):
            print(f"{worker_id}\n\tMISSING DATA")
            continue

        try:
            bg = njdoe.criminal_history.get_applicant_approval_employment_history(
                *ssn.split("-"), *dob
            )
            if bg:
                bg["worker_id"] = worker_id
                bg["employee_number"] = p["employee_number"]

                file_name = f"njdoe_backround_check_records_{p['employee_number']}.json"
                file_path = file_dir / file_name
                with open(file_path, "w+") as f:
                    json.dump(bg, f)

                destination_blob_name = f"njdoe/{'/'.join(file_path.parts[-2:])}"
                blob = gcs_bucket.blob(destination_blob_name)
                blob.upload_from_filename(file_path)
                print(f"{worker_id}\n\tUploaded to {destination_blob_name}!")
            else:
                print(f"{worker_id}\n\tNO MATCH")
        except Exception as xc:
            print(f"{worker_id}\n\tERROR")
            print(xc)
            print(traceback.format_exc())
        finally:
            time.sleep(WAIT_TIME)


if __name__ == "__main__":
    try:
        main()
    except Exception as xc:
        print(xc)
        print(traceback.format_exc())
