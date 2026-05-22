use std::collections::{HashMap, HashSet};
use crate::schema::Schema;
use crate::parser::ast::*;
use crate::diagnostics::{ErrorCode, Suggestion, ValidationDiagnostic};

/// TypeEnv maps variable names to a list of labels/rel-types they are bound to.
pub type TypeEnv = HashMap<String, Vec<String>>;

// ---------------------------------------------------------------------------
// Levenshtein-based "did you mean" helper
// ---------------------------------------------------------------------------

/// Compute the Levenshtein edit distance (case-insensitive) between two strings,
/// stopping early and returning `cap + 1` as soon as the distance provably exceeds `cap`.
///
/// Uses a 1-D rolling array (O(n) space) rather than a full m×n matrix.
fn levenshtein_capped(a: &str, b: &str, cap: usize) -> usize {
    // Schema identifiers are ASCII, so byte comparison is correct after lowercasing.
    let a_lo = a.to_lowercase();
    let b_lo = b.to_lowercase();
    let a_bytes = a_lo.as_bytes();
    let b_bytes = b_lo.as_bytes();
    let m = a_bytes.len();
    let n = b_bytes.len();

    // If the lengths differ by more than cap, the distance must exceed cap.
    if m.abs_diff(n) > cap {
        return cap + 1;
    }

    // prev[j] = edit distance between a[0..i] and b[0..j] from the previous row.
    let mut prev: Vec<usize> = (0..=n).collect();
    let mut curr = vec![0usize; n + 1];

    for i in 1..=m {
        curr[0] = i;
        let mut row_min = i; // track minimum in current row for early-exit
        for j in 1..=n {
            curr[j] = if a_bytes[i - 1] == b_bytes[j - 1] {
                prev[j - 1]
            } else {
                1 + prev[j - 1].min(prev[j]).min(curr[j - 1])
            };
            if curr[j] < row_min { row_min = curr[j]; }
        }
        // Every remaining row can only increase the minimum by at most 1 per row,
        // so if the current row minimum already exceeds cap we can stop early.
        if row_min > cap {
            return cap + 1;
        }
        std::mem::swap(&mut prev, &mut curr);
    }
    prev[n]
}

/// Return the closest candidate from `candidates` within `max_dist`, or None.
/// Uses the capped Levenshtein with a shrinking cap so expensive full-matrix
/// computation is avoided for strings that are clearly too far apart.
fn closest_match<'a>(name: &str, candidates: &'a [String], max_dist: usize) -> Option<&'a str> {
    let mut best: Option<(&str, usize)> = None;
    let mut cap = max_dist;
    for c in candidates {
        // Cheap early reject: if length delta already exceeds the current cap,
        // skip the full Levenshtein call.
        if name.len().abs_diff(c.len()) > cap {
            continue;
        }
        let d = levenshtein_capped(name, c, cap);
        if d <= cap {
            best = Some((c.as_str(), d));
            if d == 0 {
                return best.map(|(c, _)| c); // exact match — cannot beat
            }
            // Tighten the cap so subsequent calls bail out earlier.
            cap = d.saturating_sub(1);
        }
    }
    best.map(|(c, _)| c)
}

/// Build a "did you mean <prefix>X?" hint string, or empty string if no close match.
fn did_you_mean(name: &str, candidates: &[String], prefix: &str) -> String {
    match closest_match(name, candidates, 3) {
        Some(s) => format!(", did you mean {prefix}{s}?"),
        None => String::new(),
    }
}

/// Build a `Suggestion` for a label/rel-type correction, or None if no close match.
fn label_suggestion(name: &str, candidates: &[String], prefix: &str) -> Option<Suggestion> {
    closest_match(name, candidates, 3).map(|replacement| Suggestion {
        original: format!("{}{}", prefix, name),
        replacement: format!("{}{}", prefix, replacement),
        description: format!("Replace {}{} with {}{}", prefix, name, prefix, replacement),
    })
}

/// Build a `Suggestion` for a property correction, or None if no close match.
fn property_suggestion(name: &str, candidates: &[String]) -> Option<Suggestion> {
    closest_match(name, candidates, 3).map(|replacement| Suggestion {
        original: name.to_string(),
        replacement: replacement.to_string(),
        description: format!("Replace property '{}' with '{}'", name, replacement),
    })
}

// ---------------------------------------------------------------------------
// Built-in function registry
// ---------------------------------------------------------------------------

struct CypherBuiltinFn {
    name: &'static str,       // lowercase
    min_args: usize,
    max_args: Option<usize>,  // None = variadic
    is_aggregate: bool,
}

const BUILTIN_FUNCTIONS: &[CypherBuiltinFn] = &[
    // Aggregates
    CypherBuiltinFn { name: "count",           min_args: 1, max_args: Some(1), is_aggregate: true },
    CypherBuiltinFn { name: "collect",         min_args: 1, max_args: Some(1), is_aggregate: true },
    CypherBuiltinFn { name: "sum",             min_args: 1, max_args: Some(1), is_aggregate: true },
    CypherBuiltinFn { name: "avg",             min_args: 1, max_args: Some(1), is_aggregate: true },
    CypherBuiltinFn { name: "min",             min_args: 1, max_args: Some(1), is_aggregate: true },
    CypherBuiltinFn { name: "max",             min_args: 1, max_args: Some(1), is_aggregate: true },
    CypherBuiltinFn { name: "stdev",           min_args: 1, max_args: Some(1), is_aggregate: true },
    CypherBuiltinFn { name: "stdevp",          min_args: 1, max_args: Some(1), is_aggregate: true },
    CypherBuiltinFn { name: "percentilecont",  min_args: 2, max_args: Some(2), is_aggregate: true },
    CypherBuiltinFn { name: "percentiledisc",  min_args: 2, max_args: Some(2), is_aggregate: true },
    // String
    CypherBuiltinFn { name: "tolower",    min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "toupper",    min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "trim",       min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "ltrim",      min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "rtrim",      min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "replace",    min_args: 3, max_args: Some(3), is_aggregate: false },
    CypherBuiltinFn { name: "substring",  min_args: 2, max_args: Some(3), is_aggregate: false },
    CypherBuiltinFn { name: "left",       min_args: 2, max_args: Some(2), is_aggregate: false },
    CypherBuiltinFn { name: "right",      min_args: 2, max_args: Some(2), is_aggregate: false },
    CypherBuiltinFn { name: "split",      min_args: 2, max_args: Some(2), is_aggregate: false },
    CypherBuiltinFn { name: "reverse",    min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "tostring",   min_args: 1, max_args: Some(1), is_aggregate: false },
    // Numeric
    CypherBuiltinFn { name: "abs",        min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "ceil",       min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "floor",      min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "round",      min_args: 1, max_args: Some(2), is_aggregate: false },
    CypherBuiltinFn { name: "sign",       min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "rand",       min_args: 0, max_args: Some(0), is_aggregate: false },
    CypherBuiltinFn { name: "tointeger",  min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "tofloat",    min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "sqrt",       min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "log",        min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "log10",      min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "exp",        min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "e",          min_args: 0, max_args: Some(0), is_aggregate: false },
    CypherBuiltinFn { name: "pi",         min_args: 0, max_args: Some(0), is_aggregate: false },
    CypherBuiltinFn { name: "sin",        min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "cos",        min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "tan",        min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "asin",       min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "acos",       min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "atan",       min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "atan2",      min_args: 2, max_args: Some(2), is_aggregate: false },
    CypherBuiltinFn { name: "radians",    min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "degrees",    min_args: 1, max_args: Some(1), is_aggregate: false },
    // List / Graph
    CypherBuiltinFn { name: "size",          min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "head",          min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "tail",          min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "last",          min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "range",         min_args: 2, max_args: Some(3), is_aggregate: false },
    CypherBuiltinFn { name: "keys",          min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "labels",        min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "nodes",         min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "relationships", min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "properties",    min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "type",          min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "id",            min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "elementid",     min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "startnode",     min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "endnode",       min_args: 1, max_args: Some(1), is_aggregate: false },
    // Temporal
    CypherBuiltinFn { name: "date",          min_args: 0, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "datetime",      min_args: 0, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "time",          min_args: 0, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "localtime",     min_args: 0, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "localdatetime", min_args: 0, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "duration",      min_args: 1, max_args: Some(1), is_aggregate: false },
    // Spatial
    CypherBuiltinFn { name: "point",    min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "distance", min_args: 2, max_args: Some(2), is_aggregate: false },
    // Other
    CypherBuiltinFn { name: "coalesce",   min_args: 1, max_args: None,    is_aggregate: false },
    CypherBuiltinFn { name: "randomuuid", min_args: 0, max_args: Some(0), is_aggregate: false },
    CypherBuiltinFn { name: "timestamp",  min_args: 0, max_args: Some(0), is_aggregate: false },
    CypherBuiltinFn { name: "toboolean",  min_args: 1, max_args: Some(1), is_aggregate: false },
    CypherBuiltinFn { name: "exists",     min_args: 1, max_args: Some(1), is_aggregate: false },
];

fn lookup_builtin(name: &str) -> Option<&'static CypherBuiltinFn> {
    let lower = name.to_lowercase();
    BUILTIN_FUNCTIONS.iter().find(|f| f.name == lower)
}

pub struct SemanticValidator<'a> {
    pub schema: &'a Schema,
    pub errors: Vec<String>,
    pub warnings: Vec<String>,
    pub diagnostics: Vec<ValidationDiagnostic>,
    pub env: TypeEnv,
    /// Cached label list for "did you mean" suggestions — computed once per validation.
    known_labels: Vec<String>,
    /// Cached rel-type list for "did you mean" suggestions — computed once per validation.
    known_rel_types: Vec<String>,
}

impl<'a> SemanticValidator<'a> {
    pub fn new(schema: &'a Schema) -> Self {
        let known_labels = schema.node_labels().into_iter().map(|s| s.to_string()).collect();
        let known_rel_types = schema.rel_types().into_iter().map(|s| s.to_string()).collect();
        SemanticValidator {
            schema,
            errors: vec![],
            warnings: vec![],
            diagnostics: vec![],
            env: HashMap::new(),
            known_labels,
            known_rel_types,
        }
    }

    // ---------------------------------------------------------------------------
    // Diagnostic push helpers
    // ---------------------------------------------------------------------------

    /// Push an error diagnostic (also appends to legacy `errors` vec).
    fn push_error(&mut self, code: ErrorCode, message: String, suggestion: Option<Suggestion>) {
        self.errors.push(message.clone());
        let mut diag = ValidationDiagnostic::error(code, message);
        if let Some(s) = suggestion {
            diag = diag.with_suggestion(s);
        }
        self.diagnostics.push(diag);
    }

    /// Push a warning diagnostic (also appends to legacy `warnings` vec).
    fn push_warning(&mut self, code: ErrorCode, message: String) {
        self.warnings.push(message.clone());
        self.diagnostics.push(ValidationDiagnostic::warning(code, message));
    }

    // ---------------------------------------------------------------------------
    // Property candidate helpers for "did you mean"
    // ---------------------------------------------------------------------------

    fn node_property_candidates(&self, label: &str) -> Vec<String> {
        self.schema.node_properties(label).into_iter().map(|s| s.to_string()).collect()
    }

    fn rel_property_candidates(&self, rel_type: &str) -> Vec<String> {
        self.schema.rel_properties(rel_type).into_iter().map(|s| s.to_string()).collect()
    }

    // ---------------------------------------------------------------------------
    // Query validation entry
    // ---------------------------------------------------------------------------

    pub fn validate_query(&mut self, query: &CypherQuery) {
        match &query.statement {
            Statement::RegularQuery(rq) => self.validate_regular_query(rq),
            Statement::StandaloneCall(_) => {} // procedure calls are open-world
        }
    }

    fn validate_regular_query(&mut self, rq: &RegularQuery) {
        self.validate_single_query(&rq.single_query);
        for (_, sq) in &rq.unions {
            // Each UNION branch is validated with an independent env
            let saved_env = self.env.clone();
            self.env.clear();
            self.validate_single_query(sq);
            self.env = saved_env;
        }
    }

    fn validate_single_query(&mut self, sq: &SingleQuery) {
        match sq {
            SingleQuery::SinglePart(spq) => self.validate_single_part(spq),
            SingleQuery::MultiPart(mpq) => self.validate_multi_part(mpq),
        }
    }

    fn validate_single_part(&mut self, spq: &SinglePartQuery) {
        // First pass: collect all bindings so expressions can reference any bound var
        for rc in &spq.reading {
            self.collect_reading_bindings(rc);
        }
        for uc in &spq.updating {
            self.collect_updating_bindings(uc);
        }
        // Second pass: validate labels, properties, directions, and variable references
        for rc in &spq.reading {
            self.validate_reading_clause(rc);
        }
        for uc in &spq.updating {
            self.validate_updating_clause(uc);
        }
        if let Some(ret) = &spq.ret {
            self.validate_return_clause(ret);
        }
    }

    fn validate_multi_part(&mut self, mpq: &MultiPartQuery) {
        for (reading, updating, with) in &mpq.parts {
            // Collect bindings for this part
            for rc in reading { self.collect_reading_bindings(rc); }
            for uc in updating { self.collect_updating_bindings(uc); }
            // Validate this part against current env
            for rc in reading { self.validate_reading_clause(rc); }
            for uc in updating { self.validate_updating_clause(uc); }
            // Process WITH: validate its expressions, then reset env to projected vars only
            self.process_with_clause(with);
        }
        // Final part: collect then validate
        for rc in &mpq.reading {
            self.collect_reading_bindings(rc);
        }
        for uc in &mpq.updating {
            self.collect_updating_bindings(uc);
        }
        for rc in &mpq.reading {
            self.validate_reading_clause(rc);
        }
        for uc in &mpq.updating {
            self.validate_updating_clause(uc);
        }
        if let Some(ret) = &mpq.ret {
            self.validate_return_clause(ret);
        }
    }

    // ===== WITH scope management =====

    fn process_with_clause(&mut self, with: &WithClause) {
        // Validate WITH projection expressions against the current (pre-reset) env.
        for item in &with.items {
            self.validate_expr(&item.expr);
        }
        self.check_alias_uniqueness(&with.items);

        // Reset env: only projected variables survive the WITH boundary.
        // In Cypher, ORDER BY and WHERE after WITH are evaluated in the *projected* scope,
        // so aliases introduced by the WITH projection are visible in both.
        let mut new_env: TypeEnv = HashMap::new();
        for item in &with.items {
            let name = item.alias.clone().or_else(|| {
                if let Expr::Variable(v) = &item.expr { Some(v.clone()) } else { None }
            });
            if let Some(name) = name {
                // Carry labels forward when projecting a bare variable
                let labels = if let Expr::Variable(v) = &item.expr {
                    self.env.get(v.as_str()).cloned().unwrap_or_default()
                } else {
                    vec![]
                };
                new_env.insert(name, labels);
            }
        }
        self.env = new_env;

        // ORDER BY, SKIP, LIMIT, and WHERE are evaluated in the projected scope
        if let Some(order) = &with.order {
            for si in order { self.validate_expr(&si.expr); }
        }
        if let Some(s) = &with.skip { self.validate_pagination_expr(s, "SKIP"); }
        if let Some(l) = &with.limit { self.validate_pagination_expr(l, "LIMIT"); }
        if let Some(where_expr) = &with.where_clause {
            self.validate_expr(where_expr);
        }
    }

    // ===== Binding collection =====

    fn collect_reading_bindings(&mut self, rc: &ReadingClause) {
        match rc {
            ReadingClause::Match(m) => self.collect_pattern_bindings(&m.pattern),
            ReadingClause::Unwind(u) => {
                self.env.insert(u.variable.clone(), vec![]);
            }
            ReadingClause::Call(c) => {
                // CALL YIELD variables are bound in scope
                for yi in &c.yield_items {
                    self.env.insert(yi.variable.clone(), vec![]);
                }
            }
            ReadingClause::CallSubquery(_) => {
                // Bindings from CALL subquery are resolved during validation
                // (the subquery's RETURN clause determines what's visible after)
            }
        }
    }

    fn collect_updating_bindings(&mut self, uc: &UpdatingClause) {
        match uc {
            UpdatingClause::Create(pat) => self.collect_pattern_bindings(pat),
            UpdatingClause::Merge(m) => {
                let pattern = Pattern { parts: vec![m.pattern_part.clone()] };
                self.collect_pattern_bindings(&pattern);
            }
            // FOREACH variable is locally scoped; not projected into outer env
            _ => {}
        }
    }

    fn collect_pattern_bindings(&mut self, pattern: &Pattern) {
        for part in &pattern.parts {
            if let Some(v) = &part.variable {
                self.env.insert(v.clone(), vec![]);
            }
            let elem = &part.element;
            self.collect_node_bindings(&elem.start);
            for (rel, node) in &elem.chain {
                self.collect_rel_bindings(rel);
                self.collect_node_bindings(node);
            }
        }
    }

    fn collect_node_bindings(&mut self, node: &NodePattern) {
        if let Some(var) = &node.variable {
            // Split lookup to avoid cloning `node.labels` when the entry already exists.
            if let Some(existing) = self.env.get_mut(var.as_str()) {
                for l in &node.labels {
                    if !existing.contains(l) {
                        existing.push(l.clone());
                    }
                }
            } else {
                self.env.insert(var.clone(), node.labels.clone());
            }
        }
    }

    fn collect_rel_bindings(&mut self, rel: &RelationshipPattern) {
        if let Some(var) = &rel.variable {
            if let Some(existing) = self.env.get_mut(var.as_str()) {
                for t in &rel.rel_types {
                    if !existing.contains(t) {
                        existing.push(t.clone());
                    }
                }
            } else {
                self.env.insert(var.clone(), rel.rel_types.clone());
            }
        }
    }

    // ===== Validation =====

    fn validate_reading_clause(&mut self, rc: &ReadingClause) {
        match rc {
            ReadingClause::Match(m) => {
                self.validate_pattern(&m.pattern);
                if let Some(w) = &m.where_clause {
                    self.validate_expr_no_aggregate(w, "MATCH WHERE");
                }
                self.check_cartesian_product(m);
                self.check_match_complexity(m);
            }
            ReadingClause::Unwind(u) => self.validate_expr(&u.expr),
            ReadingClause::Call(_) => {}
            ReadingClause::CallSubquery(rq) => {
                // Outer scope visible inside; validate the inner query
                self.validate_regular_query(rq);
            }
        }
    }

    /// Collect all variable names introduced by a single pattern part.
    fn pattern_part_vars(part: &PatternPart) -> HashSet<String> {
        let mut vars: HashSet<String> = HashSet::new();
        if let Some(v) = &part.variable {
            vars.insert(v.clone());
        }
        let elem = &part.element;
        if let Some(v) = &elem.start.variable {
            vars.insert(v.clone());
        }
        for (rel, node) in &elem.chain {
            if let Some(v) = &rel.variable {
                vars.insert(v.clone());
            }
            if let Some(v) = &node.variable {
                vars.insert(v.clone());
            }
        }
        vars
    }

    /// Gap 2: warn when a MATCH has disconnected pattern parts (Cartesian product).
    ///
    /// Checks structural connectivity of the pattern parts: two parts are connected if they
    /// share at least one variable.  Because binding collection runs before validation,
    /// `self.env` already contains every variable in the current clause — so we work purely
    /// on the pattern structure rather than using `self.env` as a "bound before" proxy.
    fn check_cartesian_product(&mut self, m: &MatchClause) {
        if m.pattern.parts.len() < 2 {
            return;
        }
        let mut connected: HashSet<String> = HashSet::new();
        let mut has_first = false;
        for part in &m.pattern.parts {
            let vars = Self::pattern_part_vars(part);
            if !has_first {
                connected.extend(vars);
                has_first = true;
            } else if vars.is_disjoint(&connected) {
                // This part shares no variable with any previously seen part → Cartesian
                self.push_warning(
                    ErrorCode::W101CartesianProduct,
                    "MATCH pattern contains disconnected parts that will produce a Cartesian \
                     product; add a relationship or shared variable to connect them"
                        .to_string(),
                );
                break; // one warning per MATCH clause is enough
            } else {
                connected.extend(vars);
            }
        }
    }

    // ===== Aggregate-context helpers =====

    /// Returns true if `expr` (anywhere in its subtree) contains an aggregate function call
    /// or COUNT(*), which are only valid in RETURN / WITH / ORDER BY projection context.
    fn contains_aggregate(expr: &Expr) -> bool {
        match expr {
            Expr::CountStar => true,
            Expr::FunctionCall { name, args, .. } => {
                lookup_builtin(name).map_or(false, |f| f.is_aggregate)
                    || args.iter().any(Self::contains_aggregate)
            }
            Expr::Or(a, b) | Expr::Xor(a, b) | Expr::And(a, b)
            | Expr::Eq(a, b) | Expr::Ne(a, b) | Expr::Lt(a, b) | Expr::Lte(a, b)
            | Expr::Gt(a, b) | Expr::Gte(a, b) | Expr::Regex(a, b)
            | Expr::In(a, b) | Expr::StartsWith(a, b) | Expr::EndsWith(a, b)
            | Expr::Contains(a, b)
            | Expr::Add(a, b) | Expr::Sub(a, b) | Expr::Mul(a, b)
            | Expr::Div(a, b) | Expr::Mod(a, b) | Expr::Pow(a, b) => {
                Self::contains_aggregate(a) || Self::contains_aggregate(b)
            }
            Expr::Not(e) | Expr::Neg(e) | Expr::IsNull(e) | Expr::IsNotNull(e) => {
                Self::contains_aggregate(e)
            }
            Expr::Property { expr: e, .. } => Self::contains_aggregate(e),
            Expr::Subscript { expr: e, index } => {
                Self::contains_aggregate(e) || Self::contains_aggregate(index)
            }
            Expr::List(items) => items.iter().any(Self::contains_aggregate),
            Expr::Map(map) => map.values().any(Self::contains_aggregate),
            Expr::Case { subject, alternatives, default } => {
                subject.as_ref().map_or(false, |s| Self::contains_aggregate(s))
                    || alternatives.iter().any(|(w, t)| {
                        Self::contains_aggregate(w) || Self::contains_aggregate(t)
                    })
                    || default.as_ref().map_or(false, |d| Self::contains_aggregate(d))
            }
            _ => false,
        }
    }

    /// Validate `expr` and error if it contains an aggregate function in a context that
    /// does not support aggregation (e.g. MATCH WHERE, SET, DELETE).
    fn validate_expr_no_aggregate(&mut self, expr: &Expr, context: &str) {
        if Self::contains_aggregate(expr) {
            self.push_error(
                ErrorCode::E602AggregateInForbiddenContext,
                format!(
                    "Aggregate function not allowed in {} context; \
                     aggregates are only valid in RETURN, WITH, or ORDER BY",
                    context
                ),
                None,
            );
        }
        self.validate_expr(expr);
    }

    /// Validate a SKIP/LIMIT expression: must be an integer, parameter, or variable —
    /// not a string, boolean, null, or float.
    fn validate_pagination_expr(&mut self, expr: &Expr, context: &str) {
        match expr {
            Expr::Str(_) => self.push_error(
                ErrorCode::E611PaginationTypeString,
                format!("{} expression must be an integer, got a string literal", context),
                None,
            ),
            Expr::Bool(_) => self.push_error(
                ErrorCode::E612PaginationTypeBool,
                format!("{} expression must be an integer, got a boolean literal", context),
                None,
            ),
            Expr::Null => self.push_error(
                ErrorCode::E613PaginationTypeNull,
                format!("{} expression must be an integer, got NULL", context),
                None,
            ),
            Expr::Float(_) => self.push_error(
                ErrorCode::E614PaginationTypeFloat,
                format!("{} expression must be an integer, got a float literal", context),
                None,
            ),
            _ => self.validate_expr(expr),
        }
    }

    /// Gap 5: warn about unlabeled full-graph scans and unbounded variable-length relationships.
    fn check_match_complexity(&mut self, m: &MatchClause) {
        // A: unlabeled node with no WHERE clause
        if m.where_clause.is_none()
            && m.pattern.parts.iter().any(|part| {
                part.element.start.labels.is_empty()
                    || part.element.chain.iter().any(|(_, n)| n.labels.is_empty())
            })
        {
            self.push_warning(
                ErrorCode::W201UnlabeledFullScan,
                "MATCH contains an unlabeled node with no WHERE clause; \
                 this will scan all nodes in the graph"
                    .to_string(),
            );
        }

        // B: unbounded variable-length relationship
        for part in &m.pattern.parts {
            for (rel, _) in &part.element.chain {
                if let Some(r) = &rel.range {
                    if r.max.is_none() {
                        self.push_warning(
                            ErrorCode::W202UnboundedVarLength,
                            "Variable-length relationship without an upper bound ([*] or [*n..]) \
                             may cause unbounded traversal"
                                .to_string(),
                        );
                    }
                }
            }
        }
    }

    fn validate_updating_clause(&mut self, uc: &UpdatingClause) {
        match uc {
            UpdatingClause::Create(pat) => self.validate_pattern(pat),
            UpdatingClause::Merge(m) => {
                let pattern = Pattern { parts: vec![m.pattern_part.clone()] };
                self.validate_pattern(&pattern);
            }
            UpdatingClause::Set(items) => {
                for item in items { self.validate_set_item(item); }
            }
            UpdatingClause::Remove(items) => {
                for item in items { self.validate_remove_item(item); }
            }
            UpdatingClause::Delete { exprs, .. } => {
                for e in exprs {
                    self.validate_expr_no_aggregate(e, "DELETE");
                }
            }
            UpdatingClause::Foreach { variable, list_expr, body } => {
                self.validate_expr(list_expr);
                // variable is locally scoped to the FOREACH body
                let was_bound = self.env.contains_key(variable.as_str());
                if !was_bound { self.env.insert(variable.clone(), vec![]); }
                for clause in body { self.validate_updating_clause(clause); }
                if !was_bound { self.env.remove(variable.as_str()); }
            }
        }
    }

    fn validate_return_clause(&mut self, ret: &ReturnClause) {
        match &ret.items {
            ReturnItems::Items(items) => {
                for item in items { self.validate_expr(&item.expr); }
                self.check_alias_uniqueness(items);
            }
            ReturnItems::Wildcard => {}
        }
        if let Some(order) = &ret.order {
            for si in order { self.validate_expr(&si.expr); }
        }
        if let Some(s) = &ret.skip { self.validate_pagination_expr(s, "SKIP"); }
        if let Some(l) = &ret.limit { self.validate_pagination_expr(l, "LIMIT"); }
    }

    fn check_alias_uniqueness(&mut self, items: &[ReturnItem]) {
        let mut seen: HashSet<String> = HashSet::new();
        for item in items {
            let name = item.alias.clone().or_else(|| {
                if let Expr::Variable(v) = &item.expr { Some(v.clone()) } else { None }
            });
            if let Some(n) = name {
                if !seen.insert(n.clone()) {
                    self.push_error(
                        ErrorCode::E502DuplicateProjectionName,
                        format!("Duplicate projection name '{}' in RETURN/WITH", n),
                        None,
                    );
                }
            }
        }
    }

    // ===== Pattern validation (direction + endpoint aware) =====

    fn validate_pattern(&mut self, pattern: &Pattern) {
        for part in &pattern.parts {
            let elem = &part.element;
            self.validate_node_pattern(&elem.start);
            let mut prev = &elem.start;
            for (rel, node) in &elem.chain {
                self.validate_rel_pattern_with_endpoints(rel, prev, node);
                self.validate_node_pattern(node);
                prev = node;
            }
        }
    }

    fn validate_node_pattern(&mut self, node: &NodePattern) {
        for label in &node.labels {
            if !self.schema.has_node_label(label) {
                let hint = did_you_mean(label, &self.known_labels, ":");
                let message = format!("Unknown node label: :{}{}", label, hint);
                let suggestion = label_suggestion(label, &self.known_labels, ":");
                self.push_error(ErrorCode::E201UnknownNodeLabel, message, suggestion);
            }
        }
        if let Some(MapOrParam::Map(map)) = &node.properties {
            for key in map.keys() {
                for label in &node.labels {
                    if self.schema.has_node_label(label) && !self.schema.node_has_property(label, key) {
                        let candidates = self.node_property_candidates(label);
                        let hint = did_you_mean(key, &candidates, ".");
                        let message = format!(
                            "Unknown property '{}' for node label :{}{}", key, label, hint
                        );
                        let suggestion = property_suggestion(key, &candidates);
                        self.push_error(ErrorCode::E301UnknownNodeProperty, message, suggestion);
                    }
                }
            }
        }
    }

    /// Validates relationship type, properties, direction, and endpoint labels.
    fn validate_rel_pattern_with_endpoints(
        &mut self,
        rel: &RelationshipPattern,
        from_node: &NodePattern,
        to_node: &NodePattern,
    ) {
        for rel_type in &rel.rel_types {
            if !self.schema.has_rel_type(rel_type) {
                let hint = did_you_mean(rel_type, &self.known_rel_types, ":");
                let message = format!("Unknown relationship type: :{}{}", rel_type, hint);
                let suggestion = label_suggestion(rel_type, &self.known_rel_types, ":");
                self.push_error(ErrorCode::E211UnknownRelType, message, suggestion);
                continue; // skip endpoint check for unknown types
            }

            // Validate relationship properties
            if let Some(MapOrParam::Map(map)) = &rel.properties {
                for key in map.keys() {
                    if !self.schema.rel_has_property(rel_type, key) {
                        let candidates = self.rel_property_candidates(rel_type);
                        let hint = did_you_mean(key, &candidates, ".");
                        let message = format!(
                            "Unknown property '{}' for relationship type :{}{}", key, rel_type, hint
                        );
                        let suggestion = property_suggestion(key, &candidates);
                        self.push_error(ErrorCode::E302UnknownRelProperty, message, suggestion);
                    }
                }
            }

            // Validate direction and endpoint labels against schema
            if let Some((schema_src, schema_tgt)) = self.schema.rel_src_tgt(rel_type) {
                let schema_src = schema_src.to_string();
                let schema_tgt = schema_tgt.to_string();
                match &rel.direction {
                    Direction::Outgoing => {
                        // Pattern: (from_node)-[r]->(to_node)
                        // from_node is the source, to_node is the target
                        self.check_endpoint_label(from_node, &schema_src, "source", rel_type);
                        self.check_endpoint_label(to_node, &schema_tgt, "target", rel_type);
                    }
                    Direction::Incoming => {
                        // Pattern: (from_node)<-[r]-(to_node)
                        // to_node is the source, from_node is the target
                        self.check_endpoint_label(to_node, &schema_src, "source", rel_type);
                        self.check_endpoint_label(from_node, &schema_tgt, "target", rel_type);
                    }
                    Direction::Undirected => {
                        // Undirected — either orientation is valid, skip endpoint check
                    }
                }
            }
        }
    }

    /// Reports an error if `node` has known labels that don't include `expected`.
    /// Nodes without labels are skipped (open-world assumption).
    fn check_endpoint_label(
        &mut self,
        node: &NodePattern,
        expected: &str,
        role: &str,
        rel_type: &str,
    ) {
        if node.labels.is_empty() {
            return; // no labels declared: open-world, skip
        }
        if node.labels.iter().any(|l| l == expected) {
            return; // at least one label matches: valid
        }
        // Only report if at least one label is a known schema label
        // (avoids redundant errors on top of "Unknown node label" errors)
        if node.labels.iter().any(|l| self.schema.has_node_label(l)) {
            self.push_error(
                ErrorCode::E401WrongEndpointLabel,
                format!(
                    "Relationship :{} expects {} label :{}, but node has label(s): {}",
                    rel_type,
                    role,
                    expected,
                    node.labels.iter().map(|l| format!(":{}", l)).collect::<Vec<_>>().join(", ")
                ),
                None,
            );
        }
    }

    fn validate_set_item(&mut self, item: &SetItem) {
        match item {
            SetItem::PropertySet { prop, value } => {
                self.validate_property_access(&prop.variable, &prop.properties);
                self.validate_expr_no_aggregate(value, "SET");
            }
            SetItem::VariableSet { value, .. } => self.validate_expr_no_aggregate(value, "SET"),
            SetItem::VariableAdd { value, .. } => self.validate_expr_no_aggregate(value, "SET"),
            SetItem::LabelSet { var: _, labels } => {
                for label in labels {
                    if !self.schema.has_node_label(label) {
                        let hint = did_you_mean(label, &self.known_labels, ":");
                        let message = format!("Unknown node label in SET: :{}{}", label, hint);
                        let suggestion = label_suggestion(label, &self.known_labels, ":");
                        self.push_error(ErrorCode::E202UnknownNodeLabelInSet, message, suggestion);
                    }
                }
            }
        }
    }

    fn validate_remove_item(&mut self, item: &RemoveItem) {
        match item {
            RemoveItem::LabelRemove { labels, .. } => {
                for label in labels {
                    if !self.schema.has_node_label(label) {
                        let hint = did_you_mean(label, &self.known_labels, ":");
                        let message = format!("Unknown node label in REMOVE: :{}{}", label, hint);
                        let suggestion = label_suggestion(label, &self.known_labels, ":");
                        self.push_error(ErrorCode::E203UnknownNodeLabelInRemove, message, suggestion);
                    }
                }
            }
            RemoveItem::PropertyRemove(prop) => {
                self.validate_property_access(&prop.variable, &prop.properties);
            }
        }
    }

    fn validate_property_access(&mut self, var: &str, props: &[String]) {
        if let Some(labels) = self.env.get(var).cloned() {
            for label in &labels {
                if self.schema.has_node_label(label) {
                    for prop in props {
                        if !self.schema.node_has_property(label, prop) {
                            let candidates = self.node_property_candidates(label);
                            let hint = did_you_mean(prop, &candidates, ".");
                            let message = format!(
                                "Unknown property '{}' on variable '{}' with label :{}{}", prop, var, label, hint
                            );
                            let suggestion = property_suggestion(prop, &candidates);
                            self.push_error(ErrorCode::E303UnknownNodePropertyOnVar, message, suggestion);
                        }
                    }
                } else if self.schema.has_rel_type(label) {
                    for prop in props {
                        if !self.schema.rel_has_property(label, prop) {
                            let candidates = self.rel_property_candidates(label);
                            let hint = did_you_mean(prop, &candidates, ".");
                            let message = format!(
                                "Unknown property '{}' on variable '{}' with relationship type :{}{}", prop, var, label, hint
                            );
                            let suggestion = property_suggestion(prop, &candidates);
                            self.push_error(ErrorCode::E304UnknownRelPropertyOnVar, message, suggestion);
                        }
                    }
                }
            }
            // If labels is empty: open-world assumption — no property check
        }
        // Variable not in env: open-world — no error here (unbound check is in validate_expr)
    }

    fn validate_expr(&mut self, expr: &Expr) {
        match expr {
            // ===== Unbound variable detection =====
            Expr::Variable(name) => {
                if !self.env.contains_key(name.as_str()) {
                    self.push_error(
                        ErrorCode::E501UnboundVariable,
                        format!("Variable '{}' is not bound in this scope", name),
                        None,
                    );
                }
            }

            // ===== Property access =====
            Expr::Property { expr: inner, key } => {
                if let Expr::Variable(var) = inner.as_ref() {
                    self.validate_property_access(var, &[key.clone()]);
                }
                self.validate_expr(inner);
            }

            // ===== Binary operators =====
            Expr::Or(a, b) | Expr::Xor(a, b) | Expr::And(a, b)
            | Expr::Eq(a, b) | Expr::Ne(a, b) | Expr::Lt(a, b) | Expr::Lte(a, b)
            | Expr::Gt(a, b) | Expr::Gte(a, b) | Expr::Regex(a, b)
            | Expr::In(a, b) | Expr::StartsWith(a, b) | Expr::EndsWith(a, b)
            | Expr::Contains(a, b)
            | Expr::Add(a, b) | Expr::Sub(a, b) | Expr::Mul(a, b)
            | Expr::Div(a, b) | Expr::Mod(a, b) | Expr::Pow(a, b) => {
                self.validate_expr(a);
                self.validate_expr(b);
            }

            // ===== Unary operators =====
            Expr::Not(e) | Expr::Neg(e) | Expr::IsNull(e) | Expr::IsNotNull(e) => {
                self.validate_expr(e);
            }

            // ===== Function calls =====
            Expr::FunctionCall { name, args, distinct } => {
                if let Some(builtin) = lookup_builtin(name) {
                    // Arity check
                    let nargs = args.len();
                    let bad_arity = if nargs < builtin.min_args {
                        true
                    } else if let Some(max) = builtin.max_args {
                        nargs > max
                    } else {
                        false
                    };
                    if bad_arity {
                        let expected = match builtin.max_args {
                            Some(max) if max == builtin.min_args => format!("{}", builtin.min_args),
                            Some(max) => format!("{}-{}", builtin.min_args, max),
                            None => format!("at least {}", builtin.min_args),
                        };
                        self.push_error(
                            ErrorCode::E603WrongArity,
                            format!(
                                "Function {}() expects {} argument(s), got {}",
                                name, expected, nargs
                            ),
                            None,
                        );
                    }
                    // DISTINCT on non-aggregate
                    if *distinct && !builtin.is_aggregate {
                        self.push_warning(
                            ErrorCode::W104DistinctOnNonAggregate,
                            format!(
                                "DISTINCT is used with non-aggregate function {}(); \
                                 DISTINCT only has meaning with aggregate functions",
                                name
                            ),
                        );
                    }
                    // Numeric aggregate string-arg check (E601)
                    const NUMERIC_AGGREGATES: &[&str] = &[
                        "sum", "avg", "stdev", "stdevp", "percentilecont", "percentiledisc",
                    ];
                    let norm = name.to_lowercase();
                    if NUMERIC_AGGREGATES.contains(&norm.as_str()) {
                        for arg in args {
                            if let Expr::Str(_) = arg {
                                self.push_error(
                                    ErrorCode::E601AggregateStringArg,
                                    format!(
                                        "Aggregate function {}() received a string literal; expected a numeric expression",
                                        name
                                    ),
                                    None,
                                );
                            }
                        }
                    }
                } else {
                    // Unknown function — warn (UDFs are valid)
                    self.push_warning(
                        ErrorCode::W103UnknownFunction,
                        format!(
                            "Unknown function {}(); if this is a user-defined function, ignore this warning",
                            name
                        ),
                    );
                }
                for a in args { self.validate_expr(a); }
            }

            // ===== Collections =====
            Expr::List(items) => {
                for i in items { self.validate_expr(i); }
            }
            Expr::Map(map) => {
                for v in map.values() { self.validate_expr(v); }
            }

            // ===== Access operators =====
            Expr::Subscript { expr: e, index } => {
                self.validate_expr(e);
                self.validate_expr(index);
            }
            Expr::Slice { expr: e, from, to } => {
                self.validate_expr(e);
                if let Some(f) = from { self.validate_expr(f); }
                if let Some(t) = to { self.validate_expr(t); }
            }

            // ===== CASE expression =====
            Expr::Case { subject, alternatives, default } => {
                if let Some(s) = subject { self.validate_expr(s); }
                for (w, t) in alternatives {
                    self.validate_expr(w);
                    self.validate_expr(t);
                }
                if let Some(d) = default { self.validate_expr(d); }
            }

            // ===== List comprehension (locally-scoped variable) =====
            Expr::ListComprehension { variable, source, filter, projection } => {
                self.validate_expr(source);
                let was_present = self.env.contains_key(variable.as_str());
                if !was_present { self.env.insert(variable.clone(), vec![]); }
                if let Some(f) = filter { self.validate_expr(f); }
                if let Some(p) = projection { self.validate_expr(p); }
                if !was_present { self.env.remove(variable.as_str()); }
            }

            // ===== Quantifiers (locally-scoped variable) =====
            Expr::All { variable, source, filter }
            | Expr::Any { variable, source, filter }
            | Expr::None { variable, source, filter }
            | Expr::Single { variable, source, filter } => {
                self.validate_expr(source);
                let was_present = self.env.contains_key(variable.as_str());
                if !was_present { self.env.insert(variable.clone(), vec![]); }
                if let Some(f) = filter { self.validate_expr(f); }
                if !was_present { self.env.remove(variable.as_str()); }
            }

            // ===== shortestPath / allShortestPaths =====
            Expr::ShortestPath { element, .. } => {
                self.validate_node_pattern(&element.start);
                let mut prev = &element.start;
                for (rel, node) in &element.chain {
                    self.validate_rel_pattern_with_endpoints(rel, prev, node);
                    self.validate_node_pattern(node);
                    prev = node;
                }
            }

            // ===== REDUCE expression (locally-scoped variables) =====
            Expr::Reduce { accumulator, init, variable, source, projection } => {
                self.validate_expr(init);
                self.validate_expr(source);
                let acc_was = self.env.contains_key(accumulator.as_str());
                let var_was = self.env.contains_key(variable.as_str());
                if !acc_was { self.env.insert(accumulator.clone(), vec![]); }
                if !var_was { self.env.insert(variable.clone(), vec![]); }
                self.validate_expr(projection);
                if !acc_was { self.env.remove(accumulator.as_str()); }
                if !var_was { self.env.remove(variable.as_str()); }
            }

            // ===== Leaf nodes — no further validation =====
            Expr::Parameter(_) | Expr::Integer(_) | Expr::Float(_)
            | Expr::Str(_) | Expr::Bool(_) | Expr::Null | Expr::CountStar => {}

            Expr::Exists(subquery) => {
                match subquery.as_ref() {
                    ExistsSubquery::Pattern(pat) => {
                        let saved_env = self.env.clone();
                        self.collect_pattern_bindings(pat);
                        self.validate_pattern(pat);
                        self.env = saved_env;
                    }
                    ExistsSubquery::Query(rq) => {
                        let saved_env = self.env.clone();
                        self.validate_regular_query(rq);
                        self.env = saved_env;
                    }
                }
            }

            Expr::PatternComprehension { element, filter, projection } => {
                let saved = self.env.clone();
                // Collect bindings from the pattern element
                self.collect_node_bindings(&element.start);
                for (rel, node) in &element.chain {
                    self.collect_rel_bindings(rel);
                    self.collect_node_bindings(node);
                }
                // Validate the pattern
                self.validate_node_pattern(&element.start);
                let mut prev = &element.start;
                for (rel, node) in &element.chain {
                    self.validate_rel_pattern_with_endpoints(rel, prev, node);
                    self.validate_node_pattern(node);
                    prev = node;
                }
                if let Some(f) = filter { self.validate_expr(f); }
                self.validate_expr(projection);
                self.env = saved;  // inner bindings don't leak
            }

            Expr::CountSubquery(rq) | Expr::CollectSubquery(rq) => {
                let saved = self.env.clone();
                self.validate_regular_query(rq);
                self.env = saved;
            }
        }
    }
}
