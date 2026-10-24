---
id: con-03
expect:
- contradiction-hunter
ids:
- C6.1.2
- S5.1
keywords:
- utc
- timezone
- time zone
- local time
flaw: The parent requires studio-local times; C6.1.2 displays UTC.
---
=== ARTIFACT (specs/components/C6-schedule.md) ===
## Requirements

- **C6.1.1** [S5.1] When a class is created, the schedule service shall store its start time as a UTC timestamp.
- **C6.1.2** [S5.1] When the schedule screen lists classes, it shall show each start time as stored, formatted `HH:MM`.

=== PARENT (specs/system.md) ===
- **S5.1** [V1] When a member views the schedule, the system shall show each class's start time in the studio's local time.

=== CONSTITUTION ===
Requirements use EARS form. No promotional adjectives. Every requirement must be testable.

Review the ARTIFACT only. Parents and constitution are context.
