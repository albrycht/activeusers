import random
import re
from dataclasses import dataclass, replace
from threading import Lock
from typing import List, Dict, Optional, Tuple


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


@dataclass
class ParsedGroup:
    group_name: str
    limit: int = 0
    include_inactive: bool = False


def user_dict_to_user(user_dict) -> User:
    id_ = user_dict["id"]
    name = user_dict["name"]
    profile = user_dict["profile"]
    real_name = profile["real_name"]
    avatar = profile["image_48"]
    return User(id_, name, real_name, avatar, active=False)


def group_dict_to_group(group_dict) -> Group:
    id = group_dict["id"]
    handle = group_dict["handle"]
    user_ids = group_dict.get("users", [])
    return Group(id, handle, user_ids)


def apply_aliases(parsed_groups: List[ParsedGroup], aliases: Dict[str, str]) -> List[ParsedGroup]:
    """
    >>> apply_aliases([ParsedGroup('core', 1), ParsedGroup('gui', 3, True), ParsedGroup('team4')], aliases={'core': 'coreteam', 'gui': 'guiteam'})
    [ParsedGroup(group_name='coreteam', limit=1, include_inactive=False), ParsedGroup(group_name='guiteam', limit=3, include_inactive=True), ParsedGroup(group_name='team4', limit=0, include_inactive=False)]
    """
    res = []
    for group in parsed_groups:
        if group.group_name in aliases:
            res.append(replace(group, group_name=aliases[group.group_name]))
        else:
            res.append(group)
    return res


def get_limit(parsed_groups: List[ParsedGroup], group_name) -> int:
    for group in parsed_groups:
        if group.group_name == group_name:
            return group.limit
    print(f"ERROR: Did not find group {group_name} in: {parsed_groups}")
    return 0


def get_group_name_and_limit_from_msg(text: str, bot_id: str) -> List[ParsedGroup]:
    r"""
    >>> get_group_name_and_limit_from_msg("some message <@ABC123> coreteam asdlkj asldaskj", bot_id="ABC123")
    [ParsedGroup(group_name='coreteam', limit=0, include_inactive=False)]
    """
    id_str = f"<@{bot_id}>"
    assert id_str in text
    groups = []
    pattern = re.escape(id_str) + r"\s+(\w+)((?:\s+--\S+)*)"
    for match in re.finditer(pattern, text):
        group_name = match.group(1)
        args_str = match.group(2)

        limit = 0
        include_inactive = False

        args = args_str.split()
        for arg in args:
            if arg == "--all":
                include_inactive = True
            elif arg.startswith("--") and arg[2:].isdigit():
                limit = int(arg[2:])

        groups.append(
            ParsedGroup(
                group_name=group_name, limit=limit, include_inactive=include_inactive
            )
        )
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

    def get_groups_and_users(self, parsed_groups: List[ParsedGroup]):
        group_name_to_group_and_users = {}

        with self._lock:
            for parsed_group in parsed_groups:
                group_name = parsed_group.group_name
                user_ids = set()
                users = []
                group = self._group_handle_to_group[group_name]
                user_ids.update(group.user_ids)
                for user_id in user_ids:
                    user = self._user_id_to_user.get(user_id)
                    if user_id is None:
                        continue
                    users.append(user)
                group_name_to_group_and_users[group_name] = (group, users)
        return group_name_to_group_and_users

    def get_groups_handles(self):
        with self._lock:
            return list(self._group_handle_to_group.keys())
