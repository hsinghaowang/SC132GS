# Feature-count correction

The original benchmark documentation described `num_pts: 200` as 200 points per camera, following the upstream YAML comment. That description is incorrect for the pinned OpenVINS revision `69488123ed9362dd44b6f28e7f4680abbff1442b`.

`ov_msckf/src/core/VioManagerHelper.cpp` calls `set_num_features(floor(params.num_pts / params.state_options.num_cameras))` when transitioning from initialization. `VioManager.cpp` also divides the tracking target among cameras. With two cameras, num_pts 200 means target 100 per eye. This is a target, not a guarantee of the number actually tracked in every frame.

The original run configurations and raw results remain unchanged. Their timing and accuracy measurements remain valid; the feature-count description is corrected here and in benchmark-conditions.json. Archived reports inside euroc-results are retained with their original hash manifest as historical evidence; read their feature-count wording with this correction.

The new feature sweep preserves the original baseline num_pts 200 and reduces it to 150 and 100, corresponding to targets 100, 75 and 50 per eye. It does not increase the original baseline to 400.
