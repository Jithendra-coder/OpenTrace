"""Generate the inspectable RouteForge scenario dataset."""

from __future__ import annotations

import argparse
from pathlib import Path

from opentrace.routeforge import RouteForgeConfig, generate_routeforge_dataset, write_artifacts


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the offline RouteForge scenarios dataset")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data") / "routeforge_scenarios",
        help="artifact output directory",
    )
    args = parser.parse_args()
    dataset = generate_routeforge_dataset(RouteForgeConfig())
    paths = write_artifacts(dataset, args.output)
    print(f"generated {len(dataset.scenarios)} scenarios and {len(dataset.rows)} rows")
    print(f"checksum {dataset.manifest.content_sha256}")
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
