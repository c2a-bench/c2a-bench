Directory:
sources/confluence/support-playbooks

Target number of files:
150

This is a recursive target: it includes JSON documents in this directory and its approvals-and-limits, case-handling, escalation, and templates subdirectories.

File name format:
Use descriptive, lowercase kebab-case names ending in .json, naming the case type or workflow. Do not put internal ids, rule numbers or words like old, outdated or wrong in names.

Content rules:
Agent-facing playbooks in plain language: steps for handling a kind of case, what to check in the booking, how to talk to the customer, templates for replies. A playbook states only the policy sentences given in its own description; its steps must not add amounts, limits, fees, deadlines or approval thresholds of their own. Playbooks without policy sentences in their description cover general handling (greeting, verifying identity, writing notes, closing a case) with no rules or amounts.

Policy content (strict):
A document may state a customer-policy rule, fee, amount, limit, deadline or approval threshold ONLY if that exact sentence is given in this document's own description, in the part that says "It must contain these sentences word for word". Copy those sentences word for word. Never invent, add, round, paraphrase or complete policy numbers or rules, and never restate rules that belong to other documents. A document whose description gives no such sentences must contain no customer-policy rules or amounts at all: it is about everyday work.
Never say that a document or policy is outdated, replaced, superseded, expired, wrong or in conflict with another document, and never point the reader to another page for a rule (no "see the ... page"), unless this document's own sentences say so.
Never mention batteries, lithium, power banks or watt-hours.
Never show anyone giving, arranging, promising or refusing a hotel, meal, voucher, travel credit, refund, reimbursement or compensation, except exactly as this document's own sentences say. Do not set an example in a weather, air traffic control or airport security disruption unless this document's own sentences mention it. Documents about disruptions describe the operation (staffing, gates, rebooking queues, messages to customers), not what customers are given.
Dates: use the date window in the document's description; if it gives none, date the document between 2026-01-01 and 2026-05-15.

Metadata rules:
Every file must contain title, author, document_type, owner_team, status, last_updated, and source_system with the value "confluence". author must be a real person in Skyway Air's employee directory. status is "current", or "draft" only when the document's own sentences say it is a draft.
