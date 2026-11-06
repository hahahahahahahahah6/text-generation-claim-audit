# Documentation claim auditor

An offline, deterministic checker for documentation claims about open-ended
model output. Uses only the Python standard library at runtime, with no model,
network access, telemetry, or filesystem writes during an audit. Requires
Python 3.9 or later.

## Install and use

```sh
python3 -m pip install .
text-generation-claim-audit --version
text-generation-claim-audit audit .
python3 -m text_generation_claim_audit audit . --json
text-generation-claim-audit audit . --verbose --ignore docs/drafts/ --ignore tests/
text-generation-claim-audit audit . --fail-on medium
python3 -m unittest discover
python3 -m build
```

The repository argument defaults to the current directory. The ignore option
accepts one or more path prefixes and can be repeated. Prefixes are relative
to the repository root, use forward slashes, and match from the start of a path.
Verbose mode reports scope, scanned and ignored files, and evidence on stderr.
JSON output contains a verdict, a message, and a findings array; each finding
includes its rule, severity, path, matched phrase, verdict, and message.

Exit status is 0 when no finding reaches the selected threshold, 2 when one
does, and 1 for usage or input errors. The default threshold is high; medium
also fails on test-only findings. A passing threshold verdict can still include
medium findings. Version output is 0.1.0.

## Scope and decisions

Checks root README.md and Markdown files recursively under docs. Fenced blocks
are excluded, while inline code counts as prose. It also checks test fixtures
under directories named tests. Python sources are parsed recursively without
executing them; Git metadata, bytecode caches, and virtual environments are
excluded. Invalid Python or unreadable input produces an error.

Claims with no matching source evidence receive high severity. Denials
contradicted by evidence also receive high severity. A denial with no evidence
passes. Positive phrases found only in test fixtures receive medium severity
when there is no evidence. No claims, or a supported positive claim, passes.

Rule identifiers:

```text
documented-text-generation-claim-false
documented-no-text-generation-claim-false
```

Evidence must occur within one Python module. Imports and aliases are resolved;
local function or class definitions shadow imported route names throughout
that module. Recognized patterns include a task-specific pipeline construction
paired with an instance call, a causal model construction paired with its output
method, a local runtime construction paired with an instance call, legacy API
calls, two supported direct APIs, and 24 explicit generic call names. Imports,
unbound references, strings, comments, subprocesses, templates, unrelated tasks,
and incomplete pairs do not establish evidence.

## Differentiation

The following neighboring tools check different operations:

```text
summarization-claim-audit
paraphrasing-claim-audit
translation-claim-audit
image-generation-claim-audit
```

In the order listed, these check condensing a document, restating a sentence,
converting languages, and producing pictures. This auditor instead checks
producing new open-ended output from a prompt, in words.

## Limitations

This is static pattern matching, not semantic judgement. Matching uses exact,
case-insensitive substrings, with no stemming, restatement detection, or hyphen
normalization. Denial spans are removed first. Longest-first matching blanks
matched spans so each occurrence counts once under its longest phrase.

A pipeline pair, a causal model pair, or a legacy completion call shows a
recognized use pattern; none proves that output is correct or useful. Generic
method names on unrelated objects can count as evidence, including this example:

```python
unrelated.generate_text()
```

Conversational APIs deliberately do not count. A dialogue operation has roles
and history, and this static fingerprint cannot distinguish a conversational
turn from a bare completion even if only one user prompt is supplied.

Some exact phrases also describe producing files or formatted output, finishing
form fields, or IDE field autocompletion. The short abbreviation below can match
inside longer identifiers. These are known ambiguities, not semantic checks:

```text
generate text
generates text
generating text
complete text
text completion
nlg
```

Construction and use split across modules do not count. Dynamic dispatch,
reflection, wildcard imports, and runtime behavior are not inferred. The scanner
does not prove that a dependency is installed or that any operation succeeds.
