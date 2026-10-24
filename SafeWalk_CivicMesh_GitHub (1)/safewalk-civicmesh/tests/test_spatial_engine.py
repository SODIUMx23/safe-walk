import math

import pytest

from backend.app.services.ai_spatial import (
    calculate_clock_and_pan, classify_hazard_elevation, generate_kinvoice_speech,
    haversine_m, project_angles,
)


def box_at(x, y=.5):
    # The pure geometry helper also permits a zero-size point for analytic tests.
    return {"x_min": x, "x_max": x, "y_min": y, "y_max": y}


@pytest.mark.parametrize("x,clock,pan", [(0, "10 o'clock", -1), (.15, "10 o'clock", -.7),
    (.325, "11 o'clock", -.35), (.5, "12 o'clock", 0), (.675, "1 o'clock", .35),
    (.85, "2 o'clock", .7), (1, "2 o'clock", 1)])
def test_clock_and_pan_anchors(x, clock, pan):
    actual_clock, actual_pan = calculate_clock_and_pan(box_at(x))
    assert actual_clock == clock
    assert actual_pan == pytest.approx(pan)


def test_pan_is_monotonic_bounded_and_symmetric():
    values = [calculate_clock_and_pan(box_at(i / 100))[1] for i in range(101)]
    assert values == sorted(values)
    assert all(-1 <= pan <= 1 for pan in values)
    for i in range(101):
        assert values[i] == pytest.approx(-values[100 - i])


@pytest.mark.parametrize("bad", [-.1, 1.1, float('nan'), float('inf')])
def test_rejects_non_normalized_boxes(bad):
    with pytest.raises(ValueError):
        calculate_clock_and_pan(box_at(bad))


def test_rejects_inverted_box():
    with pytest.raises(ValueError):
        calculate_clock_and_pan({"x_min": .7, "x_max": .2, "y_min": 0, "y_max": 1})


@pytest.mark.parametrize("drop,expected", [(None, "PATH_OBSTACLE"), (0, "PATH_OBSTACLE"),
    (39.99, "PATH_OBSTACLE"), (40, "GROUND_VOID"), (140, "GROUND_VOID")])
def test_reported_void_threshold(drop, expected):
    assert classify_hazard_elevation(box_at(.5, .8), 0, None, drop) == expected


@pytest.mark.parametrize("height,expected", [(None, "PATH_OBSTACLE"), (139.9, "PATH_OBSTACLE"),
    (140, "HEAD_LEVEL"), (165, "HEAD_LEVEL"), (190, "HEAD_LEVEL"), (190.1, "PATH_OBSTACLE")])
def test_reported_head_height_band(height, expected):
    assert classify_hazard_elevation(box_at(.5, .3), 0, height, None) == expected


def test_void_takes_priority_over_simultaneous_head_hazard():
    assert classify_hazard_elevation(box_at(.5), 0, 160, 45) == "GROUND_VOID"


def test_ray_alone_never_proves_metric_height_or_drop():
    assert classify_hazard_elevation(box_at(.5, .2), 0, None, None) == "PATH_OBSTACLE"
    assert classify_hazard_elevation(box_at(.5, .9), 0, None, None) == "PATH_OBSTACLE"


@pytest.mark.parametrize("pitch,expected", [(0, True), (18, True), (18.01, False), (-.01, False)])
def test_exact_eighteen_degree_upward_sector(pitch, expected):
    assert project_angles(box_at(.5), pitch)["in_headspace_cone"] is expected


def test_clock_geometry_is_separate_from_optical_yaw():
    assert project_angles(box_at(0), 0)["azimuth_deg"] == pytest.approx(-35)
    assert project_angles(box_at(1), 0)["azimuth_deg"] == pytest.approx(35)
    assert project_angles(box_at(.5), 0)["azimuth_deg"] == 0


@pytest.mark.parametrize("bad", [-1, math.nan, math.inf])
def test_invalid_measurements_rejected(bad):
    with pytest.raises(ValueError):
        classify_hazard_elevation(box_at(.5), 0, None, bad)


def test_unknown_distance_is_not_fabricated():
    text = generate_kinvoice_speech("obstacle", "PATH_OBSTACLE", "12 o'clock", None, "warning")
    assert "meter" not in text
    assert "Possible" in text


def test_ground_speech_is_precautionary():
    text = generate_kinvoice_speech("ground", "GROUND_VOID", "12 o'clock", None, "critical")
    assert "halt" in text and "Possible" in text and "cane" in text


def test_haversine_meter_boundaries():
    assert haversine_m(12.9165, 79.1325, 12.9165, 79.1325) == 0
    distance = haversine_m(12.9165, 79.1325, 12.916815, 79.1325)
    assert 34 < distance < 36
