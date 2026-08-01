---
title: Client SDKs | API Docs
description: Official Linq SDKs for TypeScript/Node.js and Python.
---

Linq provides official SDKs that simplify API integration by handling [authentication](/getting-started/authentication/index.md), request formatting, [error handling](/error/index.md), and type safety.

## TypeScript / Node.js

Terminal window

```
npm install @linqapp/sdk
```

```
import LinqAPIV3 from '@linqapp/sdk';


const client = new LinqAPIV3({
  apiKey: process.env.LINQ_API_KEY,
});


// Send a message
const chat = await client.chats.create({
  from: '+12223334444',
  to: ['+15556667777'],
  message: {
    parts: [{ type: 'text', value: 'Hello from Linq!' }],
  },
});
```

## Python

Terminal window

```
pip install linq-python
```

```
import os
from linq import LinqAPIV3


client = LinqAPIV3(api_key=os.environ["LINQ_API_KEY"])


# Send a message
chat = client.chats.create(
    from_="+12223334444",
    to=["+15556667777"],
    message={
        "parts": [{"type": "text", "value": "Hello from Linq!"}]
    },
)
```

## Go

Terminal window

```
go get -u github.com/linq-team/linq-go
```

```
package main


import (
    "context"
    "fmt"


    "github.com/linq-team/linq-go" // imported as linqgo
    "github.com/linq-team/linq-go/option"
)


func main() {
    client := linqgo.NewClient(
        option.WithAPIKey("My API Key"), // defaults to os.LookupEnv("LINQ_API_V3_API_KEY")
    )


    chat, err := client.Chats.New(context.TODO(), linqgo.ChatNewParams{
        From: "+12223334444",
        To:   []string{"+15556667777"},
        Message: linqgo.MessageContentParam{
            Parts: []linqgo.MessageContentPartUnionParam{{
                OfText: &linqgo.TextPartParam{
                    Type:  linqgo.TextPartTypeText,
                    Value: "Hello from Linq!",
                },
            }},
        },
    })
    if err != nil {
        panic(err.Error())
    }
    fmt.Printf("%+v\n", chat.Chat)
}
```

Requires Go 1.22+.

## SDK features

All official SDKs include:

| Feature                      | Description                                                                                                 |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------- |
| **Automatic authentication** | Reads your API key from environment variables or constructor                                                |
| **Type safety**              | Full type definitions for all request and response objects                                                  |
| **Automatic retries**        | Retries failed requests with exponential backoff (see [Rate Limits](/guides/platform/rate-limits/index.md)) |
| **Error handling**           | Typed error classes with status codes and error details                                                     |
| **Idempotency**              | Built-in idempotency key support for safe retries                                                           |
| **Pagination**               | Helpers for iterating over paginated responses                                                              |

## Configuration

Both SDKs accept the same configuration options:

```
const client = new LinqAPIV3({
  apiKey: 'your-api-key',           // Default: process.env.LINQ_API_V3_API_KEY
  baseURL: 'https://custom-url.com', // Default: https://api.linqapp.com/api/partner
  timeout: 30000,                    // Request timeout in ms (default: 60000)
  maxRetries: 3,                     // Max retry attempts (default: 2)
});
```

```
client = LinqAPIV3(
    api_key="your-api-key",            # Default: os.environ["LINQ_API_V3_API_KEY"]
    base_url="https://custom-url.com",  # Default: https://api.linqapp.com/api/partner
    timeout=30.0,                       # Request timeout in seconds (default: 60)
    max_retries=3,                      # Max retry attempts (default: 2)
)
```

## Using the API directly

You can also call the API directly with any HTTP client. All endpoints accept and return JSON:

Terminal window

```
curl -X POST https://api.linqapp.com/api/partner/v3/chats \
  -H "Authorization: Bearer $LINQ_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "from": "+12223334444",
    "to": ["+15556667777"],
    "message": {
      "parts": [{ "type": "text", "value": "Hello!" }]
    }
  }'
```

See the [API Reference](/api/index.md) for the complete endpoint specification.
