#!/usr/bin/env python3
"""
Builds docs/data.js from rice_scraper/data/rice_people.csv.

The scraped "major" field is a registrar export where double/triple majors
are concatenated with a single space and NO delimiter (e.g. "Computer
Science Linguistics" = two majors: "Computer Science" + "Linguistics").
Some people have no declared major and instead show their division
(e.g. "Engineering Division").

This script:
  1. Segments each major field into its individual atomic majors using a
     word-break search validated against the ~4900-row dataset (every
     atomic major appears standalone for at least one student, which is
     used to discover the segmentation, with a few manual overrides below
     for majors that never appear alone in this dataset).
  2. Maps each atomic major to its official Rice school/division and to a
     clean display name.
  3. Writes docs/data.js (embedded JS array, so the page works from
     file:// with no server) and docs/needs_review.csv for majors this
     script could not confidently classify.
"""
import csv
import json
import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "rice_scraper" / "data"
OUT_DIR = Path(__file__).resolve().parent
CSV_PATH = DATA_DIR / "rice_people.csv"

DIVISION_MARKERS = {
    "Architecture Division": "Architecture",
    "Business Division": "Business",
    "Engineering Division": "Engineering",
    "Humanities Division": "Humanities",
    "Music Division": "Music",
    "Natural Sciences Division": "Natural Sciences",
    "Social Sciences Division": "Social Sciences",
}

# Majors that never appear standalone in the dataset, so the automatic
# word-break segmentation can't discover them on its own. Verified by hand
# against Rice's official major list.
MANUAL_SPLITS = {
    "Ancient Mediterranean Civil History Medieval/Early Modern Studies": [
        "Ancient Mediterranean Civil", "History", "Medieval/Early Modern Studies",
    ],
    "Astrophysics Computer Science Classical Studies": [
        "Astrophysics", "Computer Science", "Classical Studies",
    ],
    "Biosciences Biochemistry and Cell Biology": [
        "Biosciences", "Biochemistry and Cell Biology",
    ],
    "Biosciences Bioscience & Health Policy": [
        "Biosciences", "Bioscience & Health Policy",
    ],
    "Biosciences Chemistry Biochemistry and Cell Biology": [
        "Biosciences", "Chemistry", "Biochemistry and Cell Biology",
    ],
    "Biosciences Classical Studies": ["Biosciences", "Classical Studies"],
    "Biosciences Education": ["Biosciences", "Education"],
    "Business Latin Americn & Latinx Studies": [
        "Business", "Latin Americn & Latinx Studies",
    ],
    "Cognitive Sciences Psychology Human-Comp Inter & Humn Factrs": [
        "Cognitive Sciences", "Psychology", "Human-Comp Inter & Humn Factrs",
    ],
    "Computer Science Visual and Dramatic Arts": [
        "Computer Science", "Visual and Dramatic Arts",
    ],
    "English Stdy of Womn Gendr & Sexuality": [
        "English", "Stdy of Womn Gendr & Sexuality",
    ],
    "Environmental Science Environmental Analysis": [
        "Environmental Science", "Environmental Analysis",
    ],
    "Health Sciences Latin Americn & Latinx Studies": [
        "Health Sciences", "Latin Americn & Latinx Studies",
    ],
    "History Classical Studies": ["History", "Classical Studies"],
    "History Education": ["History", "Education"],
    "History Stdy of Womn Gendr & Sexuality": [
        "History", "Stdy of Womn Gendr & Sexuality",
    ],
    "Managerial Econ & Org Sci Visual and Dramatic Arts": [
        "Managerial Econ & Org Sci", "Visual and Dramatic Arts",
    ],
    "Mechanical Engineering Classical Studies": [
        "Mechanical Engineering", "Classical Studies",
    ],
    "Medieval/Early Modern Studies History": [
        "Medieval/Early Modern Studies", "History",
    ],
    "Organ Performance Social Policy Analysis": [
        "Organ Performance", "Social Policy Analysis",
    ],
    "Political Science Stdy of Womn Gendr & Sexuality": [
        "Political Science", "Stdy of Womn Gendr & Sexuality",
    ],
    "Psychology Sociology Latin Americn & Latinx Studies": [
        "Psychology", "Sociology", "Latin Americn & Latinx Studies",
    ],
    "Stdy of Womn Gendr & Sexuality Sports Medicine & Exercise Phy": [
        "Stdy of Womn Gendr & Sexuality", "Sports Medicine & Exercise Phy",
    ],
    # "Art History" is itself an official Rice major (Humanities), not a
    # coincidental double major in "Art" + "History", so it's pinned as a
    # single atomic unit rather than left to the segmenter.
    "Art History": ["Art History"],
}

# atomic major (as it appears in the source data, post-segmentation) ->
# (clean display name, division). Division is None for majors this script
# could not confidently place (these get flagged for manual review).
MAJOR_INFO = {
    # Architecture
    "Architecture": ("Architecture", "Architecture"),
    "Architectural Studies": ("Architectural Studies", "Architecture"),
    # Business
    "Business": ("Business", "Business"),
    # Engineering (George R. Brown School of Engineering and Computing)
    "Artificial Intelligence": ("Artificial Intelligence", "Engineering"),
    "Bioengineering": ("Bioengineering", "Engineering"),
    "Chemical Engineering": ("Chemical Engineering", "Engineering"),
    "Civil Engineering": ("Civil Engineering", "Engineering"),
    "Civil & Environmental Engineer": ("Civil & Environmental Engineering", "Engineering"),
    "Environmental Engineering": ("Environmental Engineering", "Engineering"),
    "Electrical & Computer Eng.": ("Electrical & Computer Engineering", "Engineering"),
    "Materials Science & NanoEng": ("Materials Science & NanoEngineering", "Engineering"),
    "Mechanical Engineering": ("Mechanical Engineering", "Engineering"),
    "Computer Science": ("Computer Science", "Engineering"),
    "Computational & Applied Math": ("Computational & Applied Mathematics", "Engineering"),
    "Operations Research": ("Operations Research", "Engineering"),
    "Statistics": ("Statistics", "Engineering"),
    # Humanities
    "Ancient Mediterranean Civil": ("Ancient Mediterranean Civilizations", "Humanities"),
    "Art": ("Art", "Humanities"),
    "Art History": ("Art History", "Humanities"),
    "Asian Studies": ("Asian Studies", "Humanities"),
    "Classical Studies": ("Classical Studies", "Humanities"),
    "English": ("English", "Humanities"),
    "French Studies": ("French Studies", "Humanities"),
    "History": ("History", "Humanities"),
    "Medieval/Early Modern Studies": ("Medieval/Early Modern Studies", "Humanities"),
    "Media Studies": ("Media Studies", "Humanities"),
    "Philosophy": ("Philosophy", "Humanities"),
    "Religion": ("Religion", "Humanities"),
    "Spanish and Portuguese": ("Spanish and Portuguese", "Humanities"),
    "Stdy of Womn Gendr & Sexuality": ("Study of Women, Gender & Sexuality", "Humanities"),
    "Visual and Dramatic Arts": ("Visual and Dramatic Arts", "Humanities"),
    "Latin Americn & Latinx Studies": ("Latin American & Latinx Studies", "Humanities"),
    # Music (Shepherd School of Music)
    "Composition": ("Composition", "Music"),
    "Music": ("Music", "Music"),
    "Music History": ("Music History", "Music"),
    "Orchestral Conducting": ("Orchestral Conducting", "Music"),
    "Bassoon Performance": ("Bassoon Performance", "Music"),
    "Cello Performance": ("Cello Performance", "Music"),
    "Clarinet Performance": ("Clarinet Performance", "Music"),
    "Double Bass Performance": ("Double Bass Performance", "Music"),
    "Flute Performance": ("Flute Performance", "Music"),
    "Horn Performance": ("Horn Performance", "Music"),
    "Organ Performance": ("Organ Performance", "Music"),
    "Piano Performance": ("Piano Performance", "Music"),
    "Trumpet Performance": ("Trumpet Performance", "Music"),
    "Tuba Performance": ("Tuba Performance", "Music"),
    "Viola Performance": ("Viola Performance", "Music"),
    "Violin Performance": ("Violin Performance", "Music"),
    "Vocal Performance": ("Vocal Performance", "Music"),
    # Natural Sciences (Wiess School of Natural Sciences)
    "Astrophysics": ("Astrophysics", "Natural Sciences"),
    "Biosciences": ("Biosciences", "Natural Sciences"),
    "Biochemistry and Cell Biology": ("Biochemistry and Cell Biology", "Natural Sciences"),
    "Bioscience & Health Policy": ("Bioscience & Health Policy", "Natural Sciences"),
    "Chemical Physics": ("Chemical Physics", "Natural Sciences"),
    "Chemistry": ("Chemistry", "Natural Sciences"),
    "Earth/Environmnt/Planetary Sci": ("Earth, Environmental & Planetary Sciences", "Natural Sciences"),
    "Environmental Science": ("Environmental Science", "Natural Sciences"),
    "Health Sciences": ("Health Sciences", "Natural Sciences"),
    "Mathematics": ("Mathematics", "Natural Sciences"),
    "Neuroscience": ("Neuroscience", "Natural Sciences"),
    "Physics": ("Physics", "Natural Sciences"),
    "Public Health Sciences": ("Public Health Sciences", "Natural Sciences"),
    "Sports Medicine & Exercise Phy": ("Sports Medicine & Exercise Physiology", "Natural Sciences"),
    # Social Sciences
    "Anthropology": ("Anthropology", "Social Sciences"),
    "Cognitive Sciences": ("Cognitive Sciences", "Social Sciences"),
    "Economics": ("Economics", "Social Sciences"),
    "Global Affairs": ("Global Affairs", "Social Sciences"),
    "Linguistics": ("Linguistics", "Social Sciences"),
    "Managerial Econ & Org Sci": ("Managerial Economics & Organizational Science", "Social Sciences"),
    "Mathematical Economic Analysis": ("Mathematical Economic Analysis", "Social Sciences"),
    "Political Science": ("Political Science", "Social Sciences"),
    "Psychology": ("Psychology", "Social Sciences"),
    "Social Policy Analysis": ("Social Policy Analysis", "Social Sciences"),
    "Sociology": ("Sociology", "Social Sciences"),
    "Sport Analytics": ("Sport Analytics", "Social Sciences"),
    "Sport Management": ("Sport Management", "Social Sciences"),
    # Unresolved -- flagged for manual review, division left unknown.
    "Education": (None, None),
    "Environmental Analysis": (None, None),
    "Human-Comp Inter & Humn Factrs": (None, None),
}

GRADE_ORDER = {"Freshman": 0, "Sophomore": 1, "Junior": 2, "Senior": 3}


def segment(major_field, atomic_dict):
    if major_field in MANUAL_SPLITS:
        return list(MANUAL_SPLITS[major_field])
    words = major_field.split(" ")
    n = len(words)
    memo = {}

    def helper(start):
        if start in memo:
            return memo[start]
        if start == n:
            return [[]]
        outs = []
        for end in range(n, start, -1):
            piece = " ".join(words[start:end])
            if piece in atomic_dict:
                for rest in helper(end):
                    outs.append([piece] + rest)
        memo[start] = outs
        return outs

    segs = helper(0)
    unique = [list(s) for s in {tuple(s) for s in segs}]
    if not unique:
        # No valid decomposition found -- flag the whole string for review.
        return [major_field]
    # Prefer the fewest pieces, tie-broken by favoring longer (more
    # specific) leading pieces -- e.g. "Art History" as one piece over
    # "Art" + "History" -- which matches how real Rice major names read.
    unique.sort(key=lambda pieces: (len(pieces), [-len(p) for p in pieces]))
    return unique[0]


def build_atomic_dict():
    """Atomic segmentation units: every classified major plus the division
    markers (a division marker can appear alongside a real major, e.g.
    "Music Division Sport Management" = undeclared-in-Music + Sport Mgmt)."""
    return set(MAJOR_INFO.keys()) | set(DIVISION_MARKERS.keys())


def main():
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    atomic_dict = build_atomic_dict()

    students = []
    review_rows = []
    unmapped_leaf_majors = set()

    for row in rows:
        name = row["name"].strip()
        college = row["college"].strip()
        grade = row["calculated_grade"].strip()
        raw_major = row["major"].strip()

        majors_out = []
        division_set = set()
        no_major_declared = False
        needs_review = False

        if not raw_major:
            no_major_declared = True
        elif raw_major in DIVISION_MARKERS:
            no_major_declared = True
            division_set.add(DIVISION_MARKERS[raw_major])
        else:
            pieces = segment(raw_major, atomic_dict)
            for piece in pieces:
                if piece in DIVISION_MARKERS:
                    division_set.add(DIVISION_MARKERS[piece])
                    continue
                info = MAJOR_INFO.get(piece)
                if info is None:
                    unmapped_leaf_majors.add(piece)
                    majors_out.append(piece)
                    needs_review = True
                    continue
                display, division = info
                if display is None:
                    majors_out.append(piece)
                    needs_review = True
                else:
                    majors_out.append(display)
                    if division:
                        division_set.add(division)

        if needs_review:
            review_rows.append({
                "name": name,
                "college": college,
                "grade": grade,
                "raw_major": raw_major,
            })

        students.append({
            "name": name,
            "college": college,
            "grade": grade,
            "gradeRank": GRADE_ORDER.get(grade, -1),
            "majors": majors_out,
            "divisions": sorted(division_set),
            "noMajorDeclared": no_major_declared,
            "needsReview": needs_review,
        })

    OUT_DIR.mkdir(exist_ok=True)
    with open(OUT_DIR / "data.js", "w", encoding="utf-8") as f:
        f.write("const STUDENTS = ")
        json.dump(students, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")

    if review_rows:
        with open(OUT_DIR / "needs_review.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["name", "college", "grade", "raw_major"])
            w.writeheader()
            w.writerows(review_rows)

    print(f"Total people: {len(students)}")
    print(f"Flagged for manual review: {len(review_rows)}")
    if unmapped_leaf_majors:
        print("Unmapped leaf majors (add to MAJOR_INFO):")
        for m in sorted(unmapped_leaf_majors):
            print(" -", m)


if __name__ == "__main__":
    main()
