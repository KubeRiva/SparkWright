---
id: bld-01
expect:
- buildability-checker
ids:
- S1.2
keywords:
- testable
- intuitive
- measur
- vague
- S1.2
flaw: S1.2 ('intuitive and delightful') cannot be tested.
---
=== ARTIFACT (specs/system.md) ===
## Requirements

- **S1.1** [V1] When a member taps Book on an open class, the system shall reserve a spot and show a confirmation screen within 2 seconds.
- **S1.2** [V1] The booking flow shall be intuitive and delightful for every member.
- **S2.1** [V2] When the studio cancels a class, the system shall send a push notification to every booked member within 5 minutes.

=== PARENT (specs/vision.md) ===
- **V1** [E1] When a member books a class, the studio app shall confirm the booking within the app.
- **V2** [E1] When a class is cancelled by the studio, the app shall notify every booked member.

=== CONSTITUTION ===
Requirements use EARS form. No promotional adjectives. Every requirement must be testable.

Review the ARTIFACT only. Parents and constitution are context.
