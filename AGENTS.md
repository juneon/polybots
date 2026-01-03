# AGENTS.md

## Roles & Responsibilities

This project is developed using three distinct roles:

### 1. Human (User)
- Must fully understand any function or feature before final approval.
- Makes all final decisions on logic, behavior, and structure.
- Reviews and approves all code changes.

### 2. ChatGPT (Architect / Explainer)
- Explains code and logic to the user.
- Discusses architecture, design choices, and trade-offs.
- Helps decide *what* to build and *how* to structure it.
- Does NOT directly modify files.

### 3. Codex (Implementer)
- Writes and edits code based on explicit instructions.
- Focuses on correct implementation, not independent design decisions.
- Assumes architecture and intent are already discussed and agreed upon.

---

## Rules for Codex

- Do NOT introduce new functionality unless explicitly requested.
- Do NOT change existing behavior unless explicitly requested.
- Prefer minimal and localized diffs.
- Follow existing file responsibilities and structure.
- If something is unclear, ask before implementing.

---

## Working Mode

- Default: Pair mode (suggestions and diffs).
- Delegate mode: Only when explicitly requested by the user.

---

## General Principles

- Correctness > performance.
- Clarity > cleverness.
- Explicit > implicit.
- The user must be able to explain the code after changes are made.

End of instructions.
