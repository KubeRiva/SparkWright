---
id: clean-01
expect: []
ids: []
keywords: []
flaw: null
---
=== ARTIFACT (specs/components/C4-time-format.md) ===
## Interfaces

`format_time(dt: datetime) -> str`

## Requirements

- **C4.1.1** [S3.1] When `format_time(dt)` receives a timezone-aware `datetime`, it shall return the time as `HH:MM` in 24-hour form, zero-padded, in `dt`'s own timezone (for example 07:05 or 19:30).
- **C4.1.2** [S3.1] When `format_time` receives a naive `datetime` or any value that is not a `datetime`, it shall raise `TypeError` with the message `format_time needs a timezone-aware datetime`.

=== PARENT (specs/system.md) ===
- **S3.1** [V1] When the app shows a class time, the system shall show it as hours and minutes in 24-hour form, in the timezone the time was given in, and shall reject times without a timezone.

=== CONSTITUTION ===
Requirements use EARS form. No promotional adjectives. Every requirement must be testable.

Review the ARTIFACT only. Parents and constitution are context.
