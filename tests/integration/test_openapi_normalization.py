from pathlib import Path

from opentrace.contracts.parser import OpenAPIParser

FIXTURES = Path(__file__).parents[1] / "fixtures" / "openapi"


def test_complex_contract_normalizes_as_a_complete_typed_artifact() -> None:
    specification = OpenAPIParser().parse_file(FIXTURES / "payment.yaml")

    artifact = specification.model_dump(mode="json", by_alias=True, exclude_none=True)

    assert artifact["title"] == "Payment API"
    assert set(artifact["schemas"]) == {
        "Payment",
        "PaymentChoice",
        "PaymentEither",
        "PaymentUpdate",
    }
    assert (
        artifact["operations"][0]["responses"]["200"]["content"]["application/json"]["reference"][
            "target"
        ]
        == "#/components/schemas/Payment"
    )
