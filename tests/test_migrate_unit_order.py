"""Tests for scripts/migrate_unit_order.py: when it reverses departing unit lists, and that it refuses to guess."""
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "migrate_unit_order.py"
spec = importlib.util.spec_from_file_location("migrate_unit_order", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def part(id, a=(), b=()):
    return {"id": id, "aSide": list(a), "bSide": list(b)}


# bumpers 11 and 12 behind gateways 2 and 3 (switch 20 end); bumper 13 behind gateway 4 (switch 21 end).
PARTS = {p["id"]: p for p in [part(2, [11], [20]), part(3, [12], [20]), part(4, [21], [13]), part(11, [], [2])]}


def train_in(gateway, bumper, n=2):
    return {"firstParkingTrackPart": gateway, "entryTrackPart": bumper, "members": [{}] * n}


def train_out(gateway, bumper, n=2):
    return {"lastParkingTrackPart": gateway, "leaveTrackPart": bumper, "trainUnits": [{}] * n}


def scenario(ins, outs, in_standing=(), out_standing=()):
    return {"in": ins, "out": outs, "inStanding": list(in_standing), "outStanding": list(out_standing)}


def test_gateway_end_is_the_side_away_from_the_bumper():
    assert mod.gateway_end(PARTS, 2, 11) == (20,)
    assert mod.gateway_end(PARTS, 4, 13) == (21,)


def test_gateway_end_raises_when_the_bumper_is_not_adjacent():
    with pytest.raises(ValueError, match="cannot tell"):
        mod.gateway_end(PARTS, 2, 13)


def test_single_ended_scenario_reverses_every_multi_unit_departure():
    sc = scenario([train_in(2, 11)], [train_out(3, 12), train_out(2, 11, n=1)])
    action, detail = mod.plan(sc, PARTS)
    assert action == "reverse"
    assert detail == [sc["out"][0]]


def test_scenario_without_multi_unit_departures_needs_nothing():
    sc = scenario([train_in(2, 11)], [train_out(2, 11, n=1)])
    assert mod.plan(sc, PARTS)[0] == "nothing"


def test_two_ended_scenario_with_multi_unit_departures_is_left_to_a_human():
    sc = scenario([train_in(2, 11)], [train_out(4, 13)])
    assert mod.plan(sc, PARTS)[0] == "manual"


def test_standing_trains_are_left_to_a_human():
    sc = scenario([train_in(2, 11)], [train_out(2, 11)], in_standing=[{}])
    assert mod.plan(sc, PARTS)[0] == "manual"
