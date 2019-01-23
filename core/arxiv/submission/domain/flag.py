"""Data structures related to QA."""

from datetime import datetime
from typing import Optional, Union
from enum import Enum

from mypy_extensions import TypedDict
from dataclasses import field, dataclass

from .agent import Agent


PossibleDuplicate = TypedDict('PossibleDuplicate',
                              {'id': int, 'title': str, 'owner': Agent})


@dataclass
class Flag:
    """Base class for flags."""

    event_id: str
    creator: Agent
    created: datetime
    flag_type: str
    flag_data: Optional[Union[int, str, float, dict, list]]
    comment: str
    proxy: Optional[Agent] = field(default=None)


@dataclass
class ContentFlag(Flag):
    """A flag related to the content of the submission."""

    class FlagTypes(Enum):
        """Supported content flags."""

        LOW_STOP = 'low stopwords'
        LOW_STOP_PERCENT = 'low stopword percentage'
        LANGUAGE = 'language'
        CHARACTER_SET = 'character_set'


@dataclass
class MetadataFlag(Flag):
    """A flag related to the submittion metadata."""

    class FlagTypes(Enum):
        """Supported metadata flags."""

        POSSIBLE_DUPLICATE_TITLE = 'possible duplicate title'
        LANGUAGE = 'language'
        CHARACTER_SET = 'character_set'


@dataclass
class UserFlag(Flag):
    """A flag related to the submitter."""

    class FlagTypes(Enum):
        """Supported user flags."""

        RATE = 'rate'
