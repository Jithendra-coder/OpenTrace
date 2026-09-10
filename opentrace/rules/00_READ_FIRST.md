# OpenTrace: Read First

OpenTrace is an API Change Intelligence and Adaptive Migration Platform: it determines what an API contract change may break, explains the evidence, proposes controlled repairs, and validates them. Its permanent lifecycle is **DETECT → UNDERSTAND → PREDICT → ROUTE → REPAIR → VALIDATE → LEARN**.

`rules/` is authoritative over every other repository document and all ad-hoc assumptions. Read `CURRENT_STATE.md` first to establish whether work is authorized and which milestone is current. `08_MILESTONE_ROADMAP.md` is the sole roadmap; `CURRENT_STATE.md` is operational state, never a competing roadmap. Implement only the current milestone. Architecture changes require an ADR in `adr/`.

Before implementation, read this file, `CURRENT_STATE.md`, `43_CANONICAL_TERMINOLOGY.md`, `08_MILESTONE_ROADMAP.md`, `09_MILESTONE_EXECUTION_RULES.md`, `37_DEFINITION_OF_DONE.md`, the current milestone's specification, `07_INPUT_OUTPUT_CONTRACTS.md`, and each relevant subsystem/security/test rule. Inspect existing implementation and tests before editing. Report unsupported and unresolved behavior explicitly; never silently guess. Metrics require reproducible evidence; demo outputs must be actual analysis, never hardcoded. Every milestone requires real execution and tests.

## Mandatory agent checklist

### BEFORE CODING

- [ ] Read `00_READ_FIRST.md`
- [ ] Read `CURRENT_STATE.md`
- [ ] Read `43_CANONICAL_TERMINOLOGY.md`
- [ ] Read current milestone specification
- [ ] Read relevant subsystem specifications
- [ ] Inspect existing implementation
- [ ] Inspect existing tests
- [ ] Confirm current milestone boundary
- [ ] Confirm prohibited future features

## Governance precedence

1. This rules tree and accepted ADRs
2. Current milestone specification and roadmap
3. Existing verified tests/contracts
4. Task instructions that do not conflict with 1–3

If sources conflict, stop, document the conflict, and resolve it through an ADR or explicit project-owner decision.
