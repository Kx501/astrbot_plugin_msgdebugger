# Transparent debugger

Open **AstrBot WebUI → Plugins → MsgDebugger → Pages → logs**, send a message, and select its record in the sidebar. The page uses eight tabs: Overview, Model input, Plugin changes, Tools, Skills, Request comparison, Tokens and timing, and Echo and collection. The current UI uses Chinese labels.

The sidebar refreshes automatically. Details remain stable while reading; use the selected record's refresh button to update them. The sidebar shows the latest 200 records and supports text, user and session search.

## Reading observations

Plugin attribution reports state changes across registered message handler execution boundaries. It preserves return values, exceptions and generator yields. Downstream work between generator resumes is excluded. Nested calls and concurrent mutations mean a boundary observation is not exclusive line-level attribution. Plugin-submitted reports are labeled separately.

The built-in agent adapter records individual runner attempts before provider conversion, each with its own ID and response. It does not capture final HTTP payloads, hidden model reasoning, provider-internal retries, arbitrary background tasks or all third-party agent paths. Unsupported adapters are explicitly shown as unavailable.

Tools distinguish the live registered inventory, historical offered definitions and actual tool-start events. Skills display current local/plugin files and literal name/path matches in historical input; neither installation nor a text match proves the model read the full skill. Sandbox-only and workspace-specific skills may be missing from the catalog.

Request comparison selects a previous record in the same session by default. Choose any record and attempt manually, then compare base instructions/tools or all content. Instructions embedded in user messages require the all-content scope.

Provider-reported token usage is shown per attempt; missing usage is not zero. Cached input is already part of input totals. Character-count/4 distributions are rough estimates, not model tokenization or billing. Failed or unobserved attempts may make totals incomplete.

## Echo and storage

New installations leave echo off. Existing configured defaults are retained on upgrade. Administrators can use `/md echo on|off|status|reset`, or the page controls. Temporary overrides reset on reload. Configure passive/proactive sending, plain/full-chain content and echo-only allowlists in plugin settings. No other plugin is required.

Records use `traces.sqlite3` in the plugin data directory. Retention defaults to 200 records; the configured range is 10–1000. Limits are 256 KiB per stage, 2 MiB/300 stages per trace and about 64 MiB of stored content. Inline base64 media is omitted and truncation is marked. Storage failure degrades to memory and is displayed. The database imports legacy JSONL on first creation without deleting it; clearing the page does not remove that legacy backup. Storage uses the Python standard library SQLite driver; the only third-party runtime dependency is `PyYAML`, used to read Skill frontmatter (see `requirements.txt`).

Export offers a preview, hiding top-level identity fields and some common credential patterns. Review conversation bodies and tool arguments before sharing; automatic redaction is not comprehensive.

## Upgrade mapping

The **logs** page URL is unchanged. The former Compact/Injection/Full presets become the eight tabs above. Injection details move to Plugin changes and Request comparison. The echo command remains, now administrator-only. Historical records cannot reconstruct missing per-attempt snapshots.

Optional integrations append versioned objects to `event.get_extra("_msgdebugger_events", [])` and write the resulting list back with `event.set_extra`. Fields are `version: 1`, `source`, `kind`, `summary` and `data`. Reports must be written before the debugger request hook at priority -10000; up to 100 reports are consumed there. They are labeled self-reported. No debugger import is needed. Legacy `_md_injection` and `_ii_injected` integration keys are no longer collected.

See the [Chinese README](../../README.md) for a complete integration example and development commands. Internal adapters are version-sensitive; the minimum installation version does not guarantee every observation feature on every AstrBot release.

## Guided investigation and compact reader

Select a group or private contact in the sidebar, then open one message record. Group identity includes the platform instance; separate members in the same group share the group section. Unknown legacy identities remain grouped by their original session. Each group has a paginated record list.

Start in Overview: it summarizes the trigger, observed model requests, tools and changing plugins. Logs separate preparation, individual model requests, tool execution, agent output, pre-send processing, and send completion in observed order. A pre-send hook can occur during a sub-agent run and does not prove that the whole conversation has ended. The same clickable flow stays above every tab. Input, tools and comparison retain the selected attempt; plugin changes and usage cover the whole record.

![Guided conversation overview, using synthetic data](../images/conversation-overview.png)

Model input now uses a paginated directory (8 messages per page) and a single-message reader. It initially selects the last `user`, which may contain injected context. Fifty input messages can belong to one model request. Sequence numbers describe positions in that request's message list, not individual API calls.

The expandable beginner guide explains `model`, `messages`, `tools`, generated responses, `usage`, role relationships and the tool execution loop, plus the extra user content parts. Each selected message shows its role's meaning and immediate neighbors. The generated response is shown separately from input. Use role filters or content search to find a specific message.

For later attempts, the page compares the unchanged prefix against the previous attempt in this trace. A shortcut selects the first new or changed position; it does not claim that all differences are appends. Detailed two-request comparison remains available in its own tab.

![Single-message input reader, using synthetic data](../images/input-reader.png)

Navigation mapping: the former long input card list becomes the directory/reader; the flat overview log becomes collapsed flow segments; the flat sidebar becomes grouped records. The eight tabs and `logs` page URL remain. Compact spacing and independent desktop scroll areas reserve more room for content, with a stacked narrow-screen layout. Reload the plugin to capture group/private metadata for new records; missing legacy metadata is not guessed.

## Changes and collection status

Skill switches and owning plugin activation are shown separately. AstrBot filters skills from inactive or unregistered plugins even if their skill switches remain on. The selected request inventory remains the evidence of what was offered.

Plugin changes now show a compact deletion/addition diff above the original snapshots. Long diffs are marked as truncated; reopening old records also computes diffs.

Skills separates the selected request inventory from current local files and global switches. Persona and configuration filters can reduce the request inventory. A listed skill is not proof of reading or execution. Refresh the current catalog after changing switches. Custom prompt formats and truncated snapshots may not be recognized.

New records support AstrBot Pydantic v1 message components. Missing component data in old snapshots cannot be recovered. GeneratorExit after a final response is no longer an error; closure or cancellation before a final response is an interruption. Historical false positives remain annotated with their original payloads.
