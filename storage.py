
"""
Toolbox Inventory Reports
Persistent inventory storage.

Responsibilities:
- Initialize inventory storage
- Load and save current inventory state
- Maintain processed report history
- Prevent duplicate report processing
- Create backups before modifying stored data
- Validate inventory quantities
"""

import json
import os
import shutil
import tempfile

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from config import (
    DATA_DIR,
    STATE_FILE,
    HISTORY_FILE,
    EQUIPMENT,
    TIMEZONE,
    initialize_directories,
)


# --------------------------------------------------
# TIME HELPERS
# --------------------------------------------------

def current_timestamp():
    """Return the current timestamp in local time."""

    return datetime.now(
        ZoneInfo(TIMEZONE)
    ).isoformat(timespec="seconds")


# --------------------------------------------------
# DEFAULT INVENTORY STATE
# --------------------------------------------------

def create_default_state():
    """
    Create an unverified starting inventory state.

    Quantities are unknown until a verified
    inventory sheet establishes the baseline.

    A null on_truck value must never be
    interpreted as zero.
    """

    equipment = {}

    for name, expected in EQUIPMENT.items():

        equipment[name] = {
            "expected": expected,
            "on_truck": None,
            "outstanding": None,
            "last_verified": None,
            "locations": [],
        }

    return {
        "schema_version": 1,
        "initialized": False,
        "last_processed_date": None,
        "last_updated": current_timestamp(),
        "equipment": equipment,
    }


# --------------------------------------------------
# DEFAULT HISTORY
# --------------------------------------------------

def create_default_history():
    """
    Create an empty inventory processing history.
    """

    return {
        "schema_version": 1,
        "processed_reports": [],
    }


# --------------------------------------------------
# JSON FILE OPERATIONS
# --------------------------------------------------

def read_json(file_path):
    """
    Read a JSON file.

    Raises an error if the file is missing,
    corrupted, or contains an invalid structure.
    """

    file_path = Path(file_path)

    with open(
        file_path,
        "r",
        encoding="utf-8"
    ) as file:

        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError(
            f"Invalid JSON structure: {file_path}"
        )

    return data


def write_json(file_path, data):
    """
    Write JSON using a temporary file.

    The temporary file is replaced atomically
    to reduce the risk of incomplete writes.
    """

    file_path = Path(file_path)

    file_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    temporary_path = None

    try:

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=file_path.parent,
            suffix=".tmp",
            delete=False
        ) as temporary_file:

            temporary_path = Path(
                temporary_file.name
            )

            json.dump(
                data,
                temporary_file,
                indent=4,
                ensure_ascii=False
            )

            temporary_file.flush()
            os.fsync(
                temporary_file.fileno()
            )

        os.replace(
            temporary_path,
            file_path
        )

    finally:

        if (
            temporary_path is not None
            and temporary_path.exists()
        ):
            temporary_path.unlink()


# --------------------------------------------------
# BACKUP OPERATIONS
# --------------------------------------------------

def backup_file(file_path):
    """
    Create a timestamped backup of an existing file.

    Returns the backup path, or None if the
    original file does not exist.
    """

    file_path = Path(file_path)

    if not file_path.exists():
        return None

    backup_directory = DATA_DIR / "backups"

    backup_directory.mkdir(
        parents=True,
        exist_ok=True
    )

    timestamp = datetime.now(
        ZoneInfo(TIMEZONE)
    ).strftime("%Y%m%d_%H%M%S_%f")

    backup_path = (
        backup_directory
        / f"{file_path.stem}_{timestamp}.json"
    )

    shutil.copy2(
        file_path,
        backup_path
    )

    return backup_path


# --------------------------------------------------
# INITIALIZE STORAGE
# --------------------------------------------------

def initialize_storage():
    """
    Create required directories and JSON files.

    Existing inventory data is never overwritten.
    """

    initialize_directories()

    if not STATE_FILE.exists():

        write_json(
            STATE_FILE,
            create_default_state()
        )

    if not HISTORY_FILE.exists():

        write_json(
            HISTORY_FILE,
            create_default_history()
        )


# --------------------------------------------------
# LOAD INVENTORY STATE
# --------------------------------------------------

def load_inventory_state():
    """
    Load the most recently saved inventory state.

    Returns a deep copy to prevent accidental
    changes to the stored data.
    """

    initialize_storage()

    state = read_json(
        STATE_FILE
    )

    validate_inventory_state(
        state
    )

    return deepcopy(state)


# --------------------------------------------------
# INVENTORY VALIDATION
# --------------------------------------------------

def validate_inventory_state(state):
    """
    Verify that the inventory state contains
    valid quantities and required equipment.
    """

    if state.get("schema_version") != 1:
        raise ValueError(
            "Unsupported inventory state version."
        )

    if not isinstance(
        state.get("initialized"),
        bool
    ):
        raise ValueError(
            "Invalid inventory initialization status."
        )

    equipment_data = state.get(
        "equipment"
    )

    if not isinstance(equipment_data, dict):
        raise ValueError(
            "Inventory equipment data is missing."
        )

    if set(equipment_data) != set(EQUIPMENT):
        raise ValueError(
            "Inventory equipment categories do not "
            "match the configured equipment."
        )

    for name, expected in EQUIPMENT.items():

        item = equipment_data[name]

        if not isinstance(item, dict):
            raise ValueError(
                f"Invalid equipment record: {name}"
            )

        if item.get("expected") != expected:
            raise ValueError(
                f"Expected quantity mismatch: {name}"
            )

        on_truck = item.get(
            "on_truck"
        )

        outstanding = item.get(
            "outstanding"
        )

        if on_truck is None:

            if outstanding is not None:
                raise ValueError(
                    f"Inconsistent unknown quantity: {name}"
                )

        else:

            if (
                type(on_truck) is not int
                or not 0 <= on_truck <= expected
            ):
                raise ValueError(
                    f"Invalid on-truck quantity: {name}"
                )

            if (
                type(outstanding) is not int
                or outstanding != expected - on_truck
            ):
                raise ValueError(
                    f"Outstanding quantity mismatch: {name}"
                )

        locations = item.get(
            "locations"
        )

        if not isinstance(locations, list):
            raise ValueError(
                f"Invalid location records: {name}"
            )

        for location in locations:

            if not isinstance(location, dict):
                raise ValueError(
                    f"Invalid location entry: {name}"
                )

            quantity = location.get(
                "quantity"
            )

            if (
                type(quantity) is not int
                or quantity < 0
            ):
                raise ValueError(
                    f"Invalid location quantity: {name}"
                )

    if state["initialized"]:

        for name in EQUIPMENT:

            if (
                equipment_data[name]["on_truck"]
                is None
            ):
                raise ValueError(
                    f"Missing verified baseline: {name}"
                )


# --------------------------------------------------
# SAVE INVENTORY STATE
# --------------------------------------------------

def save_inventory_state(state):
    """
    Validate and save the current inventory state.

    A backup is created before overwriting
    the existing file.
    """

    state = deepcopy(state)

    validate_inventory_state(
        state
    )

    state["last_updated"] = (
        current_timestamp()
    )

    backup_file(
        STATE_FILE
    )

    write_json(
        STATE_FILE,
        state
    )


# --------------------------------------------------
# LOAD REPORT HISTORY
# --------------------------------------------------

def load_history():
    """
    Load the history of processed inventory sheets.
    """

    initialize_storage()

    history = read_json(
        HISTORY_FILE
    )

    if history.get("schema_version") != 1:
        raise ValueError(
            "Unsupported inventory history version."
        )

    if not isinstance(
        history.get("processed_reports"),
        list
    ):
        raise ValueError(
            "Invalid processed report history."
        )

    return deepcopy(history)


# --------------------------------------------------
# CHECK FOR DUPLICATE REPORT
# --------------------------------------------------

def report_already_processed(report_id):
    """
    Check whether a report ID already exists
    in processing history.
    """

    history = load_history()

    for report in history["processed_reports"]:

        if report.get("report_id") == report_id:
            return True

    return False


# --------------------------------------------------
# SAVE REPORT HISTORY
# --------------------------------------------------

def save_history(history):
    """
    Save the report processing history.
    """

    if history.get("schema_version") != 1:
        raise ValueError(
            "Unsupported inventory history version."
        )

    if not isinstance(
        history.get("processed_reports"),
        list
    ):
        raise ValueError(
            "Invalid processed report history."
        )

    backup_file(
        HISTORY_FILE
    )

    write_json(
        HISTORY_FILE,
        history
    )


# --------------------------------------------------
# ADD PROCESSED REPORT
# --------------------------------------------------

def add_processed_report(
    report_id,
    report_date,
    source_file,
    quantities,
    location_updates=None
):
    """
    Record a successfully processed inventory sheet.

    report_id:
        Unique identifier for the source report.

    report_date:
        Inventory date in YYYY-MM-DD format.

    source_file:
        Original PDF filename.

    quantities:
        Verified on-truck equipment quantities.

    location_updates:
        Verified location information from the sheet.
    """

    history = load_history()

    for report in history["processed_reports"]:

        if report.get("report_id") == report_id:
            raise ValueError(
                f"Report already processed: {report_id}"
            )

    entry = {
        "report_id": report_id,
        "report_date": report_date,
        "source_file": str(source_file),
        "processed_at": current_timestamp(),
        "quantities": deepcopy(quantities),
        "location_updates": deepcopy(
            location_updates or []
        ),
    }

    history["processed_reports"].append(
        entry
    )

    history["processed_reports"].sort(
        key=lambda report: (
            report["report_date"],
            report["report_id"]
        )
    )

    save_history(
        history
    )

    return entry


# --------------------------------------------------
# GET PROCESSED REPORTS
# --------------------------------------------------

def get_processed_reports(
    start_date=None,
    end_date=None
):
    """
    Return processed reports within an optional
    inclusive date range.

    Dates must use YYYY-MM-DD format.
    """

    history = load_history()

    reports = history[
        "processed_reports"
    ]

    if start_date is not None:

        reports = [
            report
            for report in reports
            if report["report_date"] >= start_date
        ]

    if end_date is not None:

        reports = [
            report
            for report in reports
            if report["report_date"] <= end_date
        ]

    return deepcopy(reports)


# --------------------------------------------------
# INVENTORY SUMMARY
# --------------------------------------------------

def get_inventory_summary():
    """
    Return current equipment quantities.

    Unknown quantities remain None until
    a verified baseline has been established.
    """

    state = load_inventory_state()

    summary = []

    for name, item in state["equipment"].items():

        summary.append({
            "equipment": name,
            "expected": item["expected"],
            "on_truck": item["on_truck"],
            "outstanding": item["outstanding"],
            "locations": deepcopy(
                item["locations"]
            ),
        })

    return summary


# --------------------------------------------------
# RESET INVENTORY DATA
# --------------------------------------------------

def reset_storage():
    """
    Reset inventory state and processing history.

    Backups are created before resetting.

    This function must only be called after
    explicit user confirmation.
    """

    backup_file(
        STATE_FILE
    )

    backup_file(
        HISTORY_FILE
    )

    write_json(
        STATE_FILE,
        create_default_state()
    )

    write_json(
        HISTORY_FILE,
        create_default_history()
    )
