from app.agents.relevance_screener_agent import second_pass_stage_budget_seconds as budget


def test_second_pass_budget_keeps_the_floor_for_a_small_job():
    assert budget(169) == 1800.0
    assert budget(639) == 1800.0
    assert budget(0) == 1800.0


def test_second_pass_budget_grows_with_the_candidate_count():
    assert budget(2171) == 4950.0  # 435 chunks, 55 waves of 8
    assert budget(1389) == 3150.0  # 278 chunks, 35 waves


def test_second_pass_budget_is_capped():
    assert budget(100_000) == 10800.0


def test_second_pass_budget_reads_explicit_arguments():
    explicit = budget(80, batch_size=5, concurrency=8, floor_s=10.0, wave_s=7.0, ceiling_s=1000.0)
    assert explicit == 14.0
    # A ceiling below the floor: the floor wins.
    assert budget(80, floor_s=10.0, wave_s=7.0, ceiling_s=-1.0) == 10.0
