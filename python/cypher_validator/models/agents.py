"""AgentTools, ExtendedAgentTools — AI agent tool specifications."""

from __future__ import annotations

from typing import Any, Type

from cypher_validator.models.orm import NodeModel, _python_type_to_json_type
from cypher_validator.models.query import Query
from cypher_validator.models.schema import GraphSchema
from cypher_validator.models.session import BulkOps, Traversal


# ---------------------------------------------------------------------------
# AI Agent Tools
# ---------------------------------------------------------------------------


class AgentTools:
    """Generate AI-agent-friendly tool specs and helpers.

    Produces OpenAI/Anthropic function-calling tool definitions from
    your Pydantic graph schema, enabling agents to build validated
    Cypher queries via structured function calls.
    """

    def __init__(self, schema: GraphSchema) -> None:
        self.schema = schema
        self._label_map = {m.label(): m for m in schema.node_models}
        self._rel_type_map = {m.rel_type(): m for m in schema.rel_models}

    def query_tool_spec(self, format: str = "openai") -> dict[str, Any]:
        """Tool spec for generating Cypher queries.

        Args:
            format: "openai" or "anthropic"

        Returns:
            Tool definition dict ready for function-calling APIs.
        """
        schema_text = self.schema.to_prompt()
        properties: dict[str, Any] = {
            "query_type": {
                "type": "string",
                "enum": ["match", "create", "merge", "delete", "update"],
                "description": "Type of Cypher operation",
            },
            "cypher": {
                "type": "string",
                "description": f"Valid Cypher query. Schema:\n{schema_text}",
            },
            "parameters": {
                "type": "object",
                "description": "Query parameters as key-value pairs. Use $param_name in Cypher.",
                "additionalProperties": True,
            },
            "explanation": {
                "type": "string",
                "description": "Brief natural language explanation of what the query does",
            },
        }
        tool_def = {
            "type": "function",
            "function": {
                "name": "execute_cypher",
                "description": (
                    "Execute a Cypher query against the graph database. "
                    "Always use parameterized queries ($param) for values."
                ),
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": ["query_type", "cypher"],
                },
            },
        }
        if format == "anthropic":
            return {
                "name": "execute_cypher",
                "description": tool_def["function"]["description"],
                "input_schema": tool_def["function"]["parameters"],
            }
        return tool_def

    def create_node_tool_spec(self, format: str = "openai") -> dict[str, Any]:
        """Tool spec for creating nodes with proper validation."""
        node_schemas: dict[str, Any] = {}
        for m in self.schema.node_models:
            props: dict[str, Any] = {}
            for pname, ptype in m.property_types().items():
                json_type = _python_type_to_json_type(ptype)
                props[pname] = {"type": json_type}
            node_schemas[m.label()] = {
                "type": "object",
                "properties": props,
                "required": m.required_properties(),
            }

        properties = {
            "label": {
                "type": "string",
                "enum": [m.label() for m in self.schema.node_models],
                "description": "Node label",
            },
            "properties": {
                "type": "object",
                "description": "Node properties",
                "additionalProperties": True,
            },
        }
        tool_def = {
            "type": "function",
            "function": {
                "name": "create_node",
                "description": (
                    "Create a node in the graph database. "
                    f"Available labels: {', '.join(m.label() for m in self.schema.node_models)}"
                ),
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": ["label", "properties"],
                },
            },
        }
        if format == "anthropic":
            return {
                "name": "create_node",
                "description": tool_def["function"]["description"],
                "input_schema": tool_def["function"]["parameters"],
            }
        return tool_def

    def create_relationship_tool_spec(self, format: str = "openai") -> dict[str, Any]:
        """Tool spec for creating relationships."""
        rel_info = []
        for m in self.schema.rel_models:
            rel_info.append(
                f"(:{m.source_label()})-[:{m.rel_type()}]->(:{m.target_label()})"
            )

        properties = {
            "rel_type": {
                "type": "string",
                "enum": [m.rel_type() for m in self.schema.rel_models],
                "description": "Relationship type",
            },
            "source_match": {
                "type": "object",
                "description": "Properties to match the source node",
                "additionalProperties": True,
            },
            "target_match": {
                "type": "object",
                "description": "Properties to match the target node",
                "additionalProperties": True,
            },
            "properties": {
                "type": "object",
                "description": "Relationship properties",
                "additionalProperties": True,
            },
        }
        tool_def = {
            "type": "function",
            "function": {
                "name": "create_relationship",
                "description": (
                    "Create a relationship between nodes. "
                    f"Available patterns: {', '.join(rel_info)}"
                ),
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": ["rel_type", "source_match", "target_match"],
                },
            },
        }
        if format == "anthropic":
            return {
                "name": "create_relationship",
                "description": tool_def["function"]["description"],
                "input_schema": tool_def["function"]["parameters"],
            }
        return tool_def

    def all_tool_specs(self, format: str = "openai") -> list[dict[str, Any]]:
        """All tool specs as a list."""
        return [
            self.query_tool_spec(format),
            self.create_node_tool_spec(format),
            self.create_relationship_tool_spec(format),
        ]

    def handle_tool_call(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> tuple[str, dict[str, Any]] | None:
        """Convert a tool call from an AI agent into a (cypher, params) tuple.

        Returns None if tool_name is not recognized.
        """
        if tool_name == "execute_cypher":
            return arguments["cypher"], arguments.get("parameters", {})
        elif tool_name == "create_node":
            label = arguments["label"]
            props = arguments.get("properties", {})
            m = self._label_map.get(label)
            if m:
                instance = m(**props)
                return instance.to_create_cypher()
            # Fallback: raw create
            params = {f"n_{k}": v for k, v in props.items()}
            prop_str = ", ".join(f"{k}: $n_{k}" for k in props)
            return f"CREATE (n:{label} {{{prop_str}}}) RETURN n", params
        elif tool_name == "create_relationship":
            rel_type_str = arguments["rel_type"]
            src_match = arguments.get("source_match", {})
            tgt_match = arguments.get("target_match", {})
            rel_props = arguments.get("properties", {})
            m = self._rel_type_map.get(rel_type_str)
            if m:
                instance = m(**rel_props)
                return instance.to_create_cypher(
                    src_match=src_match, tgt_match=tgt_match
                )
            return None
        return None

    def schema_context_for_prompt(self) -> str:
        """Complete schema context string suitable for LLM system prompts."""
        return (
            "You have access to a Neo4j graph database with the following schema.\n"
            "Always use parameterized queries ($param) for values to prevent injection.\n\n"
            + self.schema.to_prompt()
            + "\n\nAvailable tools: execute_cypher, create_node, create_relationship\n"
        )


# ---------------------------------------------------------------------------
# Extended AgentTools — additional tool specs
# ---------------------------------------------------------------------------


class ExtendedAgentTools(AgentTools):
    """Extended agent tools with search, graph traversal, and schema info.

    Builds on AgentTools with more specialized tool specs that let AI
    agents perform complex graph operations through structured function calls.
    """

    def search_nodes_tool_spec(self, format: str = "openai") -> dict[str, Any]:
        """Tool spec for searching nodes by property values."""
        properties = {
            "label": {
                "type": "string",
                "enum": [m.label() for m in self.schema.node_models],
                "description": "Node label to search",
            },
            "filters": {
                "type": "object",
                "description": "Property-value pairs to filter on",
                "additionalProperties": True,
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results (default: 25)",
                "default": 25,
            },
            "order_by": {
                "type": "string",
                "description": "Property to sort by, optionally with DESC suffix",
            },
        }
        tool_def = {
            "type": "function",
            "function": {
                "name": "search_nodes",
                "description": "Search for nodes by label and property filters",
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": ["label"],
                },
            },
        }
        if format == "anthropic":
            return {
                "name": "search_nodes",
                "description": tool_def["function"]["description"],
                "input_schema": tool_def["function"]["parameters"],
            }
        return tool_def

    def find_neighbors_tool_spec(self, format: str = "openai") -> dict[str, Any]:
        """Tool spec for finding neighbor nodes."""
        rel_types = [m.rel_type() for m in self.schema.rel_models]
        properties = {
            "label": {
                "type": "string",
                "enum": [m.label() for m in self.schema.node_models],
                "description": "Label of the source node",
            },
            "match_properties": {
                "type": "object",
                "description": "Properties to identify the source node",
                "additionalProperties": True,
            },
            "relationship_type": {
                "type": "string",
                "enum": rel_types,
                "description": "Filter by relationship type (optional)",
            },
            "direction": {
                "type": "string",
                "enum": ["in", "out", "both"],
                "description": "Direction of relationships (default: both)",
                "default": "both",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of neighbors to return",
                "default": 25,
            },
        }
        tool_def = {
            "type": "function",
            "function": {
                "name": "find_neighbors",
                "description": "Find nodes connected to a given node via relationships",
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": ["label", "match_properties"],
                },
            },
        }
        if format == "anthropic":
            return {
                "name": "find_neighbors",
                "description": tool_def["function"]["description"],
                "input_schema": tool_def["function"]["parameters"],
            }
        return tool_def

    def find_path_tool_spec(self, format: str = "openai") -> dict[str, Any]:
        """Tool spec for finding paths between nodes."""
        properties = {
            "source_label": {
                "type": "string",
                "enum": [m.label() for m in self.schema.node_models],
            },
            "source_properties": {
                "type": "object",
                "additionalProperties": True,
            },
            "target_label": {
                "type": "string",
                "enum": [m.label() for m in self.schema.node_models],
            },
            "target_properties": {
                "type": "object",
                "additionalProperties": True,
            },
            "max_depth": {
                "type": "integer",
                "description": "Maximum path length (default: 5)",
                "default": 5,
            },
        }
        tool_def = {
            "type": "function",
            "function": {
                "name": "find_path",
                "description": "Find the shortest path between two nodes in the graph",
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": [
                        "source_label", "source_properties",
                        "target_label", "target_properties",
                    ],
                },
            },
        }
        if format == "anthropic":
            return {
                "name": "find_path",
                "description": tool_def["function"]["description"],
                "input_schema": tool_def["function"]["parameters"],
            }
        return tool_def

    def get_schema_tool_spec(self, format: str = "openai") -> dict[str, Any]:
        """Tool spec for retrieving schema information."""
        tool_def = {
            "type": "function",
            "function": {
                "name": "get_graph_schema",
                "description": "Get the schema of the graph database (node types, relationship types, properties)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "format": {
                            "type": "string",
                            "enum": ["text", "markdown", "json"],
                            "description": "Output format (default: text)",
                            "default": "text",
                        },
                    },
                },
            },
        }
        if format == "anthropic":
            return {
                "name": "get_graph_schema",
                "description": tool_def["function"]["description"],
                "input_schema": tool_def["function"]["parameters"],
            }
        return tool_def

    def bulk_create_tool_spec(self, format: str = "openai") -> dict[str, Any]:
        """Tool spec for bulk node creation."""
        properties = {
            "label": {
                "type": "string",
                "enum": [m.label() for m in self.schema.node_models],
                "description": "Node label to create",
            },
            "items": {
                "type": "array",
                "items": {"type": "object", "additionalProperties": True},
                "description": "List of property dicts, one per node",
            },
        }
        tool_def = {
            "type": "function",
            "function": {
                "name": "bulk_create_nodes",
                "description": "Create multiple nodes at once efficiently",
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": ["label", "items"],
                },
            },
        }
        if format == "anthropic":
            return {
                "name": "bulk_create_nodes",
                "description": tool_def["function"]["description"],
                "input_schema": tool_def["function"]["parameters"],
            }
        return tool_def

    def all_tool_specs(self, format: str = "openai") -> list[dict[str, Any]]:
        """All tool specs including extended ones."""
        base = super().all_tool_specs(format)
        base.extend([
            self.search_nodes_tool_spec(format),
            self.find_neighbors_tool_spec(format),
            self.find_path_tool_spec(format),
            self.get_schema_tool_spec(format),
            self.bulk_create_tool_spec(format),
        ])
        return base

    def handle_tool_call(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> tuple[str, dict[str, Any]] | None:
        """Handle all tool calls including extended ones."""
        # Check base tools first
        result = super().handle_tool_call(tool_name, arguments)
        if result is not None:
            return result

        if tool_name == "search_nodes":
            label = arguments["label"]
            filters = arguments.get("filters", {})
            limit = arguments.get("limit", 25)
            order_by = arguments.get("order_by")
            m = self._label_map.get(label)
            if not m:
                return None
            q = Query().match(m, "n")
            params: dict[str, Any] = {}
            if filters:
                where_parts = []
                for k, v in filters.items():
                    params[f"n_{k}"] = v
                    where_parts.append(f"n.{k} = $n_{k}")
                q = q.where(" AND ".join(where_parts))
            q = q.return_("n")
            if order_by:
                q = q.order_by(f"n.{order_by}")
            q = q.limit(limit)
            cypher = q.build_cypher()
            return cypher, params

        elif tool_name == "find_neighbors":
            label = arguments["label"]
            match_props = arguments["match_properties"]
            rel_type = arguments.get("relationship_type")
            direction = arguments.get("direction", "both")
            limit = arguments.get("limit", 25)
            m = self._label_map.get(label)
            if not m:
                return None
            return Traversal.neighbors(
                m, match_props=match_props,
                rel_type=rel_type, direction=direction, limit=limit,
            )

        elif tool_name == "find_path":
            src_label = arguments["source_label"]
            tgt_label = arguments["target_label"]
            src_props = arguments["source_properties"]
            tgt_props = arguments["target_properties"]
            max_depth = arguments.get("max_depth", 5)
            src_model = self._label_map.get(src_label)
            tgt_model = self._label_map.get(tgt_label)
            if src_model and tgt_model:
                return Traversal.shortest_path(
                    src_model, tgt_model, src_props, tgt_props, max_depth=max_depth,
                )
            return None

        elif tool_name == "get_graph_schema":
            fmt = arguments.get("format", "text")
            if fmt == "markdown":
                return self.schema.to_markdown(), {}
            elif fmt == "json":
                return self.schema.to_json(), {}
            else:
                return self.schema.to_prompt(), {}

        elif tool_name == "bulk_create_nodes":
            label = arguments["label"]
            items = arguments["items"]
            m = self._label_map.get(label)
            if m:
                return BulkOps.bulk_create_nodes(m, items)
            return None

        return None
