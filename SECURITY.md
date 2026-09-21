# Security and Data Handling

- Never commit `.env`, API keys, Leaderboard Keys, or Memory System Keys.
- Health is public. Add and Search can require Bearer, Token, or `X-Api-Key` authentication.
- Retrieval is scoped to the exact `user_id` supplied in each request.
- The service does not log request bodies or model credentials.
- Delete the configured SQLite database or Docker volume no later than 30 days after the evaluation finishes, unless written organizer permission says otherwise.
- Revoke any accidentally exposed credential before opening a sanitized private report.

