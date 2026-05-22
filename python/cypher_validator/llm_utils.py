"""
LLM integration utilities for cypher_validator.

Provides helpers for the full LLM ↔ graph-database loop:

* Extracting Cypher from LLM text output (handles markdown code fences,
  inline backticks, and plain-text fallback).
* Feeding validation errors back to an LLM for self-correction.
* Formatting Neo4j result records as Markdown, CSV, JSON, or plain text
  for insertion into the next LLM prompt.
* Building tool/function-call specifications compatible with the
  Anthropic and OpenAI APIs.
* Generating labelled few-shot (description, cypher) example pairs from
  a :class:`~cypher_validator.CypherGenerator` instance.
"""
from __future__ import annotations

import csv
import io
import json
import re
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from cypher_validator import CypherGenerator, CypherValidator, Schema, ValidationResult

# ---------------------------------------------------------------------------
# Cypher extraction
# ---------------------------------------------------------------------------

# Keywords that unambiguously identify a Cypher statement
_CYPHER_KEYWORDS = frozenset(
    ["MATCH", "CREATE", "MERGE", "RETURN", "WITH", "WHERE",
     "DELETE", "SET", "REMOVE", "CALL", "UNWIND", "OPTIONAL"]
)

# Precompiled patterns — extract_cypher_from_text runs once per LLM repair
# iteration, so the recompile cost is non-trivial on long ingestion runs.
_RE_FENCED_TAGGED = re.compile(
    r"```(?:cypher|sql|sparql)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE
)
_RE_FENCED_ANY = re.compile(r"```\w*\s*\n(.*?)```", re.DOTALL)
_RE_BACKTICK = re.compile(r"`([^`\n]+)`")
_RE_CYPHER_LINE = re.compile(
    r"^\s*(MATCH|CREATE|MERGE|WITH|CALL|UNWIND|OPTIONAL)\b", re.IGNORECASE
)


def _looks_like_cypher(text: str) -> bool:
    upper = text.upper()
    return any(kw in upper for kw in _CYPHER_KEYWORDS)


def extract_cypher_from_text(text: str) -> str:
    """Extract a Cypher query from LLM-generated text.

    Handles these common LLM output patterns (in order of preference):

    1. Fenced code block — ` ```cypher … ``` `
    2. Fenced code block with any tag — ` ```sql … ``` ` or plain ` ``` … ``` `
    3. Inline backtick — `` `MATCH … ` ``
    4. Line-anchored Cypher — the first line starting with a Cypher keyword
    5. Fallback — return the whole text stripped

    Parameters
    ----------
    text:
        Raw LLM output string.

    Returns
    -------
    str
        The extracted Cypher query, or the original text (stripped) if no
        recognisable pattern is found.

    Examples
    --------
    ::

        output = \"\"\"
        Sure! Here's the query:

        ```cypher
        MATCH (p:Person {name: $name})-[:WORKS_FOR]->(c:Company)
        RETURN p, c
        ```
        \"\"\"
        cypher = extract_cypher_from_text(output)
        # "MATCH (p:Person {name: $name})-[:WORKS_FOR]->(c:Company)\\nRETURN p, c"
    """
    if not text or not text.strip():
        return ""

    # 1. Fenced block: ```cypher or ```sql or ```
    m = _RE_FENCED_TAGGED.search(text)
    if m:
        return m.group(1).strip()

    # 2. Any fenced block that looks like Cypher
    m = _RE_FENCED_ANY.search(text)
    if m:
        candidate = m.group(1).strip()
        if _looks_like_cypher(candidate):
            return candidate

    # 3. Inline backtick span
    m = _RE_BACKTICK.search(text)
    if m:
        candidate = m.group(1).strip()
        if _looks_like_cypher(candidate):
            return candidate

    # 4. Line-anchored Cypher: collect consecutive non-blank lines starting
    #    from the first line that begins with a Cypher keyword.
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if _RE_CYPHER_LINE.match(line):
            start = i
            break

    if start is not None:
        collected: List[str] = []
        for line in lines[start:]:
            if line.strip() == "" and collected:
                break
            collected.append(line)
        return "\n".join(collected).strip()

    # 5. Fallback
    return text.strip()


# ---------------------------------------------------------------------------
# Record formatting
# ---------------------------------------------------------------------------

def format_records(
    records: List[Dict[str, Any]],
    format: str = "markdown",  # noqa: A002
) -> str:
    """Format Neo4j result records as a string suitable for LLM context.

    Parameters
    ----------
    records:
        List of record dicts as returned by
        :meth:`~cypher_validator.Neo4jDatabase.execute`.
    format:
        Output format — one of ``"markdown"``, ``"csv"``, ``"json"``,
        or ``"text"``.

    Returns
    -------
    str
        Formatted string, or ``""`` when *records* is empty.

    Raises
    ------
    ValueError
        For an unrecognised *format*.

    Examples
    --------
    ::

        records = [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]

        print(format_records(records))
        # | name  | age |
        # |-------|-----|
        # | Alice |  30 |
        # | Bob   |  25 |

        print(format_records(records, format="csv"))
        # name,age
        # Alice,30
        # Bob,25
    """
    if not records:
        return ""

    fmt = format.lower()
    if fmt not in ("markdown", "csv", "json", "text"):
        raise ValueError(
            f"Unknown format {format!r}. Use 'markdown', 'csv', 'json', or 'text'."
        )

    if fmt == "json":
        return json.dumps(records, indent=2, default=str)

    if fmt == "csv":
        buf = io.StringIO()
        headers = list(records[0].keys())
        writer = csv.DictWriter(buf, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for row in records:
            writer.writerow({k: str(v) for k, v in row.items()})
        return buf.getvalue().rstrip()

    if fmt == "text":
        lines: List[str] = []
        for i, record in enumerate(records, 1):
            lines.append(f"Record {i}:")
            for k, v in record.items():
                lines.append(f"  {k}: {v}")
        return "\n".join(lines)

    # markdown
    headers = list(records[0].keys())
    rows = [[str(rec.get(h, "")) for h in headers] for rec in records]
    col_widths = [
        max(len(h), max((len(r[i]) for r in rows), default=0))
        for i, h in enumerate(headers)
    ]
    sep = "|" + "|".join("-" * (w + 2) for w in col_widths) + "|"
    header_row = (
        "| "
        + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
        + " |"
    )
    data_rows = [
        "| "
        + " | ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(row))
        + " |"
        for row in rows
    ]
    return "\n".join([header_row, sep] + data_rows)


# ---------------------------------------------------------------------------
# Cypher self-repair loop
# ---------------------------------------------------------------------------

def repair_cypher(
    validator: "CypherValidator",
    query: str,
    llm_fn: Callable[[str, List[str]], str],
    max_retries: int = 3,
) -> Tuple[str, "ValidationResult"]:
    """Validate a Cypher query and use an LLM to repair it when invalid.

    The *llm_fn* is called with ``(current_query, error_list)`` and must
    return a corrected query string.  The loop runs until the query passes
    validation or *max_retries* is exhausted.

    Parameters
    ----------
    validator:
        A :class:`~cypher_validator.CypherValidator` instance.
    query:
        Initial Cypher query (possibly invalid).
    llm_fn:
        Callable that receives ``(query: str, errors: list[str])`` and
        returns a repaired query string.
    max_retries:
        Maximum number of LLM repair attempts (default: 3).

    Returns
    -------
    tuple[str, ValidationResult]
        ``(final_query, final_validation_result)`` — the result's
        ``is_valid`` tells you whether the loop converged.

    Examples
    --------
    ::

        def fix_with_llm(query: str, errors: list[str]) -> str:
            # call your LLM here
            ...

        cypher, result = repair_cypher(validator, bad_query, fix_with_llm)
        if result.is_valid:
            print("Repaired:", cypher)
        else:
            print("Could not repair after retries:", result.errors)
    """
    result = validator.validate(query)
    for _ in range(max_retries):
        if result.is_valid:
            break
        # Try auto-fix before calling the LLM
        if result.fixed_query is not None:
            query = result.fixed_query
            result = validator.validate(query)
            if result.is_valid:
                break
        query = llm_fn(query, list(result.errors))
        result = validator.validate(query)
    return query, result


# ---------------------------------------------------------------------------
# Tool / function-call specification builders
# ---------------------------------------------------------------------------

def cypher_tool_spec(
    schema: Optional["Schema"] = None,
    db_description: str = "",
    format: str = "anthropic",  # noqa: A002
) -> Dict[str, Any]:
    """Build a tool/function-call specification for Cypher execution.

    Returns a dict ready to pass to the Anthropic or OpenAI API so an LLM
    can call the tool to execute Cypher against a Neo4j database.

    Parameters
    ----------
    schema:
        Optional :class:`~cypher_validator.Schema`.  When provided, the
        inline Cypher-pattern representation is embedded in the tool
        description so the LLM knows which labels and types are available.
    db_description:
        Short description of the database (e.g. ``"knowledge graph of
        scientific papers"``).  Appended to the tool description.
    format:
        ``"anthropic"`` (default) or ``"openai"``.

    Returns
    -------
    dict
        Tool specification dict.

    Examples
    --------
    ::

        # Anthropic (tool_use)
        tool = cypher_tool_spec(schema, format="anthropic")
        response = client.messages.create(
            model="claude-opus-4-6",
            tools=[tool],
            messages=[{"role": "user", "content": "Who works for Acme Corp?"}],
        )

        # OpenAI (function calling)
        tool = cypher_tool_spec(schema, format="openai")
        response = openai.chat.completions.create(
            model="gpt-4o",
            tools=[tool],
            messages=[{"role": "user", "content": "Who works for Acme Corp?"}],
        )
    """
    schema_hint = ""
    if schema is not None:
        schema_hint = f"\n\nAvailable schema:\n{schema.to_cypher_context()}"

    db_hint = f" ({db_description})" if db_description else ""
    description = (
        f"Execute a Cypher query against the Neo4j graph database{db_hint}. "
        f"Returns a list of result records as JSON objects."
        f"{schema_hint}"
    )

    parameters_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "cypher": {
                "type": "string",
                "description": (
                    "A valid Cypher query to execute. "
                    "Use $param placeholders for dynamic values."
                ),
            },
            "parameters": {
                "type": "object",
                "description": (
                    "Optional key-value pairs for $param placeholders "
                    "in the query (e.g. {\"name\": \"Alice\"})."
                ),
                "additionalProperties": True,
            },
        },
        "required": ["cypher"],
    }

    if format.lower() == "openai":
        return {
            "type": "function",
            "function": {
                "name": "execute_cypher",
                "description": description,
                "parameters": parameters_schema,
            },
        }

    # Anthropic tool_use format (default)
    return {
        "name": "execute_cypher",
        "description": description,
        "input_schema": parameters_schema,
    }


# ---------------------------------------------------------------------------
# Few-shot example generation
# ---------------------------------------------------------------------------

_QUERY_TYPE_TEMPLATES: Dict[str, str] = {
    "match_return":       "Return all {labels}",
    "match_where_return": "Find {labels} matching a property condition",
    "create":             "Create a new {labels}",
    "merge":              "Upsert (create-or-match) a {labels}",
    "aggregation":        "Count or aggregate {labels} properties",
    "match_relationship": "Find {labels} connected via {rels}",
    "create_relationship": "Create a {rels} relationship between nodes",
    "match_set":          "Update a property on matching {labels}",
    "match_delete":       "Delete {labels} matching a condition",
    "with_chain":         "Use WITH to chain sub-queries over {labels}",
    "distinct_return":    "Return distinct values from {labels}",
    "order_by":           "Return {labels} sorted by a property",
    "unwind":             "Expand a list property of {labels}",
}


def few_shot_examples(
    generator: "CypherGenerator",
    n: int = 5,
    query_type: Optional[str] = None,
) -> List[Tuple[str, str]]:
    """Generate ``(natural_language_description, cypher)`` pairs for few-shot LLM prompting.

    The descriptions are derived from the query type and the labels/relationship
    types extracted from each generated query, so they reflect the actual schema.

    Parameters
    ----------
    generator:
        A :class:`~cypher_validator.CypherGenerator` instance (with seed for
        reproducibility).
    n:
        Number of examples to generate.
    query_type:
        Generate only this query type.  When ``None``, examples are spread
        evenly across all supported types.

    Returns
    -------
    list[tuple[str, str]]
        ``[(description, cypher), ...]``

    Examples
    --------
    ::

        gen = CypherGenerator(schema, seed=0)
        examples = few_shot_examples(gen, n=4)
        for desc, cypher in examples:
            print(f"Q: {desc}")
            print(f"A: {cypher}")
            print()
    """
    from cypher_validator import parse_query

    supported = generator.supported_types()
    if query_type is not None:
        if query_type not in supported:
            raise ValueError(
                f"Unknown query_type {query_type!r}. "
                f"Supported: {supported}"
            )
        types = [query_type] * n
    else:
        # Distribute evenly across all types, cycle if n > len(supported)
        types = [supported[i % len(supported)] for i in range(n)]

    results: List[Tuple[str, str]] = []
    for qt in types:
        cypher = generator.generate(qt)
        info = parse_query(cypher)

        # Build human-readable tokens for the description template
        labels_str = (
            " and ".join(f":{lbl}" for lbl in info.labels_used[:2])
            if info.labels_used
            else "nodes"
        )
        rels_str = (
            " and ".join(f":{rt}" for rt in info.rel_types_used[:1])
            if info.rel_types_used
            else "relationship"
        )
        template = _QUERY_TYPE_TEMPLATES.get(qt, "Query {labels}")
        description = template.format(labels=labels_str, rels=rels_str)
        results.append((description, cypher))

    return results
