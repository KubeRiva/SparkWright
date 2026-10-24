---
id: cov-01
expect:
- coverage-auditor
ids:
- V2
keywords:
- V2
- cancel
- notif
flaw: System level omits Vision V2 (cancellation notices).
---
=== ARTIFACT (specs/system.md) ===
## Requirements

- **S1.1** [V1] When a member taps Book on an open class, the system shall reserve a spot and show a confirmation screen.
- **S1.2** [V1] When a class is full, the system shall show a waitlist option.

=== PARENT (specs/vision.md) ===
- **V1** [E1] When a member books a class, the studio app shall confirm the booking within the app.
- **V2** [E1] When a class is cancelled by the studio, the app shall notify every booked member.

=== CONSTITUTION ===
Requirements use EARS form. No promotional adjectives. Every requirement must be testable.

Review the ARTIFACT only. Parents and constitution are context.
