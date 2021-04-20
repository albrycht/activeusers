import os
import socket
import time
from http.client import HTTPException
from threading import Thread
from typing import List
from urllib.error import URLError

from slack_bolt import App
from slack_sdk.errors import SlackApiError

from utils import GroupsAndUsersThreadSafeDict, User, Group, user_dict_to_user, group_dict_to_group, \
    get_group_name_from_msg

app = App(
    token=os.environ.get("SLACK_BOT_TOKEN"),
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET")
)

BOT_NAME = 'ActiveUsers'
groups_dict = GroupsAndUsersThreadSafeDict()

# To test locally run this tunnel:
# ssh -R 3000:localhost:3000 root@reviewraccoon.com
# but first kill working instance on server

# TODO
# Store activeness in DB and draw a graph


class RefreshStatusThread(Thread):
    def __init__(self, groups_users_dict: GroupsAndUsersThreadSafeDict, refresh_seconds=120, sleep_time=3):
        super().__init__(name="RefreshStatusThread")
        self._groups_users_dict = groups_users_dict
        self._stop_requested = False
        self.last_refresh_time = None
        self.refresh_seconds = refresh_seconds
        self.sleep_time = sleep_time
        self.bot_user = None

    def request_stop(self):
        self._stop_requested = True

    def refresh_groups_and_users_info(self):
        try:
            groups = app.client.usergroups_list(include_users=True)['usergroups']
            users = app.client.users_list()['members']
        except (SlackApiError, URLError, socket.timeout, socket.error, HTTPException):
            return
        user_id_to_user = {}
        users_in_groups_ids = set()
        for user_dict in users:
            if user_dict['is_bot'] and 'real_name' in user_dict and user_dict['real_name'] == 'ActiveUsers':
                if self.bot_user is None:
                    self.bot_user = user_dict_to_user(user_dict)
                    self._groups_users_dict.set_bot_user(self.bot_user)
                continue
            if user_dict['deleted'] or user_dict['is_bot']:
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
                presence = app.client.users_getPresence(user=user_id)['presence']
            except (SlackApiError, URLError, socket.timeout, socket.error, HTTPException):
                continue
            if presence == 'active':
                user = user_id_to_user.get(user_id)
                if user is None:
                    continue  # TODO probably we should handle it better
                user.active = True
        self._groups_users_dict.update_groups_and_users(
            list(group_handle_to_group.values()), list(user_id_to_user.values())
        )
        print("Refreshing information done")

    def run(self):
        while not self._stop_requested:
            now = time.time()
            if self.last_refresh_time is None or now - self.last_refresh_time >= self.refresh_seconds:
                self.refresh_groups_and_users_info()
                self.last_refresh_time = now
            time.sleep(self.sleep_time)


STARFISH_ALIASES = {
    'core': 'coreteam',
    'gui': 'guiteam',
}

STARFISH_TEAM_ID = "T04QW7B6D"


def _groups_str(names):
    if not names:
        return None
    if len(names) == 1:
        return names[0]
    return ', '.join(names[:-1]) + ' and ' + names[-1]


@app.event("app_mention")
def message_hello(event, say):
    if event is None:
        return
    bot_user = groups_dict.bot_user
    if bot_user is None:
        return
    team_id = event.get('team')
    text: str = event['text']
    assert bot_user.id in text
    required_groups = get_group_name_from_msg(text, bot_user.id)
    if team_id == STARFISH_TEAM_ID:
        for alias, original in STARFISH_ALIASES.items():
            if alias in required_groups:
                required_groups.remove(alias)
                required_groups.append(original)

    error_msg = None
    groups: List[Group]
    users: List[User]
    if not required_groups:
        error_msg = "You need to type name of the group!"
    else:
        try:
            groups, users = groups_dict.get_groups_and_users(required_groups)
            active_users = [user for user in users if user.active]
            if not active_users:
                if len(required_groups) == 1:
                    error_msg = f"There are no active users in group {required_groups[0]}."
                else:
                    error_msg = f"There are no active users in groups {_groups_str(required_groups)}."
        except KeyError as e:
            available_groups = ', '.join(groups_dict.get_groups_handles())
            error_msg = f"Can't recognise group {e.args[0]}. Available groups: {available_groups}"

    if error_msg:
        say(
            text=error_msg,
            thread_ts=event.get('thread_ts', event['ts'])
        )

    else:
        requesting_user_id = event['user']
        user_ids = [f"<@{user.id}>" for user in users if user.active and user.id != requesting_user_id]
        user_ids_str = ', '.join(user_ids)

        msg = f"User <@{requesting_user_id}> asked me to notify "
        msg += f'all active users of {_groups_str(required_groups)}'
        msg += f": {user_ids_str}"
        say(
            msg,
            thread_ts=event.get('thread_ts', event['ts']),
        )


def main():
    # Initializes your app with your bot token and signing secret
    global groups_dict
    thread = RefreshStatusThread(groups_dict, sleep_time=3)
    try:
        thread.start()
        app.start(port=int(os.environ.get("PORT", 3000)))
    finally:
        thread.request_stop()
        thread.join()
        pass


if __name__ == "__main__":
    main()
