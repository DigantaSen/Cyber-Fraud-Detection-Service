# Kafka Topic Manifest

Local broker settings: `partitions=12`, `replication.factor=1`, `min.insync.replicas=1`. Production raises replication to 3 and keeps the event names unchanged.

| Topic | Event type | Retention | Key |
|---|---|---:|---|
| `case.created` | `Case.Created` | 7 days | `caseId` |
| `case.updated` | `Case.Updated` | 7 days | `caseId` |
| `case.assigned` | `Case.Assigned` | 7 days | `caseId` |
| `case.closed` | `Case.Closed` | 7 days | `caseId` |
| `evidence.uploaded` | `Evidence.Uploaded` | 14 days | `caseId` |
| `evidence.deleted` | `Evidence.Deleted` | 14 days | `caseId` |
| `audio.uploaded` | `Audio.Uploaded` | 14 days | `caseId` |
| `audio.processed` | `Audio.Processed` | 14 days | `caseId` |
| `prediction.requested` | `Prediction.Requested` | 14 days | `caseId` |
| `prediction.completed` | `Prediction.Completed` | 14 days | `caseId` |
| `prediction.failed` | `Prediction.Failed` | 14 days | `caseId` |
| `prediction.overridden` | `Prediction.Overridden` | 14 days | `caseId` |
| `entity.relationship.discovered` | `Entity.RelationshipDiscovered` | 30 days | `entityId` |
| `fraud.ring.node.identified` | `FraudRing.NodeIdentified` | 30 days | `entityId` |
| `notification.requested` | `Notification.Requested` | 7 days | `userId` |
| `notification.sent` | `Notification.Sent` | 7 days | `userId` |
| `notification.delivered` | `Notification.Delivered` | 7 days | `userId` |
| `notification.failed` | `Notification.Failed` | 7 days | `userId` |
| `mhaalert.sent` | `MHAAlert.Sent` | 7 days | `caseId` |
| `audit.recorded` | `Audit.Recorded` | 30 days | `entityId` |
| `user.registered` | `User.Registered` | 7 days | `userId` |
| `user.login.failed` | `User.LoginFailed` | 7 days | `email` |
| `telecom.event.ingested` | `TelecomEvent.Ingested` | 3 days | `sessionId` |
| `transaction.ingested` | `Transaction.Ingested` | 7 days | `transactionId` |
| `callsession.initiated` | `CallSession.Initiated` | 3 days | `sessionId` |
| `callsession.flagged` | `CallSession.Flagged` | 3 days | `sessionId` |
| `intervention.requested` | `Intervention.Requested` | 3 days | `sessionId` |
| `counterfeit.scan.submitted` | `CounterfeitScan.Submitted` | 7 days | `scanId` |
| `geo.layer.updated` | `GeoLayer.Updated` | 7 days | `jurisdictionId` |
| `report.generated` | `Report.Generated` | 30 days | `reportId` |
| `intelligence.package.generated` | `IntelligencePackage.Generated` | 30 days | `packageId` |

DLQ naming: `<topic>.DLQ`. The hackathon provisioner creates DLQs for the core demo paths; production should create a DLQ for every consumed topic and route failed records after three retries.
