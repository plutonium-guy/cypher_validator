# cypher_validator — Deep Dive (all non-test funcs/methods)

Generated via gitnexus index (4195 symbols, 8638 edges, 285 flows, 152 clusters).

**Counts:** 249 functions + 342 methods = 591 callables across 18 source files. Tests/examples excluded.

---

## RUST CORE

### `src/lib.rs` — PyO3 module
- **`_cypher_validator`** (line 15) — pymodule registering `PySchema`, `PyCypherValidator`, `PyValidationResult`, `PyValidationDiagnostic`, `PyCypherGenerator`, `PyQueryInfo`, `parse_query` to Python.

### `src/error.rs`
- **`from`** (11) — `From<std::io::Error>` / `From<...>` for `CypherError` (ParseError, GeneratorError, IoError).

### `src/diagnostics.rs` — error codes, severity, suggestion, diagnostic
- **`ErrorCode::code`** (70) — short code `"E101"`…`"W202"`.
- **`ErrorCode::name`** (100) — PascalCase name.
- **`ErrorCode::severity`** (129) — Error vs Warning (W101/W103/W104/W201/W202 = Warning, rest Error).
- **`fmt`** (142, 158) — Display for `ErrorCode` / `Severity`.
- **`ValidationDiagnostic::error`** (197) — error ctor.
- **`ValidationDiagnostic::warning`** (207) — warning ctor.
- **`with_suggestion`** (217) — attach `Suggestion` (original→replacement).
- **`with_position`** (222) — attach `(line, col)` for parse errors.

### `src/schema/mod.rs` — graph schema (HashMap-based, O(1) lookups)
- **`new`** (15) — `Schema::new(nodes, relationships)`.
- **`has_node_label`** (25) — `nodes.contains_key`.
- **`has_rel_type`** (30) — `relationships.contains_key`.
- **`node_has_property`** (37) — O(1) HashSet check on node props.
- **`rel_has_property`** (42) — O(1) HashSet check on rel props.
- **`node_labels`** (50) — sorted Vec of labels.
- **`rel_types`** (56) — sorted Vec of rel types.
- **`node_properties`** (63) — sorted property names for label.
- **`rel_properties`** (72) — sorted property names for rel.
- **`rel_src_tgt`** (80) — `(src_label, tgt_label)` for rel.

### `src/parser/mod.rs` — pest entry
- **`parse`** (12) — `&str` → `CypherQuery`, stringified error.
- **`parse_with_detail`** (28) — same but returns `ParseDetail { error_message, position: Option<(line,col)> }`.
- **`try_parse`** (64) — test helper, returns `bool` from any `Rule`.
- 12 unit tests `test_null_check_*` / `test_postfix_expr_*` / `test_where_clause_*` / `test_full_query_*` (71–155).

### `src/parser/builder.rs` — pest pair → AST (47 funcs)
Top-down recursive descent. Each builds one AST node.

| Function | Line | Builds |
|---|---|---|
| `build_query` | 6 | `CypherQuery` (root) |
| `build_statement` | 15 | `Statement::RegularQuery` or `StandaloneCall` |
| `build_regular_query` | 24 | `RegularQuery` (single + UNION list, `is_all` flag) |
| `build_single_query` | 41 | `SinglePart` vs `MultiPart` |
| `build_single_part_query` | 50 | reading/updating/return |
| `build_multi_part_query` | 65 | parts separated by WITH, plus final part |
| `build_reading_clause` | 97 | Match / Unwind / CallSubquery / Call |
| `build_match_clause` | 112 | optional flag, pattern, WHERE |
| `build_unwind_clause` | 135 | `UNWIND expr AS variable` |
| `build_call_clause` | 142 | procedure name, args, YIELD items |
| `build_updating_clause` | 179 | Create / Merge / Set / Remove / Delete / Foreach |
| `build_merge_clause` | 204 | pattern_part + ON MATCH / ON CREATE SETs |
| `build_set_clause` | 234 | property-set / label-set / var-set / var-add |
| `build_remove_clause` | 273 | label-remove / property-remove |
| `build_property_expression` | 303 | `var.a.b` chains |
| `build_with_clause` | 321 | items, ORDER BY, SKIP, LIMIT, WHERE, DISTINCT |
| `build_return_clause` | 348 | wraps `build_return_body` |
| `build_return_body` | 367 | items / DISTINCT / wildcard / ORDER/SKIP/LIMIT |
| `build_return_item` | 406 | expr + optional alias |
| `build_sort_item` | 413 | ASC/DESC flag |
| `build_pattern` | 421 | list of `PatternPart` |
| `build_pattern_part` | 429 | optional `path =` variable + element |
| `build_pattern_element` | 445 | start node + `(rel,node)` chain |
| `build_node_pattern` | 481 | variable, labels, properties |
| `build_relationship_pattern` | 501 | direction (in/out/undirected), rel types, range, properties |
| `build_range_literal` | 531 | `[*min..max]` |
| `build_properties` | 547 | map literal or `$param` |
| `build_map_literal` | 556 | `{k: v, ...}` |
| `build_expression` | 570 | top of expression precedence |
| `build_or_expr` | 592 | binary OR |
| `build_xor_expr` | 602 | binary XOR |
| `build_and_expr` | 611 | binary AND |
| `build_not_expr` | 620 | unary NOT |
| `build_comparison_expr` | 633 | `=` `<>` `<` `<=` `>` `>=` `IN` `STARTS WITH` `ENDS WITH` `CONTAINS` `=~` |
| `build_add_sub_expr` | 666 | `+` `-` |
| `build_mul_div_expr` | 690 | `*` `/` |
| `build_mod_expr` | 698 | `%` |
| `build_power_expr` | 706 | `^` |
| `build_unary_expr` | 714 | unary minus |
| `build_postfix_expr` | 728 | property access, subscript, slice, `IS NULL`/`IS NOT NULL` |
| `build_atom` | 777 | literal / var / paren / case / function / subquery / pattern comp / count star |
| `build_literal` | 802 | int/float/str/bool/null/list/map |
| `build_case_expression` | 836 | CASE with optional subject, WHEN/THEN, ELSE |
| `parse_filter_expression` | 871 | helper for list comp / quantifier WHERE |
| `build_list_comprehension` | 891 | `[var IN source WHERE f \| proj]` |
| `build_quantifier_expression` | 911 | ALL/ANY/NONE/SINGLE |
| `build_exists_subquery` | 936 | `EXISTS { pattern }` or `EXISTS { query }` |
| `build_pattern_comprehension` | 945 | `[pattern WHERE f \| proj]` |
| `build_count_subquery` | 979 | `COUNT { query }` |
| `build_collect_subquery` | 985 | `COLLECT { query }` |
| `build_shortest_path_expr` | 993 | `shortestPath(...)` / `allShortestPaths(...)` |
| `build_foreach_clause` | 1019 | `FOREACH (var IN list \| clauses)` |
| `build_reduce_expression` | 1044 | `reduce(acc=init, x IN list \| expr)` |
| `build_function_invocation` | 1083 | function name + args + DISTINCT |

### `src/validator/mod.rs` — public validator façade
- **`compute_fixed_query`** (26) — apply all `Suggestion` replacements (longest-first dedup) to produce `fixed_query`. Returns `None` if any error lacks a suggestion.
- **`CypherValidator::new`** (68) — store schema.
- **`CypherValidator::validate`** (72) — parse → fall back to `E101ParseError` diag, else run `SemanticValidator`. Returns `ValidationResult { is_valid, errors, syntax_errors, semantic_errors, warnings, diagnostics, fixed_query }`.

### `src/validator/semantic.rs` — semantic validator (45 funcs)
**Levenshtein "did you mean":**
- `levenshtein_capped` (16) — O(n) rolling-array distance, early-exit when row min > cap.
- `closest_match` (58) — best candidate under `max_dist`.
- `did_you_mean` (74) — formats `", did you mean :X?"` hint.
- `label_suggestion` (82) — builds `Suggestion { original, replacement, description }` for label.
- `property_suggestion` (91) — same for property.

**Built-in fn registry:**
- `BUILTIN_FUNCTIONS` (111) — 80+ entries (aggregates, string, numeric, list/graph, temporal, spatial). Each `(name, min_args, max_args, is_aggregate)`.
- `lookup_builtin` (193) — case-insensitive lookup.

**`SemanticValidator` struct fields:** `schema`, `errors`, `warnings`, `diagnostics`, `env: TypeEnv` (var→labels), cached `known_labels` / `known_rel_types`.

| Method | Line | Role |
|---|---|---|
| `new` | 211 | precompute `known_labels`/`known_rel_types` |
| `push_error` | 230 | append to errors + diagnostics |
| `push_warning` | 240 | append to warnings + diagnostics |
| `node_property_candidates` | 249 | candidate list for a label |
| `rel_property_candidates` | 253 | candidate list for a rel type |
| `validate_query` | 261 | entry; RegularQuery vs StandaloneCall |
| `validate_regular_query` | 268 | single + UNION branches (env reset per branch) |
| `validate_single_query` | 279 | SinglePart vs MultiPart dispatch |
| `validate_single_part` | 286 | two-pass: collect bindings → validate clauses → return |
| `validate_multi_part` | 306 | iterate parts (collect→validate→WITH), then final part |
| `process_with_clause` | 337 | validate items, reset env to projected aliases, validate ORDER/SKIP/LIMIT/WHERE |
| `collect_reading_bindings` | 377 | from MATCH pattern / UNWIND var / CALL YIELD |
| `collect_updating_bindings` | 396 | from CREATE / MERGE pattern |
| `collect_pattern_bindings` | 408 | path var + start + chain nodes/rels |
| `collect_node_bindings` | 422 | insert var→labels (merge with existing) |
| `collect_rel_bindings` | 437 | insert var→rel-types |
| `validate_reading_clause` | 454 | MATCH(pattern + WHERE no-aggregate + Cartesian + complexity), UNWIND expr, CALL subquery |
| `pattern_part_vars` | 474 | helper — vars in a `PatternPart` (path + nodes + rels) |
| `check_cartesian_product` | 500 | W101 — pattern parts disconnected by shared vars |
| `contains_aggregate` | 530 | recurse expr to detect aggregate fn or `COUNT(*)` |
| `validate_expr_no_aggregate` | 568 | E602 if aggregate in MATCH WHERE / SET / DELETE |
| `validate_pagination_expr` | 585 | E611–E614 for SKIP/LIMIT type (string/bool/null/float) |
| `check_match_complexity` | 612 | W201 unlabeled full scan, W202 unbounded var-length rel |
| `validate_updating_clause` | 645 | CREATE/MERGE pattern, SET items, REMOVE items, DELETE exprs, FOREACH (with locally-scoped var) |
| `validate_return_clause` | 674 | items, alias uniqueness, ORDER/SKIP/LIMIT |
| `check_alias_uniqueness` | 689 | E502 duplicate projection |
| `validate_pattern` | 709 | nodes + rels-with-endpoints chain |
| `validate_node_pattern` | 722 | E201 unknown label + E301 unknown prop (with suggestions) |
| `validate_rel_pattern_with_endpoints` | 749 | E211 unknown rel type, E302 unknown rel prop, E401 wrong endpoint label per direction |
| `check_endpoint_label` | 806 | E401 — open-world if labels empty; matches one of node's labels |
| `validate_set_item` | 836 | PropertySet/VariableSet/VariableAdd/LabelSet (E202 unknown label in SET) |
| `validate_remove_item` | 857 | LabelRemove (E203), PropertyRemove → `validate_property_access` |
| `validate_property_access` | 875 | E303 (node) / E304 (rel) unknown prop on var |
| `validate_expr` | 909 | giant match: Variable (E501 unbound), Property, binops, unops, FunctionCall (E603 arity, E601 numeric agg with string, W103 unknown fn, W104 DISTINCT non-agg), List/Map, Subscript/Slice, Case, ListComprehension (locally-scoped), All/Any/None/Single (quantifiers, locally-scoped), ShortestPath, Reduce (acc+var locally-scoped), Exists, PatternComprehension, CountSubquery / CollectSubquery, leaves |

### `src/generator/mod.rs` — random Cypher generator (24 funcs)
- `CypherGenerator::new` (19) — precompute labels/rel_types/props_by_label vecs; seeded `SmallRng` or OS rng.
- `supported_types` (41) — 13 query types: match_return, match_where_return, create, merge, aggregation, match_relationship, create_relationship, match_set, match_delete, with_chain, distinct_return, order_by, unwind.
- `generate` (59) — dispatch by `query_type` string.
- `pick_node_label` / `pick_rel_type` / `pick_node_prop` (80–93) — random choice.
- `gen_scalar_value` (95) — string/int/bool/`$param`.
- `gen_string_value` (113) — random string literal.
- `gen_property_map` (123) — `{prop: val, …}`.
- `maybe_limit` (142) — optional LIMIT.
- `gen_match_return` / `gen_match_where_return` / `gen_create` / `gen_merge` / `gen_aggregation` / `gen_match_relationship` / `gen_create_relationship` / `gen_match_set` / `gen_match_delete` / `gen_with_chain` / `gen_distinct_return` / `gen_order_by` / `gen_unwind` (153–289) — one per query type.

### `src/bindings/py_*.rs` — PyO3 wrappers

**`py_schema.rs` (16 funcs)** — `PySchema::new`, `from_dict`, `from_json`, `node_labels`, `rel_types`, `has_node_label`, `has_rel_type`, `node_properties`, `rel_properties`, `rel_endpoints`, `to_dict`, `to_json`, `merge`, `to_prompt`, `to_markdown`, `to_cypher_context`, `__repr__`.

**`py_validator.rs` (15 funcs)** — `PyValidationDiagnostic` (`to_dict`, `__repr__`, `from_rust`), `PyValidationResult` (`from`, `diagnostics`, `__bool__`, `__len__`, `__repr__`, `to_dict`, `to_json`), `PyCypherValidator` (`new`, `schema`, `validate`, `validate_batch`, `__repr__`).

**`py_generator.rs` (5 funcs)** — `new`, `generate`, `generate_batch`, `supported_types`, `__repr__`.

**`py_parser.rs` (10 funcs)** — `PyQueryInfo` (`__bool__`, `__repr__`), module fn `parse_query` (48), then walkers `collect_info` / `collect_statement` / `collect_regular_query` / `collect_single_query` / `collect_reading` / `collect_updating` / `collect_pattern` / `collect_node_props` / `collect_expr` (74–230) — extract labels/rel-types/properties/params from AST.

---

## PYTHON LAYER

### `python/cypher_validator/__init__.py`
- **`_schema_from_neo4j`** (75) — `Schema.from_neo4j(uri, user, pwd, db, sample_limit)` → introspects via `Neo4jDatabase.introspect_schema`. Bound as staticmethod on the Rust `Schema` class.

### `llm_utils.py` (6 funcs)
- **`_looks_like_cypher`** (37) — uppercase substring contains `MATCH`/`CREATE`/`MERGE`/…
- **`extract_cypher_from_text`** (42) — 4-tier extract: ` ```cypher ``` ` → any fenced → backtick → keyword line → raw.
- **`format_records`** (134) — records → markdown/csv/json/text.
- **`repair_cypher`** (231) — validate-loop: try `fixed_query` auto-fix, else `llm_fn(query, errors)` up to `max_retries`. Returns `(final_query, ValidationResult)`.
- **`cypher_tool_spec`** (294) — Anthropic or OpenAI tool spec for `execute_cypher`, embeds `schema.to_cypher_context()`.
- **`few_shot_examples`** (413) — generate (description, cypher) pairs via `CypherGenerator`.

### `llm_pipeline.py` (8 funcs + 36 methods)

**`TokenBucketRateLimiter`** — async TPM quota.
- `__init__` (107), `acquire` (113) — wait until N tokens, async lock.
- `_refill` (125) — accumulate by elapsed.
- `estimate_tokens` (136) — `len/4` heuristic.

**`LLMNLToCypher`** — NL → Cypher main pipeline (sync + async).
- `__init__` (277) — schema, db, `llm_fn`/`async_llm_fn`, max repair retries, system prompt override, rate limiter.
- Builders: `from_openai` (328), `from_deepseek` (351), `from_anthropic` (376), `from_langchain` (406), `from_env` (451).
- Context mgmt: `close`/`__enter__`/`__exit__`/`__aenter__`/`__aexit__` (547–570).
- `_resolve_schema` (575) — user > cached discovered > DB introspect.
- `reset_discovered_schema` (596) — clear cache.
- `_build_prompt` (608) — schema-known vs schema-unknown system prompt + mode instruction.
- `_parse_inferred_schema` (638) — regex `{"inferred_schema": ...}` JSON + `cypher` block.
- `_schema_dict_to_schema` (679) — dict → `Schema` object.
- `_merge_inferred_schema` (706) — merge into cached.
- `_validate_and_repair` (718) — auto-fix → `llm_fn(repair_prompt)` loop.
- `__call__` (765) — wraps `ingest_with_context`.
- `ingest_with_context` (795) — build prompt, call LLM, parse, validate+repair, optionally execute.
- `_chunk_text` (867) — sentence-boundary chunking with overlap.
- `_build_provenance_cypher` (914) — derives `Chunk` MERGE + `MENTIONED_IN` from parsed labels.
- `_finish_chunk` (954) — provenance + execute → `ChunkResult`.
- `ingest_texts` (1016) — two-phase: schema-stabilize sample → MERGE remainder.
- `ingest_document` (1187) — chunk + `ingest_texts`.
- `_get_async_llm_fn` (1227) — wrap sync via `asyncio.to_thread` (helper `_wrapped` at 1238).
- `_async_llm_call` (1243) — rate-limit + invoke.
- `_avalidate_and_repair` (1255) — async version.
- `acall` (1296), `aingest_with_context` (1308), `aingest_texts` (1362), `aingest_document` (1519) — async siblings.
- LLM backend builders (module fns): `_build_openai_fn` (1552), `call_llm` (1580), `_build_anthropic_fn` (1596), `_split_prompt_to_messages` (1650), `_build_langchain_fn` (1682), `_build_async_openai_fn` (1715), `_build_async_anthropic_fn` (1750), `_process_text` (1455).

**Dataclasses:** `ChunkResult` (63), `IngestionResult` (80).

### `rag.py` — `GraphRAGPipeline` (6 methods)
- `__init__` (82) — schema, db, `llm_fn`, max retries, result format, optional system-prompt overrides; constructs `CypherValidator`.
- `_default_cypher_system` (109) — system prompt with schema context.
- `_default_answer_system` (124) — answer-synthesis prompt.
- `query` (136) — returns answer.
- `query_with_context` (151) — full 5-step: cypher gen → validate+repair → execute → format → answer.
- `__repr__` (244).

### `gliner2_integration.py` (2 funcs + ~35 methods)

**Helpers:** `_to_cypher_rel_type` (56) upper-snake, `_inline_params` (61) longest-key-first `$param` substitution.

**`Neo4jDatabase`** (93–392) — Neo4j driver wrapper.
- `__init__` (133), `execute` (153), `introspect_schema` (178) — tries `db.schema.nodeTypeProperties` / `relTypeProperties` first, falls back to sampling.
- `execute_and_format` (309) — execute + `format_records`.
- `execute_many` (351) — list of (cypher, params) in single session.
- `close` / `__enter__` / `__exit__` / `__repr__`.

**`RelationToCypherConverter`** (397–) — relations dict → Cypher.
- `__init__` (426), `_get_endpoints` (438), `_clean_pairs` (446).
- `to_match_query` (456), `to_merge_query` (531), `to_create_query` (562), `_build_clause` (591).
- `convert` (646) — dispatch by mode (match/merge/create).
- `to_db_aware_query` (692) — schema-aware variant.

**`EntityNERExtractor`** (903–) — generic NER.
- `__init__`, `from_spacy` (916), `from_transformers` (955), `extract` (1003), `_extract_spacy` (1024), `_extract_transformers` (1034).

**`GLiNER2RelationExtractor`** (1079–) — GLiNER2 model.
- `__init__`, `from_pretrained` (1094), `extract_relations` (1131).

**`NLToCypher`** (1275–) — end-to-end pipeline.
- `__init__` (1275), `from_env` (1310), `from_pretrained` (1368), `_collect_entity_status` (1420), `__call__` (1549), `extract_and_convert` (1638).

### `models.py` (12 funcs + ~270 methods) — Pydantic Cypher ORM

**Module helpers:** `_all_node_models` (60), `_all_rel_models` (64), `_to_upper_snake` (276), `_python_type_to_json_type` (1565), `node` (1584), `relationship` (1614), `_validate_direction` (1656), `_match_with_ref` (2724), `_return_with_ref` (2737), `schema_to_pipeline_kwargs` (3132).

**`_NodeMeta` / `_RelMeta` metaclasses** — auto-register subclasses into `_NODE_REGISTRY` / `_REL_REGISTRY` by `__label__` / `__rel_type__`.

**`NodeModel`** (98–) — `label`, `labels`, `labels_cypher`, `property_names`, `property_types`, `required_properties`, `optional_properties`, `from_record`, `from_records`, `to_property_map`, `to_create_cypher`, `to_merge_cypher`, `match_cypher`, `to_schema_description`.

**`RelationshipModel`** (259–) — `rel_type`, `source_label`, `target_label`, `property_names`, `property_types`, `required_properties`, `from_record`, `to_property_map`, `to_create_cypher`, `to_schema_description`.

**`Op`/`Cond`/`CondGroup`/`RawExpr`** (435–520) — comparison ops, fluent `__and__`/`__or__` for WHERE.

**`Query`** (541–966) — fluent builder.
- ctor `__init__` + `_next_param` / `_node_pattern` / `_rel_pattern` helpers.
- Reads: `match`, `optional_match`, `match_path`, `where`, `and_where`, `or_where`.
- Writes: `create`, `merge`, `create_path`, `set`, `set_props`, `on_create_set`, `on_match_set`, `remove`, `delete`.
- Composition: `with_`, `return_`, `order_by`, `skip`, `limit`, `unwind`, `call_subquery`, `foreach`, `union`, `raw`.
- Params: `param`, `params`.
- Build: `build`, `build_cypher`, `__str__`, `__repr__`, `to_dict`, `to_json`, `from_dict`, `from_json`, `validate`, `explain`.

**`GraphSchema`** (994–) — `from_models`, `from_registry`, `to_dict`, `to_cypher_schema` (→ Rust `Schema`), `from_dict`, `from_neo4j_db`, `to_json`, `to_prompt`, `to_markdown`, `merge`, `get_constraints`, `get_indexes`.

**`AgentTools`** (1228–) — `query_tool_spec`, `create_node_tool_spec`, `create_relationship_tool_spec`, `all_tool_specs`, `handle_tool_call`, `schema_context_for_prompt`.

**`QueryPlan`/`QueryStep`/`QueryResult`** (1462–1550) — multi-step plan execution: `validate_all`, `to_execution_order`, `explain`, `success`, `count`, `to_markdown`, `to_json`, `to_natural_language`.

**`Traversal`** (1670–) — `neighbors`, `shortest_path`, `subgraph`, `degree`, `common_neighbors`, `path_exists`.

**`BulkOps`** (1858–) — `bulk_create_nodes`, `bulk_merge_nodes`, `bulk_create_relationships`, `bulk_merge_relationships`, `bulk_delete_nodes`.

**`SchemaDDL`** (2002–) — `uniqueness_constraints`, `existence_constraints`, `property_indexes`, `composite_indexes`, `fulltext_index`, `custom_constraints`, `custom_indexes`, `generate_all`, `drop_all`.

**`GraphSession`** (2120–) — sync Neo4j session wrapper: `execute`, `execute_query`, `query`, `create`, `merge`, `delete`, `bulk_create`, `bulk_merge`, `create_relationship`, `neighbors`, `shortest_path`, `apply_ddl`.

**`ExtendedAgentTools`** (2263–) — `search_nodes_tool_spec`, `find_neighbors_tool_spec`, `find_path_tool_spec`, `get_schema_tool_spec`, `bulk_create_tool_spec`, `all_tool_specs`, `handle_tool_call`.

**`PropExpr`** (2586–) — fluent property comparators: `ref`, `__eq__`/`__ne__`/`__lt__`/`__le__`/`__gt__`/`__ge__`, `contains`, `starts_with`, `ends_with`, `in_`, `is_null`, `is_not_null`, `regex`.

**`NodeRef`/`RelRef`** (2658–2715) — typed `__getattr__` returning `PropExpr` (`p.name == "Alice"` → `Cond("p.name", "=", $param)`).

**`QueryHistory`** (2784–) — `add`, `add_from_result`, `entries`, `last`, `clear`, `to_context`, `to_list`, `successful_queries`, `failed_queries`, `find_similar`.

**`SchemaDiff`** (2885–) — `_compute`, `has_changes`, `summary`, `migration_ddl`, `to_dict`.

**`AsyncGraphSession`** (3032–3130) — async siblings: `execute`, `execute_query`, `query`, `create`, `merge`, `bulk_create`, `bulk_merge`, `neighbors`, `__aenter__`, `__aexit__`, `history`.

**`CypherFn`** (3165–3325) — aggregates & functions: `count`, `count_distinct`, `sum`, `avg`, `min`, `max`, `collect`, `collect_distinct`, `coalesce`, `head`, `last`, `size`, `length`, `type`, `labels`, `id`, `element_id`, `to_lower`, `to_upper`, `trim`, `replace`, `substring`, `abs`, `ceil`, `floor`, `round`, `timestamp`, `date`, `datetime`, `as_`.

**`PathBuilder`** (3357–) — `_next_param`, `_node_str`, `_rel_str`, `rel`, `to`, `build`, `params`, `__str__`, `__repr__`, `to_query`.

**`Repository[T]`** (3502–) — `_execute`, `find_all`, `find_by`, `find_one`, `exists`, `count`, `create`, `create_many`, `merge`, `merge_many`, `update`, `delete`, `delete_all`, `query`.

### `scripts/train_pharma_ner.py` (11 funcs)
GLiNER2 training pipeline: `_parse_device` (122), `_device_env` (143), `_gpu_id_args` (168), `_detect_available_devices` (178), `_rebuild_text` (196), `bigbio_to_docs` (215), `prepare` (253), `config` (446), `train` (464), `evaluate` (501), `main` (542).

---

## Top execution flows

Pick deeper trace via `gitnexus://repo/cypher_validator/process/<id>`:
- `Build_match_clause → Build_or_expr` / `Build_xor_expr` (9 steps each)
- `Parse_query → SinglePartQuery` (8 steps) — full parse path
- `Build_pattern → Build_and/or/xor_expr` (8 steps)
- `Parse_with_detail → ReturnClause / WithClause` (8 steps)
- `Validate_single_part → Collect_rel_bindings` (4 steps)
- `_process_text → _validate_and_repair / _looks_like_cypher / estimate_tokens / _get_async_llm_fn` (4 steps each)
