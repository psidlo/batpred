# Integration: Predbat v9.8.0 + currency_scale + SolaX service power

## Origin

- Official upstream Predbat [v9.8.0](https://github.com/springfall2008/batpred/releases/tag/v9.8.0), tag commit `53190724324acbb89f7bbb392c7ea8af5d8401bc`, is an ancestor of this branch.
- The branch starts at [psidlo/batpred PR #6221 head](https://github.com/springfall2008/batpred/pull/6221), commit `64fa3cc0f3d5a009e6225bf2c9977723cf3aa845`, adding monetary heuristic calibration and ABI 13 kernel builds.
- The SolaX service-control fix comes from upstream [PR #5373](https://github.com/springfall2008/batpred/pull/5373), adapted to the v9.8.0 execution paths. It delays calls to services carrying `{power}` until the selected charge/discharge rate is written, and retains a last-set rate where an inverter has no writable rate entity.
- `POWER_SERVICES` and `services_send_power()` already existed in the PR #6221 source snapshot and were not duplicated.
- Additional v9.8.0 `discharging_to_target` control paths also use deferred immediate calls.
- The PR #6221 `currency_scale: 29` logic and matching ABI 13 native binaries are retained unmodified.

## Validation and deployment

A branch-specific CI trigger runs the currency configuration/calibration and native kernel tests together with PR #5373 service-power and execution regressions. Check the branch workflow result before deploying. The branch is **not deployed** by creating commits; Home Assistant / Predbat / SolaX settings must be changed separately with explicit approval.

If switching a live Predbat installation, keep the previously deployed branch available for rollback and verify charge/export transitions and actual power requests after restart.
