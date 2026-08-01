---
title: Authentication | API Docs
description: API keys, bearer tokens, and securing your requests.
---

All requests to the Linq Partner API require authentication via a bearer token in the `Authorization` header. The official [SDKs](/getting-started/sdks/index.md) handle authentication automatically.

## Bearer token authentication

Include your API token in every request:

```
Authorization: Bearer YOUR_TOKEN
```

Your token determines:

- Which **phone numbers** you can send from
- Which **data** you can access (chats, messages, attachments)
- Your **rate limits** and daily message quotas

## Getting your token

Generate a token yourself from the Linq dashboard:

1. Go to [dashboard.linqapp.com/api-tooling](https://dashboard.linqapp.com/api-tooling).
2. **API → Overview**
3. Click **Generate new token**.

## Making authenticated requests

Terminal window

```
curl https://api.linqapp.com/api/partner/v3/chats \
  -H "Authorization: Bearer $LINQ_API_KEY" \
  -H "Content-Type: application/json"
```

```
import LinqAPIV3 from '@linqapp/sdk';


const client = new LinqAPIV3({
  apiKey: process.env.LINQ_API_KEY, // reads LINQ_API_V3_API_KEY by default
});
```

```
import os
from linq import LinqAPIV3


client = LinqAPIV3(api_key=os.environ["LINQ_API_KEY"])
```

## Token security best practices

- **Use environment variables** — Never hardcode tokens in source code
- **Never commit tokens** — Add `.env` to `.gitignore`
- **Rotate regularly** — Request new tokens periodically from your Linq representative
- **Limit access** — Only share tokens with team members who need them
- **Use separate tokens** — Use different tokens for development and production

## Error responses

| Status | Code                                    | Description                                                                                     |
| ------ | --------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `401`  | [2004](/error/codes/2xxx/2004/index.md) | Missing or invalid bearer token. Check that your `Authorization` header is correctly formatted. |
| `403`  | [2005](/error/codes/2xxx/2005/index.md) | Valid token but insufficient permissions for this resource.                                     |
| `403`  | [2006](/error/codes/2xxx/2006/index.md) | You cannot send from this phone number. Verify the phone is assigned to your account.           |
| `429`  | [1007](/error/codes/1xxx/1007/index.md) | Rate limit exceeded. See [Rate Limits](/guides/platform/rate-limits/index.md).                  |

See [Error Codes](/error/index.md) for the complete error reference and the [API Reference](/api/index.md) for endpoint specifications.
