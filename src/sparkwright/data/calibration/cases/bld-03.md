---
id: bld-03
expect:
- buildability-checker
ids:
- C7.1.2
keywords:
- reasonable
- measur
- testable
- vague
- number
- how long
flaw: C7.1.2 says 'within a reasonable time'.
---
=== ARTIFACT (specs/components/C7-waitlist.md) ===
## Requirements

- **C7.1.1** [S8.1] When a booked member cancels, the waitlist service shall offer the freed spot to the first member on the waitlist.
- **C7.1.2** [S8.1] When an offered member does not accept within a reasonable time, the waitlist service shall offer the spot to the next member.

=== PARENT (specs/system.md) ===
- **S8.1** [V1] When a spot frees up in a full class, the system shall offer it to waitlisted members in the order they joined.

=== CONSTITUTION ===
Requirements use EARS form. No promotional adjectives. Every requirement must be testable.

Review the ARTIFACT only. Parents and constitution are context.
