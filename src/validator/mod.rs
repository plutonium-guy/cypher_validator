pub mod semantic;

use crate::diagnostics::{ErrorCode, Severity, ValidationDiagnostic};
use crate::schema::Schema;
use crate::parser;
use crate::validator::semantic::SemanticValidator;

#[derive(Debug, Clone)]
pub struct ValidationResult {
    pub is_valid: bool,
    /// All errors combined (backward-compatible).
    pub errors: Vec<String>,
    /// Parse/syntax errors only.
    pub syntax_errors: Vec<String>,
    /// Schema-level semantic errors only.
    pub semantic_errors: Vec<String>,
    /// Advisory warnings (not errors — query still runs, but may be slow or wrong).
    pub warnings: Vec<String>,
    /// Structured diagnostics with error codes and suggestions.
    pub diagnostics: Vec<ValidationDiagnostic>,
    /// Auto-corrected query when ALL errors have applicable suggestions.
    pub fixed_query: Option<String>,
}

/// Apply all diagnostic suggestions to `query` to produce a fixed version.
/// Returns `None` if any error diagnostic lacks a suggestion.
fn compute_fixed_query(query: &str, diagnostics: &[ValidationDiagnostic]) -> Option<String> {
    let error_diags: Vec<&ValidationDiagnostic> = diagnostics
        .iter()
        .filter(|d| d.severity == Severity::Error)
        .collect();

    if error_diags.is_empty() {
        return None; // no errors → no fix needed
    }

    // Every error must have a suggestion
    if error_diags.iter().any(|d| d.suggestion.is_none()) {
        return None;
    }

    let mut result = query.to_string();
    // Collect all (original, replacement) pairs, deduplicate, sort longest-first
    // to avoid substring conflicts. HashSet dedup avoids O(n²) `Vec::contains`.
    let mut seen: std::collections::HashSet<(&str, &str)> = std::collections::HashSet::new();
    let mut replacements: Vec<(&str, &str)> = Vec::with_capacity(error_diags.len());
    for d in &error_diags {
        if let Some(s) = &d.suggestion {
            let pair = (s.original.as_str(), s.replacement.as_str());
            if seen.insert(pair) {
                replacements.push(pair);
            }
        }
    }
    // Sort by original length descending to replace longer strings first
    replacements.sort_by(|a, b| b.0.len().cmp(&a.0.len()));

    for (original, replacement) in &replacements {
        result = result.replace(original, replacement);
    }

    Some(result)
}

pub struct CypherValidator {
    pub schema: Schema,
}

impl CypherValidator {
    pub fn new(schema: Schema) -> Self {
        CypherValidator { schema }
    }

    pub fn validate(&self, query: &str) -> ValidationResult {
        // Phase 1: syntax
        let ast = match parser::parse_with_detail(query) {
            Ok(ast) => ast,
            Err(detail) => {
                let msg = detail.error_message;
                let mut diag = ValidationDiagnostic::error(
                    ErrorCode::E101ParseError,
                    msg.clone(),
                );
                if let Some((line, col)) = detail.position {
                    diag = diag.with_position(line, col);
                }
                return ValidationResult {
                    is_valid: false,
                    errors: vec![msg.clone()],
                    syntax_errors: vec![msg],
                    semantic_errors: vec![],
                    warnings: vec![],
                    diagnostics: vec![diag],
                    fixed_query: None,
                };
            }
        };

        // Phase 2: semantic
        let mut sem = SemanticValidator::new(&self.schema);
        sem.validate_query(&ast);

        let warnings = sem.warnings;
        let semantic_errors = sem.errors;
        let errors = semantic_errors.clone();
        let is_valid = errors.is_empty();
        let diagnostics = sem.diagnostics;
        let fixed_query = if !is_valid {
            compute_fixed_query(query, &diagnostics)
        } else {
            None
        };

        ValidationResult {
            is_valid,
            errors,
            syntax_errors: vec![],
            semantic_errors,
            warnings,
            diagnostics,
            fixed_query,
        }
    }
}
