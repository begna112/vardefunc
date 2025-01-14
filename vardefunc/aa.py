
__all__ = [
    'eedi3', 'nnedi3',
    'SuperSampler',
    'Nnedi3SS', 'Znedi3SS', 'Eedi3SS',
    'SingleRater',
    'SangNomSR',
    'Eedi3SR',
    'upscaled_sraa'
]

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from functools import partial
from typing import Any, Callable, Dict, Optional

import vapoursynth as vs
from vskernels import Catrom, Kernel
from vsutil import get_w

core = vs.core


def eedi3(*, opencl: bool) -> Callable[..., vs.VideoNode]:
    return partial(core.eedi3m.EEDI3) if not opencl else partial(core.eedi3m.EEDI3CL)


def nnedi3(*, opencl: bool) -> Callable[..., vs.VideoNode]:
    return partial(core.nnedi3.nnedi3) if not opencl else partial(core.nnedi3cl.NNEDI3CL)


class SuperSampler(ABC):
    def __init__(self) -> None:
        pass

    def __call__(self,) -> Callable[[vs.VideoNode, int, int], vs.VideoNode]:
        return self.do_ss()

    @abstractmethod
    def do_ss(self) -> Callable[[vs.VideoNode, int, int], vs.VideoNode]:
        pass

    @property
    def scale(self) -> Callable[[vs.VideoNode, int, int], vs.VideoNode]:
        return self.do_ss()


@dataclass
class Nnedi3SS(SuperSampler):
    opencl: bool = False
    nsize: int = 4
    nns: int = 4
    qual: int = 2

    shifter: Kernel = Catrom()

    nnedi3_args: Dict[str, Any] = field(default_factory=dict)


    def do_ss(self) -> Callable[[vs.VideoNode, int, int], vs.VideoNode]:

        def func(clip: vs.VideoNode, w: int, h: int) -> vs.VideoNode:
            if self.opencl:
                clip = nnedi3(opencl=True)(clip, 0, True, True, nsize=self.nsize, nns=self.nns, qual=self.qual, **self.nnedi3_args)
            else:
                clip = clip.std.Transpose()
                clip = nnedi3(opencl=False)(clip, 0, True, nsize=self.nsize, nns=self.nns, qual=self.qual, **self.nnedi3_args)
                clip = clip.std.Transpose()
                clip = nnedi3(opencl=False)(clip, 0, True, nsize=self.nsize, nns=self.nns, qual=self.qual, **self.nnedi3_args)
            return self.shifter.scale(clip, w, h, shift=(.5, .5))

        return func


@dataclass
class Znedi3SS(SuperSampler):
    nsize: int = 4
    nns: int = 4
    qual: int = 2

    shifter: Kernel = Catrom()

    nnedi3_args: Dict[str, Any] = field(default_factory=dict)

    def do_ss(self) -> Callable[[vs.VideoNode, int, int], vs.VideoNode]:

        def func(clip: vs.VideoNode, w: int, h: int) -> vs.VideoNode:
            clip = clip.std.Transpose()
            clip = core.znedi3.nnedi3(clip, 0, True, nsize=self.nsize, nns=self.nns, qual=self.qual, **self.nnedi3_args)
            clip = clip.std.Transpose()
            clip = core.znedi3.nnedi3(clip, 0, True, nsize=self.nsize, nns=self.nns, qual=self.qual, **self.nnedi3_args)
            return self.shifter.scale(clip, w, h, shift=(.5, .5))

        return func


@dataclass
class Eedi3SS(SuperSampler):
    eedi3cl: bool = False
    nnedi3cl: bool = False

    alpha: float = 0.2
    beta: float = 0.8
    gamma: float = 1000
    nrad: int = 1
    mdis: int = 15

    shifter: Kernel = Catrom()

    eedi3_args: Dict[str, Any] = field(default_factory=dict)
    nnedi3_args: Dict[str, Any] = field(default_factory=dict)

    def do_ss(self) -> Callable[[vs.VideoNode, int, int], vs.VideoNode]:

        eeargs: Dict[str, Any] = dict(alpha=self.alpha, beta=self.beta, gamma=self.gamma, nrad=self.nrad, mdis=self.mdis)
        eeargs |= self.eedi3_args

        nnargs: Dict[str, Any] = dict(nsize=4, nns=4, qual=2, etype=1)
        nnargs |= self.nnedi3_args

        def func(clip: vs.VideoNode, w: int, h: int) -> vs.VideoNode:
            clip = clip.std.Transpose()
            clip = eedi3(opencl=self.eedi3cl)(clip, 0, True, sclip=nnedi3(opencl=self.nnedi3cl)(clip, 0, True, **nnargs), **eeargs)
            clip = clip.std.Transpose()
            clip = eedi3(opencl=self.eedi3cl)(clip, 0, True, sclip=nnedi3(opencl=self.nnedi3cl)(clip, 0, True, **nnargs), **eeargs)

            return self.shifter.scale(clip, w, h, shift=(.5, .5))

        return func


class SingleRater(ABC):
    def __init__(self) -> None:
        pass

    def __call__(self,) -> Callable[[vs.VideoNode], vs.VideoNode]:
        return self.do_aa()

    @abstractmethod
    def do_aa(self) -> Callable[[vs.VideoNode], vs.VideoNode]:
        pass

    @property
    def aa(self) -> Callable[[vs.VideoNode], vs.VideoNode]:
        return self.do_aa()


@dataclass
class SangNomSR(SingleRater):
    aa_param: int = 48
    order: int = 1

    def do_aa(self) -> Callable[[vs.VideoNode], vs.VideoNode]:
        def func(clip: vs.VideoNode) -> vs.VideoNode:
            clip = clip.std.Transpose()
            clip = clip.sangnom.SangNom(self.order, aa=self.aa_param)
            clip = clip.std.Transpose()
            clip = clip.sangnom.SangNom(self.order, aa=self.aa_param)
            return clip

        return func


@dataclass
class Eedi3SR(SingleRater):
    eedi3cl: bool = False
    nnedi3cl: bool = False

    alpha: float = 0.25
    beta: float = 0.5
    gamma: float = 40
    nrad: int = 2
    mdis: int = 20
    mclip: Optional[vs.VideoNode] = None

    eedi3_args: Dict[str, Any] = field(default_factory=dict)
    nnedi3_args: Dict[str, Any] = field(default_factory=dict)

    def do_aa(self) -> Callable[[vs.VideoNode], vs.VideoNode]:

        eeargs: Dict[str, Any] = dict(alpha=self.alpha, beta=self.beta, gamma=self.gamma, nrad=self.nrad, mdis=self.mdis)
        eeargs |= self.eedi3_args

        nnargs: Dict[str, Any] = dict(nsize=4, nns=3, qual=1, etype=1)
        nnargs |= self.nnedi3_args

        def func(clip: vs.VideoNode) -> vs.VideoNode:
            if self.mclip:
                self.mclip = self.mclip.resize.Point(clip.width, clip.height)

            if not self.eedi3cl:
                eeargs.update(mclip=self.mclip.std.Transpose() if self.mclip else None)

            clip = clip.std.Transpose()
            clip = eedi3(opencl=self.eedi3cl)(
                clip, 0,
                sclip=nnedi3(opencl=self.nnedi3cl)(clip, 0, **nnargs),
                **eeargs
            )

            if not self.eedi3cl:
                eeargs.update(mclip=self.mclip)

            clip = clip.std.Transpose()
            clip = eedi3(opencl=self.eedi3cl)(
                clip, 0,
                sclip=nnedi3(opencl=self.nnedi3cl)(clip, 0, **nnargs),
                **eeargs
            )

            return clip

        return func


def upscaled_sraa(clip: vs.VideoNode, rfactor: float = 1.5,
                  width: Optional[int] = None, height: Optional[int] = None,
                  supersampler: SuperSampler = Nnedi3SS(),
                  downscaler: Optional[Kernel] = Catrom(),
                  singlerater: SingleRater = Eedi3SR()) -> vs.VideoNode:
    if clip.format is None:
        raise ValueError("upscaled_sraa: 'Variable-format clips not supported'")

    ssw = round(clip.width * rfactor)
    ssw = (ssw + 1) & ~1
    ssh = round(clip.height * rfactor)
    ssh = (ssh + 1) & ~1

    if not height:
        height = clip.height

    if not width:
        width = get_w(height)

    upscale = supersampler.scale(clip, ssw, ssh)
    singlerate = singlerater.aa(upscale)

    return downscaler.scale(singlerate, width, height) if downscaler else singlerate
