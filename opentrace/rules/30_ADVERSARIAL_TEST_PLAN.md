# Adversarial Test Plan

Required cases include comments/docstrings/documentation examples/unrelated strings/variable names containing endpoints; dynamic URLs; aliased imports; payload aliases and nested dictionaries; response extraction; same path across hosts; similar field names; multiple APIs; wrapper/re-exported/recursive/decorated/async/method/nested functions; same symbol names in separate modules; unresolved imports; local `post`; shadowed `requests`; query versus body parameters; request versus response fields; nested `$ref`; arrays; `allOf`; `oneOf`; `anyOf`; and optional property additions.

Each case specifies expected finding(s), non-finding(s), resolution state and rationale. False positives are as important as true positives. Add cases for defects, cycles, malformed specs/source, time/resource bounds, and no-data/unsupported behavior as milestones introduce them.
