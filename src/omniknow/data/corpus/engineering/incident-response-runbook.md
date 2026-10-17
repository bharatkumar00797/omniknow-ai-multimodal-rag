# Incident Response Runbook

## Severity levels

SEV1 is a full outage of the fleet control plane or any safety-relevant robot fault. SEV2 is a partial outage or major degradation affecting more than 10 percent of customers. SEV3 is a minor issue with a known workaround.

## Paging

The on-call engineer must acknowledge a SEV1 page within 5 minutes and a SEV2 page within 15 minutes. If the page is not acknowledged, PagerDuty escalates to the secondary on-call and then to the engineering manager.

## Communication

The incident commander posts updates in the #incident channel every 30 minutes for SEV1 and every 60 minutes for SEV2. Customer-facing status page updates are owned by the support lead.

## Postmortems

A blameless postmortem is required for every SEV1 and SEV2 incident and must be published within 5 business days.
