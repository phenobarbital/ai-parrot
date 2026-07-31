// value.rs — Scalar value model shared by extraction and matching.
// Adapted from querysource rust/src/filter_common.rs (FilterValue), with one
// difference: floats are never collapsed to ints, the comparison layer does
// numeric coercion instead (mirroring navrules/operators.py exactly).

use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::collections::HashMap;

/// A context/operand value. Send + Sync so rayon can share compiled rules.
#[derive(Debug, Clone, PartialEq)]
pub enum Value {
    Str(String),
    Int(i64),
    Float(f64),
    Bool(bool),
    List(Vec<Value>),
    Null,
}

/// Recursively extract a Python object into a Value (runs on GIL thread).
pub fn extract_value(obj: &Bound<'_, PyAny>) -> Value {
    // bool MUST be probed before int: Python bool is an int subclass.
    if let Ok(b) = obj.extract::<bool>() {
        return Value::Bool(b);
    }
    if let Ok(i) = obj.extract::<i64>() {
        return Value::Int(i);
    }
    if let Ok(f) = obj.extract::<f64>() {
        return Value::Float(f);
    }
    if let Ok(s) = obj.extract::<String>() {
        return Value::Str(s);
    }
    if let Ok(list) = obj.extract::<Vec<Bound<'_, PyAny>>>() {
        return Value::List(list.iter().map(extract_value).collect());
    }
    Value::Null
}

/// Extract a flat context dict {field: scalar} into a Rust map.
/// None values are treated as absent (the Python flatten() already drops
/// them, this is defense in depth).
pub fn extract_context(dict: &Bound<'_, PyDict>) -> HashMap<String, Value> {
    let mut map = HashMap::with_capacity(dict.len());
    for (key_obj, value_obj) in dict.iter() {
        if let Ok(key) = key_obj.extract::<String>() {
            let value = extract_value(&value_obj);
            if !matches!(value, Value::Null) {
                map.insert(key, value);
            }
        }
    }
    map
}

/// Build a Value from a JSON operand (rule compilation path).
pub fn from_json(v: &serde_json::Value) -> Value {
    match v {
        serde_json::Value::Bool(b) => Value::Bool(*b),
        serde_json::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                Value::Int(i)
            } else {
                Value::Float(n.as_f64().unwrap_or(f64::NAN))
            }
        }
        serde_json::Value::String(s) => Value::Str(s.clone()),
        serde_json::Value::Array(items) => {
            Value::List(items.iter().map(from_json).collect())
        }
        _ => Value::Null,
    }
}

fn as_number(v: &Value) -> Option<f64> {
    match v {
        Value::Int(i) => Some(*i as f64),
        Value::Float(f) => Some(*f),
        _ => None,
    }
}

/// Equality with the exact semantics of navrules.operators._eq:
/// bool never coerces to number; int/float coerce to each other; lists
/// compare elementwise with these same rules.
pub fn value_eq(a: &Value, b: &Value) -> bool {
    match (a, b) {
        (Value::Bool(x), Value::Bool(y)) => x == y,
        (Value::Bool(_), _) | (_, Value::Bool(_)) => false,
        (Value::Str(x), Value::Str(y)) => x == y,
        (Value::List(x), Value::List(y)) => {
            x.len() == y.len() && x.iter().zip(y.iter()).all(|(i, j)| value_eq(i, j))
        }
        _ => match (as_number(a), as_number(b)) {
            (Some(x), Some(y)) => x == y,
            _ => false,
        },
    }
}

/// Ordering comparison: number pairs or str pairs only (operators._ordering).
pub fn value_cmp(a: &Value, b: &Value) -> Option<std::cmp::Ordering> {
    if let (Some(x), Some(y)) = (as_number(a), as_number(b)) {
        return x.partial_cmp(&y);
    }
    if let (Value::Str(x), Value::Str(y)) = (a, b) {
        return Some(x.cmp(y));
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn eq_numeric_coercion() {
        assert!(value_eq(&Value::Int(8), &Value::Float(8.0)));
        assert!(!value_eq(&Value::Bool(true), &Value::Int(1)));
        assert!(value_eq(&Value::Bool(true), &Value::Bool(true)));
    }

    #[test]
    fn eq_lists_elementwise() {
        let a = Value::List(vec![Value::Int(1), Value::Str("x".into())]);
        let b = Value::List(vec![Value::Float(1.0), Value::Str("x".into())]);
        assert!(value_eq(&a, &b));
        let c = Value::List(vec![Value::Bool(true)]);
        let d = Value::List(vec![Value::Int(1)]);
        assert!(!value_eq(&c, &d));
    }

    #[test]
    fn cmp_str_and_numbers_only() {
        use std::cmp::Ordering;
        assert_eq!(
            value_cmp(&Value::Int(9), &Value::Float(8.5)),
            Some(Ordering::Greater)
        );
        assert_eq!(
            value_cmp(&Value::Str("a".into()), &Value::Str("b".into())),
            Some(Ordering::Less)
        );
        assert_eq!(value_cmp(&Value::Str("9".into()), &Value::Int(8)), None);
    }
}
