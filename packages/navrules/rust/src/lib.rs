// _navrules — native backend for the navrules rule engine.
//
// Exposes:
//   compile_ruleset(spec_json: str) -> CompiledRuleSet
//   CompiledRuleSet.evaluate_first_match(ctx: dict) -> int | None
//   CompiledRuleSet.evaluate_batch_first_match(ctxs: list[dict]) -> list[int | None]
//   CompiledRuleSet.evaluate_all / evaluate_any / matching_rules

use pyo3::prelude::*;

mod condition;
mod ruleset;
mod value;

use ruleset::{compile_ruleset, CompiledRuleSet};

#[pymodule]
fn _navrules(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<CompiledRuleSet>()?;
    m.add_function(wrap_pyfunction!(compile_ruleset, m)?)?;
    m.add("__rust_backend__", true)?;
    Ok(())
}
