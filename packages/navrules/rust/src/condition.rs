// condition.rs — Compiled conditions and the operator matcher.
// Semantics MUST stay bit-for-bit equal to navrules/operators.py +
// navrules/conditions.py (enforced by tests/test_parity_rust.py).

use std::cmp::Ordering;

use crate::value::{value_cmp, value_eq, Value};

#[derive(Debug)]
pub enum Op {
    Eq,
    Ne,
    Gt,
    Gte,
    Lt,
    Lte,
    In,
    NotIn,
    Contains,
    StartsWith,
    EndsWith,
    Regex(regex::Regex),
    Between,
    IsNull,
}

#[derive(Debug)]
pub struct Condition {
    pub field: String,
    pub op: Op,
    pub operand: Value,
}

impl Condition {
    pub fn parse(field: &str, op: &str, operand: Value) -> Result<Self, String> {
        let op = match op {
            "eq" => Op::Eq,
            "ne" => Op::Ne,
            "gt" => Op::Gt,
            "gte" => Op::Gte,
            "lt" => Op::Lt,
            "lte" => Op::Lte,
            "in" => Op::In,
            "not_in" => Op::NotIn,
            "contains" => Op::Contains,
            "startswith" => Op::StartsWith,
            "endswith" => Op::EndsWith,
            "between" => Op::Between,
            "is_null" => Op::IsNull,
            "regex" => {
                let pattern = match &operand {
                    Value::Str(s) => s.clone(),
                    other => format!("{other:?}"),
                };
                let re = regex::Regex::new(&pattern)
                    .map_err(|e| format!("invalid regex for field {field:?}: {e}"))?;
                Op::Regex(re)
            }
            other => return Err(format!("unknown operator {other:?} for field {field:?}")),
        };
        Ok(Condition {
            field: field.to_string(),
            op,
            operand,
        })
    }

    /// Evaluate against an (optionally missing) context value.
    /// Missing values only match is_null — everything else is False.
    pub fn matches(&self, value: Option<&Value>) -> bool {
        let missing = value.is_none();
        if let Op::IsNull = self.op {
            let operand_truthy = match &self.operand {
                Value::Bool(b) => *b,
                Value::Null => false,
                Value::Int(i) => *i != 0,
                Value::Float(f) => *f != 0.0,
                Value::Str(s) => !s.is_empty(),
                Value::List(l) => !l.is_empty(),
            };
            return missing == operand_truthy;
        }
        let Some(value) = value else { return false };

        match &self.op {
            Op::Eq => value_eq(value, &self.operand),
            Op::Ne => !value_eq(value, &self.operand),
            Op::Gt => matches!(value_cmp(value, &self.operand), Some(Ordering::Greater)),
            Op::Gte => matches!(
                value_cmp(value, &self.operand),
                Some(Ordering::Greater) | Some(Ordering::Equal)
            ),
            Op::Lt => matches!(value_cmp(value, &self.operand), Some(Ordering::Less)),
            Op::Lte => matches!(
                value_cmp(value, &self.operand),
                Some(Ordering::Less) | Some(Ordering::Equal)
            ),
            Op::In => match &self.operand {
                Value::List(items) => items.iter().any(|i| value_eq(value, i)),
                _ => false,
            },
            Op::NotIn => match &self.operand {
                Value::List(items) => !items.iter().any(|i| value_eq(value, i)),
                _ => false,
            },
            Op::Contains => match (value, &self.operand) {
                (Value::Str(v), Value::Str(o)) => v.contains(o.as_str()),
                (Value::List(items), operand) => {
                    items.iter().any(|i| value_eq(i, operand))
                }
                _ => false,
            },
            Op::StartsWith => match (value, &self.operand) {
                (Value::Str(v), Value::Str(o)) => v.starts_with(o.as_str()),
                _ => false,
            },
            Op::EndsWith => match (value, &self.operand) {
                (Value::Str(v), Value::Str(o)) => v.ends_with(o.as_str()),
                _ => false,
            },
            Op::Regex(re) => match value {
                Value::Str(v) => re.is_match(v),
                _ => false,
            },
            Op::Between => match &self.operand {
                Value::List(bounds) if bounds.len() == 2 => {
                    let ge_low = matches!(
                        value_cmp(value, &bounds[0]),
                        Some(Ordering::Greater) | Some(Ordering::Equal)
                    );
                    let le_high = matches!(
                        value_cmp(value, &bounds[1]),
                        Some(Ordering::Less) | Some(Ordering::Equal)
                    );
                    ge_low && le_high
                }
                _ => false,
            },
            Op::IsNull => unreachable!(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cond(op: &str, operand: Value) -> Condition {
        Condition::parse("f", op, operand).unwrap()
    }

    #[test]
    fn missing_only_matches_is_null() {
        assert!(!cond("eq", Value::Int(1)).matches(None));
        assert!(!cond("ne", Value::Int(1)).matches(None));
        assert!(cond("is_null", Value::Bool(true)).matches(None));
        assert!(!cond("is_null", Value::Bool(false)).matches(None));
        assert!(cond("is_null", Value::Bool(false)).matches(Some(&Value::Int(1))));
    }

    #[test]
    fn between_inclusive() {
        let c = cond(
            "between",
            Value::List(vec![Value::Int(1), Value::Int(10)]),
        );
        assert!(c.matches(Some(&Value::Int(1))));
        assert!(c.matches(Some(&Value::Float(10.0))));
        assert!(!c.matches(Some(&Value::Int(11))));
    }

    #[test]
    fn regex_is_search_like() {
        let c = cond("regex", Value::Str(r"job-\d+".into()));
        assert!(c.matches(Some(&Value::Str("xx job-123 yy".into()))));
        assert!(!c.matches(Some(&Value::Str("nope".into()))));
    }

    #[test]
    fn unknown_operator_errors() {
        assert!(Condition::parse("f", "wat", Value::Null).is_err());
    }
}
