---
id: bld-02
expect:
- buildability-checker
ids:
- C1.1.1
keywords:
- invalid
- error
- malformed
- edge
- not specified
- C1.1.1
flaw: C1.1.1 never says what happens with an invalid date string.
---
=== ARTIFACT (specs/components/C2-dates.md) ===
## Requirements

- **C2.1.1** [S1.1] When `parse_class_time(text)` receives an ISO 8601 date-time string, it shall return a timezone-aware datetime in the studio's timezone.

=== PARENT (specs/system.md) ===
- **S1.1** [V1] When a member taps Book on an open class, the system shall reserve a spot and show a confirmation screen.

=== CONSTITUTION ===
Requirements use EARS form. No promotional adjectives. Every requirement must be testable.

Review the ARTIFACT only. Parents and constitution are context.
