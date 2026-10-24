---
id: cov-02
expect:
- coverage-auditor
ids:
- S1.3
keywords:
- S1.3
- scope
- loyalty
- points
flaw: S1.3 adds a loyalty-points feature no Vision line asks for.
---
=== ARTIFACT (specs/system.md) ===
## Requirements

- **S1.1** [V1] When a member taps Book on an open class, the system shall reserve a spot and show a confirmation screen.
- **S1.2** [V2] When the studio cancels a class, the system shall send a push notification to every booked member within 5 minutes.
- **S1.3** [V1] When a member attends 10 classes, the system shall award 500 loyalty points redeemable for merchandise.

=== PARENT (specs/vision.md) ===
- **V1** [E1] When a member books a class, the studio app shall confirm the booking within the app.
- **V2** [E1] When a class is cancelled by the studio, the app shall notify every booked member.

=== CONSTITUTION ===
Requirements use EARS form. No promotional adjectives. Every requirement must be testable.

Review the ARTIFACT only. Parents and constitution are context.
