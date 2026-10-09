# py-staticmaps
# Copyright (c) 2020 Florian Pigorsch; see /LICENSE for licensing information

import math
import typing

from geographiclib.geodesic import Geodesic  # type: ignore
import s2sphere  # type: ignore

from .color import Color, RED
from .coordinates import create_latlng
from .object import Object, PixelBoundsT
from .cairo_renderer import CairoRenderer
from .pillow_renderer import PillowRenderer
from .svg_renderer import SvgRenderer


class Line(Object):
    def __init__(
        self,
        latlngs: typing.List[s2sphere.LatLng],
        color: Color = RED,
        width: int = 2,
        dash_array: typing.Optional[typing.Sequence[float]] = None,
    ) -> None:
        Object.__init__(self)
        if latlngs is None or len(latlngs) < 2:
            raise ValueError("Trying to create line with less than 2 coordinates")
        if width < 0:
            raise ValueError(f"'width' must be >= 0: {width}")
        if dash_array is not None and any(
            not math.isfinite(length) or length <= 0 for length in dash_array
        ):
            raise ValueError("'dash_array' values must be finite and > 0")

        self._latlngs = latlngs
        self._color = color
        self._width = width
        self._dash_array = list(dash_array) if dash_array else None
        self._interpolation_cache: typing.Optional[typing.List[s2sphere.LatLng]] = None

    def color(self) -> Color:
        """Return color of the line

        :return: color object
        :rtype: Color
        """
        return self._color

    def width(self) -> int:
        """Return width of line

        :return: width
        :rtype: int
        """
        return self._width

    def dash_array(self) -> typing.Optional[typing.List[float]]:
        """Return the dash and gap lengths for the line stroke, in pixels."""
        return self._dash_array

    def bounds(self) -> s2sphere.LatLngRect:
        """Return bounds of line

        :return: bounds of line
        :rtype: s2sphere.LatLngRect
        """
        b = s2sphere.LatLngRect()
        for latlng in self.interpolate():
            b = b.union(s2sphere.LatLngRect.from_point(latlng.normalized()))
        return b

    def extra_pixel_bounds(self) -> PixelBoundsT:
        """Return extra pixel bounds from line

        :return: extra pixel bounds
        :rtype: PixelBoundsT
        """
        return self._width, self._width, self._width, self._width

    def interpolate(self) -> typing.List[s2sphere.LatLng]:
        """Interpolate bounds

        :return: list of LatLng
        :rtype: typing.List[s2sphere.LatLng]
        """
        if self._interpolation_cache is not None:
            return self._interpolation_cache
        assert len(self._latlngs) >= 2
        self._interpolation_cache = []
        threshold = 2 * math.pi / 360
        last = self._latlngs[0]
        self._interpolation_cache.append(last)
        geod = Geodesic.WGS84
        for current in self._latlngs[1:]:
            # don't perform geodesic interpolation if the longitudinal distance is < threshold = 1°
            dlng = current.lng().radians - last.lng().radians
            while dlng < 0:
                dlng += 2 * math.pi
            while dlng >= math.pi:
                dlng -= 2 * math.pi
            if abs(dlng) < threshold:
                self._interpolation_cache.append(current)
                last = current
                continue
            # geodesic interpolation
            line = geod.InverseLine(
                last.lat().degrees,
                last.lng().degrees,
                current.lat().degrees,
                current.lng().degrees,
            )
            n = 2 + math.ceil(line.a13)
            for i in range(1, n + 1):
                a = (i * line.a13) / n
                g = line.ArcPosition(
                    a, Geodesic.LATITUDE | Geodesic.LONGITUDE | Geodesic.LONG_UNROLL
                )
                self._interpolation_cache.append(create_latlng(g["lat2"], g["lon2"]))
            last = current
        return self._interpolation_cache

    def render_pillow(self, renderer: PillowRenderer) -> None:
        """Render line using PILLOW

        :param renderer: pillow renderer
        :type renderer: PillowRenderer
        """
        if self.width() == 0:
            return
        xys = [
            (x + renderer.offset_x(), y)
            for (x, y) in [
                renderer.transformer().ll2pixel(latlng) for latlng in self.interpolate()
            ]
        ]
        if self.dash_array() is None:
            renderer.draw().line(xys, self.color().int_rgba(), self.width())
            return
        bounds = (
            -self.width(),
            -self.width(),
            renderer.image().width + self.width(),
            renderer.image().height + self.width(),
        )
        _draw_pillow_dashes(
            renderer.draw(),
            xys,
            self.dash_array(),
            bounds=bounds,
            fill=self.color().int_rgba(),
            width=self.width(),
        )

    def render_svg(self, renderer: SvgRenderer) -> None:
        """Render line using svgwrite

        :param renderer: svg renderer
        :type renderer: SvgRenderer
        """
        if self.width() == 0:
            return
        xys = [renderer.transformer().ll2pixel(latlng) for latlng in self.interpolate()]
        dash_array = self.dash_array()
        polyline = renderer.drawing().polyline(
            xys,
            fill="none",
            stroke=self.color().hex_rgb(),
            stroke_width=self.width(),
            opacity=self.color().float_a(),
            **(
                {"stroke_dasharray": ",".join(str(length) for length in dash_array)}
                if dash_array is not None
                else {}
            ),
        )
        renderer.group().add(polyline)

    def render_cairo(self, renderer: CairoRenderer) -> None:
        """Render line using cairo

        :param renderer: cairo renderer
        :type renderer: CairoRenderer
        """
        if self.width() == 0:
            return
        xys = [renderer.transformer().ll2pixel(latlng) for latlng in self.interpolate()]
        renderer.context().set_source_rgba(*self.color().float_rgba())
        renderer.context().set_line_width(self.width())
        renderer.context().set_dash(self.dash_array() or [])
        renderer.context().new_path()
        renderer.context().move_to(*xys[0])
        for x, y in xys[1:]:
            renderer.context().line_to(x, y)
        renderer.context().stroke()


def _dash_segments(
    points: typing.Sequence[typing.Tuple[float, float]],
    dash_array: typing.Optional[typing.Sequence[float]],
    bounds: typing.Tuple[float, float, float, float],
    close: bool = False,
) -> typing.Iterator[
    typing.Tuple[typing.Tuple[float, float], typing.Tuple[float, float]]
]:
    """Yield visible dash segments without processing portions outside the image."""
    if dash_array is None or len(points) < 2:
        return

    pattern = list(dash_array)
    if len(pattern) % 2:
        pattern *= 2
    pattern_length = sum(pattern)
    dash_options = bounds, pattern, pattern_length
    edges = list(zip(points, points[1:]))
    if close and len(points) > 1:
        edges.append((points[-1], points[0]))

    distance = 0.0
    for start, end in edges:
        edge_length = math.hypot(end[0] - start[0], end[1] - start[1])
        if edge_length == 0:
            continue
        yield from _dash_visible_edge(start, end, distance, edge_length, dash_options)
        distance += edge_length


def _dash_visible_edge(
    start: typing.Tuple[float, float],
    end: typing.Tuple[float, float],
    distance: float,
    edge_length: float,
    dash_options: typing.Tuple[
        typing.Tuple[float, float, float, float],
        typing.Sequence[float],
        float,
    ],
) -> typing.Iterator[
    typing.Tuple[typing.Tuple[float, float], typing.Tuple[float, float]]
]:
    clipped = _clip_line_segment(start, end, dash_options[0])
    if clipped is None:
        return

    dx = end[0] - start[0]
    dy = end[1] - start[1]
    visible_start = (start[0] + dx * clipped[0], start[1] + dy * clipped[0])
    visible_end = (start[0] + dx * clipped[1], start[1] + dy * clipped[1])
    phase = (distance + edge_length * clipped[0]) % dash_options[2]
    yield from _dash_line_segment(
        visible_start, visible_end, phase, dash_options[1], dash_options[2]
    )


def _clip_line_segment(
    start: typing.Tuple[float, float],
    end: typing.Tuple[float, float],
    bounds: typing.Tuple[float, float, float, float],
) -> typing.Optional[typing.Tuple[float, float]]:
    """Return the visible portion of a line as start/end ratios, if it crosses the bounds."""
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    left, top, right, bottom = bounds
    t_start = 0.0
    t_end = 1.0
    for p_value, q_value in (
        (-dx, start[0] - left),
        (dx, right - start[0]),
        (-dy, start[1] - top),
        (dy, bottom - start[1]),
    ):
        if p_value == 0:
            if q_value < 0:
                return None
            continue
        ratio = q_value / p_value
        if p_value < 0:
            t_start = max(t_start, ratio)
        else:
            t_end = min(t_end, ratio)
        if t_start > t_end:
            return None
    return t_start, t_end


def _dash_line_segment(
    start: typing.Tuple[float, float],
    end: typing.Tuple[float, float],
    phase: float,
    pattern: typing.Sequence[float],
    pattern_length: float,
) -> typing.Iterator[
    typing.Tuple[typing.Tuple[float, float], typing.Tuple[float, float]]
]:
    """Yield on portions of a clipped edge, trimming inclusive Pillow endpoints by one pixel."""
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    edge_length = math.hypot(dx, dy)
    if edge_length == 0:
        return

    phase %= pattern_length
    pattern_index = 0
    while phase >= pattern[pattern_index]:
        phase -= pattern[pattern_index]
        pattern_index = (pattern_index + 1) % len(pattern)
    pattern_remaining = pattern[pattern_index] - phase
    position = 0.0
    while position < edge_length:
        length = min(pattern_remaining, edge_length - position)
        if pattern_index % 2 == 0:
            drawn_length = max(0.0, length - 1.0)
            segment_start = (
                start[0] + dx * position / edge_length,
                start[1] + dy * position / edge_length,
            )
            segment_end = (
                start[0] + dx * (position + drawn_length) / edge_length,
                start[1] + dy * (position + drawn_length) / edge_length,
            )
            yield segment_start, segment_end
        position += length
        pattern_remaining -= length
        if pattern_remaining <= 1e-9:
            pattern_index = (pattern_index + 1) % len(pattern)
            pattern_remaining = pattern[pattern_index]


def _remove_collinear_points(
    points: typing.Sequence[typing.Tuple[float, float]],
) -> typing.List[typing.Tuple[float, float]]:
    """Drop intermediate points that do not change a line's direction."""
    result: typing.List[typing.Tuple[float, float]] = []
    for point in points:
        while len(result) >= 2:
            first = result[-2]
            middle = result[-1]
            first_to_middle = (middle[0] - first[0], middle[1] - first[1])
            middle_to_point = (point[0] - middle[0], point[1] - middle[1])
            cross = (
                first_to_middle[0] * middle_to_point[1]
                - first_to_middle[1] * middle_to_point[0]
            )
            dot = (
                first_to_middle[0] * middle_to_point[0]
                + first_to_middle[1] * middle_to_point[1]
            )
            baseline_length = math.hypot(*first_to_middle)
            # Pixel-scale interpolation wiggles should not turn one thick
            # dash into many short Pillow strokes. Keep the simplification
            # error below a quarter pixel so visible bends remain intact.
            if (baseline_length and abs(cross) / baseline_length > 0.25) or dot < 0:
                break
            result.pop()
        result.append(point)
    return result


def _nearest_direction(
    point: typing.Tuple[float, float],
    points: typing.Sequence[typing.Tuple[float, float]],
) -> typing.Tuple[float, float]:
    """Find the direction of the source segment nearest to a pixel point."""
    nearest: typing.Optional[typing.Tuple[float, float]] = None
    nearest_distance = float("inf")
    for start, end in zip(points, points[1:]):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length_squared = dx * dx + dy * dy
        if length_squared == 0:
            continue
        ratio = max(
            0.0,
            min(
                1.0,
                ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy)
                / length_squared,
            ),
        )
        closest = (start[0] + ratio * dx, start[1] + ratio * dy)
        distance = math.hypot(point[0] - closest[0], point[1] - closest[1])
        if distance < nearest_distance:
            nearest = (dx, dy)
            nearest_distance = distance
    return nearest or (0.0, 0.0)


def _draw_pillow_dashes(
    draw: typing.Any,
    points: typing.Sequence[typing.Tuple[float, float]],
    pattern: typing.Optional[typing.Sequence[float]],
    *,
    bounds: typing.Tuple[float, float, float, float],
    fill: typing.Tuple[int, int, int, int],
    width: int,
    close: bool = False,
) -> None:
    """Draw Pillow dashes without collapsing short runs to one-pixel dots."""
    points = _remove_collinear_points(points)
    for start, end in _dash_segments(points, pattern, bounds, close):
        if start != end:
            draw.line([start, end], fill=fill, width=width)
            continue
        dx, dy = _nearest_direction(start, points)
        length = math.hypot(dx, dy)
        if length:
            half_width = max(0.0, (width - 1) / 2)
            normal = (-dy / length, dx / length)
            draw.line(
                [
                    (
                        start[0] - normal[0] * half_width,
                        start[1] - normal[1] * half_width,
                    ),
                    (
                        start[0] + normal[0] * half_width,
                        start[1] + normal[1] * half_width,
                    ),
                ],
                fill=fill,
                width=1,
            )
