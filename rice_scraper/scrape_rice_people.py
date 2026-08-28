#!/usr/bin/env python3
"""Download the public Rice people directory for every residential college."""

import argparse
import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BASE_URL = "https://search.rice.edu"
CURRENT_ACADEMIC_YEAR = 2026
MINIMUM_MATRICULATION_YEAR = 2020
NON_STUDENT_AFFILIATIONS = {"academic visitor", "visiting student", "none"}
COLLEGES = [
    ("Baker College", "baker-college"),
    ("Brown College", "brown-college"),
    ("Chao College", "chao-college"),
    ("Duncan College", "duncan-college"),
    ("Hanszen College", "hanszen-college"),
    ("Jones College", "jones-college"),
    ("Lovett College", "lovett-college"),
    ("Martel College", "martel-college"),
    ("McMurtry College", "mcmurtry-college"),
    ("Sid Richardson College", "sid-richardson-college"),
    ("Wiess College", "wiess-college"),
    ("Will Rice College", "will-rice-college"),
]
def css_classes(attrs):
    values = dict(attrs)
    return set(values.get("class", "").split())


class PeopleParser(HTMLParser):
    """Parse the directory's result blocks without requiring third-party packages."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.records: List[Dict[str, str]] = []
        self.current: Optional[Dict[str, str]] = None
        self.current_field: Optional[str] = None
        self.label_parts: List[str] = []
        self.value_parts: List[str] = []
        self.in_label = False
        self.in_name = False
        self.in_phone = False

    def handle_starttag(self, tag, attrs):
        classes = css_classes(attrs)
        if tag == "div" and "results" in classes:
            self.current = {}
        elif self.current is not None and tag == "h1":
            self.in_name = True
        elif self.current is not None and tag == "h2" and "phone" in classes:
            self.in_phone = True
        elif self.current is not None and tag == "p":
            self.current_field = next(iter(classes), None)
            self.label_parts = []
            self.value_parts = []
        elif self.current_field is not None and tag == "label":
            self.in_label = True

    def handle_endtag(self, tag):
        if tag == "h1":
            self.in_name = False
        elif tag == "h2" and self.in_phone:
            phone = " ".join("".join(self.value_parts).split())
            if phone:
                self.current["phone"] = phone
            self.in_phone = False
        elif tag == "label":
            self.in_label = False
        elif tag == "p" and self.current is not None and self.current_field:
            value = " ".join("".join(self.value_parts).split())
            if value:
                label = " ".join("".join(self.label_parts).split()).rstrip(":")
                key = re.sub(r"[^a-z0-9]+", "_", (label or self.current_field).lower()).strip("_")
                self.current[key] = value
            self.current_field = None
        elif tag == "div" and self.current is not None:
            if self.current.get("name"):
                self.records.append(self.current)
            self.current = None

    def handle_data(self, data):
        if self.current is None:
            return
        if self.in_name:
            self.current["name"] = " ".join((self.current.get("name", "") + data).split())
        elif self.in_phone:
            self.value_parts.append(data)
        elif self.current_field is not None:
            if self.in_label:
                self.label_parts.append(data)
            else:
                self.value_parts.append(data)


def fetch(url: str, timeout: int) -> str:
    request = Request(url, headers={"User-Agent": "RiceStudentLookup/1.0 (public directory export)"})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def scrape_college(display_name: str, slug: str, timeout: int, retries: int) -> List[Dict[str, str]]:
    url = f"{BASE_URL}/people/college/{slug}/"
    last_error = None
    for attempt in range(retries + 1):
        try:
            parser = PeopleParser()
            parser.feed(fetch(url, timeout))
            for record in parser.records:
                record.pop("phone", None)
                record["college"] = record.get("college", display_name)
                record["college_page"] = url
            return parser.records
        except (HTTPError, URLError, TimeoutError) as error:
            last_error = error
            if attempt < retries:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"{display_name}: {last_error}")


def classify_records(records: List[Dict[str, str]]):
    """Separate high-confidence students, review cases, and excluded records."""
    review = []
    removed = []
    eligible = []
    grade_names = {1: "Freshman", 2: "Sophomore", 3: "Junior", 4: "Senior"}
    for record in records:
        affiliation = record.get("affiliation", "").strip().lower()
        if record.get("name") == "Lim, Paul":
            removed_record = dict(record)
            removed_record["removal_reason"] = "known incorrect record"
            removed.append(removed_record)
            continue
        if affiliation == "staff":
            removed_record = dict(record)
            removed_record["removal_reason"] = "staff affiliation"
            removed.append(removed_record)
            continue
        if affiliation in NON_STUDENT_AFFILIATIONS:
            removed_record = dict(record)
            removed_record["removal_reason"] = "non-student affiliation"
            removed.append(removed_record)
            continue
        term = record.get("matriculation_term", "")
        match = re.fullmatch(r"(Fall|Spring) (\d{4})", term)
        reason = None
        override_grade = None
        super_senior = False
        if match:
            matriculation_year = int(match.group(2)) - (1 if match.group(1) == "Spring" else 0)
        else:
            matriculation_year = None
        if matriculation_year is not None and matriculation_year < MINIMUM_MATRICULATION_YEAR:
            removed_record = dict(record)
            removed_record["removal_reason"] = "matriculation term before 2020"
            removed.append(removed_record)
            continue
        elif not match:
            reason = "missing or non-fall matriculation term"
        else:
            years_since_matriculation = CURRENT_ACADEMIC_YEAR - matriculation_year + 1
            calculated_grade = grade_names.get(years_since_matriculation)
            if match.group(1) == "Fall" and match.group(2) == "2022":
                override_grade = "Senior"
                super_senior = True
            elif calculated_grade == "Freshman" and affiliation == "junior":
                override_grade = "Freshman"
            elif calculated_grade == "Sophomore" and affiliation == "senior":
                override_grade = "Sophomore"
            elif calculated_grade is None:
                reason = "matriculation year may indicate a gap year, extended program, or graduate student"
            elif affiliation not in grade_names.values() and affiliation not in {grade.lower() for grade in grade_names.values()}:
                reason = "affiliation is not a standard class standing"
            elif abs(
                list(grade_names.values()).index(affiliation.title())
                - list(grade_names.values()).index(calculated_grade)
            ) > 1:
                reason = "calculated grade differs from listed affiliation"
        if reason:
            review_record = dict(record)
            review_record["review_priority"] = "high" if "missing" in reason or "not a standard" in reason else "medium"
            review_record["possible_reason"] = reason
            review.append(review_record)
        else:
            record["calculated_grade"] = override_grade or grade_names[CURRENT_ACADEMIC_YEAR - matriculation_year + 1]
            if match.group(1) == "Spring":
                record["grade_calculation_note"] = "Spring term treated as prior Fall"
            if super_senior:
                record["grade_note"] = "*"
            eligible.append(record)
    return eligible, review, removed


def write_outputs(records: List[Dict[str, str]], flagged_records: List[Dict[str, str]], removed_records: List[Dict[str, str]], output_dir: Path, scraped_at: str):
    output_dir.mkdir(parents=True, exist_ok=True)
    addresses = {record.get("address") for record in records + flagged_records}
    if len(addresses) == 1 and None not in addresses:
        for record in records + flagged_records:
            record.pop("address", None)
    json_path = output_dir / "rice_people.json"
    csv_path = output_dir / "rice_people.csv"
    flagged_path = output_dir / "flagged_people.json"
    review_path = output_dir / "review_people.json"
    removed_path = output_dir / "removed_people.json"
    metadata_path = output_dir / "scrape_metadata.json"
    json_path.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    preferred_columns = ["name", "college", "affiliation", "calculated_grade", "matriculation_term", "major", "address", "email", "college_page"]
    columns = preferred_columns + sorted({key for record in records for key in record} - set(preferred_columns))
    with csv_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    metadata_path.write_text(
        json.dumps(
            {
                "scraped_at_utc": scraped_at,
                "college_count": len(COLLEGES),
                "scraped_person_count": len(records) + len(flagged_records) + len(removed_records),
                "exported_person_count": len(records),
                "flagged_person_count": len(flagged_records),
                "review_person_count": len(flagged_records),
                "removed_person_count": len(removed_records),
                "removed_names": ["Lim, Paul"] + [record["name"] for record in removed_records],
                "address_omitted_as_uniform": bool(records) and "address" not in records[0],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    flagged_path.write_text(json.dumps(flagged_records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    review_path.write_text(json.dumps(flagged_records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    removed_path.write_text(json.dumps(removed_records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return json_path, csv_path, flagged_path, review_path, removed_path, metadata_path


def main() -> int:
    default_output = Path(__file__).resolve().parent / "data"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=default_output, help="Directory for JSON, CSV, and metadata output")
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds between college requests (default: 0.5)")
    parser.add_argument("--timeout", type=int, default=30, help="Request timeout in seconds")
    parser.add_argument("--retries", type=int, default=2, help="Retries per college after a failed request")
    args = parser.parse_args()

    all_records = []
    failures = []
    scraped_at = datetime.now(timezone.utc).isoformat()
    for index, (display_name, slug) in enumerate(COLLEGES):
        print(f"[{index + 1}/{len(COLLEGES)}] {display_name}...", file=sys.stderr)
        try:
            records = scrape_college(display_name, slug, args.timeout, args.retries)
            all_records.extend(records)
            print(f"  {len(records)} people", file=sys.stderr)
        except RuntimeError as error:
            failures.append(str(error))
            print(f"  ERROR: {error}", file=sys.stderr)
        if index < len(COLLEGES) - 1:
            time.sleep(max(0, args.delay))

    if failures:
        print("Scrape incomplete; no output was written:\n" + "\n".join(failures), file=sys.stderr)
        return 1

    all_records, flagged_records, removed_records = classify_records(all_records)
    paths = write_outputs(all_records, flagged_records, removed_records, args.output, scraped_at)
    print(f"Saved {len(all_records)} people, flagged {len(flagged_records)}, and removed {len(removed_records)} records to {args.output}")
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())