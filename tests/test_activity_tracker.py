import datetime
import os

import pytest

from activity_tracker import ActivityTracker, DateTimeRange
from utils import ParsedGroup, get_group_name_and_limit_from_msg


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

    def test_clock_step_backwards_keeps_tracking(self):
        tracker = ActivityTracker()
        later = datetime.datetime(2026, 11, 1, 5, 59, tzinfo=datetime.timezone.utc)
        earlier = later - datetime.timedelta(hours=1)

        tracker.save_activity_status(
            active_users={"ala"}, inactive_users=set(), dt=later
        )
        tracker.save_activity_status(
            active_users={"ala"}, inactive_users=set(), dt=earlier
        )

        assert "ala" in tracker.active_users
        ranges = tracker.user_to_time_ranges["ala"]
        assert ranges[0] == DateTimeRange(later, later)
        assert ranges[1] == DateTimeRange(earlier, earlier)

    def test_load_activity_tracker_from_non_existing_file(self):
        tracker = ActivityTracker()
        tracker.read_activity_status_from_file(ignore_error=True)
        assert tracker.active_users == set()
        assert len(tracker.user_to_time_ranges) == 0


    def test_get_parsed_group_list(self):
        bot_id = "ABC123"
        def test(msg, expected):
            assert get_group_name_and_limit_from_msg(msg, bot_id=bot_id) == expected
        test(f"some message <@{bot_id}> coreteam asdlkj asldaskj", [ParsedGroup(group_name='coreteam', limit=0, include_inactive=False)])
        test(f"<@{bot_id}> coreteam asdlkj asldaskj", [ParsedGroup(group_name='coreteam', limit=0, include_inactive=False)])
        test(f"<@{bot_id}> coreteam", [ParsedGroup(group_name='coreteam', limit=0, include_inactive=False)])
        test(f"<@{bot_id}>     coreteam", [ParsedGroup(group_name='coreteam', limit=0, include_inactive=False)])
        test(f"<@{bot_id}>", [])
        test(f"some msg \nasdlkj<@{bot_id}> coreteam asdasdasd", [ParsedGroup(group_name='coreteam', limit=0, include_inactive=False)])
        test(f"<@{bot_id}> coreteam <@{bot_id}> guiteam", [ParsedGroup(group_name='coreteam', limit=0, include_inactive=False), ParsedGroup(group_name='guiteam', limit=0, include_inactive=False)])
        test(f"<@{bot_id}> coreteam --2", [ParsedGroup(group_name='coreteam', limit=2, include_inactive=False)])
        test(f"<@{bot_id}> coreteam --123", [ParsedGroup(group_name='coreteam', limit=123, include_inactive=False)])
        test(f"some message <@{bot_id}> coreteam  --1 asdlkj asldaskj <@{bot_id}> team2 asdasd <@{bot_id}> team3 --3", [ParsedGroup(group_name='coreteam', limit=1, include_inactive=False), ParsedGroup(group_name='team2', limit=0, include_inactive=False), ParsedGroup(group_name='team3', limit=3, include_inactive=False)])
        test(f"<@{bot_id}> coreteam --all", [ParsedGroup(group_name='coreteam', limit=0, include_inactive=True)])
        test(f"<@{bot_id}> coreteam --all --2", [ParsedGroup(group_name='coreteam', limit=2, include_inactive=True)])
        test(f"<@{bot_id}> coreteam --2 --all", [ParsedGroup(group_name='coreteam', limit=2, include_inactive=True)])
        test(f"asd <@{bot_id}> team1 --all <@{bot_id}> team2 --3 --all <@{bot_id}> team3", [ParsedGroup(group_name='team1', limit=0, include_inactive=True), ParsedGroup(group_name='team2', limit=3, include_inactive=True), ParsedGroup(group_name='team3', limit=0, include_inactive=False)])
