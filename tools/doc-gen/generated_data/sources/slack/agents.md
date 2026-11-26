Directory:
sources/slack

Target number of files:
7000

This is a recursive target: it includes JSON documents in this directory and all nested channel directories. Suggested distribution: support-team 900; airport-ops 900; digital-team 650; irregular-ops 600; general 550; support-escalations 500; refunds-desk 450; baggage-desk 450; loyalty-team 450; finance-ops 450; support-policy-questions 400; announcements 300; random 250; policy-updates 150.

File name format:
Use descriptive, lowercase kebab-case names ending in .json, naming the thread's subject (for example shift-swap-friday-evening.json or kiosk-printer-jam-gate-12.json). Do not put internal ids, rule numbers or words like old, outdated or wrong in names.

Content rules:
Each file is one Slack thread or a day of messages between real Skyway Air employees, in plain, informal working language. Most threads are everyday work: shift swaps and staffing, queue volumes, system hiccups and IT tickets, training sessions, airport logistics, gate and kiosk issues, project check-ins, team news, congratulations and social chat. Some threads are agents asking each other how to handle a case; when the description gives policy sentences, the people say them naturally, one message at a time. Do not end a thread with a summary line that restates the answer.

Policy content (strict):
A document may state a customer-policy rule, fee, amount, limit, deadline or approval threshold ONLY if that exact sentence is given in this document's own description, in the part that says "It must contain these sentences word for word". Copy those sentences word for word. Never invent, add, round, paraphrase or complete policy numbers or rules, and never restate rules that belong to other documents. A document whose description gives no such sentences must contain no customer-policy rules or amounts at all: it is about everyday work.
Never say that a document or policy is outdated, replaced, superseded, expired, wrong or in conflict with another document, and never point the reader to another page for a rule (no "see the ... page"), unless this document's own sentences say so.
Never mention batteries, lithium, power banks or watt-hours.
Never show anyone giving, arranging, promising or refusing a hotel, meal, voucher, travel credit, refund, reimbursement or compensation, except exactly as this document's own sentences say. Do not set an example in a weather, air traffic control or airport security disruption unless this document's own sentences mention it. Documents about disruptions describe the operation (staffing, gates, rebooking queues, messages to customers), not what customers are given.
Dates: use the date window in the document's description; if it gives none, date the document between 2026-01-01 and 2026-05-15.

Metadata rules:
Every file must contain title, channel, document_type, created_at, participants, and source_system with the value "slack". participants must only name real people from Skyway Air's employee directory. document_type is thread, question, announcement, coordination or social. If you include a status, use open, pending, resolved or closed only.
