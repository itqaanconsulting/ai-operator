# Test emails for AI Commitment Operator

Send these emails to yourself, then add the Gmail label `AI-Operator` and click
**Scan Gmail** in the dashboard. Use fictional details only.

## 1. Sales lead

**Subject:** Interested in an AI automation pilot

**Body:**

Hi,

We are exploring an AI automation solution for our customer support team. Could
you send us a short pilot proposal and estimated price by September 10, 2026?
We would also like to schedule a 30-minute introduction call next week.

Kind regards,
Sarah
Northstar Retail

Expected: `sales`; proposal task, deadline, meeting request, and reply draft.

## 2. Customer issue and escalation

**Subject:** Urgent: order automation is failing

**Body:**

Hi,

Since this morning, new orders are no longer reaching our warehouse system.
Approximately 120 orders are waiting. Please investigate this today, update us
before 15:00, and send a temporary workaround if the issue cannot be fixed.

Regards,
Michael
Contoso Commerce

Expected: `escalation` or `customer_service`; investigation, update deadline,
workaround, and high urgency.

## 3. Finance and payment

**Subject:** Invoice INV-2026-104 requires payment

**Body:**

Hello,

Invoice INV-2026-104 for EUR 4,850 is attached. Please verify the amount, arrange
payment before September 15, 2026, and confirm by email after the payment has
been approved. The purchase order number is PO-7781.

Best regards,
Emma
Alpine Supplies

Expected: `finance`; invoice verification, payment deadline, and confirmation
reply as separate work items.

## 4. Contract review and approval

**Subject:** Updated service agreement for approval

**Body:**

Hi,

Attached is the updated service agreement. The new version changes the notice
period from 30 to 90 days and adds an annual price increase of 7%. Please compare
it with our previous agreement and tell me by September 12, 2026 whether we
should approve it or request revisions.

Thanks,
Daniel
Blue River Logistics

Expected: `contract` or `approval`; comparison, risk review, decision deadline,
and proposed revision/approval action.

## 5. Meeting with preparation tasks

**Subject:** Quarterly review meeting and preparation

**Body:**

Hello,

Can we meet on September 18, 2026 at 10:00 for our quarterly review? Before the
meeting, please prepare the sales figures, list the three largest delivery risks,
and send the agenda to all attendees by September 16.

Regards,
Olivia
Carrefour Demo

Expected: `meeting`; meeting request plus three preparation/follow-up items.

## 6. Multi-scenario executive email

**Subject:** Carrefour launch: contract, campaign and invoice actions

**Body:**

Hi,

For the Carrefour launch, please complete the following:

1. Review the supplier contract and flag any liability changes by September 9.
2. Approve or reject the influencer campaign budget of EUR 12,000 by September 10.
3. Verify invoice CF-882 for EUR 2,400 and prepare it for payment by September 14.
4. Draft an update to Carrefour confirming the launch status and any blockers.
5. Schedule a final readiness call for September 16 at 14:00.

Do not send anything externally until I approve it.

Thanks,
Alex

Expected: multiple scenarios/work items: contract review, approval, finance,
follow-up draft, and meeting. Every external action must require approval.

## 7. HR candidate review

**Subject:** Application for Automation Engineer — Sam de Vries

```text
Hi Hiring Team,

I would like to apply for the Automation Engineer role. I have five years of
Python experience and three years building n8n and API-based workflows. I have
also worked with Gmail, Google Calendar, Trello, and CRM integrations.

Please create a candidate review for the Recruiting team. The next step is to
review my experience against the role before deciding whether to schedule an
interview. Do not send a reply or schedule an interview automatically.

Kind regards,
Sam de Vries
sam.devries@example.com
```

Expected: `hr`; one `job_application` finding and an approval-gated candidate
review owned by Recruiting. No reply or interview is created automatically.

## Quick test procedure

1. Send one example to your own Gmail address.
2. Add the label `AI-Operator` to the received message.
3. Wait for the published n8n inbox workflow, or run that workflow once in n8n.
4. Open `http://127.0.0.1:8000/dashboard`.
5. Check **New from latest scan** for separate findings and deadlines.
6. Open the email group and review the proposed outcome.
7. Run only a safe test action after checking its editable details.
8. Confirm the expected record or draft exists and that no email was sent.
