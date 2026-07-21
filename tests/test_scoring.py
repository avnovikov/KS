from ks.models import GatherCandidate
from ks.policy.scoring import best_gather, score_gather


def test_haul_capped_by_march_load():
    c = GatherCandidate("bread", tile_amount=5_000_000, march_time_one_way_s=60.0, vision_confidence=0.9)
    s = score_gather(c, march_load=1_000_000, gather_rate_per_sec=200.0)
    assert s.haul == 1_000_000
    assert s.t_march_round_s == 120.0
    assert s.t_gather_s == 1_000_000 / 200.0
    assert s.score == s.haul / (s.t_gather_s + s.t_march_round_s)


def test_nearer_smaller_tile_can_beat_distant_huge_tile():
    near = GatherCandidate("bread", 200_000, march_time_one_way_s=30.0, vision_confidence=0.9)
    far = GatherCandidate("bread", 14_000_000, march_time_one_way_s=3600.0, vision_confidence=0.9)
    load = 500_000
    rate = 200.0
    sn = score_gather(near, march_load=load, gather_rate_per_sec=rate)
    sf = score_gather(far, march_load=load, gather_rate_per_sec=rate)
    assert sn.score > sf.score
    assert best_gather([sf, sn]) is sn


def test_rejects_non_positive_inputs():
    c = GatherCandidate("wood", 1000, 10.0, 0.9)
    try:
        score_gather(c, march_load=0, gather_rate_per_sec=10.0)
        assert False, "expected ValueError"
    except ValueError:
        pass
