"""Response schemas for the Claude calls.

Passed to `client.messages.parse()` as structured outputs, which constrains
generation to this shape. That replaces regex-scraping JSON out of prose and
removes the whole class of "the model wrapped it in a fence again" failures --
worth it on a stage that costs money and runs unattended at 4am.
"""
from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field

Section = Literal[
    "cold_open", "setup", "escalation", "turn", "aftermath", "resolution", "outro"
]


class Beat(BaseModel):
    id: int
    section: Section
    narration: str = Field(description="The words the narrator says. No stage directions.")
    image_prompt: str = Field(description="Photographic description of the still image.")
    hero: bool = Field(description="True for the shots that carry the episode.")
    pause_after: float = Field(description="Seconds of silence after this beat, 0.4-1.8.")


class Script(BaseModel):
    title: str
    logline: str
    content_warnings: List[str]
    beats: List[Beat]


class Metadata(BaseModel):
    title: str
    title_alternates: List[str]
    description: str
    tags: List[str]
    thumbnail_prompt: str
    thumbnail_text: str
    pinned_comment: str
