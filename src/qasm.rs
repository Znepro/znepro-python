//! OpenQASM canonicalizer for outbound job payloads.
//!
//! OpenQASM 3 headers, `qubit`/`bit` declarations, and `c = measure q`
//! assignments become OpenQASM 2. `cnot` becomes `cx` with the same control,
//! target order. Gate angles accept decimal literals, scientific notation, and
//! arithmetic `pi` expressions.

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

/// Rewrite OpenQASM 3 syntax, gate aliases, and angle expressions.
pub fn canonicalize_qasm(source: &str) -> Result<String, QasmError> {
    let lines = prepare_lines(source)?;
    let (quantum, classical) = collect_registers(&lines);
    let mut out = Vec::with_capacity(lines.len());
    for line in &lines {
        out.push(canonicalize_line(line, &quantum, &classical)?);
    }
    Ok(finish(source, &out))
}

/// Gates in source order, after the same normalization `canonicalize_qasm` applies.
pub fn qasm_gates(source: &str) -> Result<Vec<QasmGate>, QasmError> {
    let lines = prepare_lines(source)?;
    let (quantum, classical) = collect_registers(&lines);
    let mut gates = Vec::new();
    for line in &lines {
        let code = statement_code(line);
        if !code.is_empty() && rewrite_measure(code, &quantum, &classical)?.is_some() {
            continue;
        }
        if let Some(gate) = parse_gate_line(line, &quantum)? {
            gates.push(gate);
        }
    }
    Ok(gates)
}

fn finish(source: &str, lines: &[String]) -> String {
    let mut text = lines.join("\n");
    if source.ends_with('\n') || !text.is_empty() {
        text.push('\n');
    }
    text
}

fn prepare_lines(source: &str) -> Result<Vec<String>, QasmError> {
    let mut lines = Vec::new();
    let mut oq3 = false;
    let mut has_qelib = false;
    for raw in source.lines() {
        let line = raw.trim_end_matches('\r');
        let code = statement_code(line);
        if code.is_empty() {
            lines.push(line.to_owned());
            continue;
        }
        if let Some((header, is_oq3)) = rewrite_header(code) {
            oq3 |= is_oq3;
            lines.push(header);
            continue;
        }
        if let Some((include, std)) = rewrite_include(code) {
            has_qelib |= std;
            lines.push(include);
            continue;
        }
        if let Some(decl) = rewrite_typed_decl(code)? {
            lines.push(decl);
            continue;
        }
        lines.push(line.to_owned());
    }
    if oq3 && !has_qelib {
        if let Some(pos) = lines.iter().position(|line| line.starts_with("OPENQASM ")) {
            lines.insert(pos + 1, "include \"qelib1.inc\";".to_owned());
        }
    }
    Ok(lines)
}

fn collect_registers(lines: &[String]) -> (Vec<QuantumReg>, Vec<QuantumReg>) {
    let mut quantum = Vec::new();
    let mut classical = Vec::new();
    for line in lines {
        let code = statement_code(line);
        let mut parts = code.split_whitespace();
        let kind = parts.next().unwrap_or("").to_ascii_lowercase();
        let Some(decl) = parts.next() else {
            continue;
        };
        if parts.next().is_some() {
            continue;
        }
        let Some((name, length)) = split_index(decl) else {
            continue;
        };
        let register = QuantumReg { name, length };
        if kind == "qreg" {
            quantum.push(register);
        } else if kind == "creg" {
            classical.push(register);
        }
    }
    (quantum, classical)
}

fn canonicalize_line(
    line: &str,
    quantum: &[QuantumReg],
    classical: &[QuantumReg],
) -> Result<String, QasmError> {
    let code = statement_code(line);
    if code.is_empty() {
        return Ok(line.to_owned());
    }
    if let Some(measure) = rewrite_measure(code, quantum, classical)? {
        return Ok(measure);
    }
    if let Some(gate) = parse_gate_line(line, quantum)? {
        return Ok(format_gate(&gate));
    }
    Ok(line.to_owned())
}

fn statement_code(line: &str) -> &str {
    strip_comment(line).trim().trim_end_matches(';').trim()
}

fn keyword_rest<'a>(code: &'a str, keyword: &str) -> Option<&'a str> {
    if code.len() < keyword.len() || !code[..keyword.len()].eq_ignore_ascii_case(keyword) {
        return None;
    }
    let rest = &code[keyword.len()..];
    if rest.starts_with(|ch: char| ch.is_ascii_alphanumeric() || ch == '_') {
        return None;
    }
    Some(rest)
}

fn rewrite_header(code: &str) -> Option<(String, bool)> {
    let rest = keyword_rest(code, "openqasm")?;
    let version = rest.trim().trim_end_matches(';').trim();
    Some(("OPENQASM 2.0;".to_owned(), version.starts_with('3')))
}

fn rewrite_include(code: &str) -> Option<(String, bool)> {
    let rest = keyword_rest(code, "include")?.trim();
    let path = rest.trim_matches(|ch| ch == '"' || ch == '\'');
    let std = path.eq_ignore_ascii_case("stdgates.inc") || path.eq_ignore_ascii_case("qelib1.inc");
    let line = if std {
        "include \"qelib1.inc\";".to_owned()
    } else {
        format!("include {rest};")
    };
    Some((line, std))
}

fn rewrite_typed_decl(code: &str) -> Result<Option<String>, QasmError> {
    let (kind, rest) = if let Some(rest) = keyword_rest(code, "qubit") {
        ("qreg", rest.trim_start())
    } else if let Some(rest) = keyword_rest(code, "bit") {
        ("creg", rest.trim_start())
    } else {
        return Ok(None);
    };
    let (length, name_src) = if let Some(rest) = rest.strip_prefix('[') {
        let Some(close) = rest.find(']') else {
            return Err(QasmError::Target(code.to_owned()));
        };
        let length = rest[..close]
            .trim()
            .parse::<u32>()
            .map_err(|_| QasmError::Target(code.to_owned()))?;
        if length == 0 {
            return Err(QasmError::Target(code.to_owned()));
        }
        (length, rest[close + 1..].trim_start())
    } else {
        (1, rest)
    };
    let Some((name, trailing)) = take_ident(name_src) else {
        return Err(QasmError::Target(code.to_owned()));
    };
    if !trailing.is_empty() {
        return Err(QasmError::Target(code.to_owned()));
    }
    Ok(Some(format!("{kind} {name}[{length}];")))
}

fn take_ident(token: &str) -> Option<(&str, &str)> {
    let token = token.trim_start();
    let mut chars = token.chars();
    let first = chars.next()?;
    if !first.is_ascii_alphabetic() && first != '_' {
        return None;
    }
    let mut len = first.len_utf8();
    for ch in chars {
        if ch.is_ascii_alphanumeric() || ch == '_' {
            len += ch.len_utf8();
        } else {
            break;
        }
    }
    Some((&token[..len], token[len..].trim_start()))
}

fn rewrite_measure(
    code: &str,
    quantum: &[QuantumReg],
    classical: &[QuantumReg],
) -> Result<Option<String>, QasmError> {
    if let Some((lhs, rhs)) = code.split_once('=') {
        let rhs = rhs.trim();
        let Some(target) = keyword_rest(rhs, "measure") else {
            return Ok(None);
        };
        let target = target.trim().trim_end_matches(';').trim();
        let lhs = lhs.trim();
        if target.is_empty() || lhs.is_empty() {
            return Err(QasmError::Target(code.to_owned()));
        }
        check_endpoint(target, quantum)?;
        check_endpoint(lhs, classical)?;
        return Ok(Some(format!("measure {target} -> {lhs};")));
    }
    let Some(rest) = keyword_rest(code, "measure") else {
        return Ok(None);
    };
    let rest = rest.trim();
    if rest.is_empty() {
        return Err(QasmError::Target(code.to_owned()));
    }
    if let Some((qubit, clbit)) = rest.split_once("->") {
        let qubit = qubit.trim();
        let clbit = clbit.trim().trim_end_matches(';').trim();
        if qubit.is_empty() || clbit.is_empty() {
            return Err(QasmError::Target(code.to_owned()));
        }
        check_endpoint(qubit, quantum)?;
        check_endpoint(clbit, classical)?;
        return Ok(Some(format!("measure {qubit} -> {clbit};")));
    }
    check_endpoint(rest, quantum)?;
    Ok(Some(format!("measure {rest};")))
}

fn check_endpoint(token: &str, registers: &[QuantumReg]) -> Result<(), QasmError> {
    if let Some((name, index)) = split_index(token) {
        if let Some(register) = registers.iter().find(|item| item.name == name) {
            if index >= register.length {
                return Err(QasmError::Target(token.to_owned()));
            }
        }
        return Ok(());
    }
    if registers.is_empty() || registers.iter().any(|item| item.name == token) {
        return Ok(());
    }
    Err(QasmError::Target(token.to_owned()))
}

fn parse_gate_line(line: &str, registers: &[QuantumReg]) -> Result<Option<QasmGate>, QasmError> {
    let code = strip_comment(line).trim().trim_end_matches(';').trim();
    if code.is_empty() {
        return Ok(None);
    }
    let (call, args) = split_call(code);
    let opcode = call
        .split('(')
        .next()
        .unwrap_or("")
        .trim()
        .to_ascii_lowercase();
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
    let value = parser
        .parse_expr()
        .map_err(|_| QasmError::Angle(raw.to_owned()))?;
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
    let index = token[open + 1..token.len() - 1]
        .trim()
        .parse::<u32>()
        .ok()?;
    Some((name.to_owned(), index))
}

#[cfg(test)]
mod tests {
    use super::{canonicalize_qasm, qasm_gates, QasmError};

    #[test]
    fn compound_pi_matches_the_decimal_literal() {
        let expr = qasm_gates("OPENQASM 2.0;\nqreg q[2];\nry(3*pi/4) q[1];\n").expect("expr");
        let lit =
            qasm_gates("OPENQASM 2.0;\nqreg q[2];\nry(2.356194490192345) q[1];\n").expect("lit");
        assert!((expr[0].parameters[0] - lit[0].parameters[0]).abs() < 1e-15);
        assert!((expr[0].parameters[0] - 2.356194490192345).abs() < 1e-14);
        assert_eq!(expr[0].qubits[0].index, 1);
        for sample in [
            "-3*pi/4",
            "(3*pi)/4",
            "2*pi/3",
            "0.5*pi",
            "1.5707963267948966e0",
        ] {
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

    #[test]
    fn openqasm3_braket_program_normalizes_to_openqasm2() {
        let source = "\
OPENQASM 3.0;
include \"stdgates.inc\";
qubit[2] q;
bit[2] c;
h q[0];
cnot q[0], q[1];
ry(3*pi/4) q[1];
c = measure q;
";
        let text = canonicalize_qasm(source).expect("oq3");
        assert!(text.starts_with("OPENQASM 2.0;\ninclude \"qelib1.inc\";\n"));
        assert!(text.contains("qreg q[2];"));
        assert!(text.contains("creg c[2];"));
        assert!(!text.contains("qubit["));
        assert!(!text.contains("bit["));
        assert!(!text.to_ascii_lowercase().contains("cnot"));
        assert!(text.contains("cx q[0], q[1];"));
        assert!(text.contains("measure q -> c;"));
        assert!(!text.contains("stdgates"));
        assert!(!text.contains("OPENQASM 3"));
        assert_eq!(canonicalize_qasm(&text).expect("again"), text);
        let gates = qasm_gates(source).expect("gates");
        assert_eq!(gates[0].name, "h");
        assert_eq!(gates[1].name, "cx");
        assert_eq!(
            gates[1].qubits.iter().map(|q| q.index).collect::<Vec<_>>(),
            vec![0, 1]
        );
        assert_eq!(gates[2].name, "ry");
        assert!((gates[2].parameters[0] - 2.356194490192345).abs() < 1e-14);
        let literal =
            qasm_gates("OPENQASM 2.0;\nqreg q[2];\nry(2.356194490192345) q[1];\n").expect("lit");
        assert!((gates[2].parameters[0] - literal[0].parameters[0]).abs() < 1e-14);
    }

    #[test]
    fn openqasm3_register_and_measure_forms() {
        let text =
            canonicalize_qasm("OPENQASM 3;\nqubit q;\nbit c;\nc[0] = measure q[0];\nmeasure q;\n")
                .expect("forms");
        assert!(text.contains("OPENQASM 2.0;"));
        assert!(text.contains("include \"qelib1.inc\";"));
        assert!(text.contains("qreg q[1];"));
        assert!(text.contains("creg c[1];"));
        assert!(text.contains("measure q[0] -> c[0];"));
        assert!(text.contains("measure q;"));
        let indexed = canonicalize_qasm(
            "OPENQASM 2.0;\nqreg q[2];\ncreg c[2];\nc[1] = measure q[1];\nmeasure q[0];\n",
        )
        .expect("indexed");
        assert!(indexed.contains("measure q[1] -> c[1];"));
        assert!(indexed.contains("measure q[0];"));
        assert!(!indexed.contains("include "));
        let decl = canonicalize_qasm("qubit[2] q;\n").expect("decl");
        assert!(decl.starts_with("qreg q[2];"));
        let range = qasm_gates("OPENQASM 3.0;\nqubit[2] q;\nry(pi/2) q[9];\n").expect_err("range");
        assert!(range.to_string().contains("malformed target qubit 'q[9]'"));
        assert!(!range.to_string().contains("malformed angle expression"));
    }
}
