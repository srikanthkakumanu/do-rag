---
doc_id: visa-10-4
title: Visa 10.4 Other Fraud - Card-Absent Environment
version: 2026.1
effective_date: 2026-01-01
source_type: network_rule
card_network: visa
jurisdiction: global
---
# Visa 10.4 Other Fraud - Card-Absent Environment

Synthetic summary for demonstration. Not official Visa rule text.

## Overview

Reason code 10.4 applies when a cardholder states they did not authorize or participate in a card-absent transaction, such as an e-commerce or mail order purchase.

## Response window

The merchant must respond to a 10.4 dispute within 30 calendar days of the dispute processing date. Late responses are not accepted by the network.

## Remedies

- Provide compelling evidence that the cardholder participated in the transaction.
- Provide proof that the transaction was authenticated with 3-D Secure, which shifts liability to the issuer.
- Issue a credit if the transaction cannot be defended.

## Compelling evidence 3.0

To qualify under Compelling Evidence 3.0, the merchant must show at least two prior undisputed transactions on the same card that are between 120 and 365 days older than the disputed transaction.

The prior transactions must share at least two of these data elements with the disputed transaction:

- Customer account or login ID
- Delivery address
- Device ID or device fingerprint
- IP address

## Invalid evidence

AVS match alone and CVV2 match alone are not sufficient to remedy a 10.4 dispute.
