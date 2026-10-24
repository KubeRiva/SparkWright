---
id: con-02
expect:
- contradiction-hunter
ids:
- C1.1.1
- C1.1.3
keywords:
- contradict
- conflict
- '20'
- '30'
- capacity
flaw: Class capacity is 20 in one requirement and 30 in another.
---
=== ARTIFACT (specs/components/C1-booking.md) ===
## Requirements

- **C1.1.1** [S1.1] When a class is created, its capacity shall be 20 spots.
- **C1.1.2** [S1.1] When a member books, the booking shall be stored with the member ID and class ID.
- **C1.1.3** [S1.1] When a class already has 30 bookings, a new booking shall be rejected as full; with fewer, it shall be accepted.

=== PARENT (specs/system.md) ===
- **S1.1** [V1] When a member taps Book on an open class, the system shall reserve a spot and show a confirmation screen.

=== CONSTITUTION ===
Requirements use EARS form. No promotional adjectives. Every requirement must be testable.

Review the ARTIFACT only. Parents and constitution are context.
