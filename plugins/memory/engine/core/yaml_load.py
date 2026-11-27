"""The YAML parser the engine uses and the plain `safe_load` built on it. Imports only the standard library and PyYAML."""

from __future__ import annotations

import yaml

# The C parser is several times faster; searching reads every note. libyaml accepts a tab after a colon
# (`a:\tb`) and words parse errors differently. This is the one place that picks it.
BaseLoader: type[yaml.SafeLoader] = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def safe_load(text: str):
    """Plain SafeLoader values (dates stay dates) from the same C parser; HubLoader's rules do not apply."""
    return yaml.load(text, Loader=BaseLoader)
