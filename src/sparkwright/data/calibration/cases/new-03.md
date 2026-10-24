---
id: new-03
expect:
- newcomer
ids:
- S6.1
keywords:
- format
- columns
- fields
- csv
- which
- standard
flaw: '''The standard export format'' is never defined.'
---
=== ARTIFACT (specs/system.md) ===
## Requirements

- **S6.1** [V1] When a studio admin taps Export, the system shall produce the member list in the standard export format and email it to the admin.
- **S6.2** [V2] When the studio cancels a class, the system shall send a push notification to every booked member within 5 minutes.

=== PARENT (specs/vision.md) ===
- **V1** [E1] When a member books a class, the studio app shall confirm the booking within the app.
- **V2** [E1] When a class is cancelled by the studio, the app shall notify every booked member.

=== CONSTITUTION ===
Requirements use EARS form. No promotional adjectives. Every requirement must be testable.

Review the ARTIFACT only. Parents and constitution are context.
