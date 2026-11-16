<!-- cspell:words haléř haléře -->
# Currency calibration: implementation and validation

## Purpose and compatibility

Predbat's optional `currency_scale` setting accommodates currencies whose minor unit
is worth much less than a British penny. Introduced in [PR #6156](https://github.com/springfall2008/batpred/pull/6156),
the setting scales the minimum and maximum of monetary `input_number` controls. This
calibration extends the same setting to slider steps and built-in optimisation heuristics.
The motivation and user discussion are tracked in [issue #3683](https://github.com/springfall2008/batpred/issues/3683).

The factor is **not** an exchange rate: incoming tariff prices, stored monetary values
and user-configured amounts remain in local minor currency units. Built-in setting
**defaults are not rescaled**, to avoid silently altering existing installations.
`currency_scale: 1` retains the original monetary heuristics, rounding and clamping.
The supported factor is finite and at least 1; unsupported values fall back to 1.

At a non-unit scale, monetary values already saved outside the calibrated slider range
are retained, and the range is widened with a warning. At scale 1 the original clamp
remains active, including for monetary settings. Non-monetary limits always clamp.
Changing the factor requires a Predbat restart, and saved thresholds should be reviewed
for their intended economic meaning; no automatic conversion is performed.

## Implementation coverage

| Area | Behaviour |
| --- | --- |
| `UserInterface.apply_currency_scale` | Scales monetary input minima/maxima and slider steps on startup without changing defaults. |
| `Fetch` | Calibrates fixed import/export thresholds, price-window averages, monetary rounding and numeric extrema. |
| `Plan` | Calibrates charge/export preferences, swap decisions, battery valuation floors, IO credits, grouping bands, monetary tolerances and rounding. |
| `Prediction` | Applies calibrated scoring precision, gas-rate fallback and manual SoC keep-rate floors. |
| `prediction_kernel.cpp/.py` | Mirrors calibrated scoring constants; returns unrounded monetary metrics at non-unit scales for one calibrated rounding in Python. |
| `Compare` | Uses calibrated tariff comparisons, price rounding and numeric score sentinels. |
| `Octopus` | Calibrates algorithmic IO slot tolerances; provider-specific currency presentation is unchanged. |

The numeric sort keys used for price windows also support large and negative values
without ambiguous fixed-width text formatting. Physical power, energy and SoC
tolerances, display symbols, provider currency conversion and tariff inputs are
outside the scope of `currency_scale`.

## Regression coverage

- `currency_scale` covers monetary bounds, default preservation, invalid factors
  and the original clamp at scale 1.
- `currency_calibration` exercises price ordering, score boundaries, planner
  equivalence, explicit out-of-range monetary values, manual SoC floors,
  scenario comparison and Python/C++ parity at scales 1, 8.5 and 29.
- `currency_debug_plan` compares full schedules and candidate counts on a
  committed debug fixture.
- `kernel_parity`, `manual_soc`, `manual_soc_max` and `execute` cover
  related native-kernel and planner behaviour.

The native kernel context carries `currency_scale` explicitly (ABI 13,
parity revision 24); all six checked-in platform binaries must be rebuilt
from the reviewed source and independently verified before merge.
Tests and branch publication do not deploy or modify a live Home Assistant
installation.
