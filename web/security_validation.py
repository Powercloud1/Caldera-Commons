import re
from typing import Any, Optional


class SecurityValidationError(Exception):
    def __init__(self, message: str, *, field: Optional[str] = None, code: str = "invalid_input"):
        super().__init__(message)
        self.message = message
        self.field = field
        self.code = code


def validate_allow_list(value: Any, *, field_name: str, pattern: str, max_length: int, min_length: int = 1) -> str:
    if not isinstance(value, str):
        raise SecurityValidationError(f"{field_name} must be a string", field=field_name, code="invalid_type")
    if not (min_length <= len(value) <= max_length):
        raise SecurityValidationError(f"{field_name} length out of bounds", field=field_name, code="invalid_length")
    if not re.fullmatch(pattern, value):
        raise SecurityValidationError(f"{field_name} failed allow-list validation", field=field_name, code="invalid_format")
    return value


def validate_int_field(value: Any, *, field_name: str, min_value: int, max_value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SecurityValidationError(f"{field_name} must be an integer", field=field_name, code="invalid_type")
    if not (min_value <= value <= max_value):
        raise SecurityValidationError(f"{field_name} out of allowed range", field=field_name, code="invalid_range")
    return value
