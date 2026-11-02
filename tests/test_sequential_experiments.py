import pytest

from driftguard.sequential_experiments import EWMAChart, MultivariateCUSUM


def test_ewma_accumulates_sustained_drift_and_resets_at_reference():
    monitor = EWMAChart(alpha=0.5, reference_mean=0.1, threshold=0.6)
    first = monitor.observe(0.9)
    second = monitor.observe(0.9)
    assert first.score == pytest.approx(0.4)
    assert first.alerted is False
    assert second.score == pytest.approx(0.6)
    assert second.alerted is True
    monitor.reset()
    assert monitor.observe(0.1).score == 0.0


def test_multivariate_chart_accumulates_a_shift_in_nonfirst_coordinate():
    monitor = MultivariateCUSUM((0.0, 0.0), (1.0, 1.0), allowance=0.5, threshold=2.0)
    assert monitor.observe((0.0, 1.5)).alerted is False
    assert monitor.observe((0.0, 1.5)).alerted is True
    assert monitor.components == [0.0, 2.0]
    monitor.reset()
    assert monitor.observe((0.0, 0.0)).score == 0.0


def test_invalid_observation_does_not_modify_chart_state():
    monitor = MultivariateCUSUM((0.0,), (1.0,))
    monitor.observe((1.0,))
    before = (monitor.observations, monitor.components[:])
    with pytest.raises(ValueError, match="finite"):
        monitor.observe((float("nan"),))
    assert (monitor.observations, monitor.components) == before


@pytest.mark.parametrize("scale", [(0.0,), (-1.0,), (float("inf"),)])
def test_multivariate_chart_rejects_invalid_reference_scale(scale):
    with pytest.raises(ValueError):
        MultivariateCUSUM((0.0,), scale)
