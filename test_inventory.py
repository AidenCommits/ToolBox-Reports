
"""
Temporary inventory processing test.

Run only on a fresh test database.
Do not use with live inventory records.
"""

from processor import process_inventory_report

result = process_inventory_report(
    report_id="test-inventory-001",
    report_date="2026-10-13",
    source_file="test_inventory.pdf",
    quantities={
        "Vacuums": 2,
        "Dehumidifiers": 3,
        "Fans": 16,
        "Multitools": 2,
        "Sledgehammer": 1,
        "Fogger": 1,
        "Extension Cords": 4,
        "Poles": 6,
    },
    location_updates=[
        {
            "equipment": "Fans",
            "jobsite": "Johnson Residence",
            "quantity": 4,
        },
        {
            "equipment": "Dehumidifiers",
            "jobsite": "Smith Residence",
            "quantity": 1,
        },
        {
            "equipment": "Extension Cords",
            "jobsite": "Johnson Residence",
            "quantity": 2,
        },
    ],
)

print("Test inventory processed successfully.")

for movement in result["movements"]:
    print(
        f"{movement['equipment']}: "
        f"{movement['outstanding']} outstanding"
    )
