"""
download_ddt.py
Scrapes the CDER & CBER DDT Qualification Project Search database
(a Salesforce Aura site with no public API) by driving a headless
browser and capturing the project-records network response.

Output: ddt_projects.csv (all DDT projects with project number, title,
program, status, stage dates). ddtProjectNumber (e.g. DDT-COA-000084)
is the key that bridges to coa_submissions.csv.
"""
import csv
import json
from playwright.sync_api import sync_playwright

DDT_URL = "https://force-dsc.my.site.com/ddt/s/"
OUT = "ddt_projects.csv"


def scrape_ddt_projects():
    records = []

    def on_response(resp):
        if "aura" in resp.url and resp.request.method == "POST":
            try:
                data = json.loads(resp.text())
            except Exception:
                return
            for action in data.get("actions", []):
                rv = action.get("returnValue")
                if (isinstance(rv, list) and rv
                        and isinstance(rv[0], dict)
                        and "projectURL" in rv[0]):
                    records.extend(rv)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("response", on_response)
        page.goto(DDT_URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(3000)
        browser.close()

    return records


def main():
    records = scrape_ddt_projects()
    if not records:
        print("No records captured. Site structure may have changed.")
        return
    keys = list(records[0].keys())
    with open(OUT, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for r in records:
            writer.writerow({k: r.get(k, "") for k in keys})
    print(f"Saved {OUT} with {len(records)} DDT project records")


if __name__ == "__main__":
    main()
