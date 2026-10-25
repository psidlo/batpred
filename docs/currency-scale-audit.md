# Currency calibration audit

`currency_scale` is a calibration of the monetary heuristics in Predbat, not an
exchange rate applied to tariffs. The base for this change is upstream commit
`65d1a6c04cc6982c22df5662324e8c582fb1c17a` (v9.5.1). It addresses the calibration
problem discussed in [issue #3683](https://github.com/springfall2008/batpred/issues/3683).

## Monetary boundaries

All optimiser prices and costs remain in the supplied tariff's local minor unit.
An explicit value always has that same interpretation. Only a *missing* setting
uses the calibrated built-in default. `round_currency` performs algorithmic
rounding in calibrated penny units and returns local minor units; display
rounding continues to use the displayed currency's usual decimal places.

The following table records changes and deliberate exclusions. Names separated
by a slash denote related symbols in the same module, not different unit systems.

| File and symbol | Meaning and unit | Original constant | Treatment | Verification |
| --- | --- | --- | --- | --- |
| `currency.py` / `PredBat.reset` | Positive finite calibration | Missing value = 1 | Validate before configuration can run; reject booleans and non-numbers | `currency_scale`: validation and reset |
| `config.py` / `APPS_SCHEMA` | Public optional apps.yaml scalar | 1.0 | Declare numeric key; runtime validation also enforces finiteness | `currency_scale` |
| `CONFIG_ITEMS`, `currency_config_items` | Built-in money defaults, limits, steps | Values listed below | Fresh per-instance copy, never multiply supplied values or mutate the module definitions | Multiple instances, 1 → 29 → 1, repeated refresh/reset |
| `UserInterface.configure_currency` / `load_user_config` | Metadata refresh and source priority | Existing HA/JSON/apps.yaml precedence | Rebuild monetary metadata from canonical definitions; retain explicit values even at old defaults; widen conflicting ranges with warning | JSON precedence, explicit/default equality, range conflicts, legacy plugin ranges |
| `Fetch.set_rate_thresholds` | Automatic import/export and EV price margins, minor/kWh | +0.1, -0.5, -0.1, +0.5 | Multiply fixed margins only; percentage thresholds remain ratios | Incoming 363.894 unchanged, calibrated threshold and planning cases |
| `Fetch.find_charge_window`, `rate_scan_window`, `rate_minmax`, `rate_minmax_excluding_saving` | Algorithmic rate summaries and window averages | 0.01 precision | Round in calibrated units; do not modify underlying supplied rates | Negative/large/flat rates, full-plan equivalence, threshold regressions |
| `Fetch.rate_minmax` / `rate_scan_window` | Bounds while scanning prices | 99999, 0, 99, -99 | Use infinite internal bounds so finite prices cannot cross a sentinel; preserve the legacy empty-result placeholders without scaling | All-negative and large positive prices, empty tables |
| `Plan.io_confirmed_credit_update` | Confirmed IO score credit, minor/kWh | 0.1 | Calibrate credit before the time-based decay; time divisor unchanged | IO regression suite and kernel scenarios |
| `Plan.battery_value_rate` | Minimum battery value, minor/kWh | 1.0 | Calibrate floor; losses and recovery ratio unchanged | Floor and compute-metric tests |
| `Plan.optimise_charge_limit` | Current-charge commitment and option preferences, minor | 0.1; 0.003/0.002/0.001 | Calibrate fixed bonuses; do not multiply configured minimum improvement | Planner equivalence and charge regressions |
| `Plan.optimise_export` | Off/full preferences and ongoing-export commitment, minor | 0.002/0.001; max(0.5, configured gate) | Calibrate fixed terms, including the negative cost gate | Export commitment suite, planner and full debug-plan equivalence |
| `Plan._io_rate_adjustment` | Dispatch gradient, minor/kWh | Slope 1; discount cap 3; penalty cap 10 | Calculate the bounded gradient then calibrate; 1.5-hour pivot and 3-hour horizon unchanged | Three-scale gradient and IO skew tests |
| `Plan.sort_window_by_price_combined` | Candidate price grouping, minor/kWh | Precision 0.01; export precision 0.1; bands 0.2/0.1 | Calibrate precision and bands, including secondary/carbon prices | Equal band and candidate counts at 1/29/0.25 |
| `Plan.sort_window_by_price_combined`, `sort_window_by_price` | Numeric price/time order | String anchor 5000 | Structural numeric tuple key; retain time/mode tie ordering and export-last grouping; no price-dependent width/collisions | Negative, zero, repeated, >5000 and >99999 prices |
| `Plan.optimise_charge_limit_price_threads` | Below-cheapest candidate and uninitialised score bounds | Price -1; score ±9999999 | Calibrate the price step; infinite score sentinels are not monetary constants | Planner equivalence, optimisation suites and candidate benchmark |
| `Plan.compute_metric` / `should_replace_plan` | Metric/value rounding and IO cost equality, minor | 0.0001 / 0.01 | Calibrated algorithmic precision; configured retention gate unchanged | Metric, boundary, full-plan tests |
| `Plan.prune_dead_plan_slots` | Monetary dead-slot tolerance, minor | 0.02 | Calibrate epsilon; energy and time checks unchanged | Both sides of epsilon at three scales; prune/hedge suites |
| `Plan.optimise_swap_charge` | Local charge-swap improvement, minor | 0.1 | Calibrate fixed positive gate | Gains 0.099 and 0.101 in normalised units at three scales |
| `Plan.optimise_swap_export` | Configured local export-swap gate, minor | `metric_min_improvement_swap` | Already a local value; only its missing built-in default is calibrated | Export swap suite and full-plan test |
| `Prediction.__init__` / `run_prediction` | Cost precision and sparse gas fallback, minor and minor/kWh | Precision 0.0001; gas 99 | Capture calibration on the prediction; calibrate cost/keep precision and gas fallback, which is a price, not an off marker | Real Python/C++ parity and scaled prediction equivalence including sparse gas |
| `prediction_kernel.py` / `build_static_context_arrays`, `kernel_result_tuple` | C++ boundary for gas and monetary results | Same 99 and 0.0001 | Identical gas fallback and final rounding as Python | Native compiled kernel at scales 1/29/0.25 |
| `prediction_kernel.cpp` | Physical simulation and price × energy arithmetic | No fixed monetary epsilon | No ABI or native-source change needed: prices, IO credit and gas arrive in local units; all monetary rounding is in the Python result boundary | Native kernel rebuilt and exercised, not a Python substitute |
| `Octopus.rate_add_io_slots` | Tolerance against rounding of local tariff summaries | 0.01 | Calibrate this optimiser tolerance, not provider prices or rewards | IO/Octopus and threshold suites |
| `octopus.py`, `kraken.py`, `axle.py`, `futurerate.py`, `energydataservice.py` | Provider-specific currency and energy units | ×100, ÷10, points-per-penny, VAT; provider GBP price defaults | Leave documented API conversions and actual tariff/reward defaults unchanged. They are not optimiser calibration constants; mixing currencies requires explicit conversion outside this feature | Existing mocked provider suites; 363.894 input regression |
| `teslemetry.py` | Tesla tariff payload and tier quantisation | Major/minor 100, default GBP 0.28/0.15, whole minor tiers | Leave provider contract unchanged; calibration does not alter the currency of a Tesla payload or invent an exchange rate | Existing Teslemetry tariff tests |
| `Compare.fetch_rates`, `run_scenario`, `select_best` | Tariff identity and ranking | 0.01 precision; best score 9999999999 | Calibrate identity and ranking precision, preserve ranking metric through result serialisation; infinite best-score marker. Supplied tariff overrides remain local | Three-scale identity boundaries, close-score ranking, scores above the old sentinel; Compare regression suite |
| `Plan.discard_unused_charge_slots` | Average of merged charge windows, minor/kWh | 0.01 precision | Calibrate rounding because the average controls whether the next adjacent window can merge in low-power mode | Three adjacent windows with prices 10.004/10.002/10.001 at three scales |
| `annual.py`, `annual_costs.py`, `annual_cli.py`, `tariff_catalogue.py` | UK reference tariff prices, reporting | Ofgem/SEG prices; major/minor 100 | Reference tariffs are real GBP tariffs, not abstract optimiser defaults. Keep them and reporting conversion unchanged; configure a consistent local reference tariff for non-GBP studies | Annual regression suite |
| `output.py`, `web.py`, `web_helper.py`, `gateway.py`, `predbat_metrics.py`, `agent_tools.py` | Presentation and report transport | Major/minor 100; display decimal rounding | Leave major/minor conversion and currency labels unchanged. These do not set candidate bands or price decisions | Existing output/web/gateway/agent tests and golden replay |
| Planner/prediction physical quantities | kWh, kW, watts, SoC, time, ratios | 0.1 kWh steps, efficiency factors, 99/100 SoC modes, step minutes | No calibration; physical tolerances and packed mode sentinels stay physical | Whole schedule/SoC equivalence and native parity |

## Monetary configuration inventory

Every `input_number` definition with unit `p`, `p/kWh` or `p/kg` is covered,
including settings outside the original ten-setting plugin:

- `metric_min_improvement_plan`, `metric_min_improvement`,
  `metric_min_improvement_export`, `metric_min_improvement_swap`,
  `metric_min_improvement_export_freeze`;
- `metric_battery_cycle`, `metric_future_rate_offset_import`,
  `metric_future_rate_offset_export`, `metric_self_sufficiency`;
- `combine_rate_threshold`, `export_more_solar_threshold`;
- `car_charging_plan_max_price`, `manual_import_value`, `manual_export_value`;
- `carbon_metric`, `iboost_rate_threshold`, `iboost_rate_threshold_export`.

The test iterates the canonical definitions, asserting each default, minimum,
maximum and step. Dimensionless settings such as `metric_battery_value_scaling`,
`pv_metric10_weight` and `iboost_gas_scale` are deliberately excluded. A currency
symbol is never used to infer calibration.

## Acceptance checks

Run from `coverage/`, with the environment's Python virtual environment active:

```bash
PREDBAT_KERNEL_REQUIRED=1 python ../apps/predbat/unit_test.py --test currency_scale --test currency_debug_plan > /tmp/currency-tests.log 2>&1
PREDBAT_KERNEL_REQUIRED=1 python ../apps/predbat/unit_test.py --test debug_cases --test compute_metric --test kernel_parity > /tmp/currency-regression.log 2>&1
```

Inspect exit codes and saved summaries. `currency_scale` compares actual
six-hour optimisation at scales 1, 29 and 0.25 for positive, negative, zero and
flat prices. It verifies identical charge/export targets and candidate counts.
`currency_debug_plan` compares entire charge/export schedules and SoC targets
from the committed Agile fixture and records actual full-plan candidate counts
and elapsed time. Timing is reported rather than asserted because CPU scheduling
is variable; exact candidate-count assertions detect scale-dependent growth.

Monetary comparisons allow 0.0002 *calibrated penny* for independently rounded
simulation/metric boundaries, not a broad relative tolerance. Whole schedules
and physical targets must match exactly. The kernel test exercises both Python
fallback and an actual loaded native context, including EV and iBoost. Existing
golden replay verifies omitted calibration against the same base commit.

The setup baseline has a separately diagnosed `ge_cloud` test-isolation problem:
some auth-status tests make unmocked account requests with a fixture key. A
timeout there is not evidence of a currency regression. Report a blocked full
suite separately from completed tests; never describe an exclusion as a fully
passing quick suite. No real HA, inverter or provider credentials are needed.

## Review boundaries and remaining UK assumptions

The follow-up review found and corrected two algorithmic gaps: charge-window
merge rounding and tariff-comparison identity/ranking rounding. The comparison
best-score marker is now infinite, so a large finite local-currency score cannot
leave every tariff unselected.

This does not make every integration currency-independent:

- `TeslemetryAPI.current_rates`, `_quantise_side` and the tariff payload assume
  GBP and emit `currency: GBP`. They are not suitable for sending CZK tariff
  values merely by setting `currency_scale: 29`; this feature does not implement
  a Tesla currency conversion or a non-GBP tariff payload.
- `annual_costs.py` installation-cost assumptions and the default UK reference
  tariffs remain GBP values. A non-GBP economic study needs consistent reference
  and capital costs; this calibration alone does not provide them.
- `Output.publish_html_plan` uses 10/0.5/-0.5 local minor units for cost colours
  and arrows, and 0.01 local minor units to split household/car price displays.
  These are presentation decisions, not planner gates. Display rounding and
  these visual thresholds remain in local display units, so colours need not
  match across scales. `Plan.car_charge_slot_rate` similarly rounds its
  presentation-only weighted price to two decimals.
- Octopus CLI tariff grouping at 0.0001 and provider-defined defaults/rewards
  are in the provider's currency. No implicit exchange conversion is applied.

The audit covers the planner and simulation calculations, configuration,
comparison, provider boundaries and presentation distinctions. It is not a
claim that arbitrary local-currency data can be passed into every UK-specific
integration. The new regressions are part of the native `currency_scale` group.
