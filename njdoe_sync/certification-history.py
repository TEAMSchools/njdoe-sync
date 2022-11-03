import datetime
import json
import os
import pathlib

import njdoe
import requests
from google.cloud import storage

DAYFORCE_SUBDOMAIN = os.getenv("DAYFORCE_SUMDOMAIN")
DAYFORCE_USERNAME = os.getenv("DAYFORCE_USERNAME")
DAYFORCE_PASSWORD = os.getenv("DAYFORCE_PASSWORD")
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")

PROJECT_PATH = pathlib.Path(__file__).parent.absolute()
NOW_TIMESTAMP = datetime.datetime.now()
NOW_DATE_ISO = NOW_TIMESTAMP.date().isoformat()


def main():
    if not os.path.exists(SAVE_FOLDER):
        os.mkdir(SAVE_FOLDER)

    gcs_client = storage.Client()
    gcs_bucket = gcs_client.bucket(GCS_BUCKET_NAME)

    ## Dayforce query
    print("Loading Dayforce data...")
    dayforce_base_url = (
        f"https://www.dayforcehcm.com/OData/{DAYFORCE_SUBDOMAIN}/Reports/"
    )
    dayforce_auth = requests.auth.HTTPBasicAuth(DAYFORCE_USERNAME, DAYFORCE_PASSWORD)

    dayforce_base_response = requests.get(dayforce_base_url)
    if dayforce_base_response.history:
        dayforce_odata_url = dayforce_base_response.url
    else:
        dayforce_odata_url = dayforce_base_url

    service = ODataService(
        dayforce_odata_url, auth=dayforce_auth, reflect_entities=True
    )

    njdoe_export_entity = service.entities["export_njdoe"]
    njdoe_export_query = service.query(njdoe_export_entity)
    try:
        njdoe_export_data = njdoe_export_query.raw({"$select": "*", "$top": "100000"})
    except Exception as ex:
        print(ex)
        print("\tRetrying...")
        njdoe_export_data = njdoe_export_query.raw({"$select": "*", "$top": "100000"})

    for p in njdoe_export_data:
        employee_number = p["Reference_Code"]
        ssn = p["SSN/SIN"] or "000-00-0000"

        ssn_clean = ssn.replace("-", "")
        ssn1 = ssn_clean[:3]
        ssn2 = ssn_clean[3:5]
        ssn3 = ssn_clean[5:]

        last_names = set(
            [p["Last_Name"], p["Maiden_Name"], p["Preferred_Last_Name"]]
        )  # unique last name possibilites
        last_names = list(filter(None.__ne__, last_names))  # remove blanks

        for n in last_names:
            try:
                cc = njdoe.certification.application_status_check(n, ssn1, ssn2, ssn3)
                if cc:
                    cc["df_employee_number"] = employee_number
                    cc_filename = (
                        f"njdoe_certification_check_records_{employee_number}.json"
                    )
                    cc_filepath = f"{SAVE_FOLDER}/{cc_filename}"
                    with open(cc_filepath, "w+") as f:
                        json.dump(cc, f)

                    destination_blob_name = "njdoe/" + "/".join(
                        data_filename.parts[-2:]
                    )
                    blob = gcs_bucket.blob(destination_blob_name)
                    blob.upload_from_filename(data_filename)
                    print(f"\tUploaded to {destination_blob_name}!\n")

                    break
                else:
                    print("\tCERT NO MATCH -", employee_number, p["First_Name"], n)
            except:
                print("\tCERT ERROR -", employee_number, p["First_Name"], n)


if __name__ == "__main__":
    main()
