# GitHub Workflow Guide

## Rules

- Never work on `main`.
- Never work on `develop`.
- Every task should be done in a separate branch.
- One task = One commit.
- One task = One Pull Request.
- Always merge into `develop`.
- Only Diganta will merge `develop` into `main`.
- Use **Squash Merge**.
- Ask one teammate to review before merging.

---

## Starting a New Task

Update your local repository

```bash
git checkout develop
git pull origin develop
```

Create your task branch (example for Citizen/Bank UIs or BFFs)

```bash
git checkout -b feature/Surjit-citizen-ui
# OR
git checkout -b feature/Surjit-citizen-bff
```

Work on your task.

---

## Finishing a Task

```bash
git add .
git commit -m "feat(auth): complete T4 authentication service"
git push -u origin feature/Surjit-auth
```

Go to GitHub

Open a Pull Request

```
feature/Surjit-auth
        ↓
     develop
```

Ask one teammate to review.

After approval,

Click **Squash Merge**.

Delete the branch.

---

## Start Next Task

```bash
git checkout develop
git pull origin develop
git checkout -b feature/Surjit-case
```

Repeat.

---

# Task-wise Commits

## Diganta

T1

```
chore(infra): complete T1 repo setup
```

T2

```
docs(api): complete T2 API contracts
```

T3

```
docs(db): complete T3 database schema
```

T8b

```
feat(kafka): complete T8b event processing backbone
```

T4c

```
feat(bffs): complete T4c Bank, Telecom, and Gov BFFs
```

T8f

```
feat(search): complete T8f OpenSearch Kafka Consumer service
```

...

## Surjit

T4

```
feat(auth): complete T4 authentication service
```

T5a

```
feat(case): complete T5a case service
```

T4b

```
feat(citizen-bff): complete T4b gateway
```

T5d & T5e

```
feat(ui): complete T5d Telecom and T5e Bank interfaces
```

...

## Nilkanta

T6a

```
feat(evidence): complete T6a evidence service
```

T6d

```
feat(investigator-bff): complete T6d gateway
```

T5f

```
feat(ui): complete T5f Gov/MHA portal interface
```

...

## Kushal

T10a

```
feat(ml-scam): complete T10a scam classifier
```

...

---

# Final Release

All Feature Branches

↓

develop

↓

Testing

↓

Diganta creates Pull Request

↓

develop → main

↓

Tag Release

```
v0.1.0-alpha
v0.3.0-alpha
v0.5.0-beta
v0.9.0-rc
v1.0.0
```

---

# Common Commands

Check branch

```bash
git branch
```

Check status

```bash
git status
```

Pull latest

```bash
git pull origin develop
```

Push

```bash
git push
```

View commits

```bash
git log --oneline
```