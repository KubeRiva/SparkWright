---
id: clean-02
expect: []
ids: []
keywords: []
flaw: null
---
=== ARTIFACT (specs/components/C5-credits.md) ===
## Interfaces

`Wallet.balance(member_id) -> int`; `Wallet.spend(member_id) -> None`; `Wallet.refund(member_id) -> None`. `NoCredit` is raised by `spend`.

## Requirements

- **C5.1.1** [S4.1] When `spend(member_id)` is called and the member's balance is at least 1, the wallet shall reduce the balance by exactly 1.
- **C5.1.2** [S4.1] When `spend(member_id)` is called and the balance is 0, the wallet shall raise `NoCredit` and leave the balance at 0.
- **C5.1.3** [S4.2] When `refund(member_id)` is called, the wallet shall increase the balance by exactly 1.
- **C5.1.4** [S4.1, S4.2] `spend` and `refund` on the same member shall be applied one at a time in call order, so that concurrent calls never lose an update.

=== PARENT (specs/system.md) ===
- **S4.1** [V1] When a member books a class, the system shall take one credit, and shall refuse the booking when the member has no credit.
- **S4.2** [V2] When the studio cancels a booked class, the system shall return the credit to each booked member.

=== CONSTITUTION ===
Requirements use EARS form. No promotional adjectives. Every requirement must be testable.

Review the ARTIFACT only. Parents and constitution are context.
