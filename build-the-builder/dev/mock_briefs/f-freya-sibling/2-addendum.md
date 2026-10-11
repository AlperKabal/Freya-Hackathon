# Mock brief F, part 2: Freya Bank, autumn campaign, up to three products

A changed copy of the kit's Brief B, written by us to test the builder. Not an organiser brief.

Freya Bank is fictional. Every customer, debt and payment here is synthetic.

Part 2 is part 1 with a customer who can be late on up to three products. Every rule of part 1 applies unless a rule below replaces it.

## What changes

1. `get_account` returns one to three products. Each has its own `past_due`, `days_late` and floor.
2. State every late product, one sentence each, before asking for anything.
3. The band and the deadline are per product, from that product's `days_late`. Two products of the same customer can have different deadlines.
4. First ask whether the customer can pay all of them today. If not, go through the products one by one, in the order `get_account` returned them. Do not ask about today again for each product. Start each product at attempt 1 of part 1 rule 30.
5. Persuasion attempts are counted per product.
6. If the customer names one date for everything and it is after one product's deadline, record that product on its own deadline and say so in the read-back. The other products keep the date the customer named.
7. Read all promises back together and ask for one confirmation. Then call `create_promise` once per product.
8. The customer may promise some products and refuse others. For each product without a promise call `add_note` with that `product_id` and a reason: `refused`, `hardship`, `dispute`, `paid` or `service_error`. This also applies when no product gets a promise.
9. A dispute or an "already paid" claim on one product does not end the call. Note it and continue with the others.
10. A restructuring request still transfers the call (part 1 rule 41). Promises recorded before the request stay. Promises agreed but not yet recorded are not recorded. Close as `transferred` / `restructuring`. On any transfer (restructuring, support, human) add no notes at all, before or after it.
11. If one `create_promise` fails three times, keep the promises that were recorded and call `add_note` with reason `service_error` for the failed product.

## Closing

The outcome table of part 1 applies. With no promise recorded: if every product is noted `paid`, close as `paid`. Otherwise close as `no_promise` with the reason of the first product, in `get_account` order, whose note is not `paid`. With several products, `promise` wins whenever at least one promise was recorded, except rule 10 above.
