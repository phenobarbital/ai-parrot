// ruleset.rs — CompiledRuleSet: the PyO3-exposed evaluation engine.
//
// Python serializes the (already priority-sorted) rule specs to JSON ONCE at
// RuleSet.compile(); each evaluation only crosses the boundary with a flat
// context dict. Rust returns rule INDICES — result payloads (e.g. payrates)
// stay in Python.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use rayon::prelude::*;
use serde::Deserialize;
use std::collections::HashMap;

use crate::condition::Condition;
use crate::value::{extract_context, from_json, Value};

#[derive(Deserialize)]
struct ConditionSpec {
    field: String,
    op: String,
    operand: serde_json::Value,
}

#[derive(Deserialize)]
struct RuleSpec {
    #[serde(default)]
    #[allow(dead_code)]
    priority: i64,
    conditions: Vec<ConditionSpec>,
}

pub struct CompiledRule {
    conditions: Vec<Condition>,
}

impl CompiledRule {
    fn matches(&self, ctx: &HashMap<String, Value>) -> bool {
        self.conditions
            .iter()
            .all(|c| c.matches(ctx.get(&c.field)))
    }
}

/// A compiled, immutable rule set. Rules are stored in the order Python
/// provided them (already sorted by priority, descending, stable).
#[pyclass(frozen)]
pub struct CompiledRuleSet {
    rules: Vec<CompiledRule>,
}

impl CompiledRuleSet {
    fn first_match(&self, ctx: &HashMap<String, Value>) -> Option<usize> {
        self.rules.iter().position(|rule| rule.matches(ctx))
    }
}

#[pymethods]
impl CompiledRuleSet {
    /// Index of the first matching rule (priority order), or None.
    fn evaluate_first_match(
        &self,
        py: Python<'_>,
        ctx: &Bound<'_, PyDict>,
    ) -> Option<usize> {
        let map = extract_context(ctx);
        py.allow_threads(|| self.first_match(&map))
    }

    /// True when every rule matches.
    fn evaluate_all(&self, py: Python<'_>, ctx: &Bound<'_, PyDict>) -> bool {
        let map = extract_context(ctx);
        py.allow_threads(|| self.rules.iter().all(|r| r.matches(&map)))
    }

    /// True when at least one rule matches.
    fn evaluate_any(&self, py: Python<'_>, ctx: &Bound<'_, PyDict>) -> bool {
        let map = extract_context(ctx);
        py.allow_threads(|| self.rules.iter().any(|r| r.matches(&map)))
    }

    /// Indices of every matching rule.
    fn matching_rules(&self, py: Python<'_>, ctx: &Bound<'_, PyDict>) -> Vec<usize> {
        let map = extract_context(ctx);
        py.allow_threads(|| {
            self.rules
                .iter()
                .enumerate()
                .filter(|(_, r)| r.matches(&map))
                .map(|(i, _)| i)
                .collect()
        })
    }

    /// Batch first-match over many contexts (rayon, GIL released).
    fn evaluate_batch_first_match(
        &self,
        py: Python<'_>,
        ctxs: Vec<Bound<'_, PyDict>>,
    ) -> Vec<Option<usize>> {
        // Extraction needs the GIL; matching does not.
        let maps: Vec<HashMap<String, Value>> =
            ctxs.iter().map(|d| extract_context(d)).collect();
        py.allow_threads(|| {
            maps.par_iter().map(|m| self.first_match(m)).collect()
        })
    }

    #[getter]
    fn rule_count(&self) -> usize {
        self.rules.len()
    }

    fn __repr__(&self) -> String {
        format!("<CompiledRuleSet rules={}>", self.rules.len())
    }
}

/// Compile a JSON rule-set spec (produced by navrules RuleSet.compile()).
#[pyfunction]
pub fn compile_ruleset(spec_json: &str) -> PyResult<CompiledRuleSet> {
    let specs: Vec<RuleSpec> = serde_json::from_str(spec_json)
        .map_err(|e| PyValueError::new_err(format!("invalid ruleset spec: {e}")))?;
    let mut rules = Vec::with_capacity(specs.len());
    for spec in &specs {
        let mut conditions = Vec::with_capacity(spec.conditions.len());
        for c in &spec.conditions {
            let cond = Condition::parse(&c.field, &c.op, from_json(&c.operand))
                .map_err(PyValueError::new_err)?;
            conditions.push(cond);
        }
        rules.push(CompiledRule { conditions });
    }
    Ok(CompiledRuleSet { rules })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ruleset() -> CompiledRuleSet {
        let spec = r#"[
            {"priority": 100, "conditions": [
                {"field": "env.is_weekend", "op": "eq", "operand": true},
                {"field": "ctx.worked_hours", "op": "gt", "operand": 8}
            ]},
            {"priority": 90, "conditions": [
                {"field": "env.is_weekend", "op": "eq", "operand": true}
            ]}
        ]"#;
        let specs: Vec<RuleSpec> = serde_json::from_str(spec).unwrap();
        let rules = specs
            .iter()
            .map(|s| CompiledRule {
                conditions: s
                    .conditions
                    .iter()
                    .map(|c| {
                        Condition::parse(&c.field, &c.op, from_json(&c.operand)).unwrap()
                    })
                    .collect(),
            })
            .collect();
        CompiledRuleSet { rules }
    }

    #[test]
    fn first_match_priority_and_shortcircuit() {
        let rs = ruleset();
        let mut ctx = HashMap::new();
        ctx.insert("env.is_weekend".to_string(), Value::Bool(true));
        ctx.insert("ctx.worked_hours".to_string(), Value::Int(9));
        assert_eq!(rs.first_match(&ctx), Some(0));
        ctx.insert("ctx.worked_hours".to_string(), Value::Int(6));
        assert_eq!(rs.first_match(&ctx), Some(1));
        ctx.insert("env.is_weekend".to_string(), Value::Bool(false));
        assert_eq!(rs.first_match(&ctx), None);
    }
}
