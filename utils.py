import re
from dataclasses import dataclass
from threading import Lock
from typing import List, Dict, Optional


@dataclass
class Group:
    id: str
    handle: str
    user_ids: List[str]


@dataclass
class User:
    id: str
    name: str
    real_name: str
    avatar: str
    active: bool = False


def user_dict_to_user(user_dict) -> User:
    id_ = user_dict['id']
    name = user_dict['name']
    profile = user_dict['profile']
    real_name = profile['real_name']
    avatar = profile['image_48']
    return User(id_, name, real_name, avatar, active=False)


def group_dict_to_group(group_dict) -> Group:
    id = group_dict['id']
    handle = group_dict['handle']
    user_ids = group_dict.get('users', [])
    return Group(id, handle, user_ids)


def get_group_name_from_msg(text: str, bot_id: str) -> List[str]:
    r"""
    >>> get_group_name_from_msg("some message <@ABC123> coreteam asdlkj asldaskj", bot_id="ABC123")
    ['coreteam']
    >>> get_group_name_from_msg("<@ABC123> coreteam asdlkj asldaskj", bot_id="ABC123")
    ['coreteam']
    >>> get_group_name_from_msg("<@ABC123> coreteam", bot_id="ABC123")
    ['coreteam']
    >>> get_group_name_from_msg("<@ABC123>     coreteam", bot_id="ABC123")
    ['coreteam']
    >>> get_group_name_from_msg("<@ABC123>", bot_id="ABC123")
    []
    >>> get_group_name_from_msg("some msg \nasdlkj<@ABC123> coreteam asdasdasd", bot_id="ABC123")
    ['coreteam']
    >>> get_group_name_from_msg("<@ABC123> coreteam <@ABC123> guiteam", bot_id="ABC123")
    ['coreteam', 'guiteam']
    """
    id_str = f"<@{bot_id}>"
    assert id_str in text
    groups = []
    for match in re.finditer(re.escape(id_str) + r"\s+(\w+)", text):
        groups.append(match.group(1))
    return groups


class GroupsAndUsersThreadSafeDict:
    def __init__(self):
        self._lock = Lock()
        self._group_handle_to_group: Dict[str, Group] = {}
        self._user_id_to_user: Dict[str, User] = {}
        self.bot_user: Optional[User] = None

    def update_groups_and_users(self, groups: List[Group], users: List[User]):
        with self._lock:
            self._group_handle_to_group.clear()
            for group in groups:
                self._group_handle_to_group[group.handle] = group

            self._user_id_to_user.clear()
            for user in users:
                self._user_id_to_user[user.id] = user

    def set_bot_user(self, user: User):
        self.bot_user = user

    def get_groups_and_users(self, group_names):
        user_ids = set()
        groups = []
        users = []
        with self._lock:
            for group_name in group_names:
                group = self._group_handle_to_group[group_name]
                user_ids.update(group.user_ids)
                groups.append(group)
            for user_id in user_ids:
                user = self._user_id_to_user.get(user_id)
                if user_id is None:
                    continue
                users.append(user)
        return groups, users

    def get_groups_handles(self):
        with self._lock:
            return list(self._group_handle_to_group.keys())

