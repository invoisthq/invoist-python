"""Regenerate ``invoist/_generated/models.py`` from the API's OpenAPI document.

Run from the SDK folder, after ``pip install -e '.[dev]'``::

    python scripts/generate.py

The spec is ``testdata/openapi.yaml``, or the file named by
``$INVOIST_OPENAPI``. The output is deterministic, so running this twice
leaves no diff; CI relies on that to catch models that fell behind the spec.

One step runs after datamodel-code-generator: every ``Literal[...]`` (an enum
in the spec) is wrapped as ``Annotated[Literal[...], OPEN_ENUM]``. Type
checkers still see the closed set of values, but at runtime a value the API
added after this release comes through as a plain string instead of failing
the whole response. The API adds enum values the same way it adds fields.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "invoist" / "_generated" / "models.py"
DEFAULT_SPEC = ROOT / "testdata" / "openapi.yaml"

HEADER = '''\
# This file is generated from the Invoist OpenAPI document by
# scripts/generate.py (datamodel-code-generator). Do not edit it by hand:
# change the spec, run the script, and commit the result.

"""Request and response models for the Invoist API, generated from its OpenAPI document."""

'''

OPEN_ENUM = '''

def _open_enum(value: Any) -> str:
    """Accept any string for an enum field, so new API values never break parsing."""
    if not isinstance(value, str):
        raise ValueError("expected a string")
    return value


OPEN_ENUM = PlainValidator(_open_enum, json_schema_input_type=str)
"""Marks an enum field as open: known values are typed, unknown ones still parse."""
'''

LITERAL = re.compile(r"Literal\[[^\[\]]*\]")


def _bin(name: str) -> str:
    """Prefer the tool next to this interpreter (the venv), else rely on PATH."""
    candidate = Path(sys.executable).parent / name
    return str(candidate) if candidate.exists() else name


def main() -> None:
    """Generate, post-process and format the models module."""
    spec = Path(os.environ.get("INVOIST_OPENAPI") or DEFAULT_SPEC)
    if not spec.is_file():
        sys.exit(f"OpenAPI document not found at {spec} (set INVOIST_OPENAPI)")

    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "models.py"
        subprocess.run(
            [
                _bin("datamodel-codegen"),
                "--input", str(spec),
                "--input-file-type", "openapi",
                "--output", str(raw),
                "--output-model-type", "pydantic_v2.BaseModel",
                "--target-python-version", "3.11",
                "--enum-field-as-literal", "all",
                "--use-type-alias",
                "--use-annotated",
                "--field-constraints",
                "--use-schema-description",
                "--use-field-description",
                "--use-generic-base-class",
                "--extra-fields", "allow",
                "--type-mappings", "string+uuid=string",
                "--output-datetime-class", "datetime",
                "--naming-strategy", "parent-prefixed",
                "--use-double-quotes",
                "--disable-timestamp",
                "--formatters", "builtin",
            ],
            check=True,
        )  # fmt: skip
        source = raw.read_text(encoding="utf-8")

    # Drop the generator's own banner (it names a temp path) for ours.
    source = re.sub(r"\A(#[^\n]*\n)+\n?", "", source)
    source = LITERAL.sub(lambda m: f"Annotated[{m.group(0)}, OPEN_ENUM]", source)
    # Imports the validator needs; ruff's isort below merges them in.
    source = source.replace(
        "from __future__ import annotations\n",
        "from __future__ import annotations\n\n"
        "from typing import Any\n\n"
        "from pydantic import PlainValidator\n",
        1,
    )
    # A name of our own for the shared base, instead of shadowing pydantic's.
    source = source.replace(
        "class BaseModel(_BaseModel):\n",
        "class InvoistModel(_BaseModel):\n"
        '    """Base of every model: unknown fields the API adds are kept, never an error."""\n\n',
    )
    source = re.sub(r"\(BaseModel\)", "(InvoistModel)", source)
    # The validator goes right after the imports, before the first class.
    first_class = source.index("\nclass ")
    source = source[:first_class] + OPEN_ENUM + source[first_class:]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(HEADER + source, encoding="utf-8")

    ruff = _bin("ruff")
    subprocess.run(
        [ruff, "check", "--quiet", "--fix", "--select", "I,F401,UP", "--isolated", str(OUTPUT)],
        check=True,
    )
    subprocess.run(
        [ruff, "format", "--quiet", "--isolated", "--line-length", "100", str(OUTPUT)], check=True
    )
    print(f"wrote {OUTPUT.relative_to(ROOT)} from {spec}")


if __name__ == "__main__":
    main()
