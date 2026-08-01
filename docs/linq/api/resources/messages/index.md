# Messages

## Send a message (auto-selected from-number)

**post** `/v3/messages`

Send a message to one or more recipients **without supplying a `from`
number**. Linq resolves both the sending line and the target chat for you,
then returns exactly which line was used, which chat the message landed in,
whether a new chat was created, and every resulting message id.

This fuses "create chat" and "send message" behind a single
message-centric resource. Provide only the recipients (`to`) and the
`message`; the platform decides the rest.

## How the from-number and chat are chosen

- **Reuse** — if a chat with exactly these recipients already exists on a
  line that can still send, the message is sent into that chat on its
  existing line (`from_selection.reason = reused_active_chat`). The
  most-recently-active such chat wins; chats stranded on flagged lines
  (e.g. by an earlier failover) are skipped.
- **New** — if no such chat exists, a new chat is created on the best
  available line (`from_selection.reason = new_best_number`).
- **Failover** — if matching chats exist but none is on a line that can
  send, a **new** chat is created on a fresh best line and the flagged chat
  is abandoned (`from_selection.reason = failover_flagged`,
  `previous_chat_id` set). If you supply `continuation_message`, that
  text is sent as the single message INSTEAD of `message` (useful as a
  fresh-number-appropriate opener). Exactly one message is sent either way.

Recipients (`to`) are an order-independent set: a single handle is a direct
chat, multiple handles a group chat.

## Excluding lines

`exclude_from` keeps specific lines out of **this** send's line pick. It
only affects picking a line for a new chat — an existing chat is always
reused on its own line, preferring a chat on a non-excluded line when the
recipients have more than one. An exclusion never abandons a live chat or
moves it to a new number, so if the only chat these recipients have is on
an excluded line, that chat is still used. `from` tells you the line that
was actually used.

## Differences from POST /v3/chats

- The first message **may contain a link** (including for a newly created
  chat). Note: sending a link as the very first message on a freshly
  selected line can elevate that line's flagging risk — it is allowed, not
  recommended.
- Voice memos are **not** supported here. To send an iMessage voice-memo
  bubble, use `POST /v3/chats/{chatId}/voicememo` with a known chat id.

## Service preference, effects, decorations

Set `message.preferred_service` (`iMessage` | `RCS` | `SMS`), `message.effect`,
and per-part `text_decorations` exactly as on the other send endpoints.

Always responds `202 Accepted` — chat creation is incidental to the send.

### Header Parameters

- `"Idempotency-Key": optional string`

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

- `to: array of string`

  Recipient handles (E.164 phone numbers or email addresses). One handle
  is a direct chat; multiple handles a group chat. Order-independent — the
  set identifies the chat.

- `continuation_message: optional object { text }`

  Text-only fallback that **replaces** `message` ONLY on the failover branch —
  when a chat with these recipients already existed but its line was flagged,
  so a new chat is created on a fresh line. On that branch this text is sent as
  the single message instead of `message` (the recipient is on a new number, so
  you typically want a fresh-number-appropriate opener rather than the original
  content). Ignored otherwise (a healthy reuse, or genuine first contact).
  Carries no parts, media, or effects — exactly one message is ever sent.

  - `text: string`

    The replacement message text, sent as the single message on failover.

- `exclude_from: optional array of string`

  Lines (E.164) not to pick for this send. Applies for this request
  only — nothing is remembered between calls.

  **Exclusion only affects picking a line for a new chat.** If `to`
  already has a chat, that chat is reused on its own line, and a chat on
  a non-excluded line is preferred when there is more than one. If the
  only chat these recipients have is on an excluded line, it is still
  reused — an exclusion never abandons a live chat or moves it to a new
  number. Check `from` in the response to see the line that was actually
  used.

  Numbers that are not your lines are ignored. Every entry must be
  E.164 — a value like `4155551234` is rejected rather than silently
  skipped. Excluding every one of your available lines returns 400 when
  a line has to be picked.

### Returns

- `chat_id: string`

  The resolved chat (reused or newly created) the message landed in.

- `created_new_chat: boolean`

  True when a new chat was created (new or failover), false on reuse.

- `from: string`

  The line (E.164) the message was actually sent from.

- `from_selection: object { reason, reused_existing_chat }`

  Why this line/chat was chosen.

  - `reason: "reused_active_chat" or "new_best_number" or "failover_flagged"`

    - `reused_active_chat` — reused an existing chat on its healthy line
    - `new_best_number` — created a new chat on the best available line
    - `failover_flagged` — no existing chat for these recipients was on
      a line that could send; created a new chat on a fresh line

    - `"reused_active_chat"`

    - `"new_best_number"`

    - `"failover_flagged"`

  - `reused_existing_chat: boolean`

    True only when an existing chat was reused.

- `handles: array of ChatHandle`

  Participants of the resolved chat.

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

- `is_group: boolean`

  Whether the resolved chat is a group chat.

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

- `previous_chat_id: optional string`

  Set ONLY on `failover_flagged`: the abandoned flagged chat that was NOT
  sent into. Null otherwise.

### Example

```http
curl https://api.linqapp.com/api/partner/v3/messages \
    -H 'Content-Type: application/json' \
    -H "Authorization: Bearer $LINQ_API_V3_API_KEY" \
    -d '{
          "message": {
            "parts": [
              {
                "type": "text",
                "value": "Hi! Thanks for reaching out — how can we help?"
              }
            ]
          },
          "to": [
            "+14155559876"
          ],
          "exclude_from": [
            "+12052535597"
          ]
        }'
```

#### Response

```json
{
  "chat_id": "94c6bf33-31d9-40e3-a0e9-f94250ecedb9",
  "created_new_chat": false,
  "from": "+12052535597",
  "from_selection": {
    "reason": "reused_active_chat",
    "reused_existing_chat": true
  },
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
  "service": "iMessage",
  "previous_chat_id": null
}
```

## Get all messages in a thread

**get** `/v3/messages/{messageId}/thread`

Retrieve all messages in a conversation thread. Given any message ID in the thread,
returns the originator message and all replies in chronological order.

If the message is not part of a thread, returns just that single message.

Supports pagination and configurable ordering.

### Path Parameters

- `messageId: string`

### Query Parameters

- `cursor: optional string`

  Pagination cursor from previous next_cursor response

- `limit: optional number`

  Maximum number of messages to return

- `order: optional "asc" or "desc"`

  Sort order for messages (asc = oldest first, desc = newest first)

  - `"asc"`

  - `"desc"`

### Returns

- `messages: array of Message`

  Messages in the thread, ordered by the specified order parameter

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

  Cursor for fetching the next page of results (null if no more results)

### Example

```http
curl https://api.linqapp.com/api/partner/v3/messages/$MESSAGE_ID/thread \
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
  "next_cursor": "eyJpZCI6IjEyMzQ1Njc4OTAiLCJ0cyI6MTYzMDUwMDAwMH0="
}
```

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

## Delete a message from system

**delete** `/v3/messages/{messageId}`

Deletes a message from the Linq API only. This does NOT unsend or remove the message
from the actual chat — recipients will still see the message.
Re-sending with a deleted message's idempotency key returns 404 — a deleted message is never resent.

### Path Parameters

- `messageId: string`

### Example

```http
curl https://api.linqapp.com/api/partner/v3/messages/$MESSAGE_ID \
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

## Add or remove a reaction to a message

**post** `/v3/messages/{messageId}/reactions`

Add or remove emoji reactions to messages. Reactions let users express
their response to a message without sending a new message.

**Supported Reactions:**

- love ❤️
- like 👍
- dislike 👎
- laugh 😂
- emphasize ‼️
- question ❓
- custom - any emoji (use `custom_emoji` field to specify)

### Path Parameters

- `messageId: string`

### Body Parameters

- `operation: "add" or "remove"`

  Whether to add or remove the reaction

  - `"add"`

  - `"remove"`

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

  Custom emoji string. Required when type is "custom".

- `part_index: optional number`

  Optional index of the message part to react to.
  If not provided, reacts to the entire message (part 0).

### Returns

- `message: optional string`

- `status: optional string`

- `trace_id: optional string`

### Example

```http
curl https://api.linqapp.com/api/partner/v3/messages/$MESSAGE_ID/reactions \
    -H 'Content-Type: application/json' \
    -H "Authorization: Bearer $LINQ_API_V3_API_KEY" \
    -d '{
          "operation": "add",
          "type": "love",
          "part_index": 1
        }'
```

#### Response

```json
{
  "message": "Reaction processed",
  "status": "accepted",
  "trace_id": "trace_id"
}
```

## Edit the content of a message part

**patch** `/v3/messages/{messageId}`

Edit the text content of a specific part of a previously sent message.

**Note:** A message can be edited up to 5 times, and only within 15 minutes of when it was originally sent.

### Path Parameters

- `messageId: string`

### Body Parameters

- `text: string`

  New text content for the message part

- `part_index: optional number`

  Index of the message part to edit. Defaults to 0.

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
    -X PATCH \
    -H 'Content-Type: application/json' \
    -H "Authorization: Bearer $LINQ_API_V3_API_KEY" \
    -d '{
          "text": "This is the edited message content"
        }'
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

## Update an iMessage app card in place

**post** `/v3/messages/{messageId}/update`

Replaces a previously delivered `imessage_app` card on the recipient's screen with new
content, instead of posting a new bubble (like a game move redrawing the board).

The update is delivered as a **new message** with its own id and delivery lifecycle
(`message.sent` / `message.delivered` / `message.failed` webhooks fire for the new id).
To update the card again, reference the message id returned by this call.

Constraints:

- The referenced message must be an `imessage_app` card sent by you (`400` otherwise —
  inbound cards cannot be updated).
- The referenced card must already be delivered (`409` otherwise — retry after the
  `message.delivered` webhook for it).
- The app identity (`team_id`, `bundle_id`, name) is inherited from the original card and
  cannot change; only `url`, `fallback_text`, and `layout` are replaced.
- iMessage-only, like all app cards.
- Concurrent updates against the same card are not serialized server-side; the last one
  delivered wins on the recipient's screen. Serialize updates by always referencing the
  message id returned by the previous call.

### Path Parameters

- `messageId: string`

### Body Parameters

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

- `fallback_text: optional string`

  Text shown on surfaces that cannot render the card (notifications, lock screen). Defaults
  to the caption when omitted.

- `interactive: optional boolean`

  Whether the updated card renders as your app's interactive balloon for recipients who
  have your iMessage app installed. `true` (default) lets your installed extension draw its
  live view; `false` always shows the static `layout` card. Recipients without your app
  always see the static card regardless of this flag.

  Defaults to `true` when omitted — it is **not** inherited from the original card. To keep a
  card static across updates, re-send `interactive: false` on each update.

- `url: optional string`

  URL the recipient's app opens when they tap the updated card.

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
curl https://api.linqapp.com/api/partner/v3/messages/$MESSAGE_ID/update \
    -H 'Content-Type: application/json' \
    -H "Authorization: Bearer $LINQ_API_V3_API_KEY" \
    -d '{
          "layout": {
            "caption": "Score: 2 – 1"
          },
          "fallback_text": "Score update",
          "interactive": true,
          "url": "https://app.example.com/card?game=7f3a&move=2"
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

## Domain Types

### Message

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

### Message Effect

- `MessageEffect object { name, type }`

  iMessage effect applied to a message (screen or bubble effect)

  - `name: optional string`

    Name of the effect. Common values:

    - Screen effects: confetti, fireworks, lasers, sparkles, celebration, hearts, love, balloons, happy_birthday, echo, spotlight
    - Bubble effects: slam, loud, gentle, invisible

  - `type: optional "screen" or "bubble"`

    Type of effect

    - `"screen"`

    - `"bubble"`

### Reply To

- `ReplyTo object { message_id, part_index }`

  Indicates this message is a threaded reply to another message

  - `message_id: string`

    The ID of the message to reply to

  - `part_index: optional number`

    The specific message part to reply to (0-based index).
    Defaults to 0 (first part) if not provided.
    Use this when replying to a specific part of a multipart message.

### Message Create Response

- `MessageCreateResponse object { chat_id, created_new_chat, from, 6 more }`

  Result of an auto-from send. Self-describing: which line was used, which
  chat the message landed in, whether a new chat was created, and the
  resulting message id(s).

  - `chat_id: string`

    The resolved chat (reused or newly created) the message landed in.

  - `created_new_chat: boolean`

    True when a new chat was created (new or failover), false on reuse.

  - `from: string`

    The line (E.164) the message was actually sent from.

  - `from_selection: object { reason, reused_existing_chat }`

    Why this line/chat was chosen.

    - `reason: "reused_active_chat" or "new_best_number" or "failover_flagged"`

      - `reused_active_chat` — reused an existing chat on its healthy line
      - `new_best_number` — created a new chat on the best available line
      - `failover_flagged` — no existing chat for these recipients was on
        a line that could send; created a new chat on a fresh line

      - `"reused_active_chat"`

      - `"new_best_number"`

      - `"failover_flagged"`

    - `reused_existing_chat: boolean`

      True only when an existing chat was reused.

  - `handles: array of ChatHandle`

    Participants of the resolved chat.

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

  - `is_group: boolean`

    Whether the resolved chat is a group chat.

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

  - `previous_chat_id: optional string`

    Set ONLY on `failover_flagged`: the abandoned flagged chat that was NOT
    sent into. Null otherwise.

### Message Add Reaction Response

- `MessageAddReactionResponse object { message, status, trace_id }`

  - `message: optional string`

  - `status: optional string`

  - `trace_id: optional string`

### Message Update App Card Response

- `MessageUpdateAppCardResponse object { chat_id, message }`

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
