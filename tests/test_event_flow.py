from src.event_engine.event_extractor import extract_events
from src.fund_mapper.fund_profile_loader import load_fund_profiles
from src.fund_mapper.fund_signal_router import map_event_to_fund


def test_extract_and_map_basic():
    events = extract_events("央行降息并释放流动性，利率回落", title="macro_case")
    assert events
    funds = load_fund_profiles()
    assert len(funds) >= 7
    mapped = map_event_to_fund(events[0], funds[0])
    assert "fund_code" in mapped
    assert mapped["direction_2w"] in {"利好", "利空", "中性"}
