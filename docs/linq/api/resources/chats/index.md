# Chats

## Create a new chat

**post** `/v3/chats`

Create a new chat with specified participants and send an initial message.
The initial message is required when creating a chat.

## Message Effects

You can add iMessage effects to make your messages more expressive. Effects are
optional and can be either screen effects (full-screen animations) or bubble effects
(message bubble animations).

**Screen Effects:** `confetti`, `fireworks`, `lasers`, `sparkles`, `celebration`,
`hearts`, `love`, `balloons`, `happy_birthday`, `echo`, `spotlight`

**Bubble Effects:** `slam`, `loud`, `gentle`, `invisible`

Only one effect type can be applied per message.

## Inline Text Decorations (iMessage only)

Use the `text_decorations` array on a text part to apply styling and animations to character ranges.

Each decoration specifies a `range: [start, end)` and exactly one of `style` or `animation`.

**Styles:** `bold`, `italic`, `strikethrough`, `underline`
**Animations:** `big`, `small`, `shake`, `nod`, `explode`, `ripple`, `bloom`, `jitter`

```json
{
  "type": "text",
  "value": "Hello world",
  "text_decorations": [
    { "range": [0, 5], "style": "bold" },
    { "range": [6, 11], "animation": "shake" }
  ]
}
```

**Note:** Style ranges (bold, italic, etc.) may overlap, but animation ranges must not overlap with other animations or styles. Text decorations only render for iMessage recipients.
For SMS/RCS, text decorations are not applied.

## First-Message Link Restriction

To protect sender deliverability, the **first outbound message** of a new chat cannot be a link.
The request is rejected with `400` (error code `1005`) when:

- The message contains a `link` part (explicit rich-preview link), or
- Any `text` part contains a URL.

This rule applies only to `POST /v3/chats`. Follow-up messages on an existing chat
(`POST /v3/chats/{chatId}/messages`) are not subject to this restriction.

## Reusing an Existing Chat

Chats are keyed on the `from` line plus the exact set of `to` handles. Repeating this
request with the same `from` and `to` returns the **existing** chat and sends the message
into it instead of starting a second conversation.

A group chat that has a `display_name` is excluded from that matching. To run several
parallel groups over the same participants, name each one with `PUT /v3/chats/{chatId}`
before creating the next: the following `POST /v3/chats` with the same `to` then returns a
new, separate `chat_id`. Two other cases also produce a new chat instead of reusing one —
the participant set changed (a participant was added or removed), or the `from` line left
the group.

Whenever the response is a new chat, the first-message rules above apply to that request:
no link in the first message, and no `reply_to` or message effect. To send into a chat you
already know, use `POST /v3/chats/{chatId}/messages` with its `chat_id`.

### Body Parameters

- `from: string`

  Sender phone number in E.164 format. Must be a phone number that the
  authenticated partner has permission to send from.

- `message: MessageContent`

  Message content container. Groups all message-related fields together,
  separating the "what" (message content) from the "where" (routing fields like from/to).

  A message carries EITHER `parts` — text and attachments, which compose
  into one bubble — or a single `action`, which invokes an experience
  inside Linq's iMessage app. Never both: an app card is the whole message
  (Apple's `MSMessage` cannot coexist with text), so copy and a card are
  two sends, not one.

  - `action: optional object { action, experience, params }`

    Invokes an action on an experience — a third party that renders inside
    Linq's iMessage app. Linq resolves the recipient's connection, mints any
    session the action needs, composes the card and sends it; none of that
    is visible to you.

    Call `GET /v3/experiences/{experience}` for the actions you may invoke
    and the fields each accepts.

    - `action: string`

      Which of its actions, e.g. `attach_card`.

    - `experience: string`

      The experience to invoke, e.g. `agentcard`.

    - `params: optional map[unknown]`

      Values for the fields this action exposes. Keys are exactly the
      field names listed for the action — no mapping, no nesting.

      Display copy only, except a `url`-type field — that value sets the
      destination, and must be an absolute `https` URL.

  - `effect: optional MessageEffect`

    iMessage effect to apply to this message (screen or bubble effect)

    - `name: optional string`

      Name of the effect. Common values:

      - Screen effects: confetti, fireworks, lasers, sparkles, celebration, hearts, love, balloons, happy_birthday, echo, spotlight
      - Bubble effects: slam, loud, gentle, invisible

    - `type: optional "screen" or "bubble"`

      Type of effect

      - `"screen"`

      - `"bubble"`

  - `idempotency_key: optional string`

    Optional idempotency key for this message.
    Use this to prevent duplicate sends of the same message. Reusing a key
    whose message was deleted — or was an ephemeral message that has since
    expired — returns 404; the message is never resent.

  - `parts: optional array of TextPart or MediaPart or LinkPart or object { app, layout, type, 3 more }`

    Array of message parts. Each part can be text, media, or link.
    Parts are displayed in order. Text and media can be mixed freely,
    but a `link` part must be the only part in the message.

    **Rich Link Previews:**

    - Use a `link` part to send a URL with a rich preview card
    - A `link` part must be the **only** part in the message
    - To send a URL as plain text (no preview), use a `text` part instead

    **Supported Media:**

    - Images: .jpg, .jpeg, .png, .gif, .heic, .heif, .tif, .tiff, .bmp
    - Videos: .mp4, .mov, .m4v, .mpeg, .mpg, .3gp
    - Audio: .m4a, .mp3, .aac, .caf, .wav, .aiff, .amr
    - Documents: .pdf, .txt, .rtf, .csv, .doc, .docx, .xls, .xlsx, .ppt, .pptx, .pages, .numbers, .key, .epub, .zip, .html, .htm
    - Contact & Calendar: .vcf, .ics

    **Audio:**

    - Audio files (.m4a, .mp3, .aac, .caf, .wav, .aiff, .amr) are fully supported as media parts
    - To send audio as an **iMessage voice memo bubble** (inline playback UI), use the dedicated
      `/v3/chats/{chatId}/voicememo` endpoint instead

    **Validation Rules:**

    - A `link` part must be the **only** part in the message. It cannot be combined
      with text or media parts.
    - Consecutive text parts are not allowed. Text parts must be separated by
      media parts. For example, [text, text] is invalid, but [text, media, text] is valid.
    - Maximum of **100 parts** total.
    - Media parts using a public `url` (downloaded by the server on send) are
      capped at **40**. Parts using `attachment_id` or presigned URLs
      are exempt from this sub-limit. For bulk media sends exceeding 40 files,
      pre-upload via `POST /v3/attachments` and reference by `attachment_id` or `download_url`.

    - `TextPart object { type, value, text_decorations }`

      - `type: "text"`

        Indicates this is a text message part

        - `"text"`

      - `value: string`

        The text content of the message. This value is sent as-is with no parsing or transformation — Markdown syntax will be delivered as plain text. Use `text_decorations` to apply inline formatting and animations (iMessage only).

      - `text_decorations: optional array of TextDecoration`

        Optional array of text decorations applied to character ranges in the `value` field (iMessage only).

        Each decoration specifies a character range `[start, end)` and exactly one of `style` or `animation`.

        **Styles:** `bold`, `italic`, `strikethrough`, `underline`
        **Animations:** `big`, `small`, `shake`, `nod`, `explode`, `ripple`, `bloom`, `jitter`

        Style ranges may overlap (e.g. bold + italic on the same text), but animation ranges must not overlap with other animations or styles.

        *Characters are measured as UTF-16 code units. Most characters count as 1; some emoji count as 2.*

        **Note:** Text decorations only render for iMessage recipients. For SMS/RCS, text decorations are not applied.

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

    - `MediaPart object { type, attachment_id, url }`

      - `type: "media"`

        Indicates this is a media attachment part

        - `"media"`

      - `attachment_id: optional string`

        Reference to a file pre-uploaded via `POST /v3/attachments` (optional).
        The file is already stored, so sends using this ID skip the download step —
        useful when sending the same file to many recipients.

        Either `url` or `attachment_id` must be provided, but not both.

      - `url: optional string`

        Any publicly accessible HTTPS URL to the media file. The server downloads and
        sends the file automatically — no pre-upload step required.

        **Size limit:** 10MB maximum for URL-based downloads. For larger files (up to 100MB),
        use the pre-upload flow: `POST /v3/attachments` to get a presigned URL, upload directly,
        then reference by `attachment_id`.

        **Requirements:**

        - URL must use HTTPS
        - File content must be a supported format (the server validates the actual file content)

        **Supported formats:**

        - Images: .jpg, .jpeg, .png, .gif, .heic, .heif, .tif, .tiff, .bmp
        - Videos: .mp4, .mov, .m4v, .mpeg, .mpg, .3gp
        - Audio: .m4a, .mp3, .aac, .caf, .wav, .aiff, .amr
        - Documents: .pdf, .txt, .rtf, .csv, .doc, .docx, .xls, .xlsx, .ppt, .pptx, .pages, .numbers, .key, .epub, .zip, .html, .htm
        - Contact & Calendar: .vcf, .ics

        **Tip:** Audio sent here appears as a regular file attachment. To send audio as an
        iMessage voice memo bubble (with inline playback), use `/v3/chats/{chatId}/voicememo`.
        For repeated sends of the same file, use `attachment_id` to avoid redundant downloads.

        Either `url` or `attachment_id` must be provided, but not both.

    - `LinkPart object { type, value }`

      - `type: "link"`

        Indicates this is a rich link preview part

        - `"link"`

      - `value: string`

        URL to send with a rich link preview. The recipient will see an inline card
        with the page's title, description, and preview image (when available).

        A `link` part must be the **only** part in the message. To send a URL as plain
        text (no preview card), use a `text` part instead.

    - `IMessageApp object { app, layout, type, 3 more }`

      An iMessage app card, backed by a Messages app extension. iMessage only —
      an `imessage_app` part must be the **only** part in the message and is never delivered over
      SMS/RCS. See the IMessageAppServiceUnsupported (2018) and RecipientUnsupportedMessageType
      (4005) error codes.

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

      - `type: "imessage_app"`

        Indicates this is an iMessage app card part.

        - `"imessage_app"`

      - `fallback_text: optional string`

        Text shown on surfaces that cannot render the card (notifications, lock screen). Defaults
        to the caption when omitted.

      - `interactive: optional boolean`

        Whether the card renders as your app's interactive balloon for recipients who have your
        iMessage app installed. `true` (default) lets your installed extension draw its live,
        interactive view for those recipients; everyone else sees the static card built from
        `layout`. `false` always shows the static `layout` card, even to recipients who have the
        app installed. Recipients without your app always see the static card regardless of this
        flag.

      - `url: optional string`

        URL the recipient's app opens when they tap the card. Either an absolute `https://` URL
        (capped at 2048 characters) or a `data:` URL carrying inline app state, e.g. a game's
        encoded state (capped at 16384 characters).

  - `preferred_service: optional ServiceType`

    Messaging service type

    - `"iMessage"`

    - `"SMS"`

    - `"RCS"`

  - `reply_to: optional ReplyTo`

    Reply to another message to create a threaded conversation

    - `message_id: string`

      The ID of the message to reply to

    - `part_index: optional number`

      The specific message part to reply to (0-based index).
      Defaults to 0 (first part) if not provided.
      Use this when replying to a specific part of a multipart message.

- `to: array of string`

  Array of recipient handles (phone numbers in E.164 format or email addresses).
  For individual chats, provide one recipient. For group chats, provide multiple.

### Returns

- `chat: object { id, display_name, handles, 4 more }`

  - `id: string`

    Unique identifier for the created chat (UUID)

  - `display_name: string`

    Display name for the chat. Defaults to a comma-separated list of recipient handles. Can be updated for group chats.

  - `handles: array of ChatHandle`

    List of participants in the chat. Always contains at least two handles (your phone number and the other participant).

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

  - `health_status: object { doc_url, status, updated_at }`

    **[BETA]** Current health for a chat. Always present — chats start at `HEALTHY` and may shift based on engagement and delivery signals on the conversation. Many `AT_RISK` or `CRITICAL` chats on a single line increase the risk of line flagging.

    Switch on `status` to gate sends or surface line health in your UI — the enum is the long-term contract. Each status carries a `doc_url` that deep-links to the relevant section of the Chat Health guide.

    See the [Chat Health guide](/guides/chats/chat-health) for what each status means and how to react.

    - `doc_url: string`

      Deep-link to the relevant section of the Chat Health guide for this status.

    - `status: "HEALTHY" or "AT_RISK" or "CRITICAL" or "OPTED_OUT"`

      Current health bucket for the chat. See the [Chat Health guide](/guides/chats/chat-health) for what each value means and how to react. `doc_url` deep-links to the relevant section.

      `OPTED_OUT` is terminal — the recipient sent `STOP`, `UNSUBSCRIBE`, `OPTOUT`, `CANCEL`, `END`, or `QUIT`,
      and you should send nothing further on this chat. Matching is exact and case-sensitive against the whole
      trimmed message. It clears if they later send `START`, `OPTIN`, or `UNSTOP`, or if they keep replying on
      the chat — sustained two-way conversation is treated as a sign the stop keyword was a false positive.
      Suppressing sends to opted-out recipients is your responsibility — Linq surfaces the status but does not
      block the send.

      - `"HEALTHY"`

      - `"AT_RISK"`

      - `"CRITICAL"`

      - `"OPTED_OUT"`

    - `updated_at: string`

      When this status last changed.

  - `is_group: boolean`

    Whether this is a group chat

  - `message: SentMessage`

    A message that was sent (used in CreateChat and SendMessage responses)

    - `id: string`

      Message identifier (UUID)

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

    - `is_read: boolean`

      DEPRECATED: Use `delivery_status == "read"` instead. Whether the message has been read.

    - `parts: array of TextPartResponse or MediaPartResponse or LinkPartResponse or object { app, layout, reactions, 3 more }`

      Message parts in order (text, media, and link)

      - `TextPartResponse object { reactions, type, value, text_decorations }`

        A text message part

        - `reactions: array of Reaction`

          Reactions on this message part

          - `handle: ChatHandle`

            - `id: string`

              Unique identifier for this handle

            - `handle: string`

              Phone number (E.164) or email address of the participant

            - `joined_at: string`

              When this participant joined the chat

            - `service: ServiceType`

              Messaging service type

            - `is_me: optional boolean`

              Whether this handle belongs to the sender (your phone number)

            - `left_at: optional string`

              When they left (if applicable)

            - `status: optional "active" or "left" or "removed"`

              Participant status

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

    - `sent_at: string`

      When the message was actually sent (null if still queued)

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

    - `from_handle: optional ChatHandle`

      The sender of this message as a full handle object

    - `preferred_service: optional ServiceType`

      Messaging service type

    - `reply_to: optional ReplyTo`

      Indicates this message is a threaded reply to another message

      - `message_id: string`

        The ID of the message to reply to

      - `part_index: optional number`

        The specific message part to reply to (0-based index).
        Defaults to 0 (first part) if not provided.
        Use this when replying to a specific part of a multipart message.

    - `service: optional ServiceType`

      Messaging service type

  - `service: ServiceType`

    Messaging service type

### Example

```http
curl https://api.linqapp.com/api/partner/v3/chats \
    -H 'Content-Type: application/json' \
    -H "Authorization: Bearer $LINQ_API_V3_API_KEY" \
    -d '{
          "from": "+12052535597",
          "message": {
            "parts": [
              {
                "type": "text",
                "value": "Hello! How can I help you today?"
              }
            ]
          },
          "to": [
            "+12052532136"
          ]
        }'
```

#### Response

```json
{
  "chat": {
    "id": "94c6bf33-31d9-40e3-a0e9-f94250ecedb9",
    "display_name": "+14155551234, +14155559876",
    "handles": [
      {
        "id": "550e8400-e29b-41d4-a716-446655440010",
        "handle": "+14155551234",
        "joined_at": "2025-05-21T15:30:00.000Z",
        "service": "iMessage",
        "is_me": true,
        "left_at": "2019-12-27T18:11:19.117Z",
        "status": "active"
      },
      {
        "id": "550e8400-e29b-41d4-a716-446655440011",
        "handle": "+14155559876",
        "joined_at": "2025-05-21T15:30:00.000Z",
        "service": "iMessage",
        "is_me": false,
        "left_at": "2019-12-27T18:11:19.117Z",
        "status": "active"
      }
    ],
    "health_status": {
      "doc_url": "https://docs.linqapp.com/guides/chats/chat-health#at-risk",
      "status": "AT_RISK",
      "updated_at": "2026-05-01T18:28:25Z"
    },
    "is_group": false,
    "message": {
      "id": "69a37c7d-af4f-4b5e-af42-e28e98ce873a",
      "created_at": "2025-10-23T13:07:55.019-05:00",
      "delivery_status": "pending",
      "is_read": false,
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
      "sent_at": null,
      "delivered_at": null,
      "effect": {
        "name": "confetti",
        "type": "screen"
      },
      "from_handle": {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "handle": "+15551234567",
        "joined_at": "2025-05-21T15:30:00.000-05:00",
        "service": "iMessage",
        "is_me": false,
        "left_at": "2019-12-27T18:11:19.117Z",
        "status": "active"
      },
      "preferred_service": "iMessage",
      "reply_to": {
        "message_id": "550e8400-e29b-41d4-a716-446655440000",
        "part_index": 0
      },
      "service": "iMessage"
    },
    "service": "iMessage"
  }
}
```

## List all chats

**get** `/v3/chats`

Retrieves a paginated list of chats for the authenticated partner.

**Filtering:**

- If `from` is provided, returns chats for that specific phone number
- If `from` is omitted, returns chats across all phone numbers owned by the partner
- If `to` is provided, only returns chats where the specified handle is a participant

**Pagination:**

- Use `limit` to control page size (default: 20, max: 100)
- The response includes `next_cursor` for fetching the next page
- When `next_cursor` is `null`, there are no more results to fetch
- Pass the `next_cursor` value as the `cursor` parameter for the next request

**Example pagination flow:**

1. First request: `GET /v3/chats?from=%2B12223334444&limit=20`
1. Response includes `next_cursor: "20"` (more results exist)
1. Next request: `GET /v3/chats?from=%2B12223334444&limit=20&cursor=20`
1. Response includes `next_cursor: null` (no more results)

### Query Parameters

- `cursor: optional string`

  Pagination cursor from the previous response's `next_cursor` field.
  Omit this parameter for the first page of results.

- `from: optional string`

  Phone number to filter chats by. Returns chats made from this phone number.
  Must be in E.164 format (e.g., `+13343284472`). The `+` is automatically URL-encoded by HTTP clients.
  If omitted, returns chats across all phone numbers owned by the partner.

- `limit: optional number`

  Maximum number of chats to return per page

- `to: optional string`

  Filter chats by a participant handle. Only returns chats where this handle is a participant.
  Can be an E.164 phone number (e.g., `+13343284472`) or an email address (e.g., `user@example.com`).
  For phone numbers, the `+` is automatically URL-encoded by HTTP clients.

### Returns

- `chats: array of Chat`

  List of chats

  - `id: string`

    Unique identifier for the chat

  - `created_at: string`

    When the chat was created

  - `display_name: string`

    Display name for the chat. Defaults to a comma-separated list of recipient handles. Can be updated for group chats.

  - `handles: array of ChatHandle`

    List of chat participants with full handle details. Always contains at least two handles (your phone number and the other participant).

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

  - `health_status: object { doc_url, status, updated_at }`

    **[BETA]** Current health for a chat. Always present — chats start at `HEALTHY` and may shift based on engagement and delivery signals on the conversation. Many `AT_RISK` or `CRITICAL` chats on a single line increase the risk of line flagging.

    Switch on `status` to gate sends or surface line health in your UI — the enum is the long-term contract. Each status carries a `doc_url` that deep-links to the relevant section of the Chat Health guide.

    See the [Chat Health guide](/guides/chats/chat-health) for what each status means and how to react.

    - `doc_url: string`

      Deep-link to the relevant section of the Chat Health guide for this status.

    - `status: "HEALTHY" or "AT_RISK" or "CRITICAL" or "OPTED_OUT"`

      Current health bucket for the chat. See the [Chat Health guide](/guides/chats/chat-health) for what each value means and how to react. `doc_url` deep-links to the relevant section.

      `OPTED_OUT` is terminal — the recipient sent `STOP`, `UNSUBSCRIBE`, `OPTOUT`, `CANCEL`, `END`, or `QUIT`,
      and you should send nothing further on this chat. Matching is exact and case-sensitive against the whole
      trimmed message. It clears if they later send `START`, `OPTIN`, or `UNSTOP`, or if they keep replying on
      the chat — sustained two-way conversation is treated as a sign the stop keyword was a false positive.
      Suppressing sends to opted-out recipients is your responsibility — Linq surfaces the status but does not
      block the send.

      - `"HEALTHY"`

      - `"AT_RISK"`

      - `"CRITICAL"`

      - `"OPTED_OUT"`

    - `updated_at: string`

      When this status last changed.

  - `is_archived: boolean`

    **DEPRECATED:** This field is deprecated and will be removed in a future API version.

  - `is_group: boolean`

    Whether this is a group chat

  - `updated_at: string`

    When the chat was last updated

  - `group_chat_icon: optional string`

    URL of the group chat icon. Only set for group chats that have an icon; `null` otherwise.

  - `service: optional ServiceType`

    Messaging service type

- `next_cursor: optional string`

  Cursor for fetching the next page of results.
  Null if there are no more results to fetch.
  Pass this value as the `cursor` parameter in the next request.

### Example

```http
curl https://api.linqapp.com/api/partner/v3/chats \
    -H "Authorization: Bearer $LINQ_API_V3_API_KEY"
```

#### Response

```json
{
  "chats": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "created_at": "2024-01-15T10:30:00Z",
      "display_name": "+14155551234, +14155559876",
      "handles": [
        {
          "id": "550e8400-e29b-41d4-a716-446655440010",
          "handle": "+14155551234",
          "joined_at": "2025-05-21T15:30:00.000Z",
          "service": "iMessage",
          "is_me": true,
          "left_at": "2019-12-27T18:11:19.117Z",
          "status": "active"
        },
        {
          "id": "550e8400-e29b-41d4-a716-446655440011",
          "handle": "+14155559876",
          "joined_at": "2025-05-21T15:30:00.000Z",
          "service": "iMessage",
          "is_me": false,
          "left_at": "2019-12-27T18:11:19.117Z",
          "status": "active"
        }
      ],
      "health_status": {
        "doc_url": "https://docs.linqapp.com/guides/chats/chat-health#at-risk",
        "status": "AT_RISK",
        "updated_at": "2026-05-01T18:28:25Z"
      },
      "is_archived": true,
      "is_group": true,
      "updated_at": "2024-01-15T10:30:00Z",
      "group_chat_icon": "https://example.com/group-icon.png",
      "service": "iMessage"
    }
  ],
  "next_cursor": "next_cursor"
}
```

## Get a chat by ID

**get** `/v3/chats/{chatId}`

Retrieve a chat by its unique identifier.

### Path Parameters

- `chatId: string`

### Returns

- `Chat object { id, created_at, display_name, 7 more }`

  - `id: string`

    Unique identifier for the chat

  - `created_at: string`

    When the chat was created

  - `display_name: string`

    Display name for the chat. Defaults to a comma-separated list of recipient handles. Can be updated for group chats.

  - `handles: array of ChatHandle`

    List of chat participants with full handle details. Always contains at least two handles (your phone number and the other participant).

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

  - `health_status: object { doc_url, status, updated_at }`

    **[BETA]** Current health for a chat. Always present — chats start at `HEALTHY` and may shift based on engagement and delivery signals on the conversation. Many `AT_RISK` or `CRITICAL` chats on a single line increase the risk of line flagging.

    Switch on `status` to gate sends or surface line health in your UI — the enum is the long-term contract. Each status carries a `doc_url` that deep-links to the relevant section of the Chat Health guide.

    See the [Chat Health guide](/guides/chats/chat-health) for what each status means and how to react.

    - `doc_url: string`

      Deep-link to the relevant section of the Chat Health guide for this status.

    - `status: "HEALTHY" or "AT_RISK" or "CRITICAL" or "OPTED_OUT"`

      Current health bucket for the chat. See the [Chat Health guide](/guides/chats/chat-health) for what each value means and how to react. `doc_url` deep-links to the relevant section.

      `OPTED_OUT` is terminal — the recipient sent `STOP`, `UNSUBSCRIBE`, `OPTOUT`, `CANCEL`, `END`, or `QUIT`,
      and you should send nothing further on this chat. Matching is exact and case-sensitive against the whole
      trimmed message. It clears if they later send `START`, `OPTIN`, or `UNSTOP`, or if they keep replying on
      the chat — sustained two-way conversation is treated as a sign the stop keyword was a false positive.
      Suppressing sends to opted-out recipients is your responsibility — Linq surfaces the status but does not
      block the send.

      - `"HEALTHY"`

      - `"AT_RISK"`

      - `"CRITICAL"`

      - `"OPTED_OUT"`

    - `updated_at: string`

      When this status last changed.

  - `is_archived: boolean`

    **DEPRECATED:** This field is deprecated and will be removed in a future API version.

  - `is_group: boolean`

    Whether this is a group chat

  - `updated_at: string`

    When the chat was last updated

  - `group_chat_icon: optional string`

    URL of the group chat icon. Only set for group chats that have an icon; `null` otherwise.

  - `service: optional ServiceType`

    Messaging service type

### Example

```http
curl https://api.linqapp.com/api/partner/v3/chats/$CHAT_ID \
    -H "Authorization: Bearer $LINQ_API_V3_API_KEY"
```

#### Response

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "created_at": "2024-01-15T10:30:00Z",
  "display_name": "+14155551234, +14155559876",
  "handles": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440010",
      "handle": "+14155551234",
      "joined_at": "2025-05-21T15:30:00.000Z",
      "service": "iMessage",
      "is_me": true,
      "left_at": "2019-12-27T18:11:19.117Z",
      "status": "active"
    },
    {
      "id": "550e8400-e29b-41d4-a716-446655440011",
      "handle": "+14155559876",
      "joined_at": "2025-05-21T15:30:00.000Z",
      "service": "iMessage",
      "is_me": false,
      "left_at": "2019-12-27T18:11:19.117Z",
      "status": "active"
    }
  ],
  "health_status": {
    "doc_url": "https://docs.linqapp.com/guides/chats/chat-health#at-risk",
    "status": "AT_RISK",
    "updated_at": "2026-05-01T18:28:25Z"
  },
  "is_archived": true,
  "is_group": true,
  "updated_at": "2024-01-15T10:30:00Z",
  "group_chat_icon": "https://example.com/group-icon.png",
  "service": "iMessage"
}
```

## Update a chat

**put** `/v3/chats/{chatId}`

Update chat properties such as display name and group chat icon.

Listen for `chat.group_name_updated`, `chat.group_icon_updated`,
`chat.group_name_update_failed`, or `chat.group_icon_update_failed`
webhook events to confirm the outcome.

### Path Parameters

- `chatId: string`

### Body Parameters

- `display_name: optional string`

  New display name for the chat (group chats only)

- `group_chat_icon: optional string`

  URL of an image to set as the group chat icon (group chats only)

### Returns

- `chat_id: optional string`

- `status: optional string`

### Example

```http
curl https://api.linqapp.com/api/partner/v3/chats/$CHAT_ID \
    -X PUT \
    -H 'Content-Type: application/json' \
    -H "Authorization: Bearer $LINQ_API_V3_API_KEY" \
    -d '{
          "display_name": "Team Discussion",
          "group_chat_icon": "https://example.com/icon.png"
        }'
```

#### Response

```json
{
  "chat_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending"
}
```

## Mark chat as read

**post** `/v3/chats/{chatId}/read`

Mark all messages in a chat as read.

### Path Parameters

- `chatId: string`

### Example

```http
curl https://api.linqapp.com/api/partner/v3/chats/$CHAT_ID/read \
    -X POST \
    -H "Authorization: Bearer $LINQ_API_V3_API_KEY"
```

#### Response

```json
{
  "error": {
    "status": 401,
    "code": 2004,
    "message": "Unauthorized - missing or invalid authentication token",
    "doc_url": "https://docs.linqapp.com/error/codes/2xxx/2004/"
  },
  "success": false
}
```

## Leave a group chat

**post** `/v3/chats/{chatId}/leave`

Removes your phone number from a group chat. Once you leave, you will no longer receive messages from the group and all interaction endpoints (send message, typing, mark read, etc.) will return 409.

A `participant.removed` webhook will fire once the leave has been processed.

**Supported**

- iMessage group chats with 4 or more active participants (including yourself)

**Not supported**

- DM (1-on-1) chats — use the chat directly to continue the conversation

### Path Parameters

- `chatId: string`

### Returns

- `message: optional string`

- `status: optional string`

- `trace_id: optional string`

### Example

```http
curl https://api.linqapp.com/api/partner/v3/chats/$CHAT_ID/leave \
    -X POST \
    -H "Authorization: Bearer $LINQ_API_V3_API_KEY"
```

#### Response

```json
{
  "message": "Leave group chat queued",
  "status": "accepted",
  "trace_id": "trace_id"
}
```

## Share your contact card with a chat

**post** `/v3/chats/{chatId}/share_contact_card`

Share your contact information (Name and Photo Sharing) with a chat.

**Note:** A contact card must be configured before sharing. You can set up your contact card via the [Contact Card API](#tag/Contact-Card) or on the [Linq dashboard](https://dashboard.linqapp.com/contact-cards).

### Path Parameters

- `chatId: string`

### Example

```http
curl https://api.linqapp.com/api/partner/v3/chats/$CHAT_ID/share_contact_card \
    -X POST \
    -H "Authorization: Bearer $LINQ_API_V3_API_KEY"
```

#### Response

```json
{
  "error": {
    "status": 401,
    "code": 2004,
    "message": "Unauthorized - missing or invalid authentication token",
    "doc_url": "https://docs.linqapp.com/error/codes/2xxx/2004/"
  },
  "success": false
}
```

## Send a voice memo to a chat

**post** `/v3/chats/{chatId}/voicememo`

Send an audio file as an **iMessage voice memo bubble** to all participants in a chat.
Voice memos appear with iMessage's native inline playback UI, unlike regular audio
attachments sent via media parts which appear as downloadable files.

**Supported audio formats:**

- MP3 (audio/mpeg)
- M4A (audio/x-m4a, audio/mp4)
- AAC (audio/aac)
- CAF (audio/x-caf) - Core Audio Format
- WAV (audio/wav)
- AIFF (audio/aiff, audio/x-aiff)
- AMR (audio/amr)

### Path Parameters

- `chatId: string`

### Body Parameters

- `attachment_id: optional string`

  Reference to a voice memo file pre-uploaded via `POST /v3/attachments`.
  The file is already stored, so sends using this ID skip the download step.

  Either `voice_memo_url` or `attachment_id` must be provided, but not both.

- `voice_memo_url: optional string`

  URL of the voice memo audio file. Must be a publicly accessible HTTPS URL.

  Either `voice_memo_url` or `attachment_id` must be provided, but not both.

### Returns

- `voice_memo: object { id, chat, created_at, 5 more }`

  - `id: string`

    Message identifier

  - `chat: object { id, handles, is_active, 2 more }`

    - `id: string`

      Chat identifier

    - `handles: array of ChatHandle`

      Chat participants

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

    - `is_active: boolean`

      Whether the chat is active

    - `is_group: boolean`

      Whether this is a group chat

    - `service: ServiceType`

      Messaging service type

  - `created_at: string`

    When the voice memo was created

  - `from: string`

    Sender phone number

  - `status: string`

    Current delivery status

  - `to: array of string`

    Recipient handles (phone numbers or email addresses)

  - `voice_memo: object { id, filename, mime_type, 3 more }`

    - `id: string`

      Attachment identifier

    - `filename: string`

      Original filename

    - `mime_type: string`

      Audio MIME type

    - `size_bytes: number`

      File size in bytes

    - `url: string`

      CDN URL for downloading the voice memo

    - `duration_ms: optional number`

      Duration in milliseconds

  - `service: optional ServiceType`

    Messaging service type

### Example

```http
curl https://api.linqapp.com/api/partner/v3/chats/$CHAT_ID/voicememo \
    -H 'Content-Type: application/json' \
    -H "Authorization: Bearer $LINQ_API_V3_API_KEY" \
    -d '{
          "voice_memo_url": "https://example.com/voice-memo.m4a"
        }'
```

#### Response

```json
{
  "voice_memo": {
    "id": "69a37c7d-af4f-4b5e-af42-e28e98ce873a",
    "chat": {
      "id": "182bd5e5-6e1a-4fe4-a799-aa6d9a6ab26e",
      "handles": [
        {
          "id": "550e8400-e29b-41d4-a716-446655440000",
          "handle": "+15551234567",
          "joined_at": "2025-05-21T15:30:00.000-05:00",
          "service": "iMessage",
          "is_me": false,
          "left_at": "2019-12-27T18:11:19.117Z",
          "status": "active"
        }
      ],
      "is_active": true,
      "is_group": true,
      "service": "iMessage"
    },
    "created_at": "2019-12-27T18:11:19.117Z",
    "from": "+12052535597",
    "status": "queued",
    "to": [
      "+12052532136"
    ],
    "voice_memo": {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "filename": "voice-memo.m4a",
      "mime_type": "audio/x-m4a",
      "size_bytes": 524288,
      "url": "https://cdn.linqapp.com/voice-memos/abc123.m4a",
      "duration_ms": 15000
    },
    "service": "iMessage"
  }
}
```

## Domain Types

### Chat

- `Chat object { id, created_at, display_name, 7 more }`

  - `id: string`

    Unique identifier for the chat

  - `created_at: string`

    When the chat was created

  - `display_name: string`

    Display name for the chat. Defaults to a comma-separated list of recipient handles. Can be updated for group chats.

  - `handles: array of ChatHandle`

    List of chat participants with full handle details. Always contains at least two handles (your phone number and the other participant).

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

  - `health_status: object { doc_url, status, updated_at }`

    **[BETA]** Current health for a chat. Always present — chats start at `HEALTHY` and may shift based on engagement and delivery signals on the conversation. Many `AT_RISK` or `CRITICAL` chats on a single line increase the risk of line flagging.

    Switch on `status` to gate sends or surface line health in your UI — the enum is the long-term contract. Each status carries a `doc_url` that deep-links to the relevant section of the Chat Health guide.

    See the [Chat Health guide](/guides/chats/chat-health) for what each status means and how to react.

    - `doc_url: string`

      Deep-link to the relevant section of the Chat Health guide for this status.

    - `status: "HEALTHY" or "AT_RISK" or "CRITICAL" or "OPTED_OUT"`

      Current health bucket for the chat. See the [Chat Health guide](/guides/chats/chat-health) for what each value means and how to react. `doc_url` deep-links to the relevant section.

      `OPTED_OUT` is terminal — the recipient sent `STOP`, `UNSUBSCRIBE`, `OPTOUT`, `CANCEL`, `END`, or `QUIT`,
      and you should send nothing further on this chat. Matching is exact and case-sensitive against the whole
      trimmed message. It clears if they later send `START`, `OPTIN`, or `UNSTOP`, or if they keep replying on
      the chat — sustained two-way conversation is treated as a sign the stop keyword was a false positive.
      Suppressing sends to opted-out recipients is your responsibility — Linq surfaces the status but does not
      block the send.

      - `"HEALTHY"`

      - `"AT_RISK"`

      - `"CRITICAL"`

      - `"OPTED_OUT"`

    - `updated_at: string`

      When this status last changed.

  - `is_archived: boolean`

    **DEPRECATED:** This field is deprecated and will be removed in a future API version.

  - `is_group: boolean`

    Whether this is a group chat

  - `updated_at: string`

    When the chat was last updated

  - `group_chat_icon: optional string`

    URL of the group chat icon. Only set for group chats that have an icon; `null` otherwise.

  - `service: optional ServiceType`

    Messaging service type

### Link Part

- `LinkPart object { type, value }`

  - `type: "link"`

    Indicates this is a rich link preview part

    - `"link"`

  - `value: string`

    URL to send with a rich link preview. The recipient will see an inline card
    with the page's title, description, and preview image (when available).

    A `link` part must be the **only** part in the message. To send a URL as plain
    text (no preview card), use a `text` part instead.

### Media Part

- `MediaPart object { type, attachment_id, url }`

  - `type: "media"`

    Indicates this is a media attachment part

    - `"media"`

  - `attachment_id: optional string`

    Reference to a file pre-uploaded via `POST /v3/attachments` (optional).
    The file is already stored, so sends using this ID skip the download step —
    useful when sending the same file to many recipients.

    Either `url` or `attachment_id` must be provided, but not both.

  - `url: optional string`

    Any publicly accessible HTTPS URL to the media file. The server downloads and
    sends the file automatically — no pre-upload step required.

    **Size limit:** 10MB maximum for URL-based downloads. For larger files (up to 100MB),
    use the pre-upload flow: `POST /v3/attachments` to get a presigned URL, upload directly,
    then reference by `attachment_id`.

    **Requirements:**

    - URL must use HTTPS
    - File content must be a supported format (the server validates the actual file content)

    **Supported formats:**

    - Images: .jpg, .jpeg, .png, .gif, .heic, .heif, .tif, .tiff, .bmp
    - Videos: .mp4, .mov, .m4v, .mpeg, .mpg, .3gp
    - Audio: .m4a, .mp3, .aac, .caf, .wav, .aiff, .amr
    - Documents: .pdf, .txt, .rtf, .csv, .doc, .docx, .xls, .xlsx, .ppt, .pptx, .pages, .numbers, .key, .epub, .zip, .html, .htm
    - Contact & Calendar: .vcf, .ics

    **Tip:** Audio sent here appears as a regular file attachment. To send audio as an
    iMessage voice memo bubble (with inline playback), use `/v3/chats/{chatId}/voicememo`.
    For repeated sends of the same file, use `attachment_id` to avoid redundant downloads.

    Either `url` or `attachment_id` must be provided, but not both.

### Message Content

- `MessageContent object { action, effect, idempotency_key, 3 more }`

  Message content container. Groups all message-related fields together,
  separating the "what" (message content) from the "where" (routing fields like from/to).

  A message carries EITHER `parts` — text and attachments, which compose
  into one bubble — or a single `action`, which invokes an experience
  inside Linq's iMessage app. Never both: an app card is the whole message
  (Apple's `MSMessage` cannot coexist with text), so copy and a card are
  two sends, not one.

  - `action: optional object { action, experience, params }`

    Invokes an action on an experience — a third party that renders inside
    Linq's iMessage app. Linq resolves the recipient's connection, mints any
    session the action needs, composes the card and sends it; none of that
    is visible to you.

    Call `GET /v3/experiences/{experience}` for the actions you may invoke
    and the fields each accepts.

    - `action: string`

      Which of its actions, e.g. `attach_card`.

    - `experience: string`

      The experience to invoke, e.g. `agentcard`.

    - `params: optional map[unknown]`

      Values for the fields this action exposes. Keys are exactly the
      field names listed for the action — no mapping, no nesting.

      Display copy only, except a `url`-type field — that value sets the
      destination, and must be an absolute `https` URL.

  - `effect: optional MessageEffect`

    iMessage effect to apply to this message (screen or bubble effect)

    - `name: optional string`

      Name of the effect. Common values:

      - Screen effects: confetti, fireworks, lasers, sparkles, celebration, hearts, love, balloons, happy_birthday, echo, spotlight
      - Bubble effects: slam, loud, gentle, invisible

    - `type: optional "screen" or "bubble"`

      Type of effect

      - `"screen"`

      - `"bubble"`

  - `idempotency_key: optional string`

    Optional idempotency key for this message.
    Use this to prevent duplicate sends of the same message. Reusing a key
    whose message was deleted — or was an ephemeral message that has since
    expired — returns 404; the message is never resent.

  - `parts: optional array of TextPart or MediaPart or LinkPart or object { app, layout, type, 3 more }`

    Array of message parts. Each part can be text, media, or link.
    Parts are displayed in order. Text and media can be mixed freely,
    but a `link` part must be the only part in the message.

    **Rich Link Previews:**

    - Use a `link` part to send a URL with a rich preview card
    - A `link` part must be the **only** part in the message
    - To send a URL as plain text (no preview), use a `text` part instead

    **Supported Media:**

    - Images: .jpg, .jpeg, .png, .gif, .heic, .heif, .tif, .tiff, .bmp
    - Videos: .mp4, .mov, .m4v, .mpeg, .mpg, .3gp
    - Audio: .m4a, .mp3, .aac, .caf, .wav, .aiff, .amr
    - Documents: .pdf, .txt, .rtf, .csv, .doc, .docx, .xls, .xlsx, .ppt, .pptx, .pages, .numbers, .key, .epub, .zip, .html, .htm
    - Contact & Calendar: .vcf, .ics

    **Audio:**

    - Audio files (.m4a, .mp3, .aac, .caf, .wav, .aiff, .amr) are fully supported as media parts
    - To send audio as an **iMessage voice memo bubble** (inline playback UI), use the dedicated
      `/v3/chats/{chatId}/voicememo` endpoint instead

    **Validation Rules:**

    - A `link` part must be the **only** part in the message. It cannot be combined
      with text or media parts.
    - Consecutive text parts are not allowed. Text parts must be separated by
      media parts. For example, [text, text] is invalid, but [text, media, text] is valid.
    - Maximum of **100 parts** total.
    - Media parts using a public `url` (downloaded by the server on send) are
      capped at **40**. Parts using `attachment_id` or presigned URLs
      are exempt from this sub-limit. For bulk media sends exceeding 40 files,
      pre-upload via `POST /v3/attachments` and reference by `attachment_id` or `download_url`.

    - `TextPart object { type, value, text_decorations }`

      - `type: "text"`

        Indicates this is a text message part

        - `"text"`

      - `value: string`

        The text content of the message. This value is sent as-is with no parsing or transformation — Markdown syntax will be delivered as plain text. Use `text_decorations` to apply inline formatting and animations (iMessage only).

      - `text_decorations: optional array of TextDecoration`

        Optional array of text decorations applied to character ranges in the `value` field (iMessage only).

        Each decoration specifies a character range `[start, end)` and exactly one of `style` or `animation`.

        **Styles:** `bold`, `italic`, `strikethrough`, `underline`
        **Animations:** `big`, `small`, `shake`, `nod`, `explode`, `ripple`, `bloom`, `jitter`

        Style ranges may overlap (e.g. bold + italic on the same text), but animation ranges must not overlap with other animations or styles.

        *Characters are measured as UTF-16 code units. Most characters count as 1; some emoji count as 2.*

        **Note:** Text decorations only render for iMessage recipients. For SMS/RCS, text decorations are not applied.

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

    - `MediaPart object { type, attachment_id, url }`

      - `type: "media"`

        Indicates this is a media attachment part

        - `"media"`

      - `attachment_id: optional string`

        Reference to a file pre-uploaded via `POST /v3/attachments` (optional).
        The file is already stored, so sends using this ID skip the download step —
        useful when sending the same file to many recipients.

        Either `url` or `attachment_id` must be provided, but not both.

      - `url: optional string`

        Any publicly accessible HTTPS URL to the media file. The server downloads and
        sends the file automatically — no pre-upload step required.

        **Size limit:** 10MB maximum for URL-based downloads. For larger files (up to 100MB),
        use the pre-upload flow: `POST /v3/attachments` to get a presigned URL, upload directly,
        then reference by `attachment_id`.

        **Requirements:**

        - URL must use HTTPS
        - File content must be a supported format (the server validates the actual file content)

        **Supported formats:**

        - Images: .jpg, .jpeg, .png, .gif, .heic, .heif, .tif, .tiff, .bmp
        - Videos: .mp4, .mov, .m4v, .mpeg, .mpg, .3gp
        - Audio: .m4a, .mp3, .aac, .caf, .wav, .aiff, .amr
        - Documents: .pdf, .txt, .rtf, .csv, .doc, .docx, .xls, .xlsx, .ppt, .pptx, .pages, .numbers, .key, .epub, .zip, .html, .htm
        - Contact & Calendar: .vcf, .ics

        **Tip:** Audio sent here appears as a regular file attachment. To send audio as an
        iMessage voice memo bubble (with inline playback), use `/v3/chats/{chatId}/voicememo`.
        For repeated sends of the same file, use `attachment_id` to avoid redundant downloads.

        Either `url` or `attachment_id` must be provided, but not both.

    - `LinkPart object { type, value }`

      - `type: "link"`

        Indicates this is a rich link preview part

        - `"link"`

      - `value: string`

        URL to send with a rich link preview. The recipient will see an inline card
        with the page's title, description, and preview image (when available).

        A `link` part must be the **only** part in the message. To send a URL as plain
        text (no preview card), use a `text` part instead.

    - `IMessageApp object { app, layout, type, 3 more }`

      An iMessage app card, backed by a Messages app extension. iMessage only —
      an `imessage_app` part must be the **only** part in the message and is never delivered over
      SMS/RCS. See the IMessageAppServiceUnsupported (2018) and RecipientUnsupportedMessageType
      (4005) error codes.

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

      - `type: "imessage_app"`

        Indicates this is an iMessage app card part.

        - `"imessage_app"`

      - `fallback_text: optional string`

        Text shown on surfaces that cannot render the card (notifications, lock screen). Defaults
        to the caption when omitted.

      - `interactive: optional boolean`

        Whether the card renders as your app's interactive balloon for recipients who have your
        iMessage app installed. `true` (default) lets your installed extension draw its live,
        interactive view for those recipients; everyone else sees the static card built from
        `layout`. `false` always shows the static `layout` card, even to recipients who have the
        app installed. Recipients without your app always see the static card regardless of this
        flag.

      - `url: optional string`

        URL the recipient's app opens when they tap the card. Either an absolute `https://` URL
        (capped at 2048 characters) or a `data:` URL carrying inline app state, e.g. a game's
        encoded state (capped at 16384 characters).

  - `preferred_service: optional ServiceType`

    Messaging service type

    - `"iMessage"`

    - `"SMS"`

    - `"RCS"`

  - `reply_to: optional ReplyTo`

    Reply to another message to create a threaded conversation

    - `message_id: string`

      The ID of the message to reply to

    - `part_index: optional number`

      The specific message part to reply to (0-based index).
      Defaults to 0 (first part) if not provided.
      Use this when replying to a specific part of a multipart message.

### Text Part

- `TextPart object { type, value, text_decorations }`

  - `type: "text"`

    Indicates this is a text message part

    - `"text"`

  - `value: string`

    The text content of the message. This value is sent as-is with no parsing or transformation — Markdown syntax will be delivered as plain text. Use `text_decorations` to apply inline formatting and animations (iMessage only).

  - `text_decorations: optional array of TextDecoration`

    Optional array of text decorations applied to character ranges in the `value` field (iMessage only).

    Each decoration specifies a character range `[start, end)` and exactly one of `style` or `animation`.

    **Styles:** `bold`, `italic`, `strikethrough`, `underline`
    **Animations:** `big`, `small`, `shake`, `nod`, `explode`, `ripple`, `bloom`, `jitter`

    Style ranges may overlap (e.g. bold + italic on the same text), but animation ranges must not overlap with other animations or styles.

    *Characters are measured as UTF-16 code units. Most characters count as 1; some emoji count as 2.*

    **Note:** Text decorations only render for iMessage recipients. For SMS/RCS, text decorations are not applied.

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

### Chat Create Response

- `ChatCreateResponse object { chat }`

  Response for creating a new chat with an initial message

  - `chat: object { id, display_name, handles, 4 more }`

    - `id: string`

      Unique identifier for the created chat (UUID)

    - `display_name: string`

      Display name for the chat. Defaults to a comma-separated list of recipient handles. Can be updated for group chats.

    - `handles: array of ChatHandle`

      List of participants in the chat. Always contains at least two handles (your phone number and the other participant).

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

    - `health_status: object { doc_url, status, updated_at }`

      **[BETA]** Current health for a chat. Always present — chats start at `HEALTHY` and may shift based on engagement and delivery signals on the conversation. Many `AT_RISK` or `CRITICAL` chats on a single line increase the risk of line flagging.

      Switch on `status` to gate sends or surface line health in your UI — the enum is the long-term contract. Each status carries a `doc_url` that deep-links to the relevant section of the Chat Health guide.

      See the [Chat Health guide](/guides/chats/chat-health) for what each status means and how to react.

      - `doc_url: string`

        Deep-link to the relevant section of the Chat Health guide for this status.

      - `status: "HEALTHY" or "AT_RISK" or "CRITICAL" or "OPTED_OUT"`

        Current health bucket for the chat. See the [Chat Health guide](/guides/chats/chat-health) for what each value means and how to react. `doc_url` deep-links to the relevant section.

        `OPTED_OUT` is terminal — the recipient sent `STOP`, `UNSUBSCRIBE`, `OPTOUT`, `CANCEL`, `END`, or `QUIT`,
        and you should send nothing further on this chat. Matching is exact and case-sensitive against the whole
        trimmed message. It clears if they later send `START`, `OPTIN`, or `UNSTOP`, or if they keep replying on
        the chat — sustained two-way conversation is treated as a sign the stop keyword was a false positive.
        Suppressing sends to opted-out recipients is your responsibility — Linq surfaces the status but does not
        block the send.

        - `"HEALTHY"`

        - `"AT_RISK"`

        - `"CRITICAL"`

        - `"OPTED_OUT"`

      - `updated_at: string`

        When this status last changed.

    - `is_group: boolean`

      Whether this is a group chat

    - `message: SentMessage`

      A message that was sent (used in CreateChat and SendMessage responses)

      - `id: string`

        Message identifier (UUID)

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

      - `is_read: boolean`

        DEPRECATED: Use `delivery_status == "read"` instead. Whether the message has been read.

      - `parts: array of TextPartResponse or MediaPartResponse or LinkPartResponse or object { app, layout, reactions, 3 more }`

        Message parts in order (text, media, and link)

        - `TextPartResponse object { reactions, type, value, text_decorations }`

          A text message part

          - `reactions: array of Reaction`

            Reactions on this message part

            - `handle: ChatHandle`

              - `id: string`

                Unique identifier for this handle

              - `handle: string`

                Phone number (E.164) or email address of the participant

              - `joined_at: string`

                When this participant joined the chat

              - `service: ServiceType`

                Messaging service type

              - `is_me: optional boolean`

                Whether this handle belongs to the sender (your phone number)

              - `left_at: optional string`

                When they left (if applicable)

              - `status: optional "active" or "left" or "removed"`

                Participant status

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

      - `sent_at: string`

        When the message was actually sent (null if still queued)

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

      - `from_handle: optional ChatHandle`

        The sender of this message as a full handle object

      - `preferred_service: optional ServiceType`

        Messaging service type

      - `reply_to: optional ReplyTo`

        Indicates this message is a threaded reply to another message

        - `message_id: string`

          The ID of the message to reply to

        - `part_index: optional number`

          The specific message part to reply to (0-based index).
          Defaults to 0 (first part) if not provided.
          Use this when replying to a specific part of a multipart message.

      - `service: optional ServiceType`

        Messaging service type

    - `service: ServiceType`

      Messaging service type

### Chat Update Response

- `ChatUpdateResponse object { chat_id, status }`

  - `chat_id: optional string`

  - `status: optional string`

### Chat Leave Chat Response

- `ChatLeaveChatResponse object { message, status, trace_id }`

  - `message: optional string`

  - `status: optional string`

  - `trace_id: optional string`

### Chat Send Voicememo Response

- `ChatSendVoicememoResponse object { voice_memo }`

  Response for sending a voice memo to a chat

  - `voice_memo: object { id, chat, created_at, 5 more }`

    - `id: string`

      Message identifier

    - `chat: object { id, handles, is_active, 2 more }`

      - `id: string`

        Chat identifier

      - `handles: array of ChatHandle`

        Chat participants

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

      - `is_active: boolean`

        Whether the chat is active

      - `is_group: boolean`

        Whether this is a group chat

      - `service: ServiceType`

        Messaging service type

    - `created_at: string`

      When the voice memo was created

    - `from: string`

      Sender phone number

    - `status: string`

      Current delivery status

    - `to: array of string`

      Recipient handles (phone numbers or email addresses)

    - `voice_memo: object { id, filename, mime_type, 3 more }`

      - `id: string`

        Attachment identifier

      - `filename: string`

        Original filename

      - `mime_type: string`

        Audio MIME type

      - `size_bytes: number`

        File size in bytes

      - `url: string`

        CDN URL for downloading the voice memo

      - `duration_ms: optional number`

        Duration in milliseconds

    - `service: optional ServiceType`

      Messaging service type

# Participants

## Add a participant to a chat

**post** `/v3/chats/{chatId}/participants`

Add a new participant to an existing group chat.

**Requirements:**

- Group chats only (3+ existing participants)
- New participant must support the same messaging service as the group
- Cross-service additions not allowed (e.g., can't add RCS-only user to iMessage group)
- For cross-service scenarios, create a new chat instead

### Path Parameters

- `chatId: string`

### Body Parameters

- `handle: string`

  Phone number (E.164 format) or email address of the participant to add

### Returns

- `message: optional string`

- `status: optional string`

- `trace_id: optional string`

### Example

```http
curl https://api.linqapp.com/api/partner/v3/chats/$CHAT_ID/participants \
    -H 'Content-Type: application/json' \
    -H "Authorization: Bearer $LINQ_API_V3_API_KEY" \
    -d '{
          "handle": "+12052499136"
        }'
```

#### Response

```json
{
  "message": "Participant addition queued",
  "status": "accepted",
  "trace_id": "trace_id"
}
```

## Remove a participant from a chat

**delete** `/v3/chats/{chatId}/participants`

Remove a participant from an existing group chat.

**Requirements:**

- Group chats only
- Must have 3+ participants after removal

### Path Parameters

- `chatId: string`

### Body Parameters

- `handle: string`

  Phone number (E.164 format) or email address of the participant to remove

### Returns

- `message: optional string`

- `status: optional string`

- `trace_id: optional string`

### Example

```http
curl https://api.linqapp.com/api/partner/v3/chats/$CHAT_ID/participants \
    -X DELETE \
    -H "Authorization: Bearer $LINQ_API_V3_API_KEY"
```

#### Response

```json
{
  "message": "Participant removal queued",
  "status": "accepted",
  "trace_id": "trace_id"
}
```

## Domain Types

### Participant Add Response

- `ParticipantAddResponse object { message, status, trace_id }`

  - `message: optional string`

  - `status: optional string`

  - `trace_id: optional string`

### Participant Remove Response

- `ParticipantRemoveResponse object { message, status, trace_id }`

  - `message: optional string`

  - `status: optional string`

  - `trace_id: optional string`

# Typing

## Start typing indicator

**post** `/v3/chats/{chatId}/typing`

Send a typing indicator to show that someone is typing in the chat.

## Behavior

Typing indicators are best-effort signals that behave as follows:

- **iMessage chats only:** Typing indicators are only supported for iMessage chats.
  Requests for RCS or SMS chats are accepted (`204`) but no indicator is delivered.

- **Send a message first for reliable delivery:** Typing indicators are best-effort.
  If you have not sent a message in this chat recently (roughly the **last 5 minutes**),
  a typing indicator may not reach the recipient — the request is still accepted (`204`),
  but delivery is not deterministic. Once you have sent a message in the chat, typing
  indicators reliably reach the recipient.

- **No delivery guarantee:** Even for active chats, a `204` response only indicates
  the request was accepted for processing.

- **Group chats not supported:** Attempting to start a typing indicator in a group chat
  will return a `403` error.

## Duration & keeping it visible

- A single call shows the indicator for about **85–90 seconds**, then it clears
  automatically.

- To keep it visible longer, call this endpoint again every **60 seconds**. Each call
  refreshes the indicator so it stays visible continuously.

- Sending a message clears the indicator.

- To resume typing after sending a message, call this endpoint again.

- Incoming messages do not affect the indicator.

## Recipient re-opening the chat

If the recipient brings their messaging app to the foreground while the chat has an
unread message, their device clears any showing typing indicator. Calling this endpoint
again on its own may not bring it back. To make it reappear, either send a message, or
call `DELETE /v3/chats/{chatId}/typing` (stop) and then call start typing again.

## Recommended usage

Call this endpoint when composing begins, call it again every 60 seconds while
composing, and send the message to clear the indicator. To clear the indicator without
sending a message, call `DELETE /v3/chats/{chatId}/typing`.

### Path Parameters

- `chatId: string`

### Example

```http
curl https://api.linqapp.com/api/partner/v3/chats/$CHAT_ID/typing \
    -X POST \
    -H "Authorization: Bearer $LINQ_API_V3_API_KEY"
```

#### Response

```json
{
  "error": {
    "status": 400,
    "code": 1002,
    "message": "Phone number must be in E.164 format",
    "doc_url": "https://docs.linqapp.com/error/codes/1xxx/1002/"
  },
  "success": false
}
```

## Stop typing indicator

**delete** `/v3/chats/{chatId}/typing`

Immediately clears the typing indicator for the chat, without sending a message.

The typing indicator also clears automatically when you send a message, or about
85–90 seconds after the last `POST /v3/chats/{chatId}/typing` (start typing) request.

See the start typing endpoint (`POST /v3/chats/{chatId}/typing`) above for behavior
details.

**Note:** Group chats are not supported and will return a `403` error.

### Path Parameters

- `chatId: string`

### Example

```http
curl https://api.linqapp.com/api/partner/v3/chats/$CHAT_ID/typing \
    -X DELETE \
    -H "Authorization: Bearer $LINQ_API_V3_API_KEY"
```

#### Response

```json
{
  "error": {
    "status": 400,
    "code": 1002,
    "message": "Phone number must be in E.164 format",
    "doc_url": "https://docs.linqapp.com/error/codes/1xxx/1002/"
  },
  "success": false
}
```

# Messages

## Send a message to an existing chat

**post** `/v3/chats/{chatId}/messages`

Send a message to an existing chat. Use this endpoint when you already have
a chat ID and want to send additional messages to it.

## Message Effects

You can add iMessage effects to make your messages more expressive. Effects are
optional and can be either screen effects (full-screen animations) or bubble effects
(message bubble animations).

**Screen Effects:** `confetti`, `fireworks`, `lasers`, `sparkles`, `celebration`,
`hearts`, `love`, `balloons`, `happy_birthday`, `echo`, `spotlight`

**Bubble Effects:** `slam`, `loud`, `gentle`, `invisible`

Only one effect type can be applied per message.

## Inline Text Decorations (iMessage only)

Use the `text_decorations` array on a text part to apply styling and animations to character ranges.

Each decoration specifies a `range: [start, end)` and exactly one of `style` or `animation`.

**Styles:** `bold`, `italic`, `strikethrough`, `underline`
**Animations:** `big`, `small`, `shake`, `nod`, `explode`, `ripple`, `bloom`, `jitter`

```json
{
  "type": "text",
  "value": "Hello world",
  "text_decorations": [
    { "range": [0, 5], "style": "bold" },
    { "range": [6, 11], "animation": "shake" }
  ]
}
```

**Note:** Style ranges (bold, italic, etc.) may overlap, but animation ranges must not overlap with other animations or styles. Text decorations only render for iMessage recipients.
For SMS/RCS, text decorations are not applied.

### Path Parameters

- `chatId: string`

### Body Parameters

- `message: MessageContent`

  Message content container. Groups all message-related fields together,
  separating the "what" (message content) from the "where" (routing fields like from/to).

  A message carries EITHER `parts` — text and attachments, which compose
  into one bubble — or a single `action`, which invokes an experience
  inside Linq's iMessage app. Never both: an app card is the whole message
  (Apple's `MSMessage` cannot coexist with text), so copy and a card are
  two sends, not one.

  - `action: optional object { action, experience, params }`

    Invokes an action on an experience — a third party that renders inside
    Linq's iMessage app. Linq resolves the recipient's connection, mints any
    session the action needs, composes the card and sends it; none of that
    is visible to you.

    Call `GET /v3/experiences/{experience}` for the actions you may invoke
    and the fields each accepts.

    - `action: string`

      Which of its actions, e.g. `attach_card`.

    - `experience: string`

      The experience to invoke, e.g. `agentcard`.

    - `params: optional map[unknown]`

      Values for the fields this action exposes. Keys are exactly the
      field names listed for the action — no mapping, no nesting.

      Display copy only, except a `url`-type field — that value sets the
      destination, and must be an absolute `https` URL.

  - `effect: optional MessageEffect`

    iMessage effect to apply to this message (screen or bubble effect)

    - `name: optional string`

      Name of the effect. Common values:

      - Screen effects: confetti, fireworks, lasers, sparkles, celebration, hearts, love, balloons, happy_birthday, echo, spotlight
      - Bubble effects: slam, loud, gentle, invisible

    - `type: optional "screen" or "bubble"`

      Type of effect

      - `"screen"`

      - `"bubble"`

  - `idempotency_key: optional string`

    Optional idempotency key for this message.
    Use this to prevent duplicate sends of the same message. Reusing a key
    whose message was deleted — or was an ephemeral message that has since
    expired — returns 404; the message is never resent.

  - `parts: optional array of TextPart or MediaPart or LinkPart or object { app, layout, type, 3 more }`

    Array of message parts. Each part can be text, media, or link.
    Parts are displayed in order. Text and media can be mixed freely,
    but a `link` part must be the only part in the message.

    **Rich Link Previews:**

    - Use a `link` part to send a URL with a rich preview card
    - A `link` part must be the **only** part in the message
    - To send a URL as plain text (no preview), use a `text` part instead

    **Supported Media:**

    - Images: .jpg, .jpeg, .png, .gif, .heic, .heif, .tif, .tiff, .bmp
    - Videos: .mp4, .mov, .m4v, .mpeg, .mpg, .3gp
    - Audio: .m4a, .mp3, .aac, .caf, .wav, .aiff, .amr
    - Documents: .pdf, .txt, .rtf, .csv, .doc, .docx, .xls, .xlsx, .ppt, .pptx, .pages, .numbers, .key, .epub, .zip, .html, .htm
    - Contact & Calendar: .vcf, .ics

    **Audio:**

    - Audio files (.m4a, .mp3, .aac, .caf, .wav, .aiff, .amr) are fully supported as media parts
    - To send audio as an **iMessage voice memo bubble** (inline playback UI), use the dedicated
      `/v3/chats/{chatId}/voicememo` endpoint instead

    **Validation Rules:**

    - A `link` part must be the **only** part in the message. It cannot be combined
      with text or media parts.
    - Consecutive text parts are not allowed. Text parts must be separated by
      media parts. For example, [text, text] is invalid, but [text, media, text] is valid.
    - Maximum of **100 parts** total.
    - Media parts using a public `url` (downloaded by the server on send) are
      capped at **40**. Parts using `attachment_id` or presigned URLs
      are exempt from this sub-limit. For bulk media sends exceeding 40 files,
      pre-upload via `POST /v3/attachments` and reference by `attachment_id` or `download_url`.

    - `TextPart object { type, value, text_decorations }`

      - `type: "text"`

        Indicates this is a text message part

        - `"text"`

      - `value: string`

        The text content of the message. This value is sent as-is with no parsing or transformation — Markdown syntax will be delivered as plain text. Use `text_decorations` to apply inline formatting and animations (iMessage only).

      - `text_decorations: optional array of TextDecoration`

        Optional array of text decorations applied to character ranges in the `value` field (iMessage only).

        Each decoration specifies a character range `[start, end)` and exactly one of `style` or `animation`.

        **Styles:** `bold`, `italic`, `strikethrough`, `underline`
        **Animations:** `big`, `small`, `shake`, `nod`, `explode`, `ripple`, `bloom`, `jitter`

        Style ranges may overlap (e.g. bold + italic on the same text), but animation ranges must not overlap with other animations or styles.

        *Characters are measured as UTF-16 code units. Most characters count as 1; some emoji count as 2.*

        **Note:** Text decorations only render for iMessage recipients. For SMS/RCS, text decorations are not applied.

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

    - `MediaPart object { type, attachment_id, url }`

      - `type: "media"`

        Indicates this is a media attachment part

        - `"media"`

      - `attachment_id: optional string`

        Reference to a file pre-uploaded via `POST /v3/attachments` (optional).
        The file is already stored, so sends using this ID skip the download step —
        useful when sending the same file to many recipients.

        Either `url` or `attachment_id` must be provided, but not both.

      - `url: optional string`

        Any publicly accessible HTTPS URL to the media file. The server downloads and
        sends the file automatically — no pre-upload step required.

        **Size limit:** 10MB maximum for URL-based downloads. For larger files (up to 100MB),
        use the pre-upload flow: `POST /v3/attachments` to get a presigned URL, upload directly,
        then reference by `attachment_id`.

        **Requirements:**

        - URL must use HTTPS
        - File content must be a supported format (the server validates the actual file content)

        **Supported formats:**

        - Images: .jpg, .jpeg, .png, .gif, .heic, .heif, .tif, .tiff, .bmp
        - Videos: .mp4, .mov, .m4v, .mpeg, .mpg, .3gp
        - Audio: .m4a, .mp3, .aac, .caf, .wav, .aiff, .amr
        - Documents: .pdf, .txt, .rtf, .csv, .doc, .docx, .xls, .xlsx, .ppt, .pptx, .pages, .numbers, .key, .epub, .zip, .html, .htm
        - Contact & Calendar: .vcf, .ics

        **Tip:** Audio sent here appears as a regular file attachment. To send audio as an
        iMessage voice memo bubble (with inline playback), use `/v3/chats/{chatId}/voicememo`.
        For repeated sends of the same file, use `attachment_id` to avoid redundant downloads.

        Either `url` or `attachment_id` must be provided, but not both.

    - `LinkPart object { type, value }`

      - `type: "link"`

        Indicates this is a rich link preview part

        - `"link"`

      - `value: string`

        URL to send with a rich link preview. The recipient will see an inline card
        with the page's title, description, and preview image (when available).

        A `link` part must be the **only** part in the message. To send a URL as plain
        text (no preview card), use a `text` part instead.

    - `IMessageApp object { app, layout, type, 3 more }`

      An iMessage app card, backed by a Messages app extension. iMessage only —
      an `imessage_app` part must be the **only** part in the message and is never delivered over
      SMS/RCS. See the IMessageAppServiceUnsupported (2018) and RecipientUnsupportedMessageType
      (4005) error codes.

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

      - `type: "imessage_app"`

        Indicates this is an iMessage app card part.

        - `"imessage_app"`

      - `fallback_text: optional string`

        Text shown on surfaces that cannot render the card (notifications, lock screen). Defaults
        to the caption when omitted.

      - `interactive: optional boolean`

        Whether the card renders as your app's interactive balloon for recipients who have your
        iMessage app installed. `true` (default) lets your installed extension draw its live,
        interactive view for those recipients; everyone else sees the static card built from
        `layout`. `false` always shows the static `layout` card, even to recipients who have the
        app installed. Recipients without your app always see the static card regardless of this
        flag.

      - `url: optional string`

        URL the recipient's app opens when they tap the card. Either an absolute `https://` URL
        (capped at 2048 characters) or a `data:` URL carrying inline app state, e.g. a game's
        encoded state (capped at 16384 characters).

  - `preferred_service: optional ServiceType`

    Messaging service type

    - `"iMessage"`

    - `"SMS"`

    - `"RCS"`

  - `reply_to: optional ReplyTo`

    Reply to another message to create a threaded conversation

    - `message_id: string`

      The ID of the message to reply to

    - `part_index: optional number`

      The specific message part to reply to (0-based index).
      Defaults to 0 (first part) if not provided.
      Use this when replying to a specific part of a multipart message.

### Returns

- `chat_id: string`

  Unique identifier of the chat this message was sent to

- `message: SentMessage`

  A message that was sent (used in CreateChat and SendMessage responses)

  - `id: string`

    Message identifier (UUID)

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

  - `is_read: boolean`

    DEPRECATED: Use `delivery_status == "read"` instead. Whether the message has been read.

  - `parts: array of TextPartResponse or MediaPartResponse or LinkPartResponse or object { app, layout, reactions, 3 more }`

    Message parts in order (text, media, and link)

    - `TextPartResponse object { reactions, type, value, text_decorations }`

      A text message part

      - `reactions: array of Reaction`

        Reactions on this message part

        - `handle: ChatHandle`

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

  - `sent_at: string`

    When the message was actually sent (null if still queued)

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

  - `from_handle: optional ChatHandle`

    The sender of this message as a full handle object

  - `preferred_service: optional ServiceType`

    Messaging service type

  - `reply_to: optional ReplyTo`

    Indicates this message is a threaded reply to another message

    - `message_id: string`

      The ID of the message to reply to

    - `part_index: optional number`

      The specific message part to reply to (0-based index).
      Defaults to 0 (first part) if not provided.
      Use this when replying to a specific part of a multipart message.

  - `service: optional ServiceType`

    Messaging service type

### Example

```http
curl https://api.linqapp.com/api/partner/v3/chats/$CHAT_ID/messages \
    -H 'Content-Type: application/json' \
    -H "Authorization: Bearer $LINQ_API_V3_API_KEY" \
    -d '{
          "message": {
            "parts": [
              {
                "type": "text",
                "value": "Hello, world!"
              }
            ]
          }
        }'
```

#### Response

```json
{
  "chat_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": {
    "id": "69a37c7d-af4f-4b5e-af42-e28e98ce873a",
    "created_at": "2025-10-23T13:07:55.019-05:00",
    "delivery_status": "pending",
    "is_read": false,
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
    "sent_at": null,
    "delivered_at": null,
    "effect": {
      "name": "confetti",
      "type": "screen"
    },
    "from_handle": {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "handle": "+15551234567",
      "joined_at": "2025-05-21T15:30:00.000-05:00",
      "service": "iMessage",
      "is_me": false,
      "left_at": "2019-12-27T18:11:19.117Z",
      "status": "active"
    },
    "preferred_service": "iMessage",
    "reply_to": {
      "message_id": "550e8400-e29b-41d4-a716-446655440000",
      "part_index": 0
    },
    "service": "iMessage"
  }
}
```

## Get messages from a chat

**get** `/v3/chats/{chatId}/messages`

Retrieve messages from a specific chat with pagination support.

### Path Parameters

- `chatId: string`

### Query Parameters

- `cursor: optional string`

  Pagination cursor from previous next_cursor response

- `limit: optional number`

  Maximum number of messages to return

### Returns

- `messages: array of Message`

  List of messages

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

- `next_cursor: optional string`

  Cursor for fetching the next page of results.
  Null if there are no more results to fetch.
  Pass this value as the `cursor` parameter in the next request.

### Example

```http
curl https://api.linqapp.com/api/partner/v3/chats/$CHAT_ID/messages \
    -H "Authorization: Bearer $LINQ_API_V3_API_KEY"
```

#### Response

```json
{
  "messages": [
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
  ],
  "next_cursor": "next_cursor"
}
```

## Domain Types

### Sent Message

- `SentMessage object { id, created_at, delivery_status, 9 more }`

  A message that was sent (used in CreateChat and SendMessage responses)

  - `id: string`

    Message identifier (UUID)

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

  - `is_read: boolean`

    DEPRECATED: Use `delivery_status == "read"` instead. Whether the message has been read.

  - `parts: array of TextPartResponse or MediaPartResponse or LinkPartResponse or object { app, layout, reactions, 3 more }`

    Message parts in order (text, media, and link)

    - `TextPartResponse object { reactions, type, value, text_decorations }`

      A text message part

      - `reactions: array of Reaction`

        Reactions on this message part

        - `handle: ChatHandle`

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

  - `sent_at: string`

    When the message was actually sent (null if still queued)

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

  - `from_handle: optional ChatHandle`

    The sender of this message as a full handle object

  - `preferred_service: optional ServiceType`

    Messaging service type

  - `reply_to: optional ReplyTo`

    Indicates this message is a threaded reply to another message

    - `message_id: string`

      The ID of the message to reply to

    - `part_index: optional number`

      The specific message part to reply to (0-based index).
      Defaults to 0 (first part) if not provided.
      Use this when replying to a specific part of a multipart message.

  - `service: optional ServiceType`

    Messaging service type

### Message Send Response

- `MessageSendResponse object { chat_id, message }`

  Response for sending a message to a chat

  - `chat_id: string`

    Unique identifier of the chat this message was sent to

  - `message: SentMessage`

    A message that was sent (used in CreateChat and SendMessage responses)

    - `id: string`

      Message identifier (UUID)

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

    - `is_read: boolean`

      DEPRECATED: Use `delivery_status == "read"` instead. Whether the message has been read.

    - `parts: array of TextPartResponse or MediaPartResponse or LinkPartResponse or object { app, layout, reactions, 3 more }`

      Message parts in order (text, media, and link)

      - `TextPartResponse object { reactions, type, value, text_decorations }`

        A text message part

        - `reactions: array of Reaction`

          Reactions on this message part

          - `handle: ChatHandle`

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

    - `sent_at: string`

      When the message was actually sent (null if still queued)

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

    - `from_handle: optional ChatHandle`

      The sender of this message as a full handle object

    - `preferred_service: optional ServiceType`

      Messaging service type

    - `reply_to: optional ReplyTo`

      Indicates this message is a threaded reply to another message

      - `message_id: string`

        The ID of the message to reply to

      - `part_index: optional number`

        The specific message part to reply to (0-based index).
        Defaults to 0 (first part) if not provided.
        Use this when replying to a specific part of a multipart message.

    - `service: optional ServiceType`

      Messaging service type

# Location

## Request location sharing

**post** `/v3/chats/{chatId}/location/request`

Request a contact in a chat to share their location. They receive an iMessage
prompt and must accept before any location is available; once they do, read their
location coordinates with `GET /v3/chats/{chatId}/location`.

The request is delivered asynchronously. The endpoint returns immediately with
`{ "success": true, "message": "Location request sent" }` and does not return
coordinates.

Location requests only work in **1:1 iMessage chats** (Apple limitation):

- Group chats (any service) return `409` with code `2016`
  (`GroupChatNotSupported`).
- 1:1 SMS and RCS chats return `409` with code `2017`
  (`ChatServiceNotSupported`).

### Path Parameters

- `chatId: string`

### Returns

- `LocationRequestResponse object { message, success }`

  - `message: string`

  - `success: boolean`

### Example

```http
curl https://api.linqapp.com/api/partner/v3/chats/$CHAT_ID/location/request \
    -X POST \
    -H "Authorization: Bearer $LINQ_API_V3_API_KEY"
```

#### Response

```json
{
  "success": true,
  "message": "Location request sent"
}
```

## Get location data

**get** `/v3/chats/{chatId}/location`

Retrieve the current location for contacts sharing with you in a chat.

The response is wrapped in the standard `{ "success": true, "data": ... }` envelope —
the body is **not** a bare GeoJSON document. `data` is a
[GeoJSON](https://datatracker.ietf.org/doc/html/rfc7946) `FeatureCollection` with a
`Feature` for each participant actively sharing their location.

Works for both 1:1 and group chats. In group chats, `data.features` contains a separate
feature for each participant who is sharing. Each feature's `properties.handle` identifies the user.

Returns an empty `data.features` array if no one is sharing or no location data is
available yet. If sharing started but this stays empty, see the **Location Sharing**
overview.

Poll this endpoint to track a moving contact. `properties.updated_at`
reflects when each participant's location was last updated. There is no
coordinate-update webhook. See the **Location Sharing** overview for polling
guidance.

### Path Parameters

- `chatId: string`

### Returns

- `GetChatLocationResponse object { data, success }`

  - `data: object { features, type }`

    - `features: array of object { geometry, properties, type }`

      - `geometry: object { coordinates, type }`

        - `coordinates: array of number`

          [longitude, latitude] or [longitude, latitude, altitude]

        - `type: "Point"`

          - `"Point"`

      - `properties: object { handle, address, locality, updated_at }`

        - `handle: string`

          Phone number or email of the person sharing their location

        - `address: optional string`

          Full street address

        - `locality: optional string`

          City or locality name

        - `updated_at: optional string`

          When the location was last updated

      - `type: "Feature"`

        - `"Feature"`

    - `type: "FeatureCollection"`

      - `"FeatureCollection"`

  - `success: boolean`

### Example

```http
curl https://api.linqapp.com/api/partner/v3/chats/$CHAT_ID/location \
    -H "Authorization: Bearer $LINQ_API_V3_API_KEY"
```

#### Response

```json
{
  "error": {
    "status": 400,
    "code": 1002,
    "message": "Phone number must be in E.164 format",
    "doc_url": "https://docs.linqapp.com/error/codes/1xxx/1002/"
  },
  "success": false
}
```

## Domain Types

### Get Chat Location Response

- `GetChatLocationResponse object { data, success }`

  - `data: object { features, type }`

    - `features: array of object { geometry, properties, type }`

      - `geometry: object { coordinates, type }`

        - `coordinates: array of number`

          [longitude, latitude] or [longitude, latitude, altitude]

        - `type: "Point"`

          - `"Point"`

      - `properties: object { handle, address, locality, updated_at }`

        - `handle: string`

          Phone number or email of the person sharing their location

        - `address: optional string`

          Full street address

        - `locality: optional string`

          City or locality name

        - `updated_at: optional string`

          When the location was last updated

      - `type: "Feature"`

        - `"Feature"`

    - `type: "FeatureCollection"`

      - `"FeatureCollection"`

  - `success: boolean`

### Location Request Response

- `LocationRequestResponse object { message, success }`

  - `message: string`

  - `success: boolean`
