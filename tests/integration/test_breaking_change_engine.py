from pathlib import Path

from opentrace.contracts.changes import compare_specifications
from opentrace.contracts.models import ChangeCategory
from opentrace.contracts.parser import OpenAPIParser

FIXTURES = Path(__file__).parents[1] / "fixtures" / "openapi"


def test_compares_fixture_contracts_through_m1_normalization() -> None:
    parser = OpenAPIParser()
    changes = compare_specifications(
        parser.parse_file(FIXTURES / "spec_v1_breaking.yaml"),
        parser.parse_file(FIXTURES / "spec_v2_breaking.yaml"),
    )

    assert {change.category for change in changes} == set(ChangeCategory)
    assert all(change.reason and change.evidence for change in changes)


def test_equivalent_yaml_and_json_contracts_have_no_changes() -> None:
    parser = OpenAPIParser()

    assert (
        compare_specifications(
            parser.parse_file(FIXTURES / "equivalent.yaml"),
            parser.parse_file(FIXTURES / "equivalent.json"),
        )
        == ()
    )
