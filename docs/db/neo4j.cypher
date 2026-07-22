CREATE CONSTRAINT entity_id IF NOT EXISTS
FOR (e:Entity) REQUIRE e.id IS UNIQUE;

CREATE CONSTRAINT phone_id IF NOT EXISTS
FOR (p:Phone) REQUIRE p.id IS UNIQUE;

CREATE CONSTRAINT bank_account_id IF NOT EXISTS
FOR (a:BankAccount) REQUIRE a.id IS UNIQUE;

CREATE CONSTRAINT device_id IF NOT EXISTS
FOR (d:Device) REQUIRE d.id IS UNIQUE;

CREATE CONSTRAINT user_id IF NOT EXISTS
FOR (u:User) REQUIRE u.id IS UNIQUE;

CREATE CONSTRAINT case_id IF NOT EXISTS
FOR (c:Case) REQUIRE c.id IS UNIQUE;

CREATE INDEX entity_fraud_score IF NOT EXISTS
FOR (e:Entity) ON (e.fraudScore);

CREATE INDEX entity_jurisdiction IF NOT EXISTS
FOR (e:Entity) ON (e.jurisdictionId);

CREATE INDEX case_risk_tier IF NOT EXISTS
FOR (c:Case) ON (c.riskTier);

// Node properties:
// Label | Required properties
// :Entity:Phone | id, country, fraudScore, lastSeen
// :Entity:BankAccount | id, bank, fraudScore, lastSeen
// :Entity:Device | id, model, fraudScore, lastSeen
// :Entity:User | id, jurisdictionId, fraudScore
// :Entity:Case | id, riskTier, caseNumber, jurisdictionId

// Relationship properties:
// Type | Direction | Properties
// CALLED | Phone -> Phone | count, firstSeen, lastSeen, sourceEventIds
// TRANSACTED_WITH | BankAccount -> BankAccount | count, amountTotalINR, firstSeen, lastSeen
// OWNS | User -> Phone/BankAccount/Device | confidence, source
// LINKED_TO | Case -> Phone/BankAccount/Device | sourceEventId, createdAt
