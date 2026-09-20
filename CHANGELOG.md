# Changelog

## Unreleased

- Declare `PyYAML` in `requirements.txt`, the only dependency beyond AstrBot and the standard library.
- Fix Pydantic v1 message snapshots and false GeneratorExit errors after final responses.
- Add bounded plugin change diffs, including existing records.
- Separate request skill-directory evidence from current global skill switches and add catalog refresh.

## 2.0.0

- Add a guided conversation flow that remains visible across tabs, a beginner API/role guide, and an eight-item message directory with a single-message reader.
- Group records by platform instance and group/private contact; keep unknown legacy identities separate.
- Replace flat overview logs with collapsed flow segments and link later attempts to their first changed message. Reduce header, card and toolbar spacing.
- Navigation mapping: long input cards → directory/reader; flat overview log → flow segments; flat sidebar → contact/group sections. Existing tabs and the logs entry remain.

- Rebuild the debugger around conversation records and eight task-oriented tabs.
- Observe plugin handler boundaries with reversible adapters and explicit attribution limits.
- Capture built-in runner attempts, detached input/tool snapshots, responses and reported usage.
- Add tool and local Skill catalogs, request comparison, export preview and collection coverage.
- Preserve passive/proactive echo without requiring other plugins; add page controls and restrict chat controls to administrators. New installations default echo to off.
- Replace whole-file JSONL rewrites with bounded SQLite storage. Import existing JSONL while preserving the original archive.
- Replace Compact / Injection / Full presets with Overview / Model input / Plugin changes / Tools / Skills / Request comparison / Tokens and timing / Echo and collection. The `logs` page entry remains unchanged.
- Move injection inspection to Plugin changes and Request comparison. Replace `_md_injection` / `_ii_injected` collection with the optional `_msgdebugger_events` report list.
- Capture at the runner boundary rather than claiming wire-level visibility. Mark unavailable adapters, missing usage and truncated content explicitly.
