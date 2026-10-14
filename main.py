
"""
Toolbox Inventory Reports
Main application.

Run with:
    python main.py

Responsibilities:
- Display the application menu
- Scan and verify inventory PDFs
- Process verified inventory reports
- Generate weekly Excel reports
- Display current inventory and history
- Coordinate the complete workflow
"""

import json
import sys

from datetime import date
from pathlib import Path

from config import (
    EQUIPMENT,
    DATA_DIR,
    initialize_directories,
)

from scanner import (
    find_scanned_reports,
    scan_pdf,
    load_verified_scan,
    REVIEW_DIR,
)

from storage import (
    initialize_storage,
    load_inventory_state,
    load_history,
    report_already_processed,
)

from processor import (
    process_inventory_report,
    calculate_inventory_totals,
    get_outstanding_equipment,
    get_location_warnings,
    DuplicateReportError,
    OutOfOrderReportError,
    InventoryProcessingError,
)

from reports import generate_report


# --------------------------------------------------
# APPLICATION DISPLAY
# --------------------------------------------------

def print_header(title):
    """Display a formatted section heading."""

    print("\n" + "=" * 65)
    print(title.center(65))
    print("=" * 65)


def pause():
    """Wait for the user before returning to menu."""

    input("\nPress Enter to continue...")


def confirm(message):
    """Request confirmation before an operation."""

    while True:

        response = input(
            f"{message} (y/n): "
        ).strip().lower()

        if response in ("y", "yes"):
            return True

        if response in ("n", "no"):
            return False

        print("Please enter y or n.")


def select_file(files, title):
    """
    Display a numbered file selection menu.

    Returns a selected Path, or None if cancelled.
    """

    if not files:
        print("\nNo files available.")
        return None

    print_header(title)

    for index, file_path in enumerate(files, start=1):
        print(f"{index}. {file_path.name}")

    print("\n0. Cancel")

    while True:

        choice = input("\nSelect a file: ").strip()

        try:
            selection = int(choice)

            if selection == 0:
                return None

            if 1 <= selection <= len(files):
                return files[selection - 1]

        except ValueError:
            pass

        print("Invalid selection. Try again.")


# --------------------------------------------------
# STORAGE CONSISTENCY CHECK
# --------------------------------------------------

def check_storage_consistency():
    """
    Check basic agreement between inventory
    state and processing history.

    Refuse new processing when the files appear
    inconsistent. This is not a complete
    transaction recovery mechanism.
    """

    state = load_inventory_state()
    history = load_history()

    reports = history["processed_reports"]

    ids = [
        entry.get("report_id")
        for entry in reports
    ]

    if len(ids) != len(set(ids)):
        raise RuntimeError(
            "Duplicate report IDs found in history."
        )

    if not reports:

        if (
            state["initialized"]
            or state["last_processed_date"] is not None
        ):
            raise RuntimeError(
                "Inventory state exists without "
                "corresponding processing history."
            )

        return

    latest_date = max(
        entry["report_date"]
        for entry in reports
    )

    if (
        not state["initialized"]
        or state["last_processed_date"] != latest_date
    ):
        raise RuntimeError(
            "Inventory state and processing history "
            "do not agree. Do not continue processing. "
            "Review the backups in data/backups."
        )


# --------------------------------------------------
# SCAN ONE INVENTORY PDF
# --------------------------------------------------

def scan_inventory_menu():
    """Select, scan, and verify one PDF."""

    files = find_scanned_reports()

    selected = select_file(
        files,
        "SELECT INVENTORY PDF"
    )

    if selected is None:
        return

    report = scan_pdf(selected)

    print("\nScan verification complete.")
    print(f"Report ID: {report['report_id'][:16]}...")

    print(
        "\nThe verified report is saved and ready "
        "for inventory processing."
    )


# --------------------------------------------------
# FIND VERIFIED REPORTS
# --------------------------------------------------

def find_verified_reports():
    """Find verified JSON inventory reports."""

    if not REVIEW_DIR.exists():
        return []

    return sorted(
        REVIEW_DIR.glob("*.json")
    )


def get_pending_reports():
    """
    Return verified reports not already processed.

    Reports are ordered by inventory date and ID.
    """

    pending = []

    for path in find_verified_reports():

        report = load_verified_scan(path)

        if report_already_processed(
            report["report_id"]
        ):
            continue

        pending.append(report)

    pending.sort(
        key=lambda report: (
            report["report_date"],
            report["report_id"]
        )
    )

    return pending


# --------------------------------------------------
# PROCESS VERIFIED REPORTS
# --------------------------------------------------

def process_pending_reports():
    """
    Process verified inventory reports
    in chronological order.

    Stops immediately if a report fails.
    """

    check_storage_consistency()

    pending = get_pending_reports()

    if not pending:

        print("\nNo pending verified reports.")
        return 0

    print_header("PENDING INVENTORY REPORTS")

    for report in pending:

        print(
            f"{report['report_date']} | "
            f"{Path(report['source_file']).name}"
        )

    print(f"\nTotal pending: {len(pending)}")

    if not confirm(
        "Process these reports in date order?"
    ):
        print("Processing cancelled.")
        return 0

    processed_count = 0

    for report in pending:

        print(
            f"\nProcessing: {report['report_date']} "
            f"- {Path(report['source_file']).name}"
        )

        try:

            result = process_inventory_report(
                report_id=report["report_id"],
                report_date=report["report_date"],
                source_file=report["source_file"],
                quantities=report["quantities"],
                location_updates=report[
                    "location_updates"
                ],
            )

            processed_count += 1

            print("Successfully processed.")

            movements = [
                movement
                for movement in result["movements"]
                if (
                    movement["taken_out"] > 0
                    or movement["returned"] > 0
                )
            ]

            for movement in movements:

                print(
                    f"  {movement['equipment']}: "
                    f"-{movement['taken_out']} out, "
                    f"+{movement['returned']} returned, "
                    f"{movement['outstanding']} outstanding"
                )

        except (
            DuplicateReportError,
            OutOfOrderReportError,
            InventoryProcessingError,
            ValueError,
            OSError,
        ) as error:

            print(f"\nPROCESSING STOPPED: {error}")

            print(
                "The remaining reports were not "
                "processed. Review the error before "
                "running this operation again."
            )

            break

    print(
        f"\nSuccessfully processed "
        f"{processed_count} report(s)."
    )

    return processed_count


# --------------------------------------------------
# GENERATE EXCEL REPORT
# --------------------------------------------------

def generate_excel_menu():
    """Generate a report from current saved state."""

    print_header("GENERATE EXCEL REPORT")

    state = load_inventory_state()

    if not state["initialized"]:

        print(
            "\nNo verified inventory baseline exists."
        )

        print(
            "Process at least one verified "
            "inventory sheet first."
        )

        return

    last_date = state["last_processed_date"]

    print(f"\nLatest inventory date: {last_date}")

    print(
        "\nThis report will use the latest "
        "processed inventory state."
    )

    print(
        "The report date is a label, not a "
        "historical inventory reconstruction."
    )

    if not confirm("Generate Excel report?"):
        return

    output = generate_report(
        report_date=date.today(),
        state=state,
    )

    print("\nExcel report generated successfully.")
    print(f"\nFile: {output.resolve()}")


# --------------------------------------------------
# DISPLAY CURRENT INVENTORY
# --------------------------------------------------

def view_current_inventory():
    """Display current inventory in the terminal."""

    print_header("CURRENT TOOLBOX INVENTORY")

    state = load_inventory_state()

    if not state["initialized"]:

        print(
            "\nInventory has not been initialized "
            "from a verified report."
        )

        return

    print(
        f"\nLast verified: "
        f"{state['last_processed_date']}"
    )

    print("\n" + "-" * 65)

    print(
        f"{'Equipment':<22}"
        f"{'Expected':>10}"
        f"{'On Truck':>12}"
        f"{'Still Out':>12}"
    )

    print("-" * 65)

    for name, item in state["equipment"].items():

        print(
            f"{name:<22}"
            f"{item['expected']:>10}"
            f"{item['on_truck']:>12}"
            f"{item['outstanding']:>12}"
        )

    print("-" * 65)

    totals = calculate_inventory_totals(state)

    print(
        f"{'TOTAL':<22}"
        f"{totals['expected']:>10}"
        f"{totals['on_truck']:>12}"
        f"{totals['outstanding']:>12}"
    )

    outstanding = get_outstanding_equipment(state)

    print("\nOUTSTANDING EQUIPMENT")

    if not outstanding:
        print("All equipment accounted for.")

    for item in outstanding:

        print(
            f"\n{item['equipment']}: "
            f"{item['outstanding']} outstanding"
        )

        if not item["locations"]:
            print("  Location unknown.")

        for location in item["locations"]:

            print(
                f"  Last reported: "
                f"{location.get('jobsite', 'Unknown')} "
                f"({location['quantity']}) "
                f"[{location.get('status', 'unconfirmed')}]"
            )

    warnings = get_location_warnings(state)

    if warnings:

        print("\nINVENTORY WARNINGS")

        for warning in warnings:

            print(
                f"- {warning['equipment']}: "
                f"{warning['issue']}"
            )


# --------------------------------------------------
# DISPLAY PROCESSING HISTORY
# --------------------------------------------------

def view_processing_history():
    """Display previously processed inventory sheets."""

    print_header("PROCESSING HISTORY")

    history = load_history()

    reports = history["processed_reports"]

    if not reports:

        print("\nNo inventory reports processed yet.")
        return

    for index, report in enumerate(
        reports,
        start=1
    ):

        print(
            f"{index}. {report['report_date']} | "
            f"{Path(report['source_file']).name}"
        )

    print(
        f"\nTotal processed reports: {len(reports)}"
    )


# --------------------------------------------------
# COMPLETE WORKFLOW
# --------------------------------------------------

def run_complete_workflow():
    """
    Verify available PDFs, process pending reports,
    and generate the latest inventory report.
    """

    print_header("COMPLETE INVENTORY WORKFLOW")

    files = find_scanned_reports()

    verified_ids = set()

    for path in find_verified_reports():

        report = load_verified_scan(path)

        verified_ids.add(
            report["report_id"]
        )

    from scanner import calculate_file_hash

    unverified_files = []

    for path in files:

        file_id = calculate_file_hash(path)

        if file_id not in verified_ids:
            unverified_files.append(path)

    print(
        f"\nUnverified PDFs: "
        f"{len(unverified_files)}"
    )

    for path in unverified_files:

        print(f"\nNext scan: {path.name}")

        if not confirm(
            "Open this PDF for verification?"
        ):
            print(
                "Verification stopped. "
                "Remaining files were skipped."
            )
            break

        scan_pdf(path)

    print("\nChecking verified reports...")

    process_pending_reports()

    state = load_inventory_state()

    if state["initialized"]:

        if confirm(
            "\nGenerate the current Excel report?"
        ):
            generate_excel_menu()

    else:

        print(
            "\nNo verified inventory is available "
            "for report generation."
        )


# --------------------------------------------------
# MAIN MENU
# --------------------------------------------------

def display_menu():
    """Display application options."""

    print_header("TOOLBOX INVENTORY REPORTS")

    print("1. Scan and verify a PDF")
    print("2. Process verified inventory reports")
    print("3. Generate Excel report")
    print("4. View current inventory")
    print("5. View processing history")
    print("6. Run complete workflow")
    print("0. Exit")

    return input("\nSelect an option: ").strip()


# --------------------------------------------------
# MAIN APPLICATION
# --------------------------------------------------

def main():
    """Initialize and run the application."""

    initialize_directories()
    initialize_storage()

    print("\nToolbox Inventory Reports initialized.")

    while True:

        choice = display_menu()

        try:

            if choice == "1":
                scan_inventory_menu()

            elif choice == "2":
                process_pending_reports()

            elif choice == "3":
                generate_excel_menu()

            elif choice == "4":
                view_current_inventory()

            elif choice == "5":
                view_processing_history()

            elif choice == "6":
                run_complete_workflow()

            elif choice == "0":

                print("\nExiting Toolbox Inventory Reports.")
                break

            else:

                print("\nInvalid menu option.")

        except KeyboardInterrupt:

            print("\nOperation cancelled.")

        except Exception as error:

            print(
                f"\nERROR: {type(error).__name__}: "
                f"{error}"
            )

            print(
                "The operation could not be completed. "
                "Review the error before continuing."
            )

        if choice != "0":
            pause()


# --------------------------------------------------
# ENTRY POINT
# --------------------------------------------------

if __name__ == "__main__":
    main()
