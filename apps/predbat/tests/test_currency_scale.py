"""Currency calibration regressions using the native HA fixture and real engines."""

import copy
import json
import math
import random
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from config import CONFIG_ITEMS
from const import EXPORT_MODE_IDLE, EXPORT_MODE_TARGET, PV_SCENARIO_NOMINAL, PREDBAT_MAX_CARS
from currency import MONETARY_UNITS, round_currency, validate_currency_scale
from prediction import Prediction
from prediction_kernel import build_static_context_arrays
from tests.test_export_commitment import setup_single_export_window
from tests.test_infra import clear_manual_times, reset_inverter, reset_rates, update_rates_import, update_rates_export
from tests.test_kernel_parity import apply_random_scenario, dual_run, make_step_data, make_windows
from utils import pack_export_limit


def configured_predbat(scale=None, overrides=None):
    """Use create_predbat and model an installation without monetary HA history."""
    from unit_test import create_predbat

    base = create_predbat()
    for item in base.CONFIG_ITEMS:
        if item.get("unit") in MONETARY_UNITS:
            base.args.pop(item["name"], None)
            item.pop("value", None)
    base.config_index["expert_mode"]["value"] = True
    base.args["expert_mode"] = True
    base.args.pop("currency_scale", None)
    if scale is not None:
        base.args["currency_scale"] = scale
    base.args.update(overrides or {})
    with patch.object(base, "load_previous_value_from_ha", return_value=None):
        base.load_user_config()
    base.fetch_config_options()
    return base


def test_currency_configuration():
    """Reject invalid calibration and preserve values across instances and reloads."""
    canonical = copy.deepcopy(CONFIG_ITEMS)
    for value in (0, -1, math.nan, math.inf, -math.inf, True, False, None, "bad", "29", [], {}):
        try:
            validate_currency_scale(value)
        except ValueError as error:
            assert "currency_scale" in str(error)
        else:
            raise AssertionError("Accepted invalid scale {!r}".format(value))

    default = configured_predbat()
    scaled = configured_predbat(29)
    for item in CONFIG_ITEMS:
        name = item["name"]
        if item.get("unit") not in MONETARY_UNITS:
            continue
        for field in ("default", "min", "max", "step"):
            assert default.config_index[name][field] == item[field], (name, field)
            assert scaled.config_index[name][field] == item[field] * 29, (name, field)
    assert scaled.metric_min_improvement_plan == 58
    assert math.isclose(scaled.metric_min_improvement_export, 2.9)
    assert default.currency_scale == 1

    explicit = configured_predbat(29, {"metric_min_improvement_export": 0.1, "metric_min_improvement_plan": 58, "metric_min_improvement_swap": -7.25})
    assert explicit.metric_min_improvement_export == 0.1
    assert explicit.metric_min_improvement_plan == 58
    assert explicit.metric_min_improvement_swap == -7.25
    # Include values equal to the old default; they are still explicit values.
    explicit.config_index["metric_min_improvement_export"]["value"] = 0.1
    explicit.config_index["metric_min_improvement_plan"]["value"] = 8000
    for scale in (29, 29, 1, 0.25, 29, 1):
        explicit.args["currency_scale"] = scale
        explicit.load_user_config()
        assert explicit.config_index["metric_min_improvement_export"]["value"] == 0.1
        assert explicit.config_index["metric_min_improvement_plan"]["value"] == 8000
        assert explicit.config_index["metric_min_improvement_plan"]["max"] >= 8000
        assert explicit.config_index["metric_min_improvement_plan"]["step"] == scale
    # A legacy range plugin must not become the baseline for another multiplication.
    scaled.config_index["metric_battery_cycle"]["max"] *= 29
    scaled.load_user_config()
    assert scaled.config_index["metric_battery_cycle"]["max"] == 50 * 29
    assert default.config_index["metric_battery_cycle"]["max"] == 50
    resetter = configured_predbat(29)
    for scale in (1, 29, 1):
        resetter.args["currency_scale"] = scale
        resetter.reset()
        item = next(item for item in resetter.CONFIG_ITEMS if item["name"] == "metric_min_improvement_plan")
        assert item["default"] == 2 * scale
        assert item["max"] == 250 * scale
    assert CONFIG_ITEMS == canonical

    # JSON takes precedence over HA and apps.yaml, as in the existing startup path.
    with tempfile.TemporaryDirectory() as directory:
        Path(directory, "predbat_config.json").write_text(json.dumps({"metric_min_improvement_plan": 2.0}))
        explicit.config_root = directory
        with patch.object(explicit, "load_previous_value_from_ha", return_value=19):
            explicit.load_user_config(load_config=True)
        assert explicit.config_index["metric_min_improvement_plan"]["value"] == 2.0
    # Reset is independently validated, not just the periodic refresh path.
    explicit.args["currency_scale"] = False
    try:
        explicit.reset()
    except ValueError as error:
        assert "currency_scale" in str(error)
    else:
        raise AssertionError("reset accepted boolean currency_scale")


def test_currency_prices_and_sorting():
    """Keep incoming prices intact and order large/negative prices without collisions."""
    for scale in (1.0, 29.0, 0.25):
        base = configured_predbat(scale)
        reset_rates(base, 363.894, 0)
        base.set_rate_thresholds()
        assert base.rate_import[base.minutes_now] == 363.894
        assert abs(base.rate_import_cost_threshold - (round_currency(363.894, scale, 2) + 0.1 * scale)) < 1e-9
        base.rate_import = {base.minutes_now + i: value * scale for i, value in enumerate((-200000, -100000))}
        low, high, _, _, _ = base.rate_minmax(base.rate_import)
        assert math.isclose(low / scale, -200000)
        assert math.isclose(high / scale, -100000)
        base.rate_import = {base.minutes_now: 200000 * scale}
        assert math.isclose(base.rate_minmax(base.rate_import)[0] / scale, 200000)
        assert base.rate_minmax({})[:3] == (99999, 0, 0)
        base.prediction = SimpleNamespace(pv_forecast_minute_step={})
        base.calculate_best_charge = True
        base.calculate_best_export = True
        base.carbon_enable = False
        base.inverter_loss = base.battery_loss = base.battery_loss_discharge = 1
        base.metric_battery_cycle = base.metric_self_sufficiency = 0
        base.set_charge_freeze = base.set_export_freeze = False
        prices = [-10000, 0, 10, 10, 5001, 100000]
        windows = [{"start": 720 + i * 30, "end": 750 + i * 30, "average": price * scale} for i, price in enumerate(prices)]
        assert base.sort_window_by_price(windows) == [5, 4, 2, 3, 1, 0]
        assert base.sort_window_by_price(windows, reverse_time=True) == [5, 4, 3, 2, 1, 0]
        ordered, links, bands, _ = base.sort_window_by_price_combined(windows, [])
        assert [links[key]["id"] for key in ordered] == [5, 4, 3, 2, 1, 0]
        assert len(ordered) == len(set(ordered)) == 6
        assert len(bands) == 5
        base.minutes_now = 720
        assert math.isclose(base._io_rate_adjustment(720, 720), -1.5 * scale)
        base.rate_min_forward = {720: 0}
        base.rate_min = base.rate_max = base.rate_max_base = base.rate_export_min = 0
        assert base.battery_value_rate(720) == scale
        # Rounding precision is relative to calibration, not to the currency symbol.
        assert math.isclose(round_currency(0.123456 * scale, scale) / scale, 0.1235, abs_tol=1e-15)


def run_currency_planner(scale, price_pair=(2.0, 30.0)):
    """Optimise the same six-hour physical problem and return plan/candidate evidence."""
    base = configured_predbat(scale)
    reset_inverter(base)
    base.minutes_now = 0
    base.now_utc = base.midnight_utc
    base.forecast_minutes = 360
    base.end_record = 360
    base.soc_max = 4.0
    base.soc_kw = 0.5
    base.best_soc_step = 0.25
    base.calculate_best_charge = base.calculate_best_export = True
    base.calculate_export_oncharge = True
    base.debug_enable = False
    base.prediction_kernel_enable = True
    base.rate_import = {}
    base.rate_export = {}
    reset_rates(base, 12 * scale, 5 * scale)
    charge = [{"start": i * 30, "end": 30 + i * 30, "average": price_pair[0] * scale} for i in range(3)]
    export = [{"start": 180 + i * 30, "end": 210 + i * 30, "average": price_pair[1] * scale} for i in range(3)]
    update_rates_import(base, charge)
    update_rates_export(base, export)
    base.rate_min_forward = base.rate_min_forward_calc(base.rate_import)
    base.rate_max_base = base.rate_max
    pv = {minute: 0.0 for minute in range(0, 360, 5)}
    load = {minute: 0.04 for minute in range(0, 360, 5)}
    base.prediction = Prediction(base, pv, pv, load, load)
    ordered, links, prices, price_links = base.sort_window_by_price_combined(charge, export)
    base.optimise_charge_windows_reset(reset_all=True)
    base.optimise_charge_windows_manual()
    start = time.monotonic()
    result = base.optimise_charge_limit_price_threads(prices, price_links, links, 3, 3, [0] * 3, charge, export, [pack_export_limit(EXPORT_MODE_IDLE)] * 3, end_record=360, fast=True, quiet=True)
    elapsed = time.monotonic() - start
    # Actual candidate counts, not just elapsed time, catch a scale-dependent explosion.
    evidence = (len(prices), len(ordered), len(result[10]))
    print("currency benchmark scale={} bands/windows/tried={} time={:.4f}s".format(scale, evidence, elapsed))
    return result, evidence


def test_currency_planner_equivalence():
    """Verify actual optimisation and thresholds at ordinary, zero and negative prices."""
    for pair in ((2, 30), (-2, 0), (0, 0), (12, 12)):
        reference, counts = run_currency_planner(1, pair)
        for scale in (29, 0.25):
            result, scaled_counts = run_currency_planner(scale, pair)
            assert result[:2] == reference[:2], (pair, scale, reference[:2], result[:2])
            assert scaled_counts == counts, (pair, scale, counts, scaled_counts)
            for index in (2, 3, 4, 9):
                # Each engine/metric boundary rounds at 1e-4 calibrated penny.
                assert abs(result[index] / scale - reference[index]) <= 0.0002, (pair, scale, index, result[index], reference[index])


def test_currency_kernel_parity():
    """Exercise real compiled C++ and Python at three scales, including iBoost/EV."""
    for seed in range(6):
        reference = None
        for scale in (1, 29, 0.25):
            base = configured_predbat(scale)
            reset_inverter(base)
            base.car_charging_slots = [[] for _ in range(PREDBAT_MAX_CARS)]
            rng = random.Random(seed)
            apply_random_scenario(base, rng)
            charge_window = make_windows(rng, base.minutes_now, base.forecast_minutes, 3)
            export_window = make_windows(rng, base.minutes_now, base.forecast_minutes, 3)
            charge_limit = [base.soc_max] * len(charge_window)
            export_limits = [0] * len(export_window)
            end_record = base.forecast_minutes
            for name in ("rate_import", "rate_export", "rate_gas"):
                setattr(base, name, {minute: value * scale for minute, value in getattr(base, name).items()})
            for name in ("cost_today_sofar", "metric_standing_charge", "iboost_rate_threshold", "iboost_rate_threshold_export"):
                setattr(base, name, getattr(base, name) * scale)
            for slots in base.car_charging_slots:
                for slot in slots:
                    slot["average"] = slot.get("average", 0) * scale
            # A nonempty but incomplete gas series exercises the priced 99 fallback.
            if seed == 0:
                base.iboost_enable = base.iboost_gas = base.iboost_gas_export = True
                base.rate_gas = {-1: 7 * scale}
            data = make_step_data(base, rng)
            base.prediction_kernel_enable = False
            prediction = Prediction(base, *data)
            if seed == 0:
                arrays = build_static_context_arrays(prediction, base.forecast_minutes // 5, base.minutes_now, base.num_cars)
                assert all(math.isclose(value, 99 * scale * base.iboost_gas_scale) for value in arrays[12])
            simulation = prediction.run_prediction(charge_limit, charge_window, export_window, [pack_export_limit(0, 0, 1) for _ in export_window], PV_SCENARIO_NOMINAL, end_record)
            if reference is None:
                reference = simulation
            else:
                for index in range(11):
                    value = simulation[index] / scale if index in (0, 8) else simulation[index]
                    assert abs(value - reference[index]) < 0.0002, (seed, scale, index, value, reference[index])
            assert not dual_run("currency_{}_{}".format(seed, scale), base, *data, charge_limit, charge_window, export_window, export_limits, PV_SCENARIO_NOMINAL, end_record)


def test_currency_decision_boundaries():
    """Check both sides of pruning and swap gates at calibrated monetary precision."""
    for scale in (1, 29, 0.25):
        base = configured_predbat(scale)
        base.metric_min_improvement_plan = 2 * scale
        base.io_confirmed_tiebreak = False
        assert base.should_replace_plan(100 * scale, 98 * scale, 1, 1)
        assert not base.should_replace_plan(100 * scale, 98.001 * scale, 1, 1)
        clear_manual_times(base)
        base.end_record = 120
        base.export_window_best = []
        base.export_limits_best = []
        for gap, keep in ((0.019, False), (0.021, True)):
            base.charge_window_best = [{"start": base.minutes_now, "end": base.minutes_now + 30, "average": 10 * scale}]
            base.charge_limit_best = [2]
            with patch.object(base, "run_prediction_metric", side_effect=lambda charge, *args, **kwargs: ((100 + (gap if charge[0] == 0 else 0)) * scale,) * 8):
                base.prune_dead_plan_slots()
            assert (base.charge_limit_best[0] == 2) == keep
        for gain, keep in ((0.099, False), (0.101, True)):
            base.calculate_best_charge = True
            base.calculate_export_oncharge = True
            base.charge_window_best = [{"start": base.minutes_now + i * 30, "end": base.minutes_now + (i + 1) * 30} for i in range(2)]
            base.charge_limit_best = [2, 0]

            def metric(charge, *args, **kwargs):
                """Give the later-slot swap a controlled, calibrated improvement."""
                value = (100 - gain if charge == [0, 2] else 100) * scale
                return (value,) * 8

            with patch.object(base, "run_prediction_metric", side_effect=metric):
                base.optimise_swap_charge(2)
            assert (base.charge_limit_best == [0, 2]) == keep


def test_currency_export_commitment():
    """Compare actual running-export score bonuses and configured gates at three scales."""
    for exporting in (False, True):
        for gate in (0.1, 1.0):
            reference = None
            for scale in (1, 29, 0.25):
                base = configured_predbat(scale)
                windows, count, end_record = setup_single_export_window(base, rate_import=10 * scale, rate_export=30 * scale, battery_size=1, battery_soc=1)
                base.metric_min_improvement_export = gate * scale
                base.isExporting = exporting
                base.export_window = copy.deepcopy(windows) if exporting else []
                result = base.optimise_export(0, count, [], [], windows, [pack_export_limit(0, 0)], end_record=end_record)
                if reference is None:
                    reference = result
                    assert result[0][0] != EXPORT_MODE_IDLE, "Test must exercise a real export"
                else:
                    assert result[:2] == reference[:2], (exporting, gate, scale, result[:2], reference[:2])
                    for index in (2, 3, 6, 10):
                        assert abs(result[index] / scale - reference[index]) <= 0.0002, (exporting, gate, scale, index)


def test_currency_merge_and_compare():
    """Keep merge decisions, tariff identity and tariff ranking scale invariant."""
    from compare import Compare

    for scale in (1, 29, 0.25):
        base = configured_predbat(scale)
        base.minutes_now = 0
        base.forecast_minutes = 60
        base.predict_soc = {}
        clear_manual_times(base)
        base.all_active_keep = []
        base.set_charge_low_power = True
        windows = [{"start": n * 30, "end": (n + 1) * 30, "average": rate * scale} for n, rate in enumerate((10.004, 10.002, 10.001))]
        limits, merged = base.discard_unused_charge_slots([5, 5, 5], windows, 0)
        assert limits == [5, 5], (scale, merged)
        assert [(window["start"], window["end"]) for window in merged] == [(0, 60), (60, 90)]

        with patch.object(Compare, "load_yaml"):
            comparison = Compare(base)
        # 0.004 and 0.006 lie on opposite sides of the identity rounding boundary.
        for delta, expected in ((0.004, True), (0.006, False)):
            for side in ("import", "export"):
                rates = {minute: 10 * scale for minute in range(60)}
                tariff = {"id": "boundary", "rates_" + side: [{"rate": (10 + delta) * scale}]}
                assert comparison.fetch_rates(tariff, rates, rates) == expected, (scale, side, delta)

        # Exercise the real result construction: its metric is later used for ranking.
        base.pv_forecast_minute_step = {}
        base.pv_forecast_minute10_step = {}
        base.load_minutes_step = {}
        base.load_minutes_step10 = {}
        results = {}
        for name, metric in (("higher", 10.016), ("lower", 10.006)):
            with patch.object(base, "calculate_plan"), patch.object(base, "run_prediction", return_value=(0,) * 11), patch.object(base, "compute_metric", side_effect=[(0, 0), (metric * scale, 0)]), patch.object(
                base, "publish_html_plan", return_value=("", {})
            ):
                results[name] = comparison.run_scenario(60)
        comparison.select_best([{"id": name} for name in results], results)
        assert results["lower"]["best"] and not results["higher"]["best"], (scale, results)
        large = {"large": {"metric": 1e12 * scale}}
        comparison.select_best([{"id": "large"}], large)
        assert large["large"]["best"]


def test_currency_v960_boundaries():
    """Keep new 9.6.0 tariff identity and export staircase gates scale invariant."""
    from compare import Compare

    for scale in (1, 29, 0.25):
        base = configured_predbat(scale)
        base.minutes_now = 0
        with patch.object(Compare, "load_yaml"):
            comparison = Compare(base)
        for delta, expected in ((0.004, True), (0.006, False)):
            assert comparison.is_live_published({0: (10 + delta) * scale}, {0: 10 * scale}) == expected
        assert not comparison.is_live_published({}, {0: 10 * scale})
        clear_manual_times(base)
        base.all_active_keep_max = {}
        base.debug_enable = False
        base.charge_window_best = []
        base.charge_limit_best = []
        for gap, expected in ((0.019, 1), (0.021, 0)):
            base.export_window_best = [{"start": 0, "end": 30, "average": 10 * scale}, {"start": 30, "end": 60, "average": 10 * scale}]
            base.export_limits_best = [pack_export_limit(EXPORT_MODE_TARGET, 50), pack_export_limit(EXPORT_MODE_TARGET, 20)]
            with patch.object(base, "run_prediction_metric", side_effect=[(100 * scale,), ((100 + gap) * scale,)]):
                assert base.merge_export_staircase() == expected, (scale, gap)


def test_currency_service_power():
    """Keep physical service power unchanged with both currency calibration and PR #5373 active."""
    from tests.test_inverter_rate_no_entity import run_inverter_rate_no_entity_execute_tests, run_inverter_rate_no_entity_execute_10kw_tests

    for scale in (1, 29, 0.25):
        assert not run_inverter_rate_no_entity_execute_tests(configured_predbat(scale)), scale
        assert not run_inverter_rate_no_entity_execute_10kw_tests(configured_predbat(scale)), scale


def test_currency_saved_scenarios():
    """Preserve calibrated per-minute costs in the v9.7.1 PV10 and PV90 series."""
    for save in ("best10", "best90"):
        reference = None
        for scale in (1, 29, 0.25):
            base = configured_predbat(scale)
            reset_inverter(base)
            reset_rates(base, 0, 0)
            base.minutes_now = 0
            base.forecast_minutes = 60
            base.soc_kw = base.reserve = 0
            base.cost_today_sofar = base.metric_standing_charge = 0
            base.rate_import = {minute: 0.123456 * scale for minute in range(120)}
            base.rate_export = {minute: 0 for minute in range(120)}
            pv = {minute: 0.0 for minute in range(0, 60, 5)}
            load = {minute: 0.04 for minute in range(0, 60, 5)}
            prediction = Prediction(base, pv, pv, load, load)
            prediction.run_prediction([], [], [], [], PV_SCENARIO_NOMINAL, 60, save=save)
            metrics = {minute: value / scale for minute, value in prediction.predict_metric_best.items()}
            assert metrics and any(value != 0 for value in metrics.values()), (save, scale, metrics)
            if reference is None:
                reference = (metrics, prediction.predict_soc_best.copy())
            else:
                assert prediction.predict_soc_best == reference[1], (save, scale)
                assert metrics.keys() == reference[0].keys(), (save, scale)
                assert all(math.isclose(value, reference[0][minute], abs_tol=1e-12) for minute, value in metrics.items()), (save, scale, metrics, reference[0])


def run_currency_scale_tests(my_predbat):
    """Run calibration tests through Predbat's TEST_REGISTRY contract."""
    del my_predbat
    test_currency_configuration()
    test_currency_prices_and_sorting()
    test_currency_decision_boundaries()
    test_currency_planner_equivalence()
    test_currency_kernel_parity()
    test_currency_export_commitment()
    test_currency_merge_and_compare()
    test_currency_v960_boundaries()
    test_currency_service_power()
    test_currency_saved_scenarios()
    return False


def test_currency_debug_plan(my_predbat):
    """Replan a committed debug fixture with rescaled prices, comparing entire schedules."""
    from unit_test import create_predbat

    del my_predbat
    reference = None
    money_names = {item["name"] for item in CONFIG_ITEMS if item.get("unit") in MONETARY_UNITS}
    money_names.update(("cost_today_sofar", "cost_total_car", "cost_yesterday_car", "metric_standing_charge"))
    rate_tables = ("rate_import", "rate_export", "rate_gas", "rate_min_forward", "rate_export_max_forward", "rate_import_pre_saving", "rate_export_pre_saving", "io_confirmed_credit")
    for scale in (1, 29, 0.25):
        base = create_predbat()
        reset_inverter(base)
        base.read_debug_yaml("cases/predbat_debug_agile1.yaml")
        base.load_user_config()
        base.currency_scale = scale
        base.args["currency_scale"] = scale
        for name, value in list(base.__dict__.items()):
            is_rate_stat = name.startswith("rate_") and any(name.endswith(suffix) for suffix in ("_min", "_max", "_average", "_base", "_threshold_charge", "_threshold_export", "_cost_threshold", "_tariff_max"))
            if (name in money_names or is_rate_stat) and isinstance(value, (int, float)) and not isinstance(value, bool):
                setattr(base, name, value * scale)
        for name in rate_tables:
            table = getattr(base, name, {})
            setattr(base, name, {minute: value * scale for minute, value in table.items()})
        for name in ("low_rates", "high_export_rates", "charge_window", "export_window", "charge_window_best", "export_window_best"):
            for window in getattr(base, name):
                if "average" in window:
                    window["average"] *= scale
        for slots in base.car_charging_slots:
            for slot in slots:
                for field in ("average", "cost"):
                    if field in slot:
                        slot[field] *= scale
        base.prediction_kernel_enable = True
        base.plan_debug = base.debug_enable = False
        start = time.monotonic()
        with ExitStack() as stack:
            launches = [stack.enter_context(patch.object(base, name, wraps=getattr(base, name))) for name in ("launch_run_prediction_single", "launch_run_prediction_charge", "launch_run_prediction_charge_min_max", "launch_run_prediction_export")]
            base.calculate_plan(recompute=True, publish=False)
            candidate_count = tuple(launch.call_count for launch in launches)
        elapsed = time.monotonic() - start
        schedule = ([(w["start"], w["end"]) for w in base.charge_window_best], base.charge_limit_best, [(w["start"], w["end"]) for w in base.export_window_best], base.export_limits_best)
        metric = base.run_prediction_metric(base.charge_limit_best, base.charge_window_best, base.export_window_best, base.export_limits_best, end_record=base.end_record)
        print("currency full-plan scale={} candidates={} runtime={:.3f}s metric={}".format(scale, candidate_count, elapsed, metric[0]))
        if reference is None:
            reference = (copy.deepcopy(schedule), candidate_count, metric)
        else:
            assert schedule == reference[0], (scale, schedule, reference[0])
            assert candidate_count == reference[1], (scale, candidate_count, reference[1])
            for index in range(4):
                assert abs(metric[index] / scale - reference[2][index]) <= 0.0002, (scale, index, metric[index], reference[2][index])
    return False
