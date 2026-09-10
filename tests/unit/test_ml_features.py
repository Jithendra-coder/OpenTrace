import json
import shutil

import pytest
from opentrace.ml import FeatureEncoder, FeatureSet, feature_names, load_development_splits


def test_allowlist_excludes_truth_and_provenance_metadata() -> None:
    forbidden = {
        "ground_truth_label",
        "ground_truth_impact_type",
        "ground_truth_distance",
        "ground_truth_path",
        "row_id",
        "scenario_id",
        "migration_id",
        "repository_id",
        "repository_family_id",
        "api_family_id",
    }

    assert not forbidden & set(feature_names(FeatureSet.STRUCTURAL))
    assert not forbidden & set(feature_names(FeatureSet.STRUCTURAL_HEURISTICS))


def test_encoder_fits_train_only_and_handles_unknown_validation_category() -> None:
    splits = load_development_splits()
    encoder = FeatureEncoder(FeatureSet.STRUCTURAL)
    encoder.fit(list(splits.train))
    unknown = splits.validation[0].model_copy(
        update={
            "features": splits.validation[0].features.model_copy(
                update={"change_category": "unseen-development-category"}
            )
        }
    )

    transformed = encoder.transform([unknown])

    assert encoder.metadata()["fit_partition"] == "TRAIN"
    assert transformed.shape == (1, len(encoder.output_feature_names))
    assert transformed.min() == transformed.min()


def test_sealed_test_partition_and_group_integrity() -> None:
    splits = load_development_splits()

    assert splits.integrity.train_validation_migration_overlap == 0
    assert splits.integrity.train_test_migration_overlap == 0
    assert splits.integrity.validation_test_migration_overlap == 0
    assert splits.integrity.test.positives is None
    with pytest.raises(RuntimeError, match="sealed"):
        _ = splits.test_rows


def test_invalid_dataset_version_is_rejected(tmp_path) -> None:
    source = tmp_path / "m7"
    shutil.copytree("data/m7", source)
    manifest_path = source / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["dataset_version"] = "unknown"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="version"):
        load_development_splits(source)
