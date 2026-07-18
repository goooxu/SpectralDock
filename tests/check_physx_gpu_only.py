#!/usr/bin/env python3
"""Exercise the mandatory GPU-only PhysX worker contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

from spectraldock.physics import PhysicsError, PhysicsWorld


def build_world(worker: Path, device: int) -> PhysicsWorld:
    world = PhysicsWorld(
        worker=worker,
        device=device,
        seed=20260718,
        fixed_dt=1.0 / 120.0,
        steps=4,
        scene_name="gpu-only-contract",
    )
    contact = world.material(
        "contact", static_friction=0.6, dynamic_friction=0.4, restitution=0.1
    )
    world.static_plane("ground", material=contact)
    world.rigid_body(
        "probe", category="contract-probe", position=(0.0, 0.3, 0.0)
    ).sphere(0.25, contact)
    return world


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--device", type=int, default=0)
    arguments = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="spectraldock-physx-check-") as temporary:
        directory = Path(temporary)
        metadata_path = directory / "gpu-only.physics.json"
        result = build_world(arguments.worker, arguments.device).simulate(
            metadata_output=metadata_path,
            verify=True,
            max_attempts=1,
        )
        result.validate()
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert metadata["backend"]["mode"] == "gpu"
        assert metadata["backend"]["cuda_context_valid"] is True
        assert metadata["backend"]["cpu_fallback"] is False
        assert metadata["simulation"]["broad_phase"] == "gpu"
        assert metadata["simulation"]["flags"]["gpu_dynamics"] is True
        assert all(
            value > 0
            for key, value in metadata["backend"]["gpu_heap_bytes"].items()
            if key != "samples"
        )

        rejected_metadata = directory / "unavailable-device.physics.json"
        try:
            build_world(arguments.worker, 2_147_483_647).simulate(
                metadata_output=rejected_metadata,
                max_attempts=1,
            )
        except PhysicsError:
            pass
        else:
            raise AssertionError("an unavailable CUDA device ordinal was accepted")
        assert not rejected_metadata.exists(), "failed GPU simulation published metadata"

        print(
            "GPU-only PhysX check passed:",
            json.dumps(metadata["backend"]["gpu_heap_bytes"], sort_keys=True),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
