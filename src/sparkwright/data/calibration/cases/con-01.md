---
id: con-01
expect:
- contradiction-hunter
ids:
- S1.2
- S2.1
keywords:
- contradict
- conflict
- S1.2
- S2.1
- '24'
- never
flaw: S1.2 and S2.1 disagree on the cancellation window.
---
=== ARTIFACT (specs/system.md) ===
## Requirements

- **S1.1** [V1] When a member taps Book on an open class, the system shall reserve a spot and show a confirmation screen.
- **S1.2** [V1] When a member cancels a booking less than 24 hours before the class, the system shall refuse the cancellation.
- **S2.1** [V2] When a member cancels a booking at any time before the class starts, the system shall release the spot and refund the credit.
- **S2.2** [V2] When the studio cancels a class, the system shall notify every booked member by push notification.

=== PARENT (specs/vision.md) ===
- **V1** [E1] When a member books a class, the studio app shall confirm the booking within the app.
- **V2** [E1] When a class is cancelled by the studio, the app shall notify every booked member.

=== CONSTITUTION ===
Requirements use EARS form. No promotional adjectives. Every requirement must be testable.

Review the ARTIFACT only. Parents and constitution are context.
