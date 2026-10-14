
"""
Toolbox Inventory Reports
Configuration and project settings.
"""

from pathlib import Path


# --------------------------------------------------
# PROJECT DIRECTORIES
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = BASE_DIR / "data"
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"

# Persistent inventory state
STATE_FILE = DATA_DIR / "inventory_state.json"

# Historical records of processed inventory sheets
HISTORY_FILE = DATA_DIR / "inventory_history.json"

# Original Excel inventory template
TEMPLATE_FILE = BASE_DIR / "Toolbox_Truck_Inventory_Sheet.xlsx"


# --------------------------------------------------
# SHARED DRIVE SETTINGS
# --------------------------------------------------

# Leave as None while developing locally.
# Later, replace with the shared drive folder path.
#
# Example:
# SHARED_DRIVE_DIR = Path(
#     r"Z:\Toolbox Inventory\Scanned Reports"
# )

SHARED_DRIVE_DIR = None

# Supported scanned document formats
SUPPORTED_FILE_TYPES = (
    ".pdf",
)


# --------------------------------------------------
# EQUIPMENT INVENTORY
# --------------------------------------------------

# Expected quantities based on the Toolbox Truck
# inventory sheet.

EQUIPMENT = {
    "Vacuums": 2,
    "Dehumidifiers": 4,
    "Fans": 20,
    "Multitools": 2,
    "Sledgehammer": 1,
    "Fogger": 1,
    "Extension Cords": 6,
    "Poles": 6,
}

TOTAL_EXPECTED_EQUIPMENT = sum(EQUIPMENT.values())


# --------------------------------------------------
# INVENTORY VALIDATION
# --------------------------------------------------

# Quantities must be between zero and the expected
# number of items for each equipment type.

MIN_QUANTITY = 0

# Require confirmation before processing a scan
# containing unreadable or questionable values.
REQUIRE_SCAN_VERIFICATION = True

# Do not automatically assume an unrecorded
# equipment quantity is zero.
ALLOW_MISSING_QUANTITIES = False


# --------------------------------------------------
# PDF SCANNING SETTINGS
# --------------------------------------------------

# Resolution used when converting PDF pages
# into images for OCR.
SCAN_DPI = 300

# Language used for text recognition.
OCR_LANGUAGE = "eng"

# Optional explicit path to Tesseract on Windows.
# Leave as None if Tesseract is in the system PATH.
#
# Example:
# TESSERACT_PATH = (
#     r"C:\Program Files\Tesseract-OCR\tesseract.exe"
# )

TESSERACT_PATH = None

# Minimum OCR confidence for automatic acceptance.
# This is a preliminary threshold and will be
# adjusted after testing real handwritten scans.
OCR_CONFIDENCE_THRESHOLD = 85


# --------------------------------------------------
# REPORT SETTINGS
# --------------------------------------------------

REPORT_TITLE = "Toolbox Truck Weekly Inventory Report"

REPORT_FILENAME_PREFIX = "Toolbox_Inventory"

# Reports will summarize inventory through
# the selected reporting date.
REPORT_DAY = "Monday"

# Excel print settings
REPORT_ORIENTATION = "portrait"
REPORT_PAPER_SIZE = "letter"

# Fit report to one page wide.
REPORT_FIT_TO_WIDTH = 1

# Allow multiple pages vertically if necessary.
REPORT_FIT_TO_HEIGHT = 0

# Include jobsite information when available.
INCLUDE_JOBSITE_DETAILS = True

# Include inventory discrepancies and
# unconfirmed locations.
INCLUDE_DISCREPANCIES = True


# --------------------------------------------------
# DATE AND TIME SETTINGS
# --------------------------------------------------

TIMEZONE = "America/New_York"

DATE_FORMAT = "%m/%d/%Y"
DATETIME_FORMAT = "%m/%d/%Y %I:%M %p"


# --------------------------------------------------
# DIRECTORY INITIALIZATION
# --------------------------------------------------

def initialize_directories():
    """
    Create required project directories if they
    do not already exist.
    """

    directories = [
        DATA_DIR,
        INPUT_DIR,
        OUTPUT_DIR,
    ]

    for directory in directories:
        directory.mkdir(
            parents=True,
            exist_ok=True
        )


# --------------------------------------------------
# CONFIGURATION HELPERS
# --------------------------------------------------

def get_expected_quantity(equipment_name):
    """
    Return the expected inventory quantity
    for a specific equipment type.
    """

    return EQUIPMENT.get(equipment_name)


def get_input_directory():
    """
    Return the active directory containing
    scanned inventory reports.
    """

    if SHARED_DRIVE_DIR is not None:
        return Path(SHARED_DRIVE_DIR)

    return INPUT_DIR
