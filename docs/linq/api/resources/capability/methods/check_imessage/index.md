## Check iMessage capability

**post** `/v3/capability/check_imessage`

Check whether a recipient address (phone number or email) is reachable via iMessage.

### Body Parameters

- `address: string`

  The recipient phone number or email address to check

- `from: optional string`

  Optional sender phone number. If omitted, an available phone from your pool is used automatically.

### Returns

- `HandleCheckResponse object { address, available }`

  - `address: string`

    The recipient address that was checked

  - `available: boolean`

    Whether the recipient supports the checked messaging service

### Example

```http
curl https://api.linqapp.com/api/partner/v3/capability/check_imessage \
    -H 'Content-Type: application/json' \
    -H "Authorization: Bearer $LINQ_API_V3_API_KEY" \
    -d '{
          "address": "+15551234567",
          "from": "+15559876543"
        }'
```

#### Response

```json
{
  "address": "+15551234567",
  "available": true
}
```
