"""
Pytest integration for ORCA Integrated Browser E2E Test Suite.
Runs all 8 edge cases using the Orca integrated browser automation engine.
"""

import pytest
import os
import sys
import urllib.request

# Add project root and scripts directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts")))

from scripts.e2e_orca_browser_runner import OrcaE2ETestSuite

def _is_frontend_running() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:3000", timeout=1.0) as resp:
            return resp.status in (200, 304)
    except Exception:
        return False

pytestmark = pytest.mark.skipif(
    not _is_frontend_running(),
    reason="Frontend dev server not running on http://localhost:3000",
)

@pytest.fixture(scope="module")
def orca_suite():
    suite = OrcaE2ETestSuite()
    suite.client.ensure_tab("http://localhost:3000")
    return suite

def test_ec1_navigation_integrity(orca_suite):
    success, details = orca_suite.test_ec1_navigation_integrity()
    assert success, f"EC-1 Failed: {details}"

def test_ec2_language_switcher(orca_suite):
    success, details = orca_suite.test_ec2_language_switcher()
    assert success, f"EC-2 Failed: {details}"

def test_ec3_chat_input_validation(orca_suite):
    success, details = orca_suite.test_ec3_chat_input_validation()
    assert success, f"EC-3 Failed: {details}"

def test_ec4_map_sector_selection(orca_suite):
    success, details = orca_suite.test_ec4_map_sector_selection()
    assert success, f"EC-4 Failed: {details}"

def test_ec5_map_layer_toggles(orca_suite):
    success, details = orca_suite.test_ec5_map_layer_toggles()
    assert success, f"EC-5 Failed: {details}"

def test_ec6_coordinate_search(orca_suite):
    success, details = orca_suite.test_ec6_coordinate_search()
    assert success, f"EC-6 Failed: {details}"

def test_ec7_mobile_viewport(orca_suite):
    success, details = orca_suite.test_ec7_mobile_viewport()
    assert success, f"EC-7 Failed: {details}"

def test_ec8_safety_badge_telemetry(orca_suite):
    success, details = orca_suite.test_ec8_safety_badge_telemetry()
    assert success, f"EC-8 Failed: {details}"
