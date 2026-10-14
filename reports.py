
"""
Toolbox Inventory Reports
Weekly Excel report generator.

Responsibilities:
- Generate printable Excel inventory reports
- Summarize on-truck and outstanding equipment
- Display last-reported jobsite information
- Identify inventory discrepancies
- Configure Excel printing and page layout

This module reads inventory state but does
not modify inventory records.
"""

from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.styles import (
    Font,
    PatternFill,
    Border,
    Side,
    Alignment,
)
from openpyxl.worksheet.pagebreak import Break
from openpyxl.utils import get_column_letter

from config import (
    EQUIPMENT,
    OUTPUT_DIR,
    REPORT_TITLE,
    REPORT_FILENAME_PREFIX,
    REPORT_ORIENTATION,
    REPORT_FIT_TO_WIDTH,
    REPORT_FIT_TO_HEIGHT,
    INCLUDE_JOBSITE_DETAILS,
    INCLUDE_DISCREPANCIES,
    TIMEZONE,
    initialize_directories,
)

from storage import load_inventory_state

from processor import (
    calculate_inventory_totals,
    get_outstanding_equipment,
    get_location_warnings,
)


# --------------------------------------------------
# REPORT COLORS
# --------------------------------------------------

DARK_BLUE = "17365D"
MEDIUM_BLUE = "305496"
LIGHT_BLUE = "D9EAF7"

WHITE = "FFFFFF"
BLACK = "000000"

LIGHT_GRAY = "F2F2F2"
MEDIUM_GRAY = "D9E1F2"

GREEN = "E2F0D9"
YELLOW = "FFF2CC"
RED = "FCE4D6"

BORDER_COLOR = "B7C9D6"


# --------------------------------------------------
# REPORT STYLES
# --------------------------------------------------

THIN_BORDER = Border(
    left=Side(
        style="thin",
        color=BORDER_COLOR
    ),
    right=Side(
        style="thin",
        color=BORDER_COLOR
    ),
    top=Side(
        style="thin",
        color=BORDER_COLOR
    ),
    bottom=Side(
        style="thin",
        color=BORDER_COLOR
    ),
)


# --------------------------------------------------
# DATE HELPERS
# --------------------------------------------------

def current_date():
    """Return today's date in Eastern time."""

    return datetime.now(
        ZoneInfo(TIMEZONE)
    ).date()


def normalize_report_date(report_date):
    """
    Convert an optional report date into
    a Python date object.
    """

    if report_date is None:
        return current_date()

    if isinstance(report_date, datetime):
        return report_date.date()

    if isinstance(report_date, date):
        return report_date

    if isinstance(report_date, str):
        return date.fromisoformat(report_date)

    raise ValueError(
        "Invalid report date."
    )


# --------------------------------------------------
# WORKSHEET CONFIGURATION
# --------------------------------------------------

def configure_worksheet(ws):
    """
    Configure page dimensions, margins,
    and Excel printing settings.
    """

    ws.sheet_view.showGridLines = False

    column_widths = {
        "A": 24,
        "B": 15,
        "C": 15,
        "D": 17,
        "E": 22,
        "F": 20,
    }

    for column, width in column_widths.items():
        ws.column_dimensions[column].width = width

    ws.sheet_properties.pageSetUpPr.fitToPage = True

    ws.page_setup.orientation = REPORT_ORIENTATION

    ws.page_setup.paperSize = ws.PAPERSIZE_LETTER

    ws.page_setup.fitToWidth = REPORT_FIT_TO_WIDTH
    ws.page_setup.fitToHeight = REPORT_FIT_TO_HEIGHT

    ws.page_margins.left = 0.25
    ws.page_margins.right = 0.25

    ws.page_margins.top = 0.40
    ws.page_margins.bottom = 0.40

    ws.page_margins.header = 0.15
    ws.page_margins.footer = 0.20

    ws.print_options.horizontalCentered = True

    ws.oddFooter.center.text = (
        "Page &P of &N"
    )

    ws.oddFooter.right.text = (
        "Toolbox Inventory"
    )


# --------------------------------------------------
# CELL FORMATTING
# --------------------------------------------------

def style_cell(
    cell,
    bold=False,
    fill=None,
    font_color=BLACK,
    alignment="left",
    font_size=10,
    wrap=False,
):
    """
    Apply consistent formatting to a cell.
    """

    cell.font = Font(
        name="Aptos",
        size=font_size,
        bold=bold,
        color=font_color,
    )

    if fill:
        cell.fill = PatternFill(
            fill_type="solid",
            fgColor=fill,
        )

    cell.alignment = Alignment(
        horizontal=alignment,
        vertical="center",
        wrap_text=wrap,
    )

    cell.border = THIN_BORDER


def merged_section(
    ws,
    row,
    title,
    fill=DARK_BLUE
):
    """
    Create a full-width section heading.
    """

    ws.merge_cells(
        start_row=row,
        start_column=1,
        end_row=row,
        end_column=6,
    )

    cell = ws.cell(
        row=row,
        column=1,
        value=title
    )

    style_cell(
        cell,
        bold=True,
        fill=fill,
        font_color=WHITE,
        font_size=11,
    )

    ws.row_dimensions[row].height = 24


def write_table_header(ws, row, headers):
    """Create a formatted table header."""

    for column, value in enumerate(
        headers,
        start=1
    ):

        cell = ws.cell(
            row=row,
            column=column,
            value=value,
        )

        style_cell(
            cell,
            bold=True,
            fill=MEDIUM_BLUE,
            font_color=WHITE,
            alignment="center",
            wrap=True,
        )

    ws.row_dimensions[row].height = 28


# --------------------------------------------------
# REPORT HEADER
# --------------------------------------------------

def write_report_header(
    ws,
    report_date,
    state
):
    """
    Write report title and inventory date.
    """

    ws.merge_cells("A1:F2")

    title_cell = ws["A1"]

    title_cell.value = REPORT_TITLE

    title_cell.font = Font(
        name="Aptos Display",
        size=18,
        bold=True,
        color=WHITE,
    )

    title_cell.fill = PatternFill(
        fill_type="solid",
        fgColor=DARK_BLUE,
    )

    title_cell.alignment = Alignment(
        horizontal="center",
        vertical="center",
    )

    ws.row_dimensions[1].height = 25
    ws.row_dimensions[2].height = 25

    ws.merge_cells("A3:C3")
    ws.merge_cells("D3:F3")

    ws["A3"] = (
        "Report Date: "
        + report_date.strftime("%m/%d/%Y")
    )

    last_verified = state.get(
        "last_processed_date"
    )

    ws["D3"] = (
        "Latest Inventory: "
        + str(last_verified or "Not established")
    )

    for address in ("A3", "D3"):

        cell = ws[address]

        cell.font = Font(
            name="Aptos",
            size=10,
            bold=True,
            color=DARK_BLUE,
        )

        cell.alignment = Alignment(
            vertical="center"
        )

    ws.row_dimensions[3].height = 25


# --------------------------------------------------
# INVENTORY SUMMARY
# --------------------------------------------------

def write_inventory_summary(
    ws,
    state,
    start_row
):
    """
    Write the equipment inventory summary.

    Returns the next available row.
    """

    merged_section(
        ws,
        start_row,
        "EQUIPMENT INVENTORY SUMMARY"
    )

    header_row = start_row + 1

    headers = [
        "Equipment",
        "Expected",
        "On Truck",
        "Still Out",
        "Status",
        "Last Verified",
    ]

    write_table_header(
        ws,
        header_row,
        headers
    )

    row = header_row + 1

    for name, expected in EQUIPMENT.items():

        item = state["equipment"][name]

        on_truck = item["on_truck"]
        outstanding = item["outstanding"]

        if outstanding is None:
            status = "UNVERIFIED"
            row_fill = YELLOW

        elif outstanding == 0:
            status = "COMPLETE"
            row_fill = GREEN

        else:
            status = "OUTSTANDING"
            row_fill = YELLOW

        values = [
            name,
            expected,
            on_truck,
            outstanding,
            status,
            item.get("last_verified") or "N/A",
        ]

        for column, value in enumerate(
            values,
            start=1
        ):

            cell = ws.cell(
                row=row,
                column=column,
                value=value,
            )

            style_cell(
                cell,
                fill=row_fill,
                alignment=(
                    "left"
                    if column in (1, 5, 6)
                    else "center"
                ),
            )

        ws.row_dimensions[row].height = 22

        row += 1

    # Summary totals

    totals = calculate_inventory_totals(
        state
    )

    values = [
        "TOTAL",
        totals["expected"],
        totals["on_truck"],
        totals["outstanding"],
        "",
        "",
    ]

    for column, value in enumerate(
        values,
        start=1
    ):

        cell = ws.cell(
            row=row,
            column=column,
            value=value,
        )

        style_cell(
            cell,
            bold=True,
            fill=LIGHT_BLUE,
            alignment=(
                "left"
                if column == 1
                else "center"
            ),
        )

    ws.row_dimensions[row].height = 25

    return row + 2


# --------------------------------------------------
# OUTSTANDING JOBSITE DETAILS
# --------------------------------------------------

def write_jobsite_details(
    ws,
    state,
    start_row
):
    """
    Display last-reported locations.

    Location records are historical evidence.
    They are not treated as confirmed current
    jobsite quantities when returns are unknown.
    """

    merged_section(
        ws,
        start_row,
        "OUTSTANDING EQUIPMENT - LAST REPORTED LOCATIONS"
    )

    headers = [
        "Equipment",
        "Still Out",
        "Jobsite / Location",
        "Reported Qty",
        "Location Status",
        "Last Reported",
    ]

    write_table_header(
        ws,
        start_row + 1,
        headers
    )

    row = start_row + 2

    outstanding_items = (
        get_outstanding_equipment(state)
    )

    if not outstanding_items:

        ws.merge_cells(
            start_row=row,
            start_column=1,
            end_row=row,
            end_column=6,
        )

        ws.cell(
            row=row,
            column=1,
            value="No outstanding equipment."
        )

        ws.row_dimensions[row].height = 24

        return row + 2

    for item in outstanding_items:

        equipment = item["equipment"]
        outstanding = item["outstanding"]

        locations = item["locations"]

        if not locations:

            values = [
                equipment,
                outstanding,
                "Unknown",
                None,
                "UNCONFIRMED",
                "N/A",
            ]

            write_detail_row(
                ws,
                row,
                values,
                RED
            )

            row += 1
            continue

        for index, location in enumerate(
            locations
        ):

            status = location.get(
                "status",
                "unconfirmed"
            )

            is_reported = (
                status == "reported"
            )

            values = [
                equipment if index == 0 else "",
                outstanding if index == 0 else "",
                location.get(
                    "jobsite", "Unknown"
                ),
                location.get("quantity"),
                (
                    "LAST REPORTED"
                    if is_reported
                    else "UNCONFIRMED"
                ),
                location.get(
                    "last_reported"
                ) or "N/A",
            ]

            fill = (
                LIGHT_GRAY
                if is_reported
                else YELLOW
            )

            write_detail_row(
                ws,
                row,
                values,
                fill
            )

            row += 1

    row += 1

    ws.merge_cells(
        start_row=row,
        start_column=1,
        end_row=row,
        end_column=6,
    )

    note = ws.cell(
        row=row,
        column=1,
        value=(
            "Note: Reported jobsite quantities "
            "are historical observations. "
            "They may not equal current "
            "outstanding quantities."
        )
    )

    note.font = Font(
        name="Aptos",
        size=9,
        italic=True,
        color=DARK_BLUE,
    )

    note.alignment = Alignment(
        wrap_text=True,
        vertical="center",
    )

    ws.row_dimensions[row].height = 32

    return row + 2


# --------------------------------------------------
# DETAIL ROW FORMATTING
# --------------------------------------------------

def write_detail_row(
    ws,
    row,
    values,
    fill
):
    """Write one jobsite detail row."""

    for column, value in enumerate(
        values,
        start=1
    ):

        cell = ws.cell(
            row=row,
            column=column,
            value=value,
        )

        style_cell(
            cell,
            fill=fill,
            alignment=(
                "center"
                if column in (2, 4)
                else "left"
            ),
            wrap=True,
        )

    ws.row_dimensions[row].height = 30


# --------------------------------------------------
# INVENTORY WARNINGS
# --------------------------------------------------

def write_inventory_warnings(
    ws,
    state,
    start_row
):
    """
    Write discrepancies and uncertain locations.
    """

    merged_section(
        ws,
        start_row,
        "INVENTORY WARNINGS / ITEMS TO REVIEW"
    )

    row = start_row + 1

    warnings = get_location_warnings(
        state
    )

    if not state.get("initialized"):

        warnings.insert(
            0,
            {
                "equipment": "Inventory",
                "issue": (
                    "No verified inventory "
                    "baseline has been established."
                ),
            }
        )

    last_verified = state.get(
        "last_processed_date"
    )

    if last_verified is None:

        warnings.append({
            "equipment": "Inventory",
            "issue": (
                "No daily inventory reports "
                "have been processed."
            ),
        })

    if not warnings:

        ws.merge_cells(
            start_row=row,
            start_column=1,
            end_row=row,
            end_column=6,
        )

        cell = ws.cell(
            row=row,
            column=1,
            value="No inventory warnings."
        )

        style_cell(
            cell,
            fill=GREEN,
        )

        ws.row_dimensions[row].height = 25

        return row + 2

    for warning in warnings:

        ws.merge_cells(
            start_row=row,
            start_column=2,
            end_row=row,
            end_column=6,
        )

        equipment_cell = ws.cell(
            row=row,
            column=1,
            value=warning["equipment"],
        )

        issue_cell = ws.cell(
            row=row,
            column=2,
            value=warning["issue"],
        )

        style_cell(
            equipment_cell,
            bold=True,
            fill=YELLOW,
            wrap=True,
        )

        style_cell(
            issue_cell,
            fill=YELLOW,
            wrap=True,
        )

        ws.row_dimensions[row].height = 34

        row += 1

    return row + 2


# --------------------------------------------------
# REPORT FOOTER
# --------------------------------------------------

def write_report_footer(
    ws,
    start_row
):
    """
    Write a report-generation timestamp.
    """

    ws.merge_cells(
        start_row=start_row,
        start_column=1,
        end_row=start_row,
        end_column=6,
    )

    timestamp = datetime.now(
        ZoneInfo(TIMEZONE)
    ).strftime("%m/%d/%Y %I:%M %p")

    cell = ws.cell(
        row=start_row,
        column=1,
        value=(
            "Generated: "
            + timestamp
            + " | Toolbox Inventory Reports"
        ),
    )

    cell.font = Font(
        name="Aptos",
        size=9,
        italic=True,
        color="666666",
    )

    cell.alignment = Alignment(
        horizontal="center"
    )

    ws.row_dimensions[start_row].height = 22


# --------------------------------------------------
# REPORT FILENAME
# --------------------------------------------------

def create_report_filename(report_date):
    """
    Create a consistent weekly report filename.
    """

    date_string = report_date.strftime(
        "%Y-%m-%d"
    )

    return (
        f"{REPORT_FILENAME_PREFIX}_"
        f"{date_string}.xlsx"
    )


# --------------------------------------------------
# GENERATE EXCEL REPORT
# --------------------------------------------------

def generate_report(
    report_date=None,
    state=None,
    output_path=None,
):
    """
    Generate a weekly Excel inventory report.

    report_date:
        Date displayed on the report.

    state:
        Optional inventory state.
        Defaults to the latest saved state.

    output_path:
        Optional destination path.

    Returns:
        Path to the generated Excel workbook.
    """

    initialize_directories()

    report_date = normalize_report_date(
        report_date
    )

    if state is None:
        state = load_inventory_state()

    # Prevent presenting a later inventory snapshot
    # as if it were known on an earlier report date.
    last_processed = state.get(
        "last_processed_date"
    )

    if (
        last_processed is not None
        and last_processed > report_date.isoformat()
    ):
        raise ValueError(
            "The inventory state contains data "
            "newer than the requested report date. "
            "Use a historical state snapshot "
            "to generate that earlier report."
        )

    workbook = Workbook()

    ws = workbook.active
    ws.title = "Weekly Inventory"

    configure_worksheet(ws)

    write_report_header(
        ws,
        report_date,
        state
    )

    row = 5

    row = write_inventory_summary(
        ws,
        state,
        row
    )

    # Keep the main summary together on page one.
    # Detail sections may continue onto additional
    # pages when necessary.

    if INCLUDE_JOBSITE_DETAILS:

        row = write_jobsite_details(
            ws,
            state,
            row
        )

    if INCLUDE_DISCREPANCIES:

        row = write_inventory_warnings(
            ws,
            state,
            row
        )

    write_report_footer(
        ws,
        row
    )

    ws.print_area = f"A1:F{row}"

    ws.sheet_properties.pageSetUpPr.fitToPage = True

    # Repeat the report title and date on
    # additional printed pages.
    ws.print_title_rows = "1:3"

    if output_path is None:

        output_path = (
            OUTPUT_DIR
            / create_report_filename(
                report_date
            )
        )

    output_path = Path(
        output_path
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    workbook.save(
        output_path
    )

    return output_path


# --------------------------------------------------
# STANDALONE REPORT TEST
# --------------------------------------------------

if __name__ == "__main__":

    print("\nGenerating Toolbox Inventory Report...")

    try:

        output = generate_report()

        print(
            f"\nReport successfully generated:\n"
            f"{output}"
        )

    except Exception as error:

        print(
            f"\nReport generation failed: {error}"
        )

        raise
