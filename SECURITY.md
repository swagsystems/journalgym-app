# Security policy

JournalGym is intended for self-hosted use. Please do not include credentials, database contents, PINs, session cookies, private addresses, or production logs in a public issue.

Report suspected authentication bypasses, session-handling defects, injection paths, unintended data disclosure, or unsafe default deployment behavior privately through the contact method listed on the repository owner's GitHub profile.

Before exposing an instance outside a trusted local environment:

- Place it behind HTTPS.
- Set `FITNESS_COOKIE_SECURE=true`.
- Configure explicit trusted proxy addresses.
- Use a dedicated persistent-data directory with restricted permissions.
- Maintain and test database backups.
- Keep the image and dependencies updated.
