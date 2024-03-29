import datetime
import os
import signal
import socket
import ssl
import time
from functools import partial
from http.client import HTTPException
from threading import Thread
from urllib.error import URLError

import certifi as certifi
from ratelimit import sleep_and_retry, limits
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from activity_tracker import ActivityTracker
from utils import (
    GroupsAndUsersThreadSafeDict,
    user_dict_to_user,
    group_dict_to_group,
    get_group_name_and_limit_from_msg, apply_aliases, get_limit,
)

BOT_NAME = "ActiveUsers"
MINUTE = 60


class RefreshStatusThread(Thread):
    def __init__(
        self,
        slack_client,
        groups_users_dict: GroupsAndUsersThreadSafeDict,
        refresh_seconds=120,
        sleep_time=1,
    ):
        super().__init__(name="RefreshStatusThread")
        self._groups_users_dict = groups_users_dict
        self._client = slack_client
        self._stop_requested = False
        self.last_refresh_time = None
        self.refresh_seconds = refresh_seconds
        self.sleep_time = sleep_time
        self.bot_user = None
        self.activity_tracker = ActivityTracker(read_status_from_file=True)

    def request_stop(self):
        self._stop_requested = True

    @sleep_and_retry
    @limits(calls=20, period=MINUTE)
    def get_usergroups_list(self):
        return self._client.usergroups_list(include_users=True)["usergroups"]

    @sleep_and_retry
    @limits(calls=20, period=MINUTE)
    def get_users_list(self):
        return self._client.users_list()["members"]

    @sleep_and_retry
    @limits(calls=50, period=MINUTE)
    def get_user_presence(self, user_id):
        return self._client.users_getPresence(user=user_id)["presence"]

    def refresh_groups_and_users_info(self):
        try:
            groups = self.get_usergroups_list()
            users = self.get_users_list()
        except (SlackApiError, URLError, socket.timeout, socket.error, HTTPException):
            return
        user_id_to_user = {}
        users_in_groups_ids = set()
        for user_dict in users:
            if (
                user_dict["is_bot"]
                and "real_name" in user_dict
                and user_dict["real_name"] == BOT_NAME
            ):
                if self.bot_user is None:
                    self.bot_user = user_dict_to_user(user_dict)
                    self._groups_users_dict.set_bot_user(self.bot_user)
                continue
            if user_dict["deleted"] or user_dict["is_bot"]:
                continue
            user = user_dict_to_user(user_dict)
            user_id_to_user[user.id] = user

        group_handle_to_group = {}
        for group_dict in groups:
            group = group_dict_to_group(group_dict)
            users_in_groups_ids.update(group.user_ids)
            group_handle_to_group[group.handle] = group
        for user_id in users_in_groups_ids:
            try:
                presence = self.get_user_presence(user_id)
                if self._stop_requested:
                    return
            except (
                SlackApiError,
                URLError,
                socket.timeout,
                socket.error,
                HTTPException,
            ):
                continue
            if presence == "active":
                user = user_id_to_user.get(user_id)
                if user is None:
                    continue  # Unknown user - we will get his info next time
                user.active = True
        self._groups_users_dict.update_groups_and_users(
            list(group_handle_to_group.values()), list(user_id_to_user.values())
        )
        users = user_id_to_user.values()
        active_ids = set([u.id for u in users if u.active])
        inactive_ids = set([u.id for u in users if not u.active])
        self.activity_tracker.save_activity_status(
            active_users=active_ids,
            inactive_users=inactive_ids,
            dt=datetime.datetime.now(),
        )
        active_names = [u.id for u in users if u.active]
        active_names.sort()
        print(
            f"[{datetime.datetime.now()}] Refreshed active users: {', '.join(active_names)}"
        )

    def run(self):
        while not self._stop_requested:
            now = time.time()
            if (
                self.last_refresh_time is None
                or now - self.last_refresh_time >= self.refresh_seconds
            ):
                self.refresh_groups_and_users_info()
                self.last_refresh_time = now
            time.sleep(self.sleep_time)


STARFISH_ALIASES = {
    "core": "coreteam",
    "gui": "gui_team",
}

STARFISH_TEAM_ID = "T04QW7B6D"


def _groups_str(names):
    if not names:
        return None
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def handle_app_mention(groups_dict: GroupsAndUsersThreadSafeDict, event, say):
    if event is None:
        return
    bot_user = groups_dict.bot_user
    if bot_user is None:
        return
    team_id = event.get("team")
    text: str = event["text"]
    assert bot_user.id in text
    requested_groups_with_limits = get_group_name_and_limit_from_msg(text, bot_user.id)
    if team_id == STARFISH_TEAM_ID:
        requested_groups_with_limits = apply_aliases(requested_groups_with_limits, STARFISH_ALIASES)

    msg_list = []
    notify_msgs = []
    requesting_user_id = event["user"]
    if not requested_groups_with_limits:
        msg_list.append("You need to type name of the group!")
    else:
        try:
            group_name_to_group_and_users = groups_dict.get_groups_and_users(requested_groups_with_limits)
            for group_name, group_and_users in group_name_to_group_and_users.items():
                group, users_in_group = group_and_users
                limit = get_limit(requested_groups_with_limits, group_name)
                active_users = [user for user in users_in_group if user.active and user.id != requesting_user_id]
                if limit is not None:
                    active_users = active_users[:limit]
                if not active_users:
                    msg_list.append(f"There are no active users in group {group_name}.")
                else:
                    user_ids_str = ", ".join([f"<@{user.id}>" for user in active_users])
                    amount_str = "all" if limit is None else f"{limit}"
                    notify_msgs.append(f"{amount_str} active users of {group_name}: {user_ids_str}")
        except KeyError as e:
            available_groups = ", ".join(groups_dict.get_groups_handles())
            msg_list.append(f"Can't recognise group {e.args[0]}. Available groups: {available_groups}")

    msg = "\n".join(msg_list)
    if notify_msgs:
        if msg:
            msg += "\n"
        msg += f"User <@{requesting_user_id}> asked me to notify " + " and ".join(notify_msgs)
    say(text=msg, thread_ts=event.get("thread_ts", event["ts"]))


def connect_to_slack():
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    client = WebClient(token=os.environ.get("SLACK_BOT_TOKEN"), ssl=ssl_context)
    bolt_app = App(token=os.environ.get("SLACK_BOT_TOKEN"))
    socket_mode_handler = SocketModeHandler(bolt_app, os.environ.get("SLACK_APP_TOKEN"))
    socket_mode_handler.connect()
    return bolt_app, client


def main():
    thread = None
    while True:
        try:
            bolt_app, client = connect_to_slack()
            groups_dict = GroupsAndUsersThreadSafeDict()
            thread = RefreshStatusThread(client, groups_dict, sleep_time=3)
            handle_app_mention_with_param = partial(handle_app_mention, groups_dict)
            bolt_app.event("app_mention")(handle_app_mention_with_param)
            thread.start()
            signal.pause()
        except KeyboardInterrupt:
            print(f"KeyboardInterrupt detected")
            break
        except Exception as e:
            print(f"Exception: {e}")
            time.sleep(10)  # to prevent tight error loop
        finally:
            print("Stopping thread")
            if thread is not None and thread.is_alive():
                thread.request_stop()
                thread.join()


if __name__ == "__main__":
    main()
