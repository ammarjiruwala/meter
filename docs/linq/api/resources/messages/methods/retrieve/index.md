## Get a message by ID

**get** `/v3/messages/{messageId}`

Retrieve a specific message by its ID. This endpoint returns the full message
details including text, attachments, reactions, and metadata.

### Path Parameters

- `messageId: string`

### Returns

- `Message object { id, chat_id, created_at, 16 more }`

  - `id: string`

    Unique identifier for the message

  - `chat_id: string`

    ID of the chat this message belongs to

  - `created_at: string`

    When the message was created

  - `delivery_status: "pending" or "queued" or "sent" or 4 more`

    Current delivery status of a message

    - `"pending"`

    - `"queued"`

    - `"sent"`

    - `"delivered"`

    - `"received"`

    - `"read"`

    - `"failed"`

  - `is_delivered: boolean`

    DEPRECATED: Use `delivery_status` instead (true when `delivery_status` is `delivered` or `read`). Whether the message has been delivered.

  - `is_from_me: boolean`

    Whether this message was sent by the authenticated user

  - `is_read: boolean`

    DEPRECATED: Use `delivery_status == "read"` instead. Whether the message has been read.

  - `updated_at: string`

    When the message was last updated

  - `delivered_at: optional string`

    When the message was delivered

  - `effect: optional MessageEffect`

    iMessage effect applied to a message (screen or bubble effect)

    - `name: optional string`

      Name of the effect. Common values:

      - Screen effects: confetti, fireworks, lasers, sparkles, celebration, hearts, love, balloons, happy_birthday, echo, spotlight
      - Bubble effects: slam, loud, gentle, invisible

    - `type: optional "screen" or "bubble"`

      Type of effect

      - `"screen"`

      - `"bubble"`

  - `from: optional string`

    DEPRECATED: Use from_handle instead. Phone number of the message sender.

  - `from_handle: optional ChatHandle`

    The sender of this message as a full handle object

    - `id: string`

      Unique identifier for this handle

    - `handle: string`

      Phone number (E.164) or email address of the participant

    - `joined_at: string`

      When this participant joined the chat

    - `service: ServiceType`

      Messaging service type

      - `"iMessage"`

      - `"SMS"`

      - `"RCS"`

    - `is_me: optional boolean`

      Whether this handle belongs to the sender (your phone number)

    - `left_at: optional string`

      When they left (if applicable)

    - `status: optional "active" or "left" or "removed"`

      Participant status

      - `"active"`

      - `"left"`

      - `"removed"`

  - `parts: optional array of TextPartResponse or MediaPartResponse or LinkPartResponse or object { app, layout, reactions, 3 more }`

    Message parts in order (text, media, and link)

    - `TextPartResponse object { reactions, type, value, text_decorations }`

      A text message part

      - `reactions: array of Reaction`

        Reactions on this message part

        - `handle: ChatHandle`

        - `is_me: boolean`

          Whether this reaction is from the current user

        - `type: ReactionType`

          Type of reaction. Standard iMessage tapbacks are love, like, dislike, laugh, emphasize, question.
          Custom emoji reactions have type "custom" with the actual emoji in the custom_emoji field.
          Sticker reactions have type "sticker" with sticker attachment details in the sticker field.

          - `"love"`

          - `"like"`

          - `"dislike"`

          - `"laugh"`

          - `"emphasize"`

          - `"question"`

          - `"custom"`

          - `"sticker"`

        - `custom_emoji: optional string`

          Custom emoji if type is "custom", null otherwise

        - `sticker: optional object { file_name, height, mime_type, 2 more }`

          Sticker attachment details when reaction_type is "sticker". Null for non-sticker reactions.

          - `file_name: optional string`

            Filename of the sticker

          - `height: optional number`

            Sticker image height in pixels

          - `mime_type: optional string`

            MIME type of the sticker image

          - `url: optional string`

            Presigned URL for downloading the sticker image (expires in 1 hour).

          - `width: optional number`

            Sticker image width in pixels

      - `type: "text"`

        Indicates this is a text message part

        - `"text"`

      - `value: string`

        The text content

      - `text_decorations: optional array of TextDecoration`

        Text decorations applied to character ranges in the value

        - `range: array of number`

          Character range `[start, end)` in the `value` string where the decoration applies.
          `start` is inclusive, `end` is exclusive.
          *Characters are measured as UTF-16 code units. Most characters count as 1; some emoji count as 2.*

        - `animation: optional "big" or "small" or "shake" or 5 more`

          Animated text effect to apply. Mutually exclusive with `style`.

          - `"big"`

          - `"small"`

          - `"shake"`

          - `"nod"`

          - `"explode"`

          - `"ripple"`

          - `"bloom"`

          - `"jitter"`

        - `style: optional "bold" or "italic" or "strikethrough" or "underline"`

          Text style to apply. Mutually exclusive with `animation`.

          - `"bold"`

          - `"italic"`

          - `"strikethrough"`

          - `"underline"`

    - `MediaPartResponse object { id, filename, mime_type, 4 more }`

      A media attachment part

      - `id: string`

        Unique attachment identifier

      - `filename: string`

        Original filename

      - `mime_type: string`

        MIME type of the file

      - `reactions: array of Reaction`

        Reactions on this message part

        - `handle: ChatHandle`

        - `is_me: boolean`

          Whether this reaction is from the current user

        - `type: ReactionType`

          Type of reaction. Standard iMessage tapbacks are love, like, dislike, laugh, emphasize, question.
          Custom emoji reactions have type "custom" with the actual emoji in the custom_emoji field.
          Sticker reactions have type "sticker" with sticker attachment details in the sticker field.

        - `custom_emoji: optional string`

          Custom emoji if type is "custom", null otherwise

        - `sticker: optional object { file_name, height, mime_type, 2 more }`

          Sticker attachment details when reaction_type is "sticker". Null for non-sticker reactions.

      - `size_bytes: number`

        File size in bytes

      - `type: "media"`

        Indicates this is a media attachment part

        - `"media"`

      - `url: string`

        Presigned URL for downloading the attachment (expires in 1 hour).

    - `LinkPartResponse object { reactions, type, value }`

      A rich link preview part

      - `reactions: array of Reaction`

        Reactions on this message part

        - `handle: ChatHandle`

        - `is_me: boolean`

          Whether this reaction is from the current user

        - `type: ReactionType`

          Type of reaction. Standard iMessage tapbacks are love, like, dislike, laugh, emphasize, question.
          Custom emoji reactions have type "custom" with the actual emoji in the custom_emoji field.
          Sticker reactions have type "sticker" with sticker attachment details in the sticker field.

        - `custom_emoji: optional string`

          Custom emoji if type is "custom", null otherwise

        - `sticker: optional object { file_name, height, mime_type, 2 more }`

          Sticker attachment details when reaction_type is "sticker". Null for non-sticker reactions.

      - `type: "link"`

        Indicates this is a rich link preview part

        - `"link"`

      - `value: string`

        The URL

    - `IMessageAppPartResponse object { app, layout, reactions, 3 more }`

      An iMessage app card part.

      - `app: object { bundle_id, name, team_id, app_store_id }`

        Identifies the iMessage app (Messages app extension) that backs the card.

        - `bundle_id: string`

          Bundle identifier of the Messages app extension. Must not contain `:`.

        - `name: string`

          Display name of the app, shown by Messages' fallback UI.

        - `team_id: string`

          The app's 10-character uppercase alphanumeric team identifier.

        - `app_store_id: optional number`

          The owning app's App Store id (optional). When set, recipients without the iMessage app
          installed see a "Get the app" affordance.

      - `layout: object { caption, image_subtitle, image_title, 4 more }`

        Visible layout of the card. At least one of
        `caption`, `subcaption`, `trailing_caption`, `trailing_subcaption`, or `image_url` must be
        set, otherwise the card renders as an empty bubble.

        `image_url` displays a preview image at the top of the card. The image renders on the
        recipient's card whether or not they have your app installed. The small icon beside the
        caption is the app's own icon and is not settable here.

        `* Note - requires a trusted chat w/ inbound activity`

        `image_title` and `image_subtitle` render as text overlaid on the image (title bold, subtitle
        beneath it). They only appear when `image_url` is set — without an image there is nothing to
        overlay — so setting either without `image_url` is rejected.

        - `caption: optional string`

          Primary label, top-left and bold.

        - `image_subtitle: optional string`

          Text shown below `image_title`, overlaid on the card image. Requires `image_url`.

        - `image_title: optional string`

          Bold text overlaid on the card image. Requires `image_url` (rejected without it).

        - `image_url: optional string`

          URL of an image (JPEG, PNG, HEIF, or WebP) to display as the card's preview image; an unreachable or non-image URL returns a validation error. Renders for all recipients regardless of whether they have the app. Note - requires a trusted chat w/ inbound activity. In responses, this is the re-hosted `cdn.linqapp.com` copy of the image you supplied, not your original URL.

        - `subcaption: optional string`

          Secondary label, below `caption` on the left.

        - `trailing_caption: optional string`

          Label shown top-right.

        - `trailing_subcaption: optional string`

          Label shown below `trailing_caption`, on the right.

      - `reactions: array of Reaction`

        Reactions on this message part

        - `handle: ChatHandle`

        - `is_me: boolean`

          Whether this reaction is from the current user

        - `type: ReactionType`

          Type of reaction. Standard iMessage tapbacks are love, like, dislike, laugh, emphasize, question.
          Custom emoji reactions have type "custom" with the actual emoji in the custom_emoji field.
          Sticker reactions have type "sticker" with sticker attachment details in the sticker field.

        - `custom_emoji: optional string`

          Custom emoji if type is "custom", null otherwise

        - `sticker: optional object { file_name, height, mime_type, 2 more }`

          Sticker attachment details when reaction_type is "sticker". Null for non-sticker reactions.

      - `type: "imessage_app"`

        Indicates this is an iMessage app card part.

        - `"imessage_app"`

      - `url: string`

        The URL delivered to the iMessage app on tap.

      - `fallback_text: optional string`

        Fallback text for surfaces that cannot render the card.

  - `preferred_service: optional ServiceType`

    Messaging service type

  - `read_at: optional string`

    When the message was read

  - `reconciled_at: optional string`

    Present only when this message was recovered by reconciliation rather than delivered live, and set to the time of that recovery. The field is omitted entirely for normally-delivered messages, which is the overwhelming majority. When present, expect `sent_at` to be substantially earlier — the message is genuine but was ingested late, so it may not have appeared in earlier reads of this conversation.

  - `reply_to: optional ReplyTo`

    Indicates this message is a threaded reply to another message

    - `message_id: string`

      The ID of the message to reply to

    - `part_index: optional number`

      The specific message part to reply to (0-based index).
      Defaults to 0 (first part) if not provided.
      Use this when replying to a specific part of a multipart message.

  - `sent_at: optional string`

    When the message was sent

  - `service: optional ServiceType`

    Messaging service type

### Example

```http
curl https://api.linqapp.com/api/partner/v3/messages/$MESSAGE_ID \
    -H "Authorization: Bearer $LINQ_API_V3_API_KEY"
```

#### Response

```json
{
  "id": "69a37c7d-af4f-4b5e-af42-e28e98ce873a",
  "chat_id": "94c6bf33-31d9-40e3-a0e9-f94250ecedb9",
  "created_at": "2024-01-15T10:30:00Z",
  "delivery_status": "pending",
  "is_delivered": true,
  "is_from_me": true,
  "is_read": false,
  "updated_at": "2024-01-15T10:30:00Z",
  "delivered_at": "2024-01-15T10:30:10Z",
  "effect": {
    "name": "confetti",
    "type": "screen"
  },
  "from": "+12052535597",
  "from_handle": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "handle": "+15551234567",
    "joined_at": "2025-05-21T15:30:00.000-05:00",
    "service": "iMessage",
    "is_me": false,
    "left_at": "2019-12-27T18:11:19.117Z",
    "status": "active"
  },
  "parts": [
    {
      "reactions": [
        {
          "handle": {
            "id": "69a37c7d-af4f-4b5e-af42-e28e98ce873a",
            "handle": "+15551234567",
            "joined_at": "2025-05-21T15:30:00.000-05:00",
            "service": "iMessage",
            "is_me": false,
            "left_at": "2019-12-27T18:11:19.117Z",
            "status": "active"
          },
          "is_me": false,
          "type": "love",
          "custom_emoji": null,
          "sticker": {
            "file_name": "sticker.png",
            "height": 420,
            "mime_type": "image/png",
            "url": "https://cdn.linqapp.com/attachments/a1b2c3d4/sticker.png?signature=...",
            "width": 420
          }
        }
      ],
      "type": "text",
      "value": "Hello!",
      "text_decorations": [
        {
          "range": [
            0,
            5
          ],
          "animation": "shake",
          "style": "bold"
        }
      ]
    }
  ],
  "preferred_service": "iMessage",
  "read_at": "2024-01-15T10:35:00Z",
  "reconciled_at": "2024-01-15T14:05:00Z",
  "reply_to": {
    "message_id": "550e8400-e29b-41d4-a716-446655440000",
    "part_index": 0
  },
  "sent_at": "2024-01-15T10:30:05Z",
  "service": "iMessage"
}
```
