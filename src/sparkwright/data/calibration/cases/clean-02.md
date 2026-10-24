---
id: clean-02
expect: []
ids: []
keywords: []
flaw: null
---
=== ARTIFACT (specs/components/C1-booking.md) ===
## Requirements

- **C1.1.1** [S1.1] When `book(member_id, class_id)` is called for a class with free spots, the booking service shall store a booking and decrement free spots by one.
- **C1.1.2** [S1.1] When `book` is called for a class with no free spots, it shall raise `ClassFull` and change nothing.
- **C1.1.3** [S1.1] When `book` is called twice for the same member and class, the second call shall raise `AlreadyBooked` and change nothing.

=== PARENT (specs/system.md) ===
- **S1.1** [V1] When a member taps Book on a class with a free spot, the system shall reserve the spot and show a confirmation screen within 2 seconds.

=== CONSTITUTION ===
Requirements use EARS form. No promotional adjectives. Every requirement must be testable.

Review the ARTIFACT only. Parents and constitution are context.
