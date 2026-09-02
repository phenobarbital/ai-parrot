use std::collections::HashMap;
/// A document parser.
#[derive(Debug)]
pub struct Parser { cfg: Config }
impl Parser {
    /// Create a parser.
    pub fn new(config: Config) -> Self { todo!() }
    fn private_helper(&self) {}
}
/// Visits every node.
pub trait Visitor { fn visit(&self); }
pub mod utils;
pub enum Kind { A, B }
fn not_pub() {}
