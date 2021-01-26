import os
import time
from threading import Thread
from typing import List, Optional

from slack_bolt import App
from slack_sdk.errors import SlackApiError

from utils import GroupsAndUsersThreadSafeDict, User, Group, user_dict_to_user, group_dict_to_group, \
    get_team_name_from_msg

ALL_A = "ALL_ACTIVE_USERS"

app = App(
    token=os.environ.get("SLACK_BOT_TOKEN"),
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET")
)

BOT_NAME = 'ActiveUsers'
ALL_ACTIVE_USERS = 'ALL_ACTIVE_USERS'
CHECKBOXES_LIMIT = 10
groups_dict = GroupsAndUsersThreadSafeDict()

# TODO: improvements
# - \n i inne białe znaki kończą parsowanie nazwy grupy (nazwa grupy musi być \w+)
# - notify all nie powinno notifikować wywołującego
# - @ActiveUsers coreteam powinno z defaultu pingować wszystkich, można dorobić
#   @ActiveUsers coreteam show które wyświetli aktywnych z opcją wyboru, ale to powinna być wiadomość
#   widoczna tylko dla wywołującego polecenie!


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
        except SlackApiError:
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
            except SlackApiError:
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


@app.event("app_mention")
def message_hello(event, say):
    if event is None:
        return
    bot_user = groups_dict.bot_user
    if bot_user is None:
        return
    team_id = event['team']  # TODO use team_id?
    text: str = event['text']
    assert bot_user.id in text
    required_group = get_team_name_from_msg(text, bot_user.id)

    error_msg = None
    group: Optional[Group] = None
    users: Optional[List[User]] = None
    if not required_group:
        error_msg = "You need to type name of the group!"
    else:
        try:
            group, users = groups_dict.get_group_and_users(required_group)
            active_users = [user for user in users if user.active]
            if not active_users:
                error_msg = f"There are no active users in group {required_group}"
        except KeyError:
            available_groups = ', '.join(groups_dict.get_groups_handles())
            error_msg = f"Can't recognise group {required_group}. Available groups: {available_groups}"

    if error_msg:
        say(
            text=error_msg,
            thread_ts=event.get('thread_ts', event['ts'])
        )

    else:
        def _get_checkbox_dict(text, user_id):
            return {
                "text": {
                    "type": "mrkdwn",
                    "text": text
                },
                "value": f"{group.handle} {user_id}"
            }

        checkboxes = [_get_checkbox_dict(text="All active users", user_id=ALL_ACTIVE_USERS)]
        for user in users:
            if user.active:
                checkboxes.append(_get_checkbox_dict(text=user.real_name, user_id=user.id))
        if len(checkboxes) > CHECKBOXES_LIMIT:
            checkboxes = checkboxes[:CHECKBOXES_LIMIT]
        say(
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Group {group.handle} has {len(active_users) - 1} active users. Who should I notify?"
                    }
                },
                {
                    "type": "actions",
                    "block_id": "checkboxes",
                    "elements": [
                        {
                            "type": "checkboxes",
                            "options": checkboxes,
                            "action_id": "checkbox_clicked"
                        }
                    ]
                },
                {
                    "type": "actions",
                    "block_id": "notify_action_block",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "Notify"
                            },
                            "style": "primary",
                            "action_id": "notify_button_clicked",
                        }
                    ]
                }
            ],
            text='GentleMessenger: choose users to notify',
            thread_ts=event.get('thread_ts', event['ts']),
        )


@app.action("checkbox_clicked")
def action_button_click(body, ack, say):
    ack()


@app.action("notify_button_clicked")
def action_button_click(body, ack, say):
    ack()
    selected = body["state"]["values"]["checkboxes"]["checkbox_clicked"]["selected_options"]
    user_ids = []
    all_active_selected = False
    group_handle = None
    for option in selected:
        group_handle, user_id = option["value"].split(" ")
        if user_id == ALL_ACTIVE_USERS:
            all_active_selected = True
            group, users = groups_dict.get_group_and_users(group_handle)
            user_ids = [f'<@{user.id}>' for user in users if user.active]
            break
        else:
            user_ids.append(f'<@{user_id}>')
    user_ids_str = ', '.join(user_ids)

    app.client.chat_delete(
        channel=body["container"]["channel_id"],
        ts=body["message"]["ts"]
    )
    if group_handle is not None:
        msg = f"User <@{body['user']['id']}> asked me to notify "
        msg += f'all active users of {group_handle}' if all_active_selected else 'those users'
        msg += f": {user_ids_str}"
        say(
            msg,
            thread_ts=body['container']["thread_ts"]
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
