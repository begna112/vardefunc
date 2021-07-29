"""Noising/denoising functions"""
from abc import ABC, abstractmethod
from functools import partial
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union, cast

import lvsfunc
import vapoursynth as vs
from vsutil import Dither, depth, get_depth, get_plane_size, get_y, join, split

from .deband import dumb3kdb
from .mask import FDOG
from .placebo import deband
from .types import FormatError, Zimg, format_not_none
from .util import get_sample_type, pick_px_op

core = vs.core


class Grainer(ABC):
    """Abstract graining interface"""
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        super().__init__()

    @abstractmethod
    def grain(self, clip: vs.VideoNode, /, strength: Tuple[float, float]) -> vs.VideoNode:
        """Graining function of the Grainer

        Args:
            clip (vs.VideoNode):
                Source clip.

            strength (Tuple[float, float]):
                First value is luma strength, second value is chroma strength.

        Returns:
            vs.VideoNode: Grained clip.
        """


class AddGrain(Grainer):
    """Built-in grain.Add plugin"""
    def grain(self, clip: vs.VideoNode, /, strength: Tuple[float, float]) -> vs.VideoNode:
        return clip.grain.Add(var=strength[0], uvar=strength[1], **self.kwargs)


class PlaceboGrain(Grainer):
    """Built-in placebo.Deband plugin"""
    def grain(self, clip: vs.VideoNode, /, strength: Tuple[float, float]) -> vs.VideoNode:
        return deband(clip, threshold=0.0, grain=list(strength), **self.kwargs)


class F3kdbGrain(Grainer):
    """Built-in f3kdb.Deband plugin"""
    def grain(self, clip: vs.VideoNode, /, strength: Tuple[float, float]) -> vs.VideoNode:
        return dumb3kdb(clip, threshold=1, grain=list((int(strength[0]), int(strength[1]))), **self.kwargs)


class Graigasm():
    """Custom graining interface based on luma values"""
    thrs: List[float]
    strengths: List[Tuple[float, float]]
    sizes: List[float]
    sharps: List[float]
    overflows: List[float]
    grainers: List[Grainer]

    def __init__(self,
                 thrs: Sequence[float], strengths: Sequence[Tuple[float, float]], sizes: Sequence[float], sharps: Sequence[float], *,
                 overflows: Union[float, Sequence[float], None] = None,
                 grainers: Union[Grainer, Sequence[Grainer]] = AddGrain(seed=-1, constant=False)) -> None:
        """Constructor checks and initializes the values.
           Length of thrs must be equal to strengths, sizes and sharps.
           thrs, strengths, sizes and sharps match the same area.

        Args:
            thrs (Sequence[float]):
                Sequence of thresholds defining the grain boundary.
                Below the threshold, it's grained, above the threshold, it's not grained.

            strengths (Sequence[Tuple[float, float]]):
                Sequence of tuple representing the grain strengh of the luma and the chroma, respectively.

            sizes (Sequence[float]):
                Sequence of size of grain.

            sharps (Sequence[float]):
                Sequence of sharpened grain values. 50 is neutral Catmull-Rom (b=0, c=0.5).

            overflows (Union[float, Sequence[float]], optional):
                Percentage value determining by how much the hard limit of threshold will be extended.
                Range 0.0 - 1.0. Defaults to 1 divided by thrs's length for each thr.

            grainers (Union[Grainer, Sequence[Grainer]], optional):
                Grainer used for each combo of thrs, strengths, sizes and sharps.
                Defaults to AddGrain(seed=-1, constant=False).
        """
        self.thrs = list(thrs)
        self.strengths = list(strengths)
        self.sizes = list(sizes)
        self.sharps = list(sharps)

        length = len(self.thrs)
        datas: List[Any] = [self.strengths, self.sizes, self.sharps]
        if all(len(lst) != length for lst in datas):
            raise ValueError('Graigasm: "thrs", "strengths", "sizes" and "sharps" must have the same length!')

        if overflows is None:
            overflows = [1/length]
        if isinstance(overflows, float):
            overflows = [overflows] * length
        else:
            overflows = list(overflows)
            overflows += [overflows[-1]] * (length - len(overflows))
        self.overflows = overflows

        if isinstance(grainers, Grainer):
            grainers = [grainers] * length
        else:
            grainers = list(grainers)
            grainers += [grainers[-1]] * (length - len(grainers))
        self.grainers = grainers

    def graining(self,
                 clip: vs.VideoNode, /, *,
                 prefilter: Optional[vs.VideoNode] = None, show_masks: bool = False) -> vs.VideoNode:
        """Do grain stuff using settings from constructor.

        Args:
            clip (vs.VideoNode): Source clip.

            prefilter (clip, optional):
                Prefilter clip used to compute masks.
                Defaults to None.

            show_masks (bool, optional):
                Returns interleaved masks. Defaults to False.

        Returns:
            vs.VideoNode: Grained clip.
        """
        clip = format_not_none(clip)
        if clip.format.color_family not in (vs.YUV, vs.GRAY):
            raise FormatError('graining: Only YUV and GRAY format are supported!')


        bits = get_depth(clip)
        is_float = get_sample_type(clip) == vs.FLOAT
        peak = 1.0 if is_float else (1 << bits) - 1
        num_planes = clip.format.num_planes
        neutral = [0.5] + [0.0] * (num_planes - 1) if is_float else [float(1 << (bits - 1))] * num_planes

        pref = prefilter if prefilter is not None else get_y(clip)

        mod = self._get_mod(clip)

        masks = [self._make_mask(pref, thr, ovf, peak, is_float=is_float) for thr, ovf in zip(self.thrs, self.overflows)]
        masks = [pref.std.BlankClip(color=0)] + masks
        masks = [core.std.Expr([masks[i], masks[i-1]], 'x y -') for i in range(1, len(masks))]


        if num_planes == 3:
            if is_float:
                masks_chroma = [mask.resize.Bilinear(*get_plane_size(clip, 1)) for mask in masks]
                masks = [join([mask, mask_chroma, mask_chroma]) for mask, mask_chroma in zip(masks, masks_chroma)]
            else:
                masks = [join([mask] * 3).resize.Bilinear(format=clip.format.id) for mask in masks]

        if show_masks:
            return core.std.Interleave(
                [mask.text.Text(f'Threshold: {thr}', 7).text.FrameNum(9)
                 for thr, mask in zip(self.thrs, masks)]
            )


        graineds = [self._make_grained(clip, strength, size, sharp, grainer, neutral, mod)
                    for strength, size, sharp, grainer in zip(self.strengths, self.sizes, self.sharps, self.grainers)]

        clips_adg = [core.std.Expr([grained, clip, mask], f'x z {peak} / * y 1 z {peak} / - * +')
                     for grained, mask in zip(graineds, masks)]


        out = clip
        for clip_adg in clips_adg:
            out = core.std.MergeDiff(clip_adg, core.std.MakeDiff(clip, out))  # type: ignore


        return out

    def _make_grained(self,
                      clip: vs.VideoNode,
                      strength: Tuple[float, float], size: float, sharp: float, grainer: Grainer,
                      neutral: List[float], mod: int) -> vs.VideoNode:
        ss_w = self._m__(round(clip.width / size), mod)
        ss_h = self._m__(round(clip.height / size), mod)
        b = sharp / -50 + 1
        c = (1 - b) / 2

        blank = core.std.BlankClip(clip, ss_w, ss_h, color=neutral)
        grained = grainer.grain(blank, strength=strength).resize.Bicubic(clip.width, clip.height, filter_param_a=b, filter_param_b=c)

        return clip.std.MakeDiff(grained)

    @staticmethod
    def _get_mod(clip: vs.VideoNode) -> int:
        ss_mod: Dict[Tuple[int, int], int] = {
            (0, 0): 1,
            (1, 1): 2,
            (1, 0): 2,
            (0, 1): 2,
            (2, 2): 4,
            (2, 0): 4
        }
        assert clip.format is not None
        try:
            return ss_mod[(clip.format.subsampling_w, clip.format.subsampling_h)]
        except KeyError as kerr:
            raise ValueError('Graigasm: Format unknown!') from kerr

    @staticmethod
    def _make_mask(clip: vs.VideoNode,
                   thr: float, overflow: float, peak: float, *,
                   is_float: bool) -> vs.VideoNode:

        def _func(x: float) -> int:
            min_thr = thr - (overflow * peak) / 2
            max_thr = thr + (overflow * peak) / 2
            if min_thr <= x <= max_thr:
                x = abs(((x - min_thr) / (max_thr - min_thr)) * peak - peak)
            elif x < min_thr:
                x = peak
            elif x > max_thr:
                x = 0.0
            return round(x)

        min_thr = f'{thr} {overflow} {peak} * 2 / -'
        max_thr = f'{thr} {overflow} {peak} * 2 / +'
        # if x >= min_thr and x <= max_thr -> gradient else ...
        expr = f'x {min_thr} >= x {max_thr} <= and x {min_thr} - {max_thr} {min_thr} - / {peak} * {peak} - abs _ ?'
        # ... if x < min_thr -> peak else ...
        expr = expr.replace('_', f'x {min_thr} < {peak} _ ?')
        # ... if x > max_thr -> 0 else x
        expr = expr.replace('_', f'x {max_thr} > 0 x ?')

        return pick_px_op(is_float, (expr, _func))(clip)

    @staticmethod
    def _m__(x: int, mod: int, /) -> int:
        return x - x % mod



def decsiz(clip: vs.VideoNode, sigmaS: float = 10.0, sigmaR: float = 0.009,
           min_in: Optional[float] = None, max_in: Optional[float] = None, gamma: float = 1.0,
           protect_mask: Optional[vs.VideoNode] = None, prefilter: bool = True,
           planes: Optional[List[int]] = None, show_mask: bool = False) -> vs.VideoNode:
    """Denoising function using Bilateral intended to decrease the filesize
       by just blurring the invisible grain above max_in and keeping all of it
       below min_in. The range in between is progressive.

    Args:
        clip (vs.VideoNode): Source clip.

        sigmaS (float, optional): Bilateral parameter.
            Sigma of Gaussian function to calculate spatial weight. Defaults to 10.0.

        sigmaR (float, optional): Bilateral parameter.
            Sigma of Gaussian function to calculate range weight. Defaults to 0.009.

        min_in (Union[int, float], optional):
            Minimum pixel value below which the grain is kept. Defaults to None.

        max_in (Union[int, float], optional):
            Maximum pixel value above which the grain is blurred. Defaults to None.

        gamma (float, optional):
            Controls the degree of non-linearity of the conversion. Defaults to 1.0.

        protect_mask (vs.VideoNode, optional):
            Mask that includes all the details that should not be blurred.
            If None, it uses the default one.

        prefilter (bool, optional):
            Blurs the luma as reference or not. Defaults to True.

        planes (List[int], optional): Defaults to all planes.

        show_mask (bool, optional): Returns the mask.

    Returns:
        vs.VideoNode: Denoised clip.

    Example:
        import vardefunc as vdf

        clip = depth(clip, 16)
        clip = vdf.decsiz(clip, min_in=128<<8, max_in=200<<8)
    """
    if clip.format is None:
        raise FormatError('decsiz: Variable format not allowed!')

    bits = clip.format.bits_per_sample
    is_float = get_sample_type(clip) == vs.FLOAT
    peak = (1 << bits) - 1
    gamma = 1 / gamma
    if clip.format.color_family == vs.GRAY:
        planes = [0]
    else:
        planes = [0, 1, 2] if not planes else planes


    if not protect_mask:
        clip16 = depth(clip, 16)
        masks = split(
            lvsfunc.mask.range_mask(clip16, rad=3, radc=2).resize.Bilinear(format=vs.YUV444P16)
        ) + [
            FDOG().get_mask(get_y(clip16)).std.Maximum().std.Minimum()
        ]
        protect_mask = core.std.Expr(masks, 'x y max z max 3250 < 0 65535 ? a max 8192 < 0 65535 ?') \
            .std.BoxBlur(hradius=1, vradius=1, hpasses=2, vpasses=2)


    clip_y = get_y(clip)
    if prefilter:
        pre = clip_y.std.BoxBlur(hradius=2, vradius=2, hpasses=4, vpasses=4)
    else:
        pre = clip_y

    denoise_mask = pick_px_op(
        is_float, (f'x {min_in} max {max_in} min {min_in} - {max_in} {min_in} - / {gamma} pow 0 max 1 min {peak} *',
                   lambda x: round(min(1, max(0, pow((min(max_in, max(min_in, x)) - min_in) / (max_in - min_in), gamma))) * peak))  # type: ignore
    )(pre)

    mask = core.std.Expr(
        [depth(protect_mask, bits, range=Zimg.PixelRange.FULL, range_in=Zimg.PixelRange.FULL, dither_type=Dither.NONE),
         denoise_mask],
        'y x -'
    )

    if show_mask:
        return mask


    denoise = core.bilateral.Bilateral(clip, sigmaS=sigmaS, sigmaR=sigmaR, planes=planes, algorithm=0)

    return core.std.MaskedMerge(clip, denoise, mask, planes)


def adaptative_regrain(denoised: vs.VideoNode, new_grained: vs.VideoNode, original_grained: vs.VideoNode,
                       range_avg: Tuple[float, float] = (0.5, 0.4), luma_scaling: int = 28) -> vs.VideoNode:
    """Merge back the original grain below the lower range_avg value,
       apply the new grain clip above the higher range_avg value
       and weight both of them between the range_avg values for a smooth merge.
       Intended for use in applying a static grain in higher PlaneStatsAverage values
       to decrease the file size since we can't see a dynamic grain on that level.
       However, in dark scenes, it's more noticeable so we apply the original grain.

    Args:
        denoised (vs.VideoNode): The denoised clip.
        new_grained (vs.VideoNode): The new regrained clip.
        original_grained (vs.VideoNode): The original regrained clip.
        range_avg (Tuple[float, float], optional): Range used in PlaneStatsAverage. Defaults to (0.5, 0.4).
        luma_scaling (int, optional): Parameter in adg.Mask. Defaults to 28.

    Returns:
        vs.VideoNode: The new adaptative grained clip.

    Example:
        import vardefunc as vdf

        denoise = denoise_filter(src, ...)
        diff = core.std.MakeDiff(src, denoise)
        ...
        some filters
        ...
        new_grained = core.neo_f3kdb.Deband(last, preset='depth', grainy=32, grainc=32)
        original_grained = core.std.MergeDiff(last, diff)
        adapt_regrain = vdf.adaptative_regrain(last, new_grained, original_grained, range_avg=(0.5, 0.4), luma_scaling=28)
    """

    avg = core.std.PlaneStats(denoised)
    adapt_mask = core.adg.Mask(get_y(avg), luma_scaling)
    adapt_grained = core.std.MaskedMerge(new_grained, original_grained, adapt_mask)

    avg_max = max(range_avg)
    avg_min = min(range_avg)

    def _diff(n: int, f: vs.VideoFrame, avg_max: float, avg_min: float,  # noqa: PLW0613
              new: vs.VideoNode, adapt: vs.VideoNode) -> vs.VideoNode:
        psa = cast(float, f.props['PlaneStatsAverage'])
        if psa > avg_max:
            clip = new
        elif psa < avg_min:
            clip = adapt
        else:
            weight = (psa - avg_min) / (avg_max - avg_min)
            clip = core.std.Merge(adapt, new, [weight])
        return clip

    diff_function = partial(_diff, avg_max=avg_max, avg_min=avg_min, new=new_grained, adapt=adapt_grained)

    return core.std.FrameEval(denoised, diff_function, [avg])
