//! File: codec-rs/src/lib.rs
//!
//! Optional Rust acceleration for the `columnar` compression codec
//! (FEAT-380, TASK-1955). A single FFI crossing: JSON bytes/str in ->
//! parse -> transform -> JSON bytes out, with the transform itself run
//! under `py.allow_threads()` so the GIL is released for the duration.
//!
//! This module implements ONLY the core columnarization algorithm — the
//! exact counterpart of `ColumnarCodec._columnarize()` in
//! `parrot/tools/compression/codecs/columnar.py` (the Python
//! implementation is the executable specification this must match
//! byte-for-byte). All of the *outer* concerns (min_rows / heterogeneity /
//! nested-value guards, QueryResult unwrapping, size measurement,
//! `CompressionOutcome` construction) stay in Python — by the time this
//! function is called, the Python side has already confirmed the input is
//! eligible for columnarization.
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use serde_json::{Map, Value};

/// Split row-oriented JSON (`[{...}, {...}, ...]`) into the columnar
/// `{"columns": [...], "rows": [[...], ...], "constants": {...}}` form.
///
/// Column order is derived from the data (first-seen order across rows,
/// in each row's own key order) — never sorted, matching the Python
/// reference implementation's determinism guarantee (G4).
///
/// `min_rows` is accepted for parity with the Python codec's signature,
/// but the min-rows guard is evaluated by the PYTHON caller before this
/// function is ever invoked; it is not re-checked here (harmless no-op
/// when the input already satisfies it).
fn columnarize_json(payload: &[u8], _min_rows: usize) -> Result<Vec<u8>, String> {
    let rows: Vec<Map<String, Value>> = serde_json::from_slice::<Vec<Value>>(payload)
        .map_err(|e| format!("invalid row-oriented JSON: {e}"))?
        .into_iter()
        .map(|v| match v {
            Value::Object(m) => Ok(m),
            other => Err(format!("expected a JSON object row, got: {other}")),
        })
        .collect::<Result<Vec<_>, String>>()?;

    // -- column extraction: first-seen order across rows ------------------
    let mut columns: Vec<String> = Vec::new();
    {
        let mut seen = std::collections::HashSet::new();
        for row in &rows {
            for key in row.keys() {
                if seen.insert(key.clone()) {
                    columns.push(key.clone());
                }
            }
        }
    }

    // -- null-column elision: a column that is null/absent in EVERY row --
    let null_cols: Vec<String> = columns
        .iter()
        .filter(|c| {
            rows.iter()
                .all(|row| matches!(row.get(*c), None | Some(Value::Null)))
        })
        .cloned()
        .collect();
    columns.retain(|c| !null_cols.contains(c));

    // -- constant-column factoring: only when there is more than one row --
    let mut constants: Map<String, Value> = Map::new();
    if rows.len() > 1 {
        let mut factored: Vec<String> = Vec::new();
        for col in columns.iter() {
            let first = rows[0].get(col).cloned().unwrap_or(Value::Null);
            let all_equal = rows
                .iter()
                .all(|row| row.get(col).cloned().unwrap_or(Value::Null) == first);
            if all_equal {
                constants.insert(col.clone(), first);
                factored.push(col.clone());
            }
        }
        columns.retain(|c| !factored.contains(c));
    }

    // -- build positional rows, aligned to the final `columns` list -------
    let out_rows: Vec<Vec<Value>> = rows
        .iter()
        .map(|row| {
            columns
                .iter()
                .map(|c| row.get(c).cloned().unwrap_or(Value::Null))
                .collect()
        })
        .collect();

    let mut result = Map::new();
    result.insert(
        "columns".to_string(),
        Value::Array(columns.into_iter().map(Value::String).collect()),
    );
    result.insert(
        "rows".to_string(),
        Value::Array(out_rows.into_iter().map(Value::Array).collect()),
    );
    result.insert("constants".to_string(), Value::Object(constants));

    serde_json::to_vec(&Value::Object(result)).map_err(|e| format!("serialization error: {e}"))
}

/// Columnarize a row-oriented JSON payload (bytes or str), GIL released
/// for the duration of the transform.
///
/// Args:
///     payload: UTF-8 JSON bytes/str encoding a `list[dict]` of rows.
///     min_rows: Accepted for parity with the Python codec's signature;
///         not re-checked here (the Python caller already applied the
///         guard before calling this function).
///
/// Returns:
///     UTF-8 JSON bytes encoding `{"columns", "rows", "constants"}`.
#[pyfunction]
#[pyo3(signature = (payload, min_rows=20))]
fn columnarize(py: Python<'_>, payload: &[u8], min_rows: usize) -> PyResult<Vec<u8>> {
    let owned = payload.to_vec();
    // pyo3 0.29 renamed `Python::allow_threads` -> `Python::detach`
    // (verified against this crate's pinned pyo3 version, `Cargo.toml`);
    // functionally identical GIL-release mechanism (spec's own "Pattern
    // to Follow" used the older `allow_threads` name).
    py.detach(move || columnarize_json(&owned, min_rows))
        .map_err(PyRuntimeError::new_err)
}

#[pymodule]
fn parrot_codec(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(columnarize, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn run(input: &str) -> Value {
        let out = columnarize_json(input.as_bytes(), 20).expect("transform failed");
        serde_json::from_slice(&out).expect("invalid output JSON")
    }

    #[test]
    fn column_order_is_first_seen_not_sorted() {
        let out = run(r#"[{"z":1,"a":2},{"z":3,"a":4}]"#);
        assert_eq!(out["columns"], serde_json::json!(["z", "a"]));
    }

    #[test]
    fn null_columns_are_elided() {
        let out = run(r#"[{"a":1,"b":null},{"a":2,"b":null}]"#);
        assert_eq!(out["columns"], serde_json::json!(["a"]));
    }

    #[test]
    fn missing_key_counts_as_null_for_elision() {
        // "b" is entirely absent from every row -> same as always-null.
        let out = run(r#"[{"a":1},{"a":2}]"#);
        assert_eq!(out["columns"], serde_json::json!(["a"]));
    }

    #[test]
    fn constant_columns_are_factored_when_more_than_one_row() {
        let out = run(r#"[{"a":1,"region":"south"},{"a":2,"region":"south"}]"#);
        assert_eq!(out["columns"], serde_json::json!(["a"]));
        assert_eq!(out["constants"], serde_json::json!({"region": "south"}));
    }

    #[test]
    fn single_row_never_factors_constants() {
        let out = run(r#"[{"a":1,"b":2}]"#);
        assert_eq!(out["constants"], serde_json::json!({}));
        assert_eq!(out["columns"], serde_json::json!(["a", "b"]));
    }

    #[test]
    fn rows_are_positionally_aligned_with_null_padding_for_missing_keys() {
        let out = run(r#"[{"a":1,"c":3},{"a":2}]"#);
        // "c" appears in row 0 only, and is not all-null (present+non-null
        // in row 0) so it stays a column; row 1 is missing it -> null.
        assert_eq!(out["columns"], serde_json::json!(["a", "c"]));
        assert_eq!(out["rows"], serde_json::json!([[1, 3], [2, Value::Null]]));
    }

    #[test]
    fn determinism_same_input_same_output() {
        let input = r#"[{"a":1,"b":null,"region":"south"},{"a":2,"b":null,"region":"south"}]"#;
        let first = run(input);
        for _ in 0..25 {
            assert_eq!(run(input), first);
        }
    }

    #[test]
    fn rejects_non_array_input() {
        let err = columnarize_json(br#"{"not": "an array"}"#, 20);
        assert!(err.is_err());
    }

    #[test]
    fn rejects_non_object_rows() {
        let err = columnarize_json(br#"[1, 2, 3]"#, 20);
        assert!(err.is_err());
    }
}
