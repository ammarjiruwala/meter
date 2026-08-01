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
