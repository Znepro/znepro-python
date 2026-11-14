//! OpenQASM 2.0 canonicalizer for outbound job payloads.
//!
//! `cnot` becomes `cx` with the same control, target order. Gate angles accept
//! decimal literals, scientific notation, and arithmetic `pi` expressions.

use thiserror::Error;

/// A parsed gate after alias and angle normalization.
#[derive(Debug, Clone, PartialEq)]
pub struct QasmGate {
    pub name: String,
    pub qubits: Vec<QubitRef>,
    pub parameters: Vec<f64>,
}

/// One quantum operand, still named by its register.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct QubitRef {
    pub register: String,
    pub index: u32,
}

#[derive(Debug, Error, Clone, PartialEq, Eq)]
pub enum QasmError {
    #[error("malformed angle expression '{0}'")]
    Angle(String),
    #[error("malformed target qubit '{0}'")]
    Target(String),
}

struct QuantumReg {
    name: String,
    length: u32,
}

/// Rewrite gate aliases and angle expressions. Non-gate lines are preserved.
pub fn canonicalize_qasm(source: &str) -> Result<String, QasmError> {
    let registers = quantum_registers(source);
    let mut out = Vec::new();
    for line in source.lines() {
        out.push(canonicalize_line(line, &registers)?);
    }
    let mut text = out.join("\n");
    if source.ends_with('\n') || !text.is_empty() {
        text.push('\n');
    }
    Ok(text)
}

/// Gates in source order, after the same normalization `canonicalize_qasm` applies.
pub fn qasm_gates(source: &str) -> Result<Vec<QasmGate>, QasmError> {
    let registers = quantum_registers(source);
    let mut gates = Vec::new();
    for line in source.lines() {
        if let Some(gate) = parse_gate_line(line, &registers)? {
            gates.push(gate);
        }
    }
    Ok(gates)
}

fn quantum_registers(source: &str) -> Vec<QuantumReg> {
    let mut registers = Vec::new();
    for line in source.lines() {
        let code = strip_comment(line).trim().trim_end_matches(';').trim();
        let mut parts = code.split_whitespace();
        let kind = parts.next().unwrap_or("").to_ascii_lowercase();
        if kind != "qreg" {
            continue;
        }
        let Some(decl) = parts.next() else {
            continue;
        };
        let Some((name, length)) = split_index(decl) else {
            continue;
        };
        registers.push(QuantumReg { name, length });
    }
    registers
}

fn canonicalize_line(line: &str, registers: &[QuantumReg]) -> Result<String, QasmError> {
    let Some(gate) = parse_gate_line(line, registers)? else {
        return Ok(line.to_owned());
    };
    Ok(format_gate(&gate))
}

fn parse_gate_line(line: &str, registers: &[QuantumReg]) -> Result<Option<QasmGate>, QasmError> {
    let code = strip_comment(line).trim().trim_end_matches(';').trim();
    if code.is_empty() {
        return Ok(None);
    }
    let (call, args) = split_call(code);
    let opcode = call.split('(').next().unwrap_or("").trim().to_ascii_lowercase();
    if matches!(
        opcode.as_str(),
        "openqasm" | "include" | "qreg" | "creg" | "barrier" | "measure" | "reset" | "gate" | "if"
    ) {
        return Ok(None);
    }
    if opcode.is_empty() || args.is_empty() && !call.contains('(') {
        return Ok(None);
    }
    let (name, parameters) = split_name_and_parameters(call)?;
    let qubits = resolve_qubits(args, registers)?;
    Ok(Some(QasmGate {
        name,
        qubits,
        parameters,
    }))
}

fn format_gate(gate: &QasmGate) -> String {
    let args = gate
        .qubits
        .iter()
        .map(|qubit| format!("{}[{}]", qubit.register, qubit.index))
        .collect::<Vec<_>>()
        .join(", ");
    if gate.parameters.is_empty() {
        format!("{} {};", gate.name, args)
    } else {
        let params = gate
            .parameters
            .iter()
            .map(|value| format_angle(*value))
            .collect::<Vec<_>>()
            .join(",");
        format!("{}({}) {};", gate.name, params, args)
    }
}

fn format_angle(value: f64) -> String {
    let mut text = format!("{value:.16}");
    if let Some(dot) = text.find('.') {
        while text.ends_with('0') && text.len() > dot + 2 {
            text.pop();
        }
    }
    text
}

fn strip_comment(line: &str) -> &str {
    line.split("//").next().unwrap_or(line)
}

fn split_call(statement: &str) -> (&str, &str) {
    match statement.find(char::is_whitespace) {
        Some(pos) => (&statement[..pos], statement[pos + 1..].trim()),
        None => (statement, ""),
    }
}

fn split_name_and_parameters(call: &str) -> Result<(String, Vec<f64>), QasmError> {
    let call = call.trim();
    if let Some(open) = call.find('(') {
        if !call.ends_with(')') {
            return Err(QasmError::Angle(call.to_owned()));
        }
        let name = canonicalize_gate_name(&call[..open]);
        let inside = &call[open + 1..call.len() - 1];
        let mut parameters = Vec::new();
        if !inside.trim().is_empty() {
            for piece in inside.split(',') {
                parameters.push(parse_angle(piece.trim())?);
            }
        }
        return Ok((name, parameters));
    }
    Ok((canonicalize_gate_name(call), Vec::new()))
}

fn canonicalize_gate_name(raw: &str) -> String {
    let name = raw.trim().to_ascii_lowercase();
    if name == "cnot" {
        "cx".to_owned()
    } else {
        name
    }
}

fn parse_angle(raw: &str) -> Result<f64, QasmError> {
    let mut parser = AngleParser {
        bytes: raw.trim().as_bytes(),
        index: 0,
    };
    let value = parser.parse_expr().map_err(|_| QasmError::Angle(raw.to_owned()))?;
    parser.skip_ws();
    if parser.index != parser.bytes.len() || !value.is_finite() {
        return Err(QasmError::Angle(raw.to_owned()));
    }
    Ok(value)
}

struct AngleParser<'a> {
    bytes: &'a [u8],
    index: usize,
}

impl<'a> AngleParser<'a> {
    fn parse_expr(&mut self) -> Result<f64, ()> {
        let mut value = self.parse_term()?;
        loop {
            self.skip_ws();
            match self.peek() {
                Some(b'+') => {
                    self.bump();
                    value += self.parse_term()?;
                }
                Some(b'-') => {
                    self.bump();
                    value -= self.parse_term()?;
                }
                _ => return Ok(value),
            }
        }
    }

    fn parse_term(&mut self) -> Result<f64, ()> {
        let mut value = self.parse_factor()?;
        loop {
            self.skip_ws();
            match self.peek() {
                Some(b'*') => {
                    self.bump();
                    value *= self.parse_factor()?;
                }
                Some(b'/') => {
                    self.bump();
                    let divisor = self.parse_factor()?;
                    if divisor == 0.0 {
                        return Err(());
                    }
                    value /= divisor;
                }
                _ => return Ok(value),
            }
        }
    }

    fn parse_factor(&mut self) -> Result<f64, ()> {
        self.skip_ws();
        if self.peek() == Some(b'-') {
            self.bump();
            return Ok(-self.parse_factor()?);
        }
        if self.peek() == Some(b'+') {
            self.bump();
            return self.parse_factor();
        }
        if self.peek() == Some(b'(') {
            self.bump();
            let value = self.parse_expr()?;
            self.skip_ws();
            if self.peek() != Some(b')') {
                return Err(());
            }
            self.bump();
            return Ok(value);
        }
        if self.starts_with_pi() {
            self.index += 2;
            return Ok(std::f64::consts::PI);
        }
        self.parse_number()
    }

    fn parse_number(&mut self) -> Result<f64, ()> {
        let start = self.index;
        while matches!(self.peek(), Some(b'0'..=b'9') | Some(b'.')) {
            self.bump();
        }
        if matches!(self.peek(), Some(b'e') | Some(b'E')) {
            let mark = self.index;
            self.bump();
            if matches!(self.peek(), Some(b'+') | Some(b'-')) {
                self.bump();
            }
            let digits = self.index;
            while matches!(self.peek(), Some(b'0'..=b'9')) {
                self.bump();
            }
            if self.index == digits {
                self.index = mark;
            }
        }
        if self.index == start {
            return Err(());
        }
        let text = std::str::from_utf8(&self.bytes[start..self.index]).map_err(|_| ())?;
        text.parse::<f64>().map_err(|_| ())
    }

    fn starts_with_pi(&self) -> bool {
        let end = self.index + 2;
        end <= self.bytes.len()
            && self.bytes[self.index].eq_ignore_ascii_case(&b'p')
            && self.bytes[self.index + 1].eq_ignore_ascii_case(&b'i')
            && !self
                .bytes
                .get(end)
                .copied()
                .is_some_and(|byte| byte.is_ascii_alphanumeric())
    }

    fn skip_ws(&mut self) {
        while matches!(self.peek(), Some(b' ' | b'\t')) {
            self.bump();
        }
    }

    fn peek(&self) -> Option<u8> {
        self.bytes.get(self.index).copied()
    }

    fn bump(&mut self) {
        self.index += 1;
    }
}

fn resolve_qubits(args: &str, registers: &[QuantumReg]) -> Result<Vec<QubitRef>, QasmError> {
    let mut qubits = Vec::new();
    for token in args.split(',') {
        let token = token.trim();
        if token.is_empty() {
            continue;
        }
        let endpoint = token.split("->").next().unwrap_or(token).trim();
        qubits.push(resolve_one(endpoint, registers)?);
    }
    if qubits.is_empty() {
        return Err(QasmError::Target(args.to_owned()));
    }
    Ok(qubits)
}

fn resolve_one(token: &str, registers: &[QuantumReg]) -> Result<QubitRef, QasmError> {
    let Some((name, index)) = split_index(token) else {
        return Err(QasmError::Target(token.to_owned()));
    };
    if let Some(register) = registers.iter().find(|item| item.name == name) {
        if index >= register.length {
            return Err(QasmError::Target(token.to_owned()));
        }
    }
    Ok(QubitRef {
        register: name,
        index,
    })
}

fn split_index(token: &str) -> Option<(String, u32)> {
    let token = token.trim();
    let open = token.find('[')?;
    if !token.ends_with(']') {
        return None;
    }
    let name = token[..open].trim();
    if name.is_empty() {
        return None;
    }
    let index = token[open + 1..token.len() - 1].trim().parse::<u32>().ok()?;
    Some((name.to_owned(), index))
}

#[cfg(test)]
mod tests {
    use super::{canonicalize_qasm, qasm_gates, QasmError};

    #[test]
    fn compound_pi_matches_the_decimal_literal() {
        let expr = qasm_gates("OPENQASM 2.0;\nqreg q[2];\nry(3*pi/4) q[1];\n").expect("expr");
        let lit = qasm_gates("OPENQASM 2.0;\nqreg q[2];\nry(2.356194490192345) q[1];\n").expect("lit");
        assert!((expr[0].parameters[0] - lit[0].parameters[0]).abs() < 1e-15);
        assert!((expr[0].parameters[0] - 2.356194490192345).abs() < 1e-14);
        assert_eq!(expr[0].qubits[0].index, 1);
        for sample in ["-3*pi/4", "(3*pi)/4", "2*pi/3", "0.5*pi", "1.5707963267948966e0"] {
            let qasm = format!("OPENQASM 2.0;\nqreg q[1];\nry({sample}) q[0];\n");
            let parsed = qasm_gates(&qasm).unwrap_or_else(|_| panic!("{sample}"));
            assert!(parsed[0].parameters[0].is_finite(), "{sample}");
        }
        let rewritten = canonicalize_qasm("ry(3*pi/4) q[1];\n").expect("rewrite");
        let again = qasm_gates(&rewritten).expect("again");
        assert!((again[0].parameters[0] - expr[0].parameters[0]).abs() < 1e-15);
    }

    #[test]
    fn cnot_keeps_control_then_target() {
        let cnot = qasm_gates("OPENQASM 2.0;\nqreg q[2];\ncnot q[0], q[1];\n").expect("cnot");
        let cx = qasm_gates("OPENQASM 2.0;\nqreg q[2];\ncx q[0], q[1];\n").expect("cx");
        assert_eq!(cnot[0].name, "cx");
        assert_eq!(cx[0].name, "cx");
        assert_eq!(cnot[0].qubits[0].index, 0);
        assert_eq!(cnot[0].qubits[1].index, 1);
        assert_eq!(
            cnot[0].qubits.iter().map(|q| q.index).collect::<Vec<_>>(),
            cx[0].qubits.iter().map(|q| q.index).collect::<Vec<_>>()
        );
        let text = canonicalize_qasm("CNOT q[0], q[1];\n").expect("text");
        assert!(text.contains("cx q[0], q[1];"));
    }

    #[test]
    fn angle_errors_stay_distinct_from_target_errors() {
        let angle = qasm_gates("OPENQASM 2.0;\nqreg q[1];\nry(3*pi/) q[0];\n").expect_err("angle");
        assert!(matches!(angle, QasmError::Angle(_)));
        assert!(angle.to_string().contains("malformed angle expression"));
        assert!(!angle.to_string().contains("malformed target qubit"));
        let qubit = qasm_gates("OPENQASM 2.0;\nqreg q[1];\nry(pi/2) q[9];\n").expect_err("qubit");
        assert!(matches!(qubit, QasmError::Target(_)));
        assert!(qubit.to_string().contains("malformed target qubit"));
        assert!(!qubit.to_string().contains("malformed angle expression"));
    }
}
