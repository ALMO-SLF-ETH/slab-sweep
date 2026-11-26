"""A slow demo model for exercising the plugin's Run page by hand.

It honours the process contract but does no real science: it reports progress over a few
seconds, then writes a small constant-value GeoTIFF whose value is the ``level`` parameter.
This lets you watch the progress bar move and see an output layer load. It needs GDAL/numpy,
which QGIS's Python provides -- run it via QGIS, not the bare engine environment.

Usage is via the manifest ``examples/demo_model/model.toml``; you do not call this directly.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from slab_sweep.contracts import RESULT_FILENAME, RunResult, RunSpec, emit_progress

_STEPS = 20
_STEP_SECONDS = 0.2
_SIZE = 64


def _write_geotiff(path: Path, value: float) -> None:
    import numpy as np
    from osgeo import gdal, osr

    ds = gdal.GetDriverByName("GTiff").Create(str(path), _SIZE, _SIZE, 1, gdal.GDT_Float32)
    ds.SetGeoTransform([0.0, 1.0, 0.0, 0.0, 0.0, -1.0])
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())
    ds.GetRasterBand(1).WriteArray(np.full((_SIZE, _SIZE), value, dtype="float32"))
    ds.FlushCache()


def main() -> int:
    runspec_path = sys.argv[sys.argv.index("--runspec") + 1]
    spec = RunSpec.read(runspec_path)
    out_dir = Path(spec.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for i in range(_STEPS + 1):
        emit_progress(i / _STEPS, f"step {i}/{_STEPS}")
        time.sleep(_STEP_SECONDS)

    level = float(spec.params.get("level", 1.0))
    outputs: dict[str, str] = {}
    for name in spec.store_outputs or ("field",):
        path = out_dir / f"{name}.tif"
        _write_geotiff(path, level)
        outputs[name] = str(path)

    RunResult.success(
        spec.run_id, outputs, metrics={"level": level}, message="demo run complete"
    ).write(out_dir / RESULT_FILENAME)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
