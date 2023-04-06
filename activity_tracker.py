import json
import gzip
import dataclasses
import datetime
from collections import defaultdict
from typing import List, Dict, Set


class EnhancedJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        if isinstance(o, datetime.datetime):
            return o.isoformat()
        return super().default(o)


def ensure_datetime(dt):
    if isinstance(dt, str):
        return datetime.datetime.fromisoformat(dt)
    else:
        assert isinstance(dt, datetime.datetime)
        return dt


@dataclasses.dataclass
class DateTimeRange:
    start: datetime.datetime
    end: datetime.datetime

    def __init__(self, start, end):
        self.start = ensure_datetime(start)
        self.end = ensure_datetime(end)

    def __repr__(self):
        return f"[{self.start.isoformat()}, {self.end.isoformat()}]"


class ActivityTracker:
    STORAGE_FILE = "activeusers_storage.json"

    def __init__(self, read_status_from_file=True):
        self.active_users: Set[str] = set()
        self.user_to_time_ranges: Dict[str, List[DateTimeRange]] = defaultdict(list)
        if read_status_from_file:
            self.read_activity_status_from_file(ignore_error=True)

    def save_activity_status(
        self, active_users: Set[str], inactive_users: Set[str], dt: datetime.datetime
    ):
        for user in active_users:
            if user in self.active_users:
                self._prolong_last_activity(user, dt)
            else:
                self._add_new_activity(user, dt)

        for user in inactive_users:
            if user in self.active_users:
                self._prolong_last_activity(user, dt)

        self.active_users.update(active_users)
        self.active_users = self.active_users - inactive_users
        self.store_activity_in_file()

    def get_activity_status_json(self):
        return json.dumps(
            {
                "active_users": list(self.active_users),
                "user_to_time_ranges": self.user_to_time_ranges,
                "now": datetime.datetime.now(),
            },
            cls=EnhancedJSONEncoder,
        )

    def restore_activity_status_from_json(self, activity_json):
        activity_dict = json.loads(activity_json)
        self.active_users = set(activity_dict["active_users"])
        range_dicts_list = activity_dict["user_to_time_ranges"]
        self.user_to_time_ranges.clear()
        for user, range_list in range_dicts_list.items():
            for range_dict in range_list:
                dt_range = DateTimeRange(**range_dict)
                self.user_to_time_ranges[user].append(dt_range)
        then = datetime.datetime.fromisoformat(activity_dict["now"])
        now = datetime.datetime.now()
        if then + datetime.timedelta(minutes=10) < now:
            # long pause - mark all users as offline on then
            self.save_activity_status(
                active_users=set(), inactive_users=set(self.active_users), dt=then
            )

    def store_activity_in_file(self):
        content = self.get_activity_status_json()
        with gzip.open(ActivityTracker.STORAGE_FILE, "wt") as f:
            f.write(content)

    def read_activity_status_from_file(self, ignore_error=False):
        try:
            with gzip.open(ActivityTracker.STORAGE_FILE, "rt") as f:
                content = f.read()
            self.restore_activity_status_from_json(content)
        except OSError:
            if not ignore_error:
                raise

    def _prolong_last_activity(self, user: str, dt: datetime.datetime):
        try:
            last_range = self.user_to_time_ranges[user][-1]
            last_range.end = dt
            assert last_range.start <= last_range.end
        except IndexError:
            self._add_new_activity(user, dt)

    def _add_new_activity(self, user: str, dt: datetime.datetime):
        new_range = DateTimeRange(dt, dt)
        self.user_to_time_ranges[user].append(new_range)

    def pprint(self):
        print("=================================================")
        for user, activity_list in self.user_to_time_ranges.items():
            print(f"User: {user}")
            for dt_range in activity_list:
                print(f"   {dt_range}")
