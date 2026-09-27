"""Page finder works on layouts beyond DESC / GPC (FPL Ten-Year Site Plan style)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from page_detect import score_page  # noqa: E402

FPL_SCHEDULE_10 = """Florida Power & Light Company 315
Page 1 of 84
Schedule 10
Status Report and Specifications of Proposed Transmission Lines
Clover Solar Energy Center (St. Lucie County)
(1) Point of Origin and Termination: Sunbreak Substation to the new Clover Substation
(4) Line Length: Approximately 2 miles
(5) Voltage: 230 kV
(6) Anticipated Construction Timing: Start date: 2025
End date: 2026
(8) Substations: Clover Substation
"""

FPL_TABLE = """III.E Transmission Plan
Table III.E.1: List of Proposed Power Lines
Line Ownership Terminals (To) Terminals (From) Line Length CKT. Miles Commercial In-Service Date (Mo/Yr)
FPL Sweatt Whidden 79 June/2026 230 1,195
FPL Oasis Andytown 30 December/2031 500 3,464
"""

FPL_SCHEDULE_9 = """Florida Power & Light Company 215
Page 1 of 100
Schedule 9
Status Report and Specifications of Proposed Generating Facilities
Construction start date: 2025 Commercial in-service date: 2026 substation line
"""


def test_month_year_and_year_only_dates_count():
    assert score_page(FPL_SCHEDULE_10)["dates"] >= 1
    assert score_page(FPL_TABLE)["dates"] >= 2
    assert score_page(FPL_SCHEDULE_10)["score"] > 12 and score_page(FPL_TABLE)["score"] > 12


def test_power_plant_pages_are_excluded():
    assert score_page(FPL_SCHEDULE_9)["excluded"] and score_page(FPL_SCHEDULE_9)["score"] == 0
