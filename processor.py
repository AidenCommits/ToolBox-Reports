
"""
Toolbox Inventory Reports
Inventory processing and reconciliation.

Responsibilities:
- Validate verified inventory sheet data
- Establish the initial inventory baseline
- Calculate daily inventory movements
- Track outstanding equipment quantities
- Preserve last-reported jobsite information
- Flag uncertain equipment locations
- Update persistent inventory records

Input must contain verified data.
OCR output must be reviewed before processing.
"""

from copy import deepcopy
from datetime import date, datetime

from config import EQUIPMENT

from storage import (
    load_inventory_state,
    load_history,
    save_inventory_state,
    save_history,
    report_already_processed,
    current_timestamp,
)


# --------------------------------------------------
# CUSTOM EXCEPTIONS
# --------------------------------------------------

class InventoryProcessingError(Exception):
    """Base exception for inventory processing."""


class InventoryValidationError(InventoryProcessingError):
    """Raised when inventory input is invalid."""


class DuplicateReportError(InventoryProcessingError):
    """Raised when a report was already processed."""


class OutOfOrderReportError(InventoryProcessingError):
    """Raised when a report is older than current state."""


# --------------------------------------------------
# DATE VALIDATION
# --------------------------------------------------

def validate_report_date(report_date):
    """
    Validate a report date in YYYY-MM-DD format.
    """

    if not isinstance(report_date, str):
        raise InventoryValidationError(
            "Report date must be a string."
        )

    try:
        parsed = date.fromisoformat(report_date)

    except ValueError as error:
        raise InventoryValidationError(
            f"Invalid report date: {report_date}"
        ) from error

    if parsed.isoformat() != report_date:
        raise InventoryValidationError(
            "Report date must use YYYY-MM-DD."
        )

    return report_date


# --------------------------------------------------
# QUANTITY VALIDATION
# --------------------------------------------------

def validate_quantities(quantities):
    """
    Validate a complete inventory snapshot.

    Every configured equipment type must have
    a verified integer on-truck quantity.
    """

    if not isinstance(quantities, dict):
        raise InventoryValidationError(
            "Quantities must be a dictionary."
        )

    expected_names = set(EQUIPMENT)
    received_names = set(quantities)

    missing = expected_names - received_names
    unexpected = received_names - expected_names

    if missing:
        raise InventoryValidationError(
            "Missing equipment quantities: "
            + ", ".join(sorted(missing))
        )

    if unexpected:
        raise InventoryValidationError(
            "Unknown equipment categories: "
            + ", ".join(sorted(unexpected))
        )

    for name, quantity in quantities.items():

        expected = EQUIPMENT[name]

        if type(quantity) is not int:
            raise InventoryValidationError(
                f"{name}: quantity must be an integer."
            )

        if not 0 <= quantity <= expected:
            raise InventoryValidationError(
                f"{name}: quantity {quantity} is outside "
                f"the valid range of 0 to {expected}."
            )

    return deepcopy(quantities)


# --------------------------------------------------
# LOCATION VALIDATION
# --------------------------------------------------

def validate_location_updates(location_updates):
    """
    Validate newly reported off-truck locations.

    Expected format:

    [
        {
            "equipment": "Fans",
            "jobsite": "Johnson Residence",
            "quantity": 3
        }
    ]
    """

    if location_updates is None:
        return []

    if not isinstance(location_updates, list):
        raise InventoryValidationError(
            "Location updates must be a list."
        )

    validated = []

    for index, entry in enumerate(location_updates):

        if not isinstance(entry, dict):
            raise InventoryValidationError(
                f"Location entry {index + 1} is invalid."
            )

        equipment = entry.get("equipment")
        jobsite = entry.get("jobsite")
        quantity = entry.get("quantity")

        if equipment not in EQUIPMENT:
            raise InventoryValidationError(
                f"Unknown equipment: {equipment}"
            )

        if (
            not isinstance(jobsite, str)
            or not jobsite.strip()
        ):
            raise InventoryValidationError(
                f"Missing jobsite for {equipment}."
            )

        if (
            type(quantity) is not int
            or quantity <= 0
            or quantity > EQUIPMENT[equipment]
        ):
            raise InventoryValidationError(
                f"Invalid location quantity for {equipment}."
            )

        validated.append({
            "equipment": equipment,
            "jobsite": jobsite.strip(),
            "quantity": quantity,
        })

    return validated


# --------------------------------------------------
# INVENTORY MOVEMENT CALCULATION
# --------------------------------------------------

def calculate_movement(
    previous_on_truck,
    current_on_truck,
    expected
):
    """
    Calculate inventory changes between snapshots.

    Returns:
        taken_out
        returned
        outstanding
    """

    outstanding = expected - current_on_truck

    if previous_on_truck is None:

        return {
            "taken_out": 0,
            "returned": 0,
            "outstanding": outstanding,
            "baseline": True,
        }

    difference = current_on_truck - previous_on_truck

    return {
        "taken_out": max(-difference, 0),
        "returned": max(difference, 0),
        "outstanding": outstanding,
        "baseline": False,
    }


# --------------------------------------------------
# LOCATION RECONCILIATION
# --------------------------------------------------

def reconcile_locations(
    previous_locations,
    previous_outstanding,
    current_outstanding,
    new_locations,
    report_date
):
    """
    Reconcile outstanding equipment locations.

    Location entries are evidence of reported
    jobsite placement, not guaranteed custody.

    If quantities return without jobsite attribution,
    the remaining locations become uncertain.

    New location updates are treated as observations
    of equipment at a jobsite, not automatically
    as additional outstanding quantities.
    """

    locations = deepcopy(previous_locations)

    if current_outstanding == 0:
        return []

    # Normalize previously stored records.
    normalized = []

    for location in locations:

        quantity = location.get("quantity", 0)

        if type(quantity) is not int or quantity <= 0:
            continue

        normalized.append({
            "jobsite": location.get(
                "jobsite", "Unknown"
            ),
            "quantity": quantity,
            "status": location.get(
                "status", "unconfirmed"
            ),
            "last_reported": location.get(
                "last_reported"
            ),
        })

    locations = normalized

    # An increase in on-truck quantity indicates
    # returns, but the source jobsite is unknown.
    if (
        previous_outstanding is not None
        and current_outstanding < previous_outstanding
    ):

        for location in locations:
            location["status"] = "unconfirmed"

    # New jobsite observations are retained,
    # without assuming that they represent
    # additional equipment leaving the truck.
    for update in new_locations:

        jobsite = update["jobsite"]
        quantity = update["quantity"]

        existing = next(
            (
                location
                for location in locations
                if location["jobsite"] == jobsite
            ),
            None
        )

        if existing is not None:

            existing["quantity"] = quantity
            existing["status"] = "reported"
            existing["last_reported"] = report_date

        else:

            locations.append({
                "jobsite": jobsite,
                "quantity": quantity,
                "status": "reported",
                "last_reported": report_date,
            })

    # Check whether the known location quantities
    # exceed the actual outstanding inventory.
    recorded_total = sum(
        location["quantity"]
        for location in locations
    )

    if recorded_total > current_outstanding:

        # We cannot reliably determine which
        # locations account for the remaining
        # equipment, so retain the evidence but
        # mark the quantities as unconfirmed.
        for location in locations:
            location["status"] = "unconfirmed"

    return locations


# --------------------------------------------------
# BUILD UPDATED INVENTORY STATE
# --------------------------------------------------

def build_updated_state(
    previous_state,
    report_date,
    quantities,
    location_updates
):
    """
    Calculate the next inventory state without
    modifying the original state.

    Returns:
        updated_state
        movement_summary
    """

    updated_state = deepcopy(previous_state)

    movement_summary = []

    for name, expected in EQUIPMENT.items():

        item = updated_state["equipment"][name]

        previous_on_truck = item["on_truck"]
        current_on_truck = quantities[name]

        previous_outstanding = item["outstanding"]

        movement = calculate_movement(
            previous_on_truck,
            current_on_truck,
            expected
        )

        equipment_locations = [
            {
                "jobsite": entry["jobsite"],
                "quantity": entry["quantity"],
            }
            for entry in location_updates
            if entry["equipment"] == name
        ]

        locations = reconcile_locations(
            previous_locations=item["locations"],
            previous_outstanding=previous_outstanding,
            current_outstanding=movement["outstanding"],
            new_locations=equipment_locations,
            report_date=report_date,
        )

        item["on_truck"] = current_on_truck
        item["outstanding"] = movement["outstanding"]
        item["last_verified"] = report_date
        item["locations"] = locations

        movement_summary.append({
            "equipment": name,
            "expected": expected,
            "previous_on_truck": previous_on_truck,
            "on_truck": current_on_truck,
            "taken_out": movement["taken_out"],
            "returned": movement["returned"],
            "outstanding": movement["outstanding"],
            "baseline": movement["baseline"],
            "locations": deepcopy(locations),
        })

    updated_state["initialized"] = True
    updated_state["last_processed_date"] = report_date
    updated_state["last_updated"] = current_timestamp()

    return updated_state, movement_summary


# --------------------------------------------------
# BUILD PROCESSING HISTORY ENTRY
# --------------------------------------------------

def build_history_entry(
    report_id,
    report_date,
    source_file,
    quantities,
    location_updates
):
    """
    Create a history entry for a verified report.
    """

    return {
        "report_id": report_id,
        "report_date": report_date,
        "source_file": str(source_file),
        "processed_at": current_timestamp(),
        "quantities": deepcopy(quantities),
        "location_updates": deepcopy(location_updates),
    }


# --------------------------------------------------
# PROCESS VERIFIED INVENTORY REPORT
# --------------------------------------------------

def process_inventory_report(
    report_id,
    report_date,
    source_file,
    quantities,
    location_updates=None
):
    """
    Process one verified daily inventory report.

    Reports must be processed chronologically.

    The report ID should be a stable identifier,
    preferably derived from the source PDF's
    content hash.

    Returns a movement summary and updated state.
    """

    if not isinstance(report_id, str) or not report_id.strip():
        raise InventoryValidationError(
            "A valid report ID is required."
        )

    validate_report_date(report_date)

    quantities = validate_quantities(quantities)

    location_updates = validate_location_updates(
        location_updates
    )

    previous_state = load_inventory_state()
    history = load_history()

    if report_already_processed(report_id):
        raise DuplicateReportError(
            f"Report already processed: {report_id}"
        )

    last_date = previous_state.get(
        "last_processed_date"
    )

    if (
        last_date is not None
        and report_date < last_date
    ):
        raise OutOfOrderReportError(
            f"Report dated {report_date} is older "
            f"than the latest processed date {last_date}."
        )

    updated_state, movement_summary = (
        build_updated_state(
            previous_state=previous_state,
            report_date=report_date,
            quantities=quantities,
            location_updates=location_updates,
        )
    )

    entry = build_history_entry(
        report_id=report_id,
        report_date=report_date,
        source_file=source_file,
        quantities=quantities,
        location_updates=location_updates,
    )

    updated_history = deepcopy(history)

    updated_history["processed_reports"].append(
        entry
    )

    updated_history["processed_reports"].sort(
        key=lambda report: (
            report["report_date"],
            report["report_id"]
        )
    )

    # The two files cannot be committed atomically.
    # Keep the history entry ready for recovery.
    #
    # We will add an explicit recovery mechanism
    # before connecting this to automated OCR.
    save_inventory_state(updated_state)
    save_history(updated_history)

    return {
        "report_id": report_id,
        "report_date": report_date,
        "movements": movement_summary,
        "state": updated_state,
    }


# --------------------------------------------------
# INVENTORY TOTALS
# --------------------------------------------------

def calculate_inventory_totals(state):
    """
    Calculate aggregate inventory totals.

    Unknown quantities remain unknown until
    a verified baseline is established.
    """

    total_expected = sum(EQUIPMENT.values())

    if not state.get("initialized"):
        return {
            "expected": total_expected,
            "on_truck": None,
            "outstanding": None,
        }

    total_on_truck = sum(
        item["on_truck"]
        for item in state["equipment"].values()
    )

    return {
        "expected": total_expected,
        "on_truck": total_on_truck,
        "outstanding": (
            total_expected - total_on_truck
        ),
    }


# --------------------------------------------------
# GET OUTSTANDING EQUIPMENT
# --------------------------------------------------

def get_outstanding_equipment(state):
    """
    Return equipment categories with outstanding
    quantities greater than zero.
    """

    outstanding = []

    for name, item in state["equipment"].items():

        quantity = item["outstanding"]

        if quantity is None or quantity <= 0:
            continue

        outstanding.append({
            "equipment": name,
            "expected": item["expected"],
            "on_truck": item["on_truck"],
            "outstanding": quantity,
            "locations": deepcopy(item["locations"]),
        })

    return outstanding


# --------------------------------------------------
# GET LOCATION WARNINGS
# --------------------------------------------------

def get_location_warnings(state):
    """
    Identify equipment whose location records
    are incomplete, uncertain, or inconsistent.
    """

    warnings = []

    for name, item in state["equipment"].items():

        outstanding = item["outstanding"]

        if outstanding is None or outstanding == 0:
            continue

        locations = item["locations"]

        recorded_total = sum(
            location.get("quantity", 0)
            for location in locations
        )

        if not locations:

            warnings.append({
                "equipment": name,
                "issue": "No jobsite location recorded.",
            })

            continue

        if recorded_total != outstanding:

            warnings.append({
                "equipment": name,
                "issue": (
                    f"Location records total {recorded_total}, "
                    f"but {outstanding} items are outstanding."
                ),
            })

        if any(
            location.get("status") != "reported"
            for location in locations
        ):

            warnings.append({
                "equipment": name,
                "issue": (
                    "One or more jobsite locations "
                    "are unconfirmed."
                ),
            })

    return warnings
