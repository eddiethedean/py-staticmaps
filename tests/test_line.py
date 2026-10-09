# py-staticmaps
# Copyright (c) 2020 Florian Pigorsch; see /LICENSE for licensing information

import typing

import pytest
from PIL import Image, ImageDraw

import staticmaps
from staticmaps.line import _draw_pillow_dashes
from staticmaps.pillow_renderer import PillowRenderer
from staticmaps.transformer import Transformer


def test_bad_creation() -> None:
    with pytest.raises(ValueError):
        staticmaps.Line([])

    with pytest.raises(ValueError):
        staticmaps.Line([staticmaps.create_latlng(48, 8)])

    with pytest.raises(ValueError):
        staticmaps.Line(
            [staticmaps.create_latlng(48, 8), staticmaps.create_latlng(49, 9)],
            width=-123,
        )


def test_creation() -> None:
    staticmaps.Line(
        [
            staticmaps.create_latlng(48, 8),
            staticmaps.create_latlng(49, 9),
            staticmaps.create_latlng(50, 8),
        ],
        color=staticmaps.YELLOW,
    )


def test_bounds() -> None:
    line = staticmaps.Line(
        [
            staticmaps.create_latlng(48, 8),
            staticmaps.create_latlng(49, 9),
            staticmaps.create_latlng(50, 8),
        ],
        color=staticmaps.YELLOW,
    )
    assert not line.bounds().is_point()


def test_dash_array_preserves_one_pixel_gaps_in_pillow() -> None:
    start = staticmaps.create_latlng(0, 0)
    end = staticmaps.create_latlng(0, 0.5)
    transformer = Transformer(200, 100, 8, start, 256)
    renderer = PillowRenderer(transformer)
    renderer.render_objects([staticmaps.Line([start, end], width=1, dash_array=[1, 1])])

    row = [
        typing.cast(
            typing.Tuple[int, int, int, int], renderer.image().getpixel((x, 50))
        )[3]
        > 0
        for x in range(100, 110)
    ]
    assert row == [True, False] * 5


def test_dash_array_is_serialized_in_svg() -> None:
    start = staticmaps.create_latlng(0, 0)
    end = staticmaps.create_latlng(0, 0.5)
    renderer = staticmaps.SvgRenderer(Transformer(200, 100, 8, start, 256))
    renderer.render_objects(
        [staticmaps.Line([start, end], width=1, dash_array=[10, 5])]
    )

    svg = renderer.drawing().tostring()
    assert 'stroke-dasharray="10,5"' in svg


def test_short_dashes_preserve_pillow_stroke_width() -> None:
    image = Image.new("RGBA", (40, 20))
    _draw_pillow_dashes(
        ImageDraw.Draw(image),
        [(10, 10), (30, 10)],
        [1, 1],
        bounds=(0, 0, 40, 20),
        fill=(0, 0, 0, 255),
        width=4,
    )

    assert (
        sum(
            typing.cast(typing.Tuple[int, int, int, int], image.getpixel((10, y)))[3]
            > 0
            for y in range(20)
        )
        == 4
    )


def test_collinear_vertices_do_not_collapse_pillow_dashes() -> None:
    bounds = (0, 0, 120, 20)
    color = (0, 0, 0, 255)
    simple = Image.new("RGBA", (120, 20))
    dense = Image.new("RGBA", (120, 20))
    _draw_pillow_dashes(
        ImageDraw.Draw(simple),
        [(10, 10), (110, 10)],
        [1000, 10],
        bounds=bounds,
        fill=color,
        width=4,
    )
    _draw_pillow_dashes(
        ImageDraw.Draw(dense),
        [(10 + index, 10 + (index % 2) * 0.02) for index in range(101)],
        [1000, 10],
        bounds=bounds,
        fill=color,
        width=4,
    )

    assert simple.tobytes() == dense.tobytes()
