---
id: cov-03
expect:
- coverage-auditor
ids:
- S2.1
keywords:
- moved
- reschedul
- time change
- new time
flaw: S2.1 covers classes cancelled or moved to another time; the component only handles
  cancellation.
---
=== ARTIFACT (specs/components/C3-notify.md) ===
## Requirements

- **C3.1.1** [S2.1] When `notify_cancellation(class_id)` runs, the notifier shall send one push message to each member with an active booking on that class.
- **C3.1.2** [S2.1] When a push message fails, the notifier shall retry it up to 3 times at 1-minute intervals and then log the failure with the member ID.

=== PARENT (specs/system.md) ===
- **S2.1** [V2] When the studio cancels a class or moves it to another time, the system shall notify every member booked on it within 5 minutes, stating what changed.

=== CONSTITUTION ===
Requirements use EARS form. No promotional adjectives. Every requirement must be testable.

Review the ARTIFACT only. Parents and constitution are context.
