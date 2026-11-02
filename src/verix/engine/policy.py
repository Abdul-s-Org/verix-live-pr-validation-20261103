"""Validated repository policy and replayable deterministic evaluation."""

from copy import deepcopy
from fnmatch import fnmatchcase
import json
from pathlib import Path

import yaml

from verix.engine.git import VerixError, digest

DEFAULT = {
    "version": 1,
    "mode": "advisory",
    "risk": {},
    "exclude": [".env*", ".verix/*"],
    "checks": {},
}


class UniqueLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in mapping:
                raise yaml.constructor.ConstructorError(
                    None, None, "Policy keys must be unique strings", key_node.start_mark
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def load(path: Path) -> dict:
    try:
        raw = path.read_text() if path.exists() else ""
        data = yaml.load(raw, Loader=UniqueLoader) if raw else {}
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        location = f" line {mark.line + 1}" if mark else ""
        raise VerixError(f"Invalid policy{location}: {exc}") from exc
    if not isinstance(data, dict) or set(data) - set(DEFAULT):
        raise VerixError("Policy must be a mapping with known fields")
    result = {**deepcopy(DEFAULT), **data}
    if (
        type(result["version"]) is not int
        or result["version"] != 1
        or result["mode"] not in ("advisory", "blocking")
    ):
        raise VerixError("Unsupported policy version or mode")
    if not isinstance(result["risk"], dict) or any(
        not isinstance(k, str) or v not in ("low", "medium", "high")
        for k, v in result["risk"].items()
    ):
        raise VerixError("risk must map path patterns to low, medium, or high")
    if not isinstance(result["exclude"], list) or any(
        not isinstance(p, str) for p in result["exclude"]
    ):
        raise VerixError("exclude must be a list of path patterns")
    if not isinstance(result["checks"], dict) or any(
        not isinstance(k, str)
        or not isinstance(v, list)
        or not v
        or any(not isinstance(arg, str) or not arg for arg in v)
        for k, v in result["checks"].items()
    ):
        raise VerixError("checks must map names to nonempty argument lists")
    return result


def excluded(policy: dict, path: str) -> bool:
    return any(fnmatchcase(path, pattern) for pattern in policy["exclude"])


def risk(policy: dict, path: str) -> str:
    levels = {"low": 0, "medium": 1, "high": 2}
    matches = [value for pattern, value in policy["risk"].items() if fnmatchcase(path, pattern)]
    return max(matches, key=levels.get) if matches else "medium"


def policy_hash(policy: dict) -> str:
    return digest(json.dumps(policy, sort_keys=True).encode())


def evaluate(states: list[str], level: str, incomplete: bool) -> str:
    if "invalid" in states:
        return "block"
    if incomplete or not states or "unknown" in states:
        return "unresolved" if level != "low" else "allow"
    if "suspect" in states:
        return "block" if level == "high" else "verify"
    return "allow"
