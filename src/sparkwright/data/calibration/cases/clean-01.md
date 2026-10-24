---
id: clean-01
expect: []
ids: []
keywords: []
flaw: null
---
=== ARTIFACT (specs/system.md) ===
## Requirements

- **S1.1** [V1] When a member taps Book on a class with a free spot, the system shall reserve the spot and show a confirmation screen within 2 seconds.
- **S1.2** [V1] When a member taps Book on a class with no free spot, the system shall show 'Class full' and offer the waitlist.
- **S2.1** [V2] When the studio cancels a class, the system shall send a push notification to every member booked on it within 5 minutes and release their credits.

=== PARENT (specs/vision.md) ===
- **V1** [E1] When a member books a class, the studio app shall confirm the booking within the app.
- **V2** [E1] When a class is cancelled by the studio, the app shall notify every booked member.

=== CONSTITUTION ===
Requirements use EARS form. No promotional adjectives. Every requirement must be testable.

Review the ARTIFACT only. Parents and constitution are context.
