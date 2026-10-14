
"""
Toolbox Inventory Reports
OCR recognition and automatic Excel report test.

Run:
    python ocr_test.py

This test does NOT modify inventory state or history.
"""

import re
from pathlib import Path

import pymupdf
import pytesseract

from PIL import Image, ImageOps, ImageEnhance

from config import (
    EQUIPMENT,
    INPUT_DIR,
    OUTPUT_DIR,
    TESSERACT_PATH,
)

from storage import create_default_state
from processor import build_updated_state
from reports import generate_report


# --------------------------------------------------
# OCR CONFIGURATION
# --------------------------------------------------

# Coordinates are based on the supplied PDF
# rendered at 1030 x 796 pixels.
REFERENCE_WIDTH = 1030
REFERENCE_HEIGHT = 796

ROW_CENTERS = [
    219, 254, 288, 321,
    355, 389, 422, 457,
]

ON_TRUCK_X = (345, 400)
OFF_TRUCK_X = (425, 490)

RENDER_SCALE = 2.5

if TESSERACT_PATH:
    pytesseract.pytesseract.tesseract_cmd = (
        TESSERACT_PATH
    )


# --------------------------------------------------
# PDF RENDERING
# --------------------------------------------------

def render_pdf_page(pdf_path):
    """Render the first page at high resolution."""

    with pymupdf.open(pdf_path) as document:

        if document.page_count != 1:
            raise ValueError(
                "This test expects a one-page PDF."
            )

        page = document[0]

        pix = page.get_pixmap(
            matrix=pymupdf.Matrix(
                RENDER_SCALE,
                RENDER_SCALE
            ),
            colorspace=pymupdf.csRGB,
            alpha=False,
        )

        return Image.frombytes(
            "RGB",
            (pix.width, pix.height),
            pix.samples,
        )


# --------------------------------------------------
# CROP HANDWRITTEN CELL
# --------------------------------------------------

def crop_cell(image, row_index, column):
    """Crop a quantity cell using scaled coordinates."""

    center_y = ROW_CENTERS[row_index]

    if column == "on":
        left, right = ON_TRUCK_X
    else:
        left, right = OFF_TRUCK_X

    top = center_y - 15
    bottom = center_y + 15

    scale_x = image.width / REFERENCE_WIDTH
    scale_y = image.height / REFERENCE_HEIGHT

    box = (
        round(left * scale_x),
        round(top * scale_y),
        round(right * scale_x),
        round(bottom * scale_y),
    )

    return image.crop(box)


# --------------------------------------------------
# PREPROCESS HANDWRITING
# --------------------------------------------------

def preprocess_cell(image):
    """Improve contrast for digit recognition."""

    image = ImageOps.grayscale(image)
    image = ImageOps.autocontrast(image)

    image = ImageEnhance.Contrast(
        image
    ).enhance(1.8)

    return image


# --------------------------------------------------
# RECOGNIZE HANDWRITTEN NUMBER
# --------------------------------------------------

def recognize_number(image, maximum):
    """
    Try several Tesseract recognition modes.

    Return a candidate only when all nonempty
    valid readings agree. Otherwise return None.
    """

    processed = preprocess_cell(image)

    candidates = []

    for psm in (6, 7, 10, 13):

        config = (
            f"--psm {psm} "
            "-c tessedit_char_whitelist=0123456789"
        )

        text = pytesseract.image_to_string(
            processed,
            config=config
        ).strip()

        if not re.fullmatch(r"\d+", text):
            continue

        value = int(text)

        if 0 <= value <= maximum:
            candidates.append(value)

    if not candidates:
        return None

    if len(set(candidates)) != 1:
        return None

    return candidates[0]


# --------------------------------------------------
# VERIFY A NUMBER
# --------------------------------------------------

def verify_number(label, candidate, maximum):
    """
    Ask the user to verify an OCR reading.

    Press Enter to accept a candidate.
    Enter a number to correct it.
    """

    while True:

        shown = (
            str(candidate)
            if candidate is not None
            else "UNKNOWN"
        )

        value = input(
            f"{label} [OCR: {shown}] "
            f"(Enter=accept, or type correction): "
        ).strip()

        if not value and candidate is not None:
            return candidate

        if value.isdigit():

            number = int(value)

            if 0 <= number <= maximum:
                return number

        print(
            f"Enter a whole number from "
            f"0 to {maximum}."
        )


# --------------------------------------------------
# EXTRACT AND VERIFY INVENTORY
# --------------------------------------------------

def extract_inventory(image):
    """Read and verify all equipment quantities."""

    quantities = {}
    locations = []

    print("\n" + "=" * 60)
    print("OCR INVENTORY VERIFICATION")
    print("=" * 60)

    for index, (name, expected) in enumerate(
        EQUIPMENT.items()
    ):

        on_crop = crop_cell(
            image, index, "on"
        )

        off_crop = crop_cell(
            image, index, "off"
        )

        on_candidate = recognize_number(
            on_crop, expected
        )

        off_candidate = recognize_number(
            off_crop, expected
        )

        print(f"\n{name} (expected: {expected})")

        # Display the original handwriting.
        # This opens an image viewer on Windows.
        preview = Image.new(
            "RGB",
            (
                on_crop.width + off_crop.width + 20,
                max(on_crop.height, off_crop.height)
            ),
            "white"
        )

        preview.paste(on_crop, (0, 0))

        preview.paste(
            off_crop,
            (on_crop.width + 20, 0)
        )

        preview.show()

        print(
            "Image: left = on truck, "
            "right = off truck"
        )

        on_truck = verify_number(
            "On truck",
            on_candidate,
            expected
        )

        off_truck = verify_number(
            "Off truck",
            off_candidate,
            expected
        )

        while on_truck + off_truck != expected:

            print(
                "\nWARNING: On truck + off truck "
                "does not equal expected."
            )

            print(
                f"{on_truck} + {off_truck} "
                f"!= {expected}"
            )

            on_truck = verify_number(
                "Correct on truck",
                None,
                expected
            )

            off_truck = verify_number(
                "Correct off truck",
                None,
                expected
            )

        quantities[name] = on_truck

        if off_truck > 0:

            print(
                f"\n{name}: {off_truck} outstanding."
            )

            print(
                "Enter any jobsite locations "
                "written on the sheet."
            )

            while True:

                jobsite = input(
                    "Jobsite (blank to finish): "
                ).strip()

                if not jobsite:
                    break

                while True:

                    value = input(
                        "Quantity at jobsite: "
                    ).strip()

                    if (
                        value.isdigit()
                        and 1 <= int(value) <= expected
                    ):
                        break

                    print("Invalid quantity.")

                locations.append({
                    "equipment": name,
                    "jobsite": jobsite,
                    "quantity": int(value),
                })

    return quantities, locations


# --------------------------------------------------
# PRINT SUMMARY
# --------------------------------------------------

def print_summary(quantities):
    """Display recognized inventory totals."""

    print("\n" + "=" * 60)
    print("VERIFIED INVENTORY")
    print("=" * 60)

    total_on = 0
    total_out = 0

    for name, expected in EQUIPMENT.items():

        on_truck = quantities[name]
        outstanding = expected - on_truck

        total_on += on_truck
        total_out += outstanding

        print(
            f"{name:<20} "
            f"On: {on_truck:>2} "
            f"Out: {outstanding:>2}"
        )

    print("-" * 60)

    print(f"TOTAL ON TRUCK: {total_on}")
    print(f"TOTAL OUTSTANDING: {total_out}")


# --------------------------------------------------
# GENERATE TEST REPORT
# --------------------------------------------------

def generate_test_report(
    report_date,
    quantities,
    locations
):
    """
    Build an inventory snapshot and generate
    an Excel report without modifying storage.
    """

    state = create_default_state()

    updated_state, movements = build_updated_state(
        previous_state=state,
        report_date=report_date,
        quantities=quantities,
        location_updates=locations,
    )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    output_path = (
        OUTPUT_DIR
        / f"OCR_TEST_{report_date}.xlsx"
    )

    return generate_report(
        report_date=report_date,
        state=updated_state,
        output_path=output_path,
    )


# --------------------------------------------------
# MAIN TEST
# --------------------------------------------------

def main():

    pdf_files = sorted(
        INPUT_DIR.glob("*.pdf")
    )

    if not pdf_files:
        print("No PDF files found in input.")
        return

    print("\nAvailable PDFs:")

    for index, path in enumerate(
        pdf_files, start=1
    ):
        print(f"{index}. {path.name}")

    selection = int(
        input("\nSelect PDF number: ")
    ) - 1

    if not 0 <= selection < len(pdf_files):
        print("Invalid selection.")
        return

    pdf_path = pdf_files[selection]

    print(f"\nSelected: {pdf_path.name}")

    report_date = input(
        "Inventory date (YYYY-MM-DD): "
    ).strip()

    from datetime import date

    parsed_date = date.fromisoformat(
        report_date
    )

    report_date = parsed_date.isoformat()

    image = render_pdf_page(
        pdf_path
    )

    quantities, locations = extract_inventory(
        image
    )

    print_summary(
        quantities
    )

    confirmation = input(
        "\nGenerate Excel report? (y/n): "
    ).strip().lower()

    if confirmation != "y":
        print("Report generation cancelled.")
        return

    output_path = generate_test_report(
        report_date,
        quantities,
        locations
    )

    print(
        "\nExcel report generated successfully!"
    )

    print(
        f"File: {output_path.resolve()}"
    )

    print(
        "\nInventory state and processing "
        "history were not modified."
    )


# --------------------------------------------------
# ENTRY POINT
# --------------------------------------------------

if __name__ == "__main__":
    main()
