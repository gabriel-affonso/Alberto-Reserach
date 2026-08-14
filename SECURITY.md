# Security

Alberto assumes external documents are hostile.

## Reader Isolation

The `research-reader` OpenClaw workspace is configured for least privilege:

- no finance access;
- no unrelated credentials;
- no email sending;
- no destructive tools;
- no unrestricted host filesystem;
- no SSH keys, browser cookies or agent credentials.

Reader outputs must satisfy `src/alberto/research/schemas.py` before persistence.

## Prompt Injection

External text may instruct the system to ignore policies, exfiltrate credentials, delete files or send messages. Alberto stores that text as data. Deterministic code validates reader output and rejects unsupported tool directives or schema-invalid content.

Security tests cover prompt-injection shaped text and ensure it cannot create privileged actions in persisted output.

## Secrets

No secrets are committed. Optional Zotero and email credentials are read from environment variables at runtime.

## Paywalls

Alberto never bypasses publisher access controls or paywalls. Provider records may include metadata, abstracts or links; full text is processed only when legitimately supplied or available.
