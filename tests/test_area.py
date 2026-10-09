# py-staticmaps
# Copyright (c) 2020 Florian Pigorsch; see /LICENSE for licensing information

import xml.etree.ElementTree as ET

import staticmaps


def test_dash_array_is_serialized_on_area_outline() -> None:
    points = [
        staticmaps.create_latlng(0, 0),
        staticmaps.create_latlng(0, 0.5),
        staticmaps.create_latlng(0.5, 0.5),
    ]
    renderer = staticmaps.SvgRenderer(staticmaps.Transformer(200, 100, 8, points[0], 256))
    renderer.render_objects([staticmaps.Area(points, color=staticmaps.BLUE, width=2, dash_array=[10, 5])])

    root = ET.fromstring(renderer.drawing().tostring())
    polyline = root.find(".//{http://www.w3.org/2000/svg}polyline")

    assert polyline is not None
    assert polyline.get("stroke-dasharray") == "10,5"
    assert polyline.get("points", "").split()[0] == polyline.get("points", "").split()[-1]
