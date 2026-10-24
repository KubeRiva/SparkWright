---
id: new-02
expect:
- newcomer
- buildability-checker
ids:
- C1.2.1
keywords:
- ambiguous
- which
- unclear
- refer
flaw: C1.2.1 uses 'it' and 'the record' without saying which entity is meant.
---
=== ARTIFACT (specs/components/C1-booking.md) ===
## Requirements

- **C1.1.1** [S1.1] When a member books a class with a free spot, the booking service shall create a booking record and decrement the class's free spots.
- **C1.2.1** [S1.1] When it is updated after the other one changes, the record shall be synced and it shall be marked done.

=== PARENT (specs/system.md) ===
- **S1.1** [V1] When a member taps Book on an open class, the system shall reserve a spot and show a confirmation screen.

=== CONSTITUTION ===
Requirements use EARS form. No promotional adjectives. Every requirement must be testable.

Review the ARTIFACT only. Parents and constitution are context.
