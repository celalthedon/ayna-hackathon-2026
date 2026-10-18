"""Small counterexamples for the saved-substring test's geometric guarantee."""
import math

import pytest

from geometry_assertions import PATH_TOLERANCE_M, assert_same_directed_path


@pytest.mark.parametrize('extra', [
    [(0, 0), (0, 0), (10, 0)],
    [(0, 0), (1e-9, 0), (10, 0)],
    [(0, 0), (3, 0), (7, 0), (10, 0)],
    [(0, 0), (3, 1e-9), (7, 0), (10, 0)],
    [(0, 0), (3, 0), (3, 0), (10, 0), (10, 0)],
])
def test_equivalent_redundant_vertices_in_both_arguments(extra):
    # Realistic UTM magnitude, including the reported ~1e-9 m start edge.
    offset = lambda points: [(500000 + x, 4460000 + y) for x, y in points]
    original, redundant = offset([(0, 0), (10, 0)]), offset(extra)
    before = list(redundant)
    assert_same_directed_path(redundant, original)
    assert_same_directed_path(original, redundant)
    assert redundant == before


def test_redundant_vertices_retain_bends_and_stationary_paths():
    assert_same_directed_path([(0, 0), (5, 0), (10, 0), (10, 4), (10, 10)],
                              [(0, 0), (10, 0), (10, 10)])
    assert_same_directed_path([(2, 3)] * 3, [(2, 3)])


def test_reported_linux_ride_14_b_16_with_extra_start_vertex():
    # Complete small pair from Ali's shapely_diff_linux.geojson, ride
    # bus_ride:14_B:16. Archive/GeoJSON hashes and provenance are in the note.
    from pyproj import Transformer
    saved = [(49.80311800000019, 40.388735999999795),
             (49.8026592987256, 40.39158992003936)]
    regenerated = [(49.80311800000018, 40.388735999999795),
                   saved[0], (49.8026592987256, 40.391589920039344)]
    project = Transformer.from_crs('EPSG:4326', 'EPSG:32639', always_xy=True)
    metric = lambda points: list(zip(*project.transform(*zip(*points))))
    assert_same_directed_path(metric(regenerated), metric(saved))
    assert_same_directed_path(metric(saved), metric(regenerated))


@pytest.mark.parametrize('actual,expected,label', [
    ([(0, 0), (10, 0)], [(10, 0), (0, 0)], 'start'),
    ([(0, 0), (10 + 2e-6, 0)], [(0, 0), (10, 0)], 'end'),
    ([(0, 2e-6), (10, 2e-6)], [(0, 0), (10, 0)], 'start'),
    # Same endpoints and exactly equal lengths, but a different path.
    ([(0, 0), (5, 1), (10, 0)], [(0, 0), (5, -1), (10, 0)], 'Ordered'),
    # Same spatial point set and endpoints, but an added backtrack.
    ([(0, 0), (6, 0), (4, 0), (10, 0)], [(0, 0), (10, 0)], 'length'),
    # Same spatial set, endpoints AND length; traversal order still matters.
    ([(0, 0), (3, 0), (0, 0), (0, 3), (0, 0), (1, 1)],
     [(0, 0), (0, 3), (0, 0), (3, 0), (0, 0), (1, 1)], 'Ordered'),
    ([(0, 0), (3, 0), (0, 3), (0, 0)],
     [(0, 0), (0, 3), (3, 0), (0, 0)], 'Ordered'),
    # A near-duplicate is not blindly removed if its displacement matters.
    ([(0, 0), (1e-9, 2e-6), (10, 0)], [(0, 0), (10, 0)], 'length'),
])
def test_incorrect_geometry_is_rejected(actual, expected, label):
    with pytest.raises(AssertionError, match=label):
        assert_same_directed_path(actual, expected)


def test_absolute_length_check_catches_accumulated_sub_tolerance_detours():
    # Everything lies within the 1 micrometre path corridor, but repeated
    # detours accumulate too much length. A Hausdorff-only check would pass.
    expected = [(0, 0), (1e-5, 0)]
    actual = [(i * 1e-7, (i % 2) * 5e-7) for i in range(101)]
    with pytest.raises(AssertionError, match='length'):
        assert_same_directed_path(actual, expected)


@pytest.mark.parametrize('invalid', [[], [(math.nan, 0)], [(0, math.inf)], [(0, 0, 0)]])
def test_invalid_coordinates_are_not_silently_accepted(invalid):
    with pytest.raises(AssertionError, match='finite 2D'):
        assert_same_directed_path(invalid, [(0, 0)])


def test_tolerance_is_absolute_metric_not_relative_to_coordinate_magnitude():
    assert PATH_TOLERANCE_M == 1e-6
    with pytest.raises(AssertionError, match='start'):
        assert_same_directed_path([(500000, 4460000)], [(500000, 4460000 + 2e-6)])
