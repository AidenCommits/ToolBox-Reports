
"""
Toolbox Inventory Reports
PDF scanner and manual verification.

Responsibilities:
- Discover scanned PDF inventory sheets
- Render PDF pages for inspection
- Extract preliminary OCR text
- Verify inventory quantities and jobsite entries
- Save verified data for processor.py

Important:
Handwritten OCR is not considered authoritative.
Every report requires manual verification.
"""

import hashlib
import json
import re

from datetime import date, datetime
from pathlib import Path

import pymupdf as fitz
import pytesseract

from PIL import Image, ImageOps, ImageEnhance

from config import (
    EQUIPMENT,
    DATA_DIR,
    SCAN_DPI,
    OCR_LANGUAGE,
    TESSERACT_PATH,
    SUPPORTED_FILE_TYPES,
    get_input_directory,
    initialize_directories,
)


# --------------------------------------------------
# SCANNER DIRECTORIES
# --------------------------------------------------

REVIEW_DIR = DATA_DIR / "scan_reviews"

if TESSERACT_PATH:
    pytesseract.pytesseract.tesseract_cmd = (
        TESSERACT_PATH
    )


# --------------------------------------------------
# CUSTOM EXCEPTIONS
# --------------------------------------------------

class ScannerError(Exception):
    """General PDF scanning error."""


class VerificationError(ScannerError):
    """Invalid verified inventory data."""


# --------------------------------------------------
# FILE DISCOVERY
# --------------------------------------------------

def find_scanned_reports():
    """
    Find PDF files in the configured input folder.

    Files are returned in filename order.
    The processor will use verified report dates
    to determine chronological processing order.
    """

    input_dir = Path(get_input_directory())

    if not input_dir.exists():
        raise ScannerError(
            f"Input directory not found: {input_dir}"
        )

    reports = [
        path
        for path in input_dir.iterdir()
        if path.is_file()
        and path.suffix.lower() in SUPPORTED_FILE_TYPES
    ]

    return sorted(
        reports,
        key=lambda path: path.name.lower()
    )


# --------------------------------------------------
# FILE IDENTIFICATION
# --------------------------------------------------

def calculate_file_hash(file_path):
    """
    Calculate a SHA-256 hash for duplicate detection.

    Identical PDF files produce identical hashes.
    """

    digest = hashlib.sha256()

    with open(file_path, "rb") as file:
        for chunk in iter(
            lambda: file.read(1024 * 1024),
            b""
        ):
            digest.update(chunk)

    return digest.hexdigest()


# --------------------------------------------------
# PDF RENDERING
# --------------------------------------------------

def render_pdf(file_path):
    """
    Convert every PDF page into a PIL image.

    Uses the configured scan resolution.
    """

    file_path = Path(file_path)

    if not file_path.is_file():
        raise ScannerError(
            f"PDF not found: {file_path}"
        )

    images = []

    try:
        with fitz.open(file_path) as document:

            if document.page_count == 0:
                raise ScannerError(
                    "The PDF contains no pages."
                )

            for page in document:

                pixmap = page.get_pixmap(
                    dpi=SCAN_DPI,
                    colorspace=fitz.csRGB,
                    alpha=False,
                )

                image = Image.frombytes(
                    "RGB",
                    (pixmap.width, pixmap.height),
                    pixmap.samples,
                )

                images.append(image)

    except ScannerError:
        raise

    except Exception as error:
        raise ScannerError(
            f"Unable to read PDF: {file_path}"
        ) from error

    return images


# --------------------------------------------------
# IMAGE PREPROCESSING
# --------------------------------------------------

def preprocess_image(image):
    """
    Prepare an image for preliminary OCR.

    Preserve handwriting by avoiding aggressive
    thresholding or destructive filtering.
    """

    image = ImageOps.grayscale(image)

    image = ImageOps.autocontrast(image)

    image = ImageEnhance.Contrast(
        image
    ).enhance(1.4)

    return image


# --------------------------------------------------
# PRELIMINARY OCR
# --------------------------------------------------

def extract_ocr_text(images):
    """
    Extract preliminary OCR text from PDF pages.

    This output is diagnostic only and must
    not be used as verified inventory data.
    """

    results = []

    for page_number, image in enumerate(
        images,
        start=1
    ):

        processed = preprocess_image(image)

        try:
            text = pytesseract.image_to_string(
                processed,
                lang=OCR_LANGUAGE,
                config="--psm 6",
            )

        except pytesseract.TesseractNotFoundError:
            text = (
                "[Tesseract is not installed or "
                "its executable was not found.]"
            )

        except pytesseract.TesseractError as error:
            text = f"[OCR failed: {error}]"

        results.append({
            "page": page_number,
            "text": text,
        })

    return results


# --------------------------------------------------
# DATE VALIDATION
# --------------------------------------------------

def normalize_date(value):
    """
    Accept YYYY-MM-DD or MM/DD/YYYY.

    Return YYYY-MM-DD for processor.py.
    """

    value = value.strip()

    for date_format in (
        "%Y-%m-%d",
        "%m/%d/%Y",
    ):

        try:
            parsed = datetime.strptime(
                value,
                date_format
            ).date()

            if parsed > date.today():
                raise VerificationError(
                    "Inventory date cannot be "
                    "in the future."
                )

            return parsed.isoformat()

        except ValueError:
            continue

    raise VerificationError(
        "Enter a date as YYYY-MM-DD "
        "or MM/DD/YYYY."
    )


# --------------------------------------------------
# QUANTITY VALIDATION
# --------------------------------------------------

def validate_quantity(name, quantity):
    """
    Validate an on-truck quantity.
    """

    expected = EQUIPMENT[name]

    if type(quantity) is not int:
        raise VerificationError(
            f"{name}: quantity must be an integer."
        )

    if not 0 <= quantity <= expected:
        raise VerificationError(
            f"{name}: quantity must be "
            f"between 0 and {expected}."
        )

    return quantity


# --------------------------------------------------
# CONSOLE INPUT HELPERS
# --------------------------------------------------

def ask_nonempty(prompt):
    """Request a nonempty text value."""

    while True:

        value = input(prompt).strip()

        if value:
            return value

        print("This field cannot be empty.")


def ask_date():
    """Request a valid inventory date."""

    while True:

        value = input(
            "Inventory date (MM/DD/YYYY): "
        )

        try:
            return normalize_date(value)

        except VerificationError as error:
            print(error)


def ask_quantity(name):
    """
    Request a verified on-truck quantity.
    """

    expected = EQUIPMENT[name]

    while True:

        value = input(
            f"{name} on truck (0-{expected}): "
        ).strip()

        try:
            quantity = int(value)

            return validate_quantity(
                name,
                quantity
            )

        except (ValueError, VerificationError):
            print(
                f"Enter a whole number "
                f"between 0 and {expected}."
            )


def ask_yes_no(prompt):
    """Request a yes/no response."""

    while True:

        value = input(
            f"{prompt} (y/n): "
        ).strip().lower()

        if value in ("y", "yes"):
            return True

        if value in ("n", "no"):
            return False

        print("Enter y or n.")


# --------------------------------------------------
# VERIFY INVENTORY QUANTITIES
# --------------------------------------------------

def verify_quantities():
    """
    Manually verify on-truck quantities.

    The original sheet's off-truck quantity
    is checked against expected - on_truck.
    """

    quantities = {}

    print("\n--- VERIFY INVENTORY ---")

    for name, expected in EQUIPMENT.items():

        quantity = ask_quantity(name)

        quantities[name] = quantity

        outstanding = expected - quantity

        print(
            f"  Expected: {expected} | "
            f"Off truck: {outstanding}"
        )

    return quantities


# --------------------------------------------------
# VERIFY JOBSITE INFORMATION
# --------------------------------------------------

def verify_locations(quantities):
    """
    Record jobsite information from the sheet.

    Location entries are observations, not
    proof that equipment is still at a jobsite.

    The processor will reconcile these records
    with verified on-truck totals.
    """

    locations = []

    print("\n--- VERIFY OFF-TRUCK LOCATIONS ---")

    for name, expected in EQUIPMENT.items():

        outstanding = (
            expected - quantities[name]
        )

        if outstanding == 0:
            continue

        print(
            f"\n{name}: {outstanding} off truck"
        )

        print(
            "Enter locations written on this "
            "sheet. Leave blank if none."
        )

        while True:

            jobsite = input(
                "Jobsite / location "
                "(blank to finish): "
            ).strip()

            if not jobsite:
                break

            while True:

                value = input(
                    "Quantity at location: "
                ).strip()

                try:
                    quantity = int(value)

                    if not 1 <= quantity <= expected:
                        raise ValueError

                    break

                except ValueError:
                    print(
                        "Enter a valid positive "
                        "equipment quantity."
                    )

            locations.append({
                "equipment": name,
                "jobsite": jobsite,
                "quantity": quantity,
            })

        reported_total = sum(
            entry["quantity"]
            for entry in locations
            if entry["equipment"] == name
        )

        if reported_total > outstanding:
            print(
                "WARNING: Recorded location "
                "quantities exceed the current "
                "off-truck total. The processor "
                "will flag uncertain locations."
            )

    return locations


# --------------------------------------------------
# DISPLAY VERIFICATION SUMMARY
# --------------------------------------------------

def display_summary(report):
    """Display the verified inventory."""

    print("\n" + "=" * 60)
    print("VERIFIED INVENTORY SUMMARY")
    print("=" * 60)

    print(
        f"Date: {report['report_date']}"
    )

    print(
        f"Crew Lead: {report['crew_lead']}"
    )

    print(
        f"Source: {report['source_file']}"
    )

    print("-" * 60)

    total_on = 0
    total_out = 0

    for name, expected in EQUIPMENT.items():

        on_truck = report["quantities"][name]
        outstanding = expected - on_truck

        total_on += on_truck
        total_out += outstanding

        print(
            f"{name:<20} "
            f"On: {on_truck:>3}  "
            f"Out: {outstanding:>3}"
        )

    print("-" * 60)

    print(
        f"TOTAL ON TRUCK: {total_on}"
    )

    print(
        f"TOTAL OUTSTANDING: {total_out}"
    )

    print("\nRecorded locations:")

    if not report["location_updates"]:
        print("  No jobsite entries.")

    for entry in report["location_updates"]:

        print(
            f"  {entry['equipment']}: "
            f"{entry['quantity']} - "
            f"{entry['jobsite']}"
        )

    print("=" * 60)


# --------------------------------------------------
# SAVE VERIFIED SCAN
# --------------------------------------------------

def save_verified_scan(report):
    """
    Save verified report data as JSON.

    This does not update inventory state.
    processor.py handles that separately.
    """

    REVIEW_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    report_id = report["report_id"]

    output_path = (
        REVIEW_DIR
        / f"{report_id}.json"
    )

    if output_path.exists():

        with open(
            output_path,
            "r",
            encoding="utf-8"
        ) as file:

            existing = json.load(file)

        if existing == report:
            return output_path

        raise VerificationError(
            "A verified report with this ID "
            "already exists. Review the existing "
            "file before replacing it."
        )

    with open(
        output_path,
        "x",
        encoding="utf-8"
    ) as file:

        json.dump(
            report,
            file,
            indent=4,
            ensure_ascii=False
        )

    return output_path


# --------------------------------------------------
# SCAN AND VERIFY ONE PDF
# --------------------------------------------------

def scan_pdf(file_path):
    """
    Read one PDF and verify its inventory.

    Returns a dictionary compatible with
    process_inventory_report().

    No inventory state is modified here.
    """

    initialize_directories()

    file_path = Path(file_path).resolve()

    report_id = calculate_file_hash(
        file_path
    )

    images = render_pdf(
        file_path
    )

    ocr_results = extract_ocr_text(
        images
    )

    print("\n" + "=" * 60)
    print("TOOLBOX INVENTORY SCANNER")
    print("=" * 60)

    print(f"File: {file_path.name}")
    print(f"Pages: {len(images)}")

    print("\nOpening scanned pages...")

    for image in images:
        image.show()

    print(
        "\nPreliminary OCR text "
        "(not verified):"
    )

    for page in ocr_results:

        print(
            f"\n--- PAGE {page['page']} ---"
        )

        print(page["text"])

    print(
        "\nUse the scanned PDF to verify "
        "the following values."
    )

    report_date = ask_date()

    crew_lead = ask_nonempty(
        "Crew lead: "
    )

    while True:

        quantities = verify_quantities()

        locations = verify_locations(
            quantities
        )

        report = {
            "report_id": report_id,
            "report_date": report_date,
            "source_file": str(file_path),
            "crew_lead": crew_lead,
            "quantities": quantities,
            "location_updates": locations,
        }

        display_summary(report)

        if ask_yes_no(
            "Is this inventory correct?"
        ):
            break

        print(
            "\nRe-entering inventory values..."
        )

    output_path = save_verified_scan(
        report
    )

    print(
        f"\nVerified scan saved: {output_path}"
    )

    return report


# --------------------------------------------------
# LOAD VERIFIED SCAN
# --------------------------------------------------

def load_verified_scan(file_path):
    """
    Load a previously verified JSON report.
    """

    with open(
        file_path,
        "r",
        encoding="utf-8"
    ) as file:

        report = json.load(file)

    required_fields = (
        "report_id",
        "report_date",
        "source_file",
        "quantities",
        "location_updates",
    )

    for field in required_fields:

        if field not in report:
            raise VerificationError(
                f"Missing verified field: {field}"
            )

    normalize_date(
        report["report_date"]
    )

    if set(report["quantities"]) != set(EQUIPMENT):
        raise VerificationError(
            "Equipment categories do not match "
            "the configured inventory."
        )

    for name, quantity in report["quantities"].items():
        validate_quantity(name, quantity)

    if not isinstance(
        report["location_updates"],
        list
    ):
        raise VerificationError(
            "Invalid location updates."
        )

    return report


# --------------------------------------------------
# STANDALONE SCANNER TEST
# --------------------------------------------------

if __name__ == "__main__":

    reports = find_scanned_reports()

    if not reports:

        print(
            "No PDF inventory sheets found "
            "in the input directory."
        )

    else:

        print("\nAvailable inventory scans:\n")

        for index, path in enumerate(
            reports,
            start=1
        ):

            print(
                f"{index}. {path.name}"
            )

        while True:

            selection = input(
                "\nSelect a report number: "
            ).strip()

            try:
                index = int(selection) - 1

                if not 0 <= index < len(reports):
                    raise ValueError

                break

            except ValueError:
                print(
                    "Enter a valid report number."
                )

        scan_pdf(
            reports[index]
        )
