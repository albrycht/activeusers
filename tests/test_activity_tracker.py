import datetime
import os

import pytest

from activity_tracker import ActivityTracker, DateTimeRange


def remove_file_if_exists(path):
    try:
        os.unlink(path)
    except OSError as exc:
        pass


@pytest.fixture(autouse=True)
def clean_activity_file():
    """Fixture to execute asserts before and after a test is run"""
    remove_file_if_exists(ActivityTracker.STORAGE_FILE)
    yield
    remove_file_if_exists(ActivityTracker.STORAGE_FILE)


class TestActivityTracker:
    def test_active_inactive_active_inactive(self):
        tracker = ActivityTracker()
        dt = datetime.datetime(year=2020, month=1, day=15, hour=13)
        dts = [dt + datetime.timedelta(hours=i) for i in range(10)]

        tracker.save_activity_status(
            active_users={"ala"}, inactive_users=set(), dt=dts[0]
        )
        tracker.save_activity_status(
            active_users=set(), inactive_users={"ala"}, dt=dts[1]
        )
        tracker.save_activity_status(
            active_users={"ala"}, inactive_users=set(), dt=dts[2]
        )
        tracker.save_activity_status(
            active_users=set(), inactive_users={"ala"}, dt=dts[3]
        )

        tracker.pprint()
        assert "ala" not in tracker.active_users
        assert tracker.user_to_time_ranges["ala"][0] == DateTimeRange(dts[0], dts[1])
        assert tracker.user_to_time_ranges["ala"][1] == DateTimeRange(dts[2], dts[3])

    def test_store_activity_in_file(self):
        tracker = ActivityTracker()
        dt = datetime.datetime(year=2020, month=1, day=15, hour=13)
        dts = [dt + datetime.timedelta(hours=i) for i in range(10)]

        tracker.save_activity_status(
            active_users={"ala", "basia"}, inactive_users=set(), dt=dts[0]
        )
        tracker.save_activity_status(
            active_users={"ala", "celina"}, inactive_users={"basia"}, dt=dts[1]
        )

        tracker.store_activity_in_file()
        del tracker

        new_tracker = ActivityTracker()
        new_tracker.read_activity_status_from_file()

        new_tracker.pprint()
        assert "ala" in new_tracker.active_users
        assert "celina" in new_tracker.active_users
        assert "basia" not in new_tracker.active_users
        assert new_tracker.user_to_time_ranges["ala"][0] == DateTimeRange(
            dts[0], dts[1]
        )
        assert new_tracker.user_to_time_ranges["basia"][0] == DateTimeRange(
            dts[0], dts[1]
        )
        assert new_tracker.user_to_time_ranges["celina"][0] == DateTimeRange(
            dts[1], dts[1]
        )

    def test_load_activity_tracker_from_non_existing_file(self):
        tracker = ActivityTracker()
        tracker.read_activity_status_from_file(ignore_error=True)
        assert tracker.active_users == set()
        assert len(tracker.user_to_time_ranges) == 0
