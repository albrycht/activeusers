import random
import re
from dataclasses import dataclass
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


def apply_aliases(groups_with_limits: List[Tuple[str, int | None]], aliases: Dict[str, str]) -> List[Tuple[str, int | None]]:
    """
    >>> apply_aliases([('core', 1), ('coreteam', None), ('gui', 3), ('team4', None)], aliases={'core': 'coreteam', 'gui': 'guiteam'})
    [('coreteam', 1), ('coreteam', None), ('guiteam', 3), ('team4', None)]
    """
    res = []
    for group_name, limit in groups_with_limits:
        if group_name in aliases:
            res.append((aliases.get(group_name), limit))
        else:
            res.append((group_name, limit))
    return res


def get_limit(group_names_with_limit, group_name) -> int | None:
    for group, limit in group_names_with_limit:
        if group == group_name:
            return limit
    print(f"ERROR: Did not find group {group_name} in: {group_names_with_limit}")
    return None


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

    def get_groups_and_users(self, group_names_with_limit):
        group_name_to_group_and_users = {}

        with self._lock:
            for group_name, _ in group_names_with_limit:
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
