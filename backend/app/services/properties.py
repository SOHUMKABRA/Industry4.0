"""Validate an asset's custom properties against its type's property_schema."""

from typing import Any

from app.schemas.definitions import PropertyDef


class PropertyValidationError(ValueError):
    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))


def _coerce(d: PropertyDef, value: Any) -> Any:
    if d.type == "boolean":
        if isinstance(value, bool):
            return value
        raise ValueError("must be true or false")
    if d.type in ("number", "integer"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("must be a number")
        if d.type == "integer":
            if int(value) != value:
                raise ValueError("must be a whole number")
            value = int(value)
        if d.min is not None and value < d.min:
            raise ValueError(f"must be ≥ {d.min:g}")
        if d.max is not None and value > d.max:
            raise ValueError(f"must be ≤ {d.max:g}")
        return value
    if d.type == "enum":
        if value not in d.options:
            raise ValueError(f"must be one of {', '.join(d.options)}")
        return value
    if not isinstance(value, str):
        raise ValueError("must be text")
    if len(value) > 2000:
        raise ValueError("is too long")
    return value


def validate_properties(schema: list[dict], values: dict[str, Any]) -> dict[str, Any]:
    """Return a cleaned copy of `values`, or raise PropertyValidationError.

    Unknown keys are rejected so typos never silently become data. Missing
    optional keys take the schema default; null clears an optional value.
    """
    defs = {d.key: d for d in (PropertyDef.model_validate(s) for s in schema)}
    errors: dict[str, str] = {}
    out: dict[str, Any] = {}
    for key in values:
        if key not in defs:
            errors[key] = "is not defined on this asset type"
    for key, d in defs.items():
        raw = values.get(key, d.default)
        if raw is None or raw == "":
            if d.required:
                errors[key] = "is required"
            continue
        try:
            out[key] = _coerce(d, raw)
        except ValueError as e:
            errors[key] = str(e)
    if errors:
        raise PropertyValidationError(errors)
    return out
