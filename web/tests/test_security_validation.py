import pytest

from security_validation import SecurityValidationError, validate_allow_list, validate_int_field


def test_validate_allow_list_accepts_allowed_characters():
    value = validate_allow_list(
        "Read 1 Chapter",
        field_name="title",
        pattern=r"[A-Za-z0-9 _\-.,'()]{1,80}",
        max_length=80,
    )
    assert value == "Read 1 Chapter"


def test_validate_allow_list_accepts_trade_names_with_slashes():
    value = validate_allow_list(
        "Logistics / Dispatch",
        field_name="trade",
        pattern=r"[A-Za-z0-9 _\-/]{1,40}",
        max_length=40,
    )
    assert value == "Logistics / Dispatch"


def test_validate_allow_list_rejects_disallowed_characters():
    with pytest.raises(SecurityValidationError) as exc_info:
        validate_allow_list(
            "bad<script>",
            field_name="title",
            pattern=r"[A-Za-z0-9 _\-.,'()]{1,80}",
            max_length=80,
        )
    assert exc_info.value.code == "invalid_format"


def test_validate_int_field_rejects_out_of_range_values():
    with pytest.raises(SecurityValidationError) as exc_info:
        validate_int_field(99, field_name="points", min_value=10, max_value=50)
    assert exc_info.value.code == "invalid_range"


def test_validate_int_field_rejects_non_integer_values():
    with pytest.raises(SecurityValidationError) as exc_info:
        validate_int_field("10", field_name="points", min_value=10, max_value=50)
    assert exc_info.value.code == "invalid_type"
