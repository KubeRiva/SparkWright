---
id: sec-03
expect:
- security-reviewer
ids:
- S9.2
keywords:
- password
- plaintext
- plain text
- hash
- email
flaw: S9.2 emails the member's current password, which requires storing it recoverably.
---
=== ARTIFACT (specs/system.md) ===
## Requirements

- **S9.1** [V1] When a member signs in with email and password, the system shall open the member's schedule.
- **S9.2** [V1] When a member taps Forgot password, the system shall email the member their current password.

=== PARENT (specs/vision.md) ===
- **V1** [E1] When a member books a class, the studio app shall confirm the booking within the app.
- **V2** [E1] When a class is cancelled by the studio, the app shall notify every booked member.

=== CONSTITUTION ===
Requirements use EARS form. No promotional adjectives. Every requirement must be testable.

Review the ARTIFACT only. Parents and constitution are context.
