---
id: E02
title: Owner interview — open design items (2026-10-24)
type: evidence
source: owner interview (structured, multiple choice with free text)
consent: "owner requested the interview in chat"
simulated: false
status: in-review
---

## Statements

- **Q1.** Approvals should count only when committed by a git author on an approver allowlist; signing optional.
- **Q2.** When a change request touches one task, only that task should change status; siblings in the same file stay approved.
- **Q3.** Keep readable hierarchical IDs; record moves as renames in a change request.
- **Q4.** Publish SparkWright under the KubeRiva family: github.com/kuberiva, copyright KubeRiva.
- **Q5.** Day-to-day use will be through a Claude Code subscription, not API keys.
- **Q6.** Set up git now and dogfood on a real project (ChessTutor) now.

## Themes

| Theme | Name | Statements |
| --- | --- | --- |
| T1 | Verifiable human control without setup burden | Q1 |
| T2 | Precise, minimal blast radius for change | Q2, Q3 |
| T3 | Part of the KubeRiva open-source family | Q4 |
| T4 | Host-agent-first operation (no API keys) | Q5 |
| T5 | Prove it on real work early | Q6 |
