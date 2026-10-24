---
id: new-01
expect:
- newcomer
ids:
- S1.1
- S1.2
keywords:
- jargon
- undefined
- define
- FOB
- PQ
- LMS
- acronym
- unclear
flaw: Undefined acronyms (FOB, PQ, LMS) make the spec unreadable to a newcomer.
---
=== ARTIFACT (specs/system.md) ===
## Requirements

- **S1.1** [V1] When a FOB is confirmed, the system shall write it to the PQ and sync the LMS.
- **S1.2** [V2] When the LMS flags a CX event, the system shall fan out over the PQ to all FOB holders.

=== PARENT (specs/vision.md) ===
- **V1** [E1] When a member books a class, the studio app shall confirm the booking within the app.
- **V2** [E1] When a class is cancelled by the studio, the app shall notify every booked member.

=== CONSTITUTION ===
Requirements use EARS form. No promotional adjectives. Every requirement must be testable.

Review the ARTIFACT only. Parents and constitution are context.
