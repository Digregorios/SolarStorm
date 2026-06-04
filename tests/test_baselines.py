import datetime as dt
from solarstorm.baselines._persistence import predict_persistence, predict_dminus1


def test_predict_persistence_returns_k_cp():
    result = predict_persistence(k_cp=15)
    assert result["p50"] == 15
    assert result["source"] == "persistence"


def test_predict_dminus1_returns_yesterday_tmax():
    result = predict_dminus1(tmax_dminus1=22)
    assert result["p50"] == 22
    assert result["source"] == "dminus1"


def test_predict_persistence_dist_has_single_bucket():
    result = predict_persistence(k_cp=18)
    assert result["prob_dist"] == {18: 1.0}
