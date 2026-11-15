<!-- cspell:words psidlo haléř haléře -->
# Currency calibration audit — Predbat v9.7.11

## Base and scope

This branch is an **extension of Predbat v9.7.11**, starting at upstream
commit `59018b15813dc437d93b1e20b404e9341d43f54b`.
The baseline `currency_scale` feature belongs to upstream
[PR #6156](https://github.com/springfall2008/batpred/pull/6156) / issue
[#6155](https://github.com/springfall2008/batpred/issues/6155). The larger
currency-independent and planner calibration request is tracked at
[issue #3683](https://github.com/springfall2008/batpred/issues/3683).

**Upstream v9.7.11 owns** the optional `apps.yaml` setting, validation,
scaling of money input_number minima/maxima, and unchanged built-in monetary
defaults and saved values. **This fork does not implement or override that
baseline**. It extends the same `currency_scale` setting; there is no second
mode, no separate range extender, and no legacy plugin dependency.

**This extension adds** monetary slider steps, fixed economic preferences and
valuation floors, numerical precision and candidate grouping, robust ordering
for large/negative prices, and consistent Python/C++ prediction scoring.
Both supplied tariff prices and explicitly stored money settings remain in
their original *local minor units*. No FX conversion is performed.

## Units and compatibility

At `currency_scale: 1`, all fixed monetary heuristics and rounding retain
upstream behaviour. At `currency_scale: 29`, a heuristic such as 0.5p is
calibrated to 14.5 haléř, without changing an input tariff of 363.894 haléř/kWh.
The upstream range policy rejects a scale below 1; this fork honours that
policy. Numeric tests use 1, 8.5 and 29.

The upstream built-in defaults are **not** rescaled. This deliberately
preserves the baseline behaviour of PR #6156. Previous versions of the fork
scaled those defaults at initial creation. When upgrading, explicitly
configured monetary values (including defaults that were saved by the
older fork) are preserved as local minor units; review their economic
meaning, do not apply an automatic conversion.

Existing stored monetary values outside the current advertised range
are preserved and the active UI range widened with a warning, without
changing any non-money clamping. A reload does not multiply an already
scaled range, and reset() uses upstream's fresh CONFIG_ITEMS copy.

## Algorithmic coverage

| Area | Additional treatment after upstream #6156 |
| --- | --- |
| `UserInterface.apply_currency_scale` | Scale steps only after upstream has scaled monetary min/max. |
| `Fetch` | Fixed import/export thresholds, price-window averages, calibrated rounding and numeric extrema. |
| `Plan` | Charge/export and swap commitments; battery value floor; time-based IO credit; grouping bands; numeric price order; calibrated decision tolerances and metric rounding. |
| `Prediction` | Monetary score rounding, sparse gas-price fallback, upstream manual SoC keep-rate floor multiplied by scale. |
| `prediction_kernel.cpp/.py` | Same calibrated manual SoC floor as Python; skip native 4dp pre-rounding of monetary fields for non-unit scales; only one calibrated rounding on the shared Python boundary. |
| `Compare` | Monetary tariff identity/ranking precision and unbounded internal score sentinel. |
| `Octopus` | Algorithmic IO slot tolerance; no changes to actual provider currency conversion. |
| `SolaX` | PR #5373-style service power control preserved independently of monetary calibration. |

Always leave the major/minor currency conversion used for display, GBP-only
provider assumptions, physical energy/SoC tolerances, actual tariff inputs,
and persisted money amounts alone. A currency symbol is not a calibration.

## Regression coverage

- Keep the upstream `currency_scale` test group unchanged for PR #6156
  (bounds, default preservation, invalid configurations).
- `currency_calibration`: fixed-money and negative-price boundaries, real
  planner equivalence, score thresholds, scenario comparison, kernel parity,
  manual SoC floors, and numeric rounding at scales 1, 8.5, 29.
- `currency_debug_plan`: complete plan and candidate-count equivalence
  on a replayed debug fixture.
- `kernel_parity`, `manual_soc`, `manual_soc_max`,
  `inverter_rate_no_entity`, `execute`: upstream/C++/SolaX regression suites.

The C++ ABI must be rebuilt for any new monetary context fields; do not
deploy a branch with old precompiled kernels when the ABI has changed.
Tests run via GitHub Actions without changing any Home Assistant or SolaX
settings. Branch publication is **not** deployment.

## Historical migration notes

The old `feature/currency-scale-v9.7.10` and
`feature/currency-scale-v9.7.10-audit-fixes` branches predate upstream
PR #6156 and implemented their own range/default calibration. That
configuration layer is intentionally **not copied** into this branch.
The v9.7.11 baseline replaces it. Previous historical audit details can
be consulted in those branches; this document describes only the current
implementation and its tested boundaries.
