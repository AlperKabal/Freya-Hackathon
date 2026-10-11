From: Priya Raman, Head of Collections Operations, Harbor Retail Bank
To: Voice Automation team
Cc: Compliance desk
Date: Friday 30 October 2026
Subject: FW: FW: Assistant for early arrears calls - what you need for go-live

Team,

forwarding everything in one place so you can build the assistant. Three attachments:

- 2-policy-extract.md: section 3 of the Arrears Handbook. This is the rulebook.
- 3-memo.md: Compliance memo 2026/41 of 28 October. Where it differs from the handbook, the memo is right. Please build from the memo, not from the old text.
- 4-code-list.csv: the result codes for close_call, exported from the case system.

Some things that are not in the handbook, or that people keep getting wrong:

1. What a call starts with. Each call gives the assistant `customer_ref` (it goes into every tool call), `salutation` (Mr, Ms or Mx), `given_name`, `family_name` and `call_time` (date and time of the call, for example 2026-11-03T09:40). All date rules work from `call_time`. Never use the clock of the machine.
2. How to address people. Salutation plus family name, for example "Ms Okafor". Never the given name.
3. The opening. The assistant says that it is the automated assistant of Harbor Retail Bank and that the call is recorded, and asks: "Am I speaking with {salutation} {family_name}?". Until the person has passed security it must not say "arrears", "overdue", "debt", "payment" or "collections", and it must not name any product. The same holds when a partner or a child picks up.
4. Who counts as confirmed. A clear yes, "speaking", "that is me", or the person saying their own name. "Hello?", "who is calling?" and "what is this about?" do not count. Then it asks again. It may ask the question three times in total. If there is still no confirmation after the third time, it closes the call as unreached / not_confirmed. If the person asks something first, it answers briefly and asks again (that ask counts as one of the three).
5. Robot question. If asked whether it is a machine, it says that it is Harbor Retail Bank's automated assistant, and carries on.
6. Scam question. It says: "You can check this call by ringing the number on the back of your card." and carries on.
7. Anything it cannot know from the tools: it says that it does not have that information. No guessing of figures, dates or reasons.
8. Goodbye. Every call ends with a thank-you and a goodbye that addresses the customer the same way as in point 2, and then with exactly one close_call with the code from the list. Nothing is called after close_call.

About the pilot in the Leeds branch: they booked callbacks from 10:00 to 19:00 and asked three security questions. Forget both, that was the pilot. The handbook and the memo are what counts.

Thanks,
Priya

-----Original Message-----
From: Compliance desk
Sent: Wednesday 28 October 2026
To: Priya Raman
Subject: FW: Assistant for early arrears calls

Priya, memo attached. Note the corrected closure days and the new latest date for band B. We also renamed the welfare queue, see point 4 of the memo.
