from solarstorm.eda._hypotheses import Hypothesis, run_hypothesis_test


def test_hypothesis_passes_when_ci_excludes_zero():
    h = Hypothesis(
        id="H_TEST", description="Test hypothesis",
        feature_column="dummy", test=None,
    )
    result = run_hypothesis_test(
        h,
        effect_size=0.15,
        ci95=(0.05, 0.25),
        p_value=0.01,
    )
    assert result.passes is True


def test_hypothesis_fails_when_ci_includes_zero():
    h = Hypothesis(id="H_TEST2", description="Test", feature_column="dummy", test=None)
    result = run_hypothesis_test(
        h,
        effect_size=0.05,
        ci95=(-0.10, 0.20),
        p_value=0.30,
    )
    assert result.passes is False


def test_hypothesis_to_dict_includes_all_fields():
    h = Hypothesis(id="H1", description="Slope 3h", feature_column="slope_3h", test=None)
    result = run_hypothesis_test(h, effect_size=0.12, ci95=(0.02, 0.22), p_value=0.02)
    d = result.to_dict()
    assert d["id"] == "H1"
    assert d["passes"] is True
    assert "ci95_low" in d
