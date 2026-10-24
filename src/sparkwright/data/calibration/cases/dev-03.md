---
id: dev-03
expect:
- devils-advocate
ids:
- S7.1
keywords:
- single
- sqlite
- front-desk
- availability
- backup
- scal
- offline
flaw: All app data lives in one SQLite file on the front-desk PC, served to every
  phone over the internet.
---
=== ARTIFACT (specs/system.md) ===
## Requirements

- **S7.1** [V1] All bookings, members and schedules shall be stored in one SQLite file on the studio's front-desk PC, which the mobile app reads and writes over the internet.
- **S7.2** [V1] When a member taps Book on a class with a free spot, the system shall reserve the spot and show a confirmation screen.
- **S7.3** [V2] When the studio cancels a class, the system shall send a push notification to every booked member within 5 minutes.

=== PARENT (specs/vision.md) ===
- **V1** [E1] When a member books a class, the studio app shall confirm the booking within the app.
- **V2** [E1] When a class is cancelled by the studio, the app shall notify every booked member.

=== CONSTITUTION ===
Requirements use EARS form. No promotional adjectives. Every requirement must be testable.

Review the ARTIFACT only. Parents and constitution are context.
