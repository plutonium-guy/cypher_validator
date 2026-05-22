use std::collections::HashSet;
use pyo3::prelude::*;
use crate::parser;
use crate::parser::ast::*;

/// Information extracted from a parsed query without a schema.
#[pyclass(name = "QueryInfo")]
pub struct PyQueryInfo {
    /// True if the query is syntactically valid.
    #[pyo3(get)]
    pub is_valid: bool,
    /// Syntax error messages (empty if valid).
    #[pyo3(get)]
    pub errors: Vec<String>,
    /// Node labels referenced in the query.
    #[pyo3(get)]
    pub labels_used: Vec<String>,
    /// Relationship types referenced in the query.
    #[pyo3(get)]
    pub rel_types_used: Vec<String>,
    /// Property keys accessed in the query (e.g. ``["name", "age"]``).
    #[pyo3(get)]
    pub properties_used: Vec<String>,
}

#[pymethods]
impl PyQueryInfo {
    fn __bool__(&self) -> bool {
        self.is_valid
    }
    fn __repr__(&self) -> String {
        format!(
            "QueryInfo(is_valid={}, labels={:?}, rel_types={:?}, properties={:?}, errors={:?})",
            self.is_valid, self.labels_used, self.rel_types_used, self.properties_used, self.errors
        )
    }
}

/// Parse a Cypher query and return structural information without requiring a schema.
///
/// Example::
///
///     info = parse_query("MATCH (p:Person)-[:ACTED_IN]->(m:Movie) RETURN p.name")
///     info.is_valid        # True
///     info.labels_used     # ["Movie", "Person"]
///     info.rel_types_used  # ["ACTED_IN"]
///     info.properties_used # ["name"]
#[pyfunction]
pub fn parse_query(query: &str) -> PyQueryInfo {
    match parser::parse(query) {
        Ok(ast) => {
            let (labels, rels, props) = collect_info(&ast);
            PyQueryInfo {
                is_valid: true,
                errors: vec![],
                labels_used: labels,
                rel_types_used: rels,
                properties_used: props,
            }
        }
        Err(e) => {
            PyQueryInfo {
                is_valid: false,
                errors: vec![e.to_string()],
                labels_used: vec![],
                rel_types_used: vec![],
                properties_used: vec![],
            }
        }
    }
}

// ===== AST info extraction =====

fn collect_info(query: &CypherQuery) -> (Vec<String>, Vec<String>, Vec<String>) {
    let mut labels: HashSet<String> = HashSet::new();
    let mut rels: HashSet<String> = HashSet::new();
    let mut props: HashSet<String> = HashSet::new();
    collect_statement(&query.statement, &mut labels, &mut rels, &mut props);
    let mut lv: Vec<String> = labels.into_iter().collect();
    let mut rv: Vec<String> = rels.into_iter().collect();
    let mut pv: Vec<String> = props.into_iter().collect();
    lv.sort();
    rv.sort();
    pv.sort();
    (lv, rv, pv)
}

fn collect_statement(
    stmt: &Statement,
    labels: &mut HashSet<String>,
    rels: &mut HashSet<String>,
    props: &mut HashSet<String>,
) {
    match stmt {
        Statement::RegularQuery(rq) => collect_regular_query(rq, labels, rels, props),
        Statement::StandaloneCall(_) => {}
    }
}

fn collect_regular_query(
    rq: &RegularQuery,
    labels: &mut HashSet<String>,
    rels: &mut HashSet<String>,
    props: &mut HashSet<String>,
) {
    collect_single_query(&rq.single_query, labels, rels, props);
    for (_, sq) in &rq.unions {
        collect_single_query(sq, labels, rels, props);
    }
}

fn collect_single_query(
    sq: &SingleQuery,
    labels: &mut HashSet<String>,
    rels: &mut HashSet<String>,
    props: &mut HashSet<String>,
) {
    match sq {
        SingleQuery::SinglePart(spq) => {
            for rc in &spq.reading { collect_reading(rc, labels, rels, props); }
            for uc in &spq.updating { collect_updating(uc, labels, rels, props); }
            if let Some(ret) = &spq.ret {
                if let ReturnItems::Items(items) = &ret.items {
                    for item in items { collect_expr(&item.expr, labels, rels, props); }
                }
            }
        }
        SingleQuery::MultiPart(mpq) => {
            for (reading, updating, _) in &mpq.parts {
                for rc in reading { collect_reading(rc, labels, rels, props); }
                for uc in updating { collect_updating(uc, labels, rels, props); }
            }
            for rc in &mpq.reading { collect_reading(rc, labels, rels, props); }
            for uc in &mpq.updating { collect_updating(uc, labels, rels, props); }
            if let Some(ret) = &mpq.ret {
                if let ReturnItems::Items(items) = &ret.items {
                    for item in items { collect_expr(&item.expr, labels, rels, props); }
                }
            }
        }
    }
}

fn collect_reading(
    rc: &ReadingClause,
    labels: &mut HashSet<String>,
    rels: &mut HashSet<String>,
    props: &mut HashSet<String>,
) {
    match rc {
        ReadingClause::Match(m) => {
            collect_pattern(&m.pattern, labels, rels, props);
            if let Some(w) = &m.where_clause {
                collect_expr(w, labels, rels, props);
            }
        }
        ReadingClause::CallSubquery(rq) => {
            collect_regular_query(rq, labels, rels, props);
        }
        _ => {}
    }
}

fn collect_updating(
    uc: &UpdatingClause,
    labels: &mut HashSet<String>,
    rels: &mut HashSet<String>,
    props: &mut HashSet<String>,
) {
    match uc {
        UpdatingClause::Create(pat) => collect_pattern(pat, labels, rels, props),
        UpdatingClause::Merge(m) => {
            let pat = Pattern { parts: vec![m.pattern_part.clone()] };
            collect_pattern(&pat, labels, rels, props);
        }
        _ => {}
    }
}

fn collect_pattern(
    pattern: &Pattern,
    labels: &mut HashSet<String>,
    rels: &mut HashSet<String>,
    props: &mut HashSet<String>,
) {
    for part in &pattern.parts {
        let elem = &part.element;
        for label in &elem.start.labels { labels.insert(label.clone()); }
        collect_node_props(&elem.start, props);
        for (rel, node) in &elem.chain {
            for rt in &rel.rel_types { rels.insert(rt.clone()); }
            for label in &node.labels { labels.insert(label.clone()); }
            collect_node_props(node, props);
        }
    }
}

fn collect_node_props(node: &NodePattern, props: &mut HashSet<String>) {
    if let Some(MapOrParam::Map(map)) = &node.properties {
        for (key, val) in map {
            props.insert(key.clone());
            // Property-value expressions in node maps do not introduce labels/rels.
            let mut sink_l: HashSet<String> = HashSet::new();
            let mut sink_r: HashSet<String> = HashSet::new();
            collect_expr(val, &mut sink_l, &mut sink_r, props);
        }
    }
}

/// Recursively walk an expression and collect labels, rel-types, and property key names.
fn collect_expr(
    expr: &Expr,
    labels: &mut HashSet<String>,
    rels: &mut HashSet<String>,
    props: &mut HashSet<String>,
) {
    match expr {
        Expr::Property { expr: inner, key } => {
            props.insert(key.clone());
            collect_expr(inner, labels, rels, props);
        }
        Expr::Subscript { expr: inner, index } => {
            collect_expr(inner, labels, rels, props);
            collect_expr(index, labels, rels, props);
        }
        Expr::Slice { expr: inner, from, to } => {
            collect_expr(inner, labels, rels, props);
            if let Some(f) = from { collect_expr(f, labels, rels, props); }
            if let Some(t) = to { collect_expr(t, labels, rels, props); }
        }
        Expr::And(a, b) | Expr::Or(a, b) | Expr::Xor(a, b)
        | Expr::Eq(a, b) | Expr::Ne(a, b)
        | Expr::Lt(a, b) | Expr::Lte(a, b)
        | Expr::Gt(a, b) | Expr::Gte(a, b)
        | Expr::Add(a, b) | Expr::Sub(a, b)
        | Expr::Mul(a, b) | Expr::Div(a, b)
        | Expr::Mod(a, b) | Expr::Pow(a, b)
        | Expr::In(a, b) | Expr::Regex(a, b)
        | Expr::StartsWith(a, b) | Expr::EndsWith(a, b)
        | Expr::Contains(a, b) => {
            collect_expr(a, labels, rels, props);
            collect_expr(b, labels, rels, props);
        }
        Expr::Not(inner) | Expr::Neg(inner)
        | Expr::IsNull(inner) | Expr::IsNotNull(inner) => {
            collect_expr(inner, labels, rels, props);
        }
        Expr::FunctionCall { args, .. } => {
            for arg in args { collect_expr(arg, labels, rels, props); }
        }
        Expr::List(items) => {
            for item in items { collect_expr(item, labels, rels, props); }
        }
        Expr::Map(map) => {
            for val in map.values() { collect_expr(val, labels, rels, props); }
        }
        Expr::Case { subject, alternatives, default } => {
            if let Some(s) = subject { collect_expr(s, labels, rels, props); }
            for (cond, then) in alternatives {
                collect_expr(cond, labels, rels, props);
                collect_expr(then, labels, rels, props);
            }
            if let Some(d) = default { collect_expr(d, labels, rels, props); }
        }
        Expr::ListComprehension { source, filter, projection, .. } => {
            collect_expr(source, labels, rels, props);
            if let Some(f) = filter { collect_expr(f, labels, rels, props); }
            if let Some(p) = projection { collect_expr(p, labels, rels, props); }
        }
        Expr::All { source, filter, .. }
        | Expr::Any { source, filter, .. }
        | Expr::None { source, filter, .. }
        | Expr::Single { source, filter, .. } => {
            collect_expr(source, labels, rels, props);
            if let Some(f) = filter { collect_expr(f, labels, rels, props); }
        }
        Expr::Exists(sub) => match sub.as_ref() {
            ExistsSubquery::Query(rq) => {
                collect_regular_query(rq, labels, rels, props);
            }
            ExistsSubquery::Pattern(pat) => {
                collect_pattern(pat, labels, rels, props);
            }
        },
        Expr::PatternComprehension { element, filter, projection, .. } => {
            for label in &element.start.labels { labels.insert(label.clone()); }
            collect_node_props(&element.start, props);
            for (rel, node) in &element.chain {
                for rt in &rel.rel_types { rels.insert(rt.clone()); }
                for label in &node.labels { labels.insert(label.clone()); }
                collect_node_props(node, props);
            }
            if let Some(f) = filter { collect_expr(f, labels, rels, props); }
            collect_expr(projection, labels, rels, props);
        }
        Expr::ShortestPath { element, .. } => {
            for label in &element.start.labels { labels.insert(label.clone()); }
            collect_node_props(&element.start, props);
            for (rel, node) in &element.chain {
                for rt in &rel.rel_types { rels.insert(rt.clone()); }
                for label in &node.labels { labels.insert(label.clone()); }
                collect_node_props(node, props);
            }
        }
        Expr::Reduce { init, source, projection, .. } => {
            collect_expr(init, labels, rels, props);
            collect_expr(source, labels, rels, props);
            collect_expr(projection, labels, rels, props);
        }
        Expr::CountSubquery(rq) | Expr::CollectSubquery(rq) => {
            collect_regular_query(rq, labels, rels, props);
        }
        // Leaf nodes: Variable, Integer, Float, Str, Bool, Null, Parameter, CountStar
        _ => {}
    }
}
