from __future__ import annotations

from typing import (Any, Callable, Dict, List, Literal, NoReturn, Optional,
                    Sequence, Tuple, TypeVar, Union, cast)

from vapoursynth import Format, VideoNode

Range = Union[int, Tuple[Optional[int], Optional[int]]]
Trim = Tuple[Optional[int], Optional[int]]
# Some outputs
Output = Union[
    VideoNode,
    List[VideoNode],
    Tuple[int, VideoNode],
    Tuple[int, List[VideoNode]]
]
# Operator Input
OpInput = Union[
    VideoNode,
    List[VideoNode],
    Tuple[VideoNode, ...],
    Tuple[List[VideoNode], ...],
    Dict[str, VideoNode],
    Dict[str, List[VideoNode]]
]
# Function Debug
F_OpInput = TypeVar('F_OpInput', bound=Callable[..., OpInput])
# Function finalise
F_VN = TypeVar('F_VN', bound=Callable[..., VideoNode])
# Generic function
F = TypeVar('F', bound=Callable[..., Any])


class VideoNode_F(VideoNode):
    """VideoNode object without a None Format"""
    format: Format


class DuplicateFrame(int):
    """Class depicting a duplicate frame"""
    dup: int

    def __new__(cls, x: int, /, dup: int = 1) -> DuplicateFrame:
        df = super().__new__(cls, x)
        df.dup = dup
        return df

    def __repr__(self) -> str:
        return f'<DuplicateFrame object: \'x:{super().__repr__()}, dup:{self.dup}\'>'

    def __str__(self) -> str:
        return f'{super().__str__()} * {self.dup}'

    def __add__(self, x: int) -> DuplicateFrame:
        return DuplicateFrame(self, dup=self.dup + x)

    def __sub__(self, x: int) -> DuplicateFrame:
        return DuplicateFrame(self, dup=self.dup - x)

    def __mul__(self, x: int) -> DuplicateFrame:
        return DuplicateFrame(self, dup=self.dup * x)

    def __floordiv__(self, x: int) -> DuplicateFrame:
        return DuplicateFrame(self, dup=self.dup // x)


class FormatError(Exception):
    """Raised when a format of VideoNode object is not allowed."""


def format_not_none(clip: VideoNode, /) -> VideoNode_F:
    if clip.format is None:
        raise FormatError('Variable format not allowed!')
    return cast(VideoNode_F, clip)
