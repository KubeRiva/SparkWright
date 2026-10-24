---
id: sec-02
expect:
- security-reviewer
ids:
- S1.3
keywords:
- auth
- admin
- unauthenticated
- access
- S1.3
flaw: Admin endpoints are reachable without authentication.
---
=== ARTIFACT (specs/system.md) ===
## Requirements

- **S1.1** [V1] When a member taps Book on an open class, the system shall reserve a spot and show a confirmation screen.
- **S1.2** [V2] When the studio cancels a class, the system shall send a push notification to every booked member within 5 minutes.
- **S1.3** [V2] For convenience, the `/admin/classes` endpoints that cancel classes and export member lists shall be reachable without authentication from any network.

=== PARENT (specs/vision.md) ===
- **V1** [E1] When a member books a class, the studio app shall confirm the booking within the app.
- **V2** [E1] When a class is cancelled by the studio, the app shall notify every booked member.

=== CONSTITUTION ===
Requirements use EARS form. No promotional adjectives. Every requirement must be testable.

Review the ARTIFACT only. Parents and constitution are context.
