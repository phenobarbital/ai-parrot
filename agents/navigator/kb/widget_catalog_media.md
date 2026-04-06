# Widget Catalog - Batch 2: Media and Specialized Widgets

> AI Agent reference for programmatically creating Navigator widgets.
> Each entry maps a `widget_type_id` to its DB row, Svelte component directory, expected `params`, `format_definition`, and a minimal working JSON.

---

## Architecture Quick Reference

| Concept | Detail |
|---------|--------|
| **DB table** | `navigator.widget_types` (`widget_type`, `description`, `classbase`, `enabled`) |
| **widget_type_id** | Stored on each widget row; prefix determines base loader: `api-*` -> `Api.svelte`, `rest-*` -> `Rest.svelte`, `media-*` / other -> `Media.svelte` |
| **classbase** | The directory name under `src/lib/components/widgets/type/` that contains `<Name>.svelte` |
| **Component resolution** | `ComponentType.svelte` imports `./type/${classbase}/${classbase}.svelte` dynamically |
| **Data flow** | `Api` base fetches from `query_slug.slug`; `Media` base passes widget data directly; `Rest` base calls a raw URL |
| **Common params.settings** | `{ settings: { toolbar: { reload, filtering, export, clone }, header: { show, title, icon, toolbar }, general: { fixed, scrollable }, appearance: { border } } }` |

---

## 1. ListOfLinks

| Field | Value |
|-------|-------|
| **widget_type_id** | `media-list-of-links` |
| **DB classbase** | `ListOfLinks` |
| **Base loader** | Media |
| **Data source** | Static (`format_definition`) -- no API call needed |

**What it does**: Renders a numbered list of clickable external links with an optional body message above.

**format_definition**:
```json
{
  "links": [
    { "title": "Google", "href": "https://google.com" },
    { "title": "Troc Global", "href": "https://trocglobal.com" }
  ]
}
```

**params**:
```json
{
  "body_message": "Check out these resources:",
  "settings": {
    "header": { "show": true, "title": true },
    "general": { "scrollable": true }
  }
}
```

**Minimal working example**:
```json
{
  "widget_type_id": "media-list-of-links",
  "format_definition": {
    "links": [
      { "title": "Example", "href": "https://example.com" }
    ]
  },
  "params": { "settings": { "toolbar": {} } }
}
```

---

## 2. ListOfDocuments

| Field | Value |
|-------|-------|
| **widget_type_id** | `media-list-of-documents` |
| **DB classbase** | `ListOfDocuments` |
| **Base loader** | Media |
| **Data source** | Static (`format_definition`) |

**What it does**: Renders a list of downloadable files. Each entry can be an external URL or an uploaded file (base64 data).

**format_definition**:
```json
{
  "files": [
    {
      "name": "Q1 Report",
      "external": true,
      "link": "https://example.com/report.pdf"
    },
    {
      "name": "Internal Doc",
      "external": false,
      "file": [{ "data": "https://cdn.example.com/file.pdf", "filename": "internal.pdf" }]
    }
  ]
}
```

**params**:
```json
{
  "body_message": "Download the documents below:",
  "settings": { "toolbar": {} }
}
```

**Minimal working example**:
```json
{
  "widget_type_id": "media-list-of-documents",
  "format_definition": {
    "files": [
      { "name": "Report", "external": true, "link": "https://example.com/report.pdf" }
    ]
  },
  "params": { "settings": { "toolbar": {} } }
}
```

---

## 3. ListOrCard

| Field | Value |
|-------|-------|
| **widget_type_id** | `media-list-cards` |
| **DB classbase** | `ListOrCard` |
| **Base loader** | Media |
| **Data source** | Static (`format_definition`) |

**What it does**: Renders content items in either a vertical list or a grid of cards. Supports cover images, links, HTML body, and custom background colors per card.

**format_definition**:
```json
{
  "items": [
    {
      "title": "Welcome",
      "link": "https://example.com",
      "cover": "https://example.com/cover.jpg",
      "backgroundCard": "#f0f0f0",
      "body": "<p>HTML content here</p>"
    }
  ]
}
```

**params**:
```json
{
  "layout": {
    "style": "Cards",
    "columns": 3
  },
  "settings": { "toolbar": {} }
}
```
- `layout.style`: `"List"` or `"Cards"` (default: `"List"`)
- `layout.columns`: `3`, `4`, or `6` (only for Cards mode)

**Minimal working example**:
```json
{
  "widget_type_id": "media-list-cards",
  "format_definition": {
    "items": [
      { "title": "Item 1", "body": "Description text" }
    ]
  },
  "params": { "layout": { "style": "List" }, "settings": { "toolbar": {} } }
}
```

---

## 4. ApiListOrCards

| Field | Value |
|-------|-------|
| **widget_type_id** | `api-list-cards` |
| **DB classbase** | `ApiListOrCards` |
| **Base loader** | Api |
| **Data source** | API (`query_slug.slug`) |

**What it does**: Same visual as ListOrCard but fetches data from an API endpoint. Includes search, origin filters, product details with pricing. Used for product catalog scenarios.

**format_definition**:
```json
{
  "items_def": {
    "title": { "label": "Product", "field": "name" },
    "body": { "label": "Model", "field": "model" }
  }
}
```

**params**:
```json
{
  "layout": { "style": "List", "columns": 3 },
  "showTitle": {
    "param": "store_id",
    "slug": "store_details",
    "field": "store_name",
    "label": "Store:"
  },
  "settings": { "toolbar": {} }
}
```

**query_slug**:
```json
{ "slug": "products_by_store" }
```

**Minimal working example**:
```json
{
  "widget_type_id": "api-list-cards",
  "query_slug": { "slug": "my_products_slug" },
  "format_definition": {
    "items_def": {
      "title": { "label": "", "field": "name" },
      "body": { "label": "", "field": "description" }
    }
  },
  "params": { "layout": { "style": "List" }, "settings": { "toolbar": {} } }
}
```

---

## 5. Carousel

| Field | Value |
|-------|-------|
| **widget_type_id** | `media-carousel` |
| **DB classbase** | `Carousel` |
| **Base loader** | Media |
| **Data source** | Static (`format_definition`) |

**What it does**: Image carousel with navigation arrows and dot indicators. Supports both external URLs and uploaded images.

**format_definition**:
```json
{
  "images": [
    { "external": true, "link": "https://example.com/img1.jpg", "position": 1 },
    { "external": false, "image": { "data": "https://cdn.example.com/img2.jpg" }, "position": 2 }
  ]
}
```

**params**:
```json
{
  "settings": { "toolbar": {} }
}
```

**Minimal working example**:
```json
{
  "widget_type_id": "media-carousel",
  "format_definition": {
    "images": [
      { "external": true, "link": "https://picsum.photos/800/400", "position": 1 }
    ]
  },
  "params": { "settings": { "toolbar": {} } }
}
```

---

## 6. YouTube

| Field | Value |
|-------|-------|
| **widget_type_id** | `media-youtube` (or legacy `youtube`) |
| **DB classbase** | `YouTube` |
| **Base loader** | Media |
| **Data source** | `widget.url` (YouTube URL) |

**What it does**: Embeds a YouTube video. Extracts the video ID from the URL using regex.

**Key field**: `url` -- the YouTube video URL.

**Minimal working example**:
```json
{
  "widget_type_id": "media-youtube",
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "params": { "settings": { "toolbar": {} } }
}
```

---

## 7. Vimeo

| Field | Value |
|-------|-------|
| **widget_type_id** | `vimeo` |
| **DB classbase** | `Vimeo` (via `VimeoWidget` classbase) |
| **Base loader** | Media |
| **Data source** | `widget.url` |

**Minimal working example**:
```json
{
  "widget_type_id": "vimeo",
  "url": "https://vimeo.com/123456789",
  "params": { "settings": { "toolbar": {} } }
}
```

---

## 8. SoundCloud

| Field | Value |
|-------|-------|
| **widget_type_id** | `soundcloud` (currently commented out in UI but component exists) |
| **DB classbase** | `SoundCloud` |
| **Base loader** | Media |
| **Data source** | `widget.url` |

**Minimal working example**:
```json
{
  "widget_type_id": "soundcloud",
  "url": "https://soundcloud.com/artist/track-name",
  "params": { "settings": { "toolbar": {} } }
}
```

---

## 9. Spotify

| Field | Value |
|-------|-------|
| **widget_type_id** | `spotify` |
| **DB classbase** | `Spotify` (via `SpotifyWidget` classbase) |
| **Base loader** | Media |
| **Data source** | `widget.url` (Spotify open URL) |

**What it does**: Embeds a Spotify player. Parses the URL to extract track/album/playlist/artist type and ID.

**Minimal working example**:
```json
{
  "widget_type_id": "spotify",
  "url": "https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC",
  "params": { "settings": { "toolbar": {} } }
}
```

---

## 10. Image

| Field | Value |
|-------|-------|
| **widget_type_id** | `image` |
| **DB classbase** | `Image` (via `ImageWidget` classbase) |
| **Base loader** | Media |
| **Data source** | `format_definition` or `widget.url` |

**What it does**: Displays a single image. Can be external URL or uploaded file.

**format_definition**:
```json
{
  "external": true,
  "link": "https://example.com/image.jpg",
  "image": []
}
```
Or for uploaded:
```json
{
  "external": false,
  "link": "",
  "image": [{ "data": "https://cdn.example.com/uploaded.jpg" }]
}
```

**Minimal working example**:
```json
{
  "widget_type_id": "image",
  "url": "https://picsum.photos/800/400",
  "format_definition": { "external": true, "link": "https://picsum.photos/800/400" },
  "params": { "settings": { "toolbar": {} } }
}
```

---

## 11. Download

| Field | Value |
|-------|-------|
| **widget_type_id** | `download-widget` |
| **DB classbase** | `DownloadWidget` -> resolves to `Download` |
| **Base loader** | Media |
| **Data source** | Static (`format_definition`) |

**What it does**: Displays a file preview with a download button and optional description. Layout can be horizontal or vertical.

**format_definition**:
```json
{
  "layout": ["Horizontal"],
  "file": [{ "data": "https://cdn.example.com/report.pdf", "filename": "report.pdf", "size": 1024, "type": "application/pdf" }],
  "description": "<p>Click to download the Q1 report</p>"
}
```

**Minimal working example**:
```json
{
  "widget_type_id": "download-widget",
  "format_definition": {
    "file": [{ "data": "https://example.com/file.pdf", "filename": "file.pdf" }],
    "description": "Download this file"
  },
  "params": { "settings": { "toolbar": {} } }
}
```

---

## 12. Dropzone

| Field | Value |
|-------|-------|
| **widget_type_id** | `dropzone` |
| **DB classbase** | `Dropzone` |
| **Base loader** | Media |
| **Data source** | User upload |

**What it does**: File upload widget. User drags/drops or selects a file, which is uploaded via `formData` POST to the configured endpoint.

**params**:
```json
{
  "dropzoneOptions": {
    "url": "/api/v1/uploads/process",
    "method": "POST"
  },
  "settings": { "toolbar": {} }
}
```

**Minimal working example**:
```json
{
  "widget_type_id": "dropzone",
  "params": {
    "dropzoneOptions": { "url": "/api/v1/uploads", "method": "POST" },
    "settings": { "toolbar": {} }
  }
}
```

---

## 13. Timeline

| Field | Value |
|-------|-------|
| **widget_type_id** | `api-timeline` |
| **DB classbase** | `TimelineWidget` -> resolves to `Timeline` |
| **Base loader** | Api |
| **Data source** | API (`query_slug.slug`) |

**What it does**: Vertical timeline with badge images, dates, descriptions, receiver/giver info. Supports drag-and-drop reordering.

**format_definition** (field mapping):
```json
{
  "title": "reward",
  "description": "display_name",
  "icon": "reward_group",
  "date": "awarded_at",
  "receiver": "receiver_name",
  "giver": "giver_name"
}
```

**params**:
```json
{
  "reorder": {
    "allowed": true,
    "callback": "reorderCallbackName"
  },
  "settings": { "toolbar": { "reload": true } }
}
```

**Minimal working example**:
```json
{
  "widget_type_id": "api-timeline",
  "query_slug": { "slug": "rewards_timeline" },
  "format_definition": {
    "title": "reward",
    "description": "display_name",
    "icon": "reward_group",
    "date": "awarded_at",
    "receiver": "receiver_name",
    "giver": "giver_name"
  },
  "params": { "settings": { "toolbar": {} } }
}
```

---

## 14. TimelineRewards

| Field | Value |
|-------|-------|
| **widget_type_id** | `media-timelinerewards` |
| **DB classbase** | `TimelineRewards` |
| **Base loader** | Media |
| **Data source** | Static (prop `activities`) or via `format_definition` |

**What it does**: Visual timeline of badge/reward achievements with user avatars and connecting lines.

**Expected data (activities array)**:
```json
[
  {
    "title": "Anniversary of 2 years",
    "date": "24 hours ago",
    "alt": "Badge 1",
    "src": "https://example.com/badge.png",
    "text": "Congratulations, Jane Doe received a new badge."
  }
]
```

**Minimal working example**:
```json
{
  "widget_type_id": "media-timelinerewards",
  "params": { "settings": { "toolbar": {} } }
}
```
Note: Uses default hardcoded sample data if none provided.

---

## 15. Comments

| Field | Value |
|-------|-------|
| **widget_type_id** | `media-comments` |
| **DB classbase** | `Comments` |
| **Base loader** | Media |
| **Data source** | Static/hardcoded demo |

**What it does**: Social-media-style post with likes, comments, and reply capabilities. Currently uses hardcoded demo content.

**Minimal working example**:
```json
{
  "widget_type_id": "media-comments",
  "params": { "settings": { "toolbar": {} } }
}
```

---

## 16. Announcements

| Field | Value |
|-------|-------|
| **widget_type_id** | `media-announcements` |
| **DB classbase** | `Announcements` |
| **Base loader** | Media |
| **Data source** | Static (`format_definition`) |

**What it does**: Paginated announcement cards with progress bar, prev/next navigation. Shows title, date, time, category, and description.

**format_definition**:
```json
{
  "announcements": [
    {
      "title": "System Maintenance",
      "date": "2024-12-01",
      "time": "10:00 AM",
      "category": "IT",
      "description": "The system will be down for maintenance."
    }
  ]
}
```

**Minimal working example**:
```json
{
  "widget_type_id": "media-announcements",
  "format_definition": {
    "announcements": [
      {
        "title": "Welcome",
        "date": "2024-01-15",
        "time": "9:00 AM",
        "category": "General",
        "description": "Welcome to the new dashboard!"
      }
    ]
  },
  "params": { "settings": { "toolbar": {} } }
}
```

---

## 17. ActionPanel

| Field | Value |
|-------|-------|
| **widget_type_id** | `media-actionPanel` |
| **DB classbase** | `ActionPanel` |
| **Base loader** | Media |
| **Data source** | `widget.attributes.actionPanel` |

**What it does**: Grid of styled action buttons that open modals. Each button has an icon, color, size, and links to a modal name.

**attributes**:
```json
{
  "actionPanel": {
    "title": "Quick Actions",
    "actions": [
      {
        "key": "contact",
        "icon": "tabler:message-chatbot",
        "mode": "modal",
        "label": "Contact agent",
        "modalName": "ContactAgentModal",
        "color": "green",
        "size": "lg"
      },
      {
        "key": "schedule",
        "icon": "tabler:calendar-event",
        "mode": "modal",
        "label": "Schedule appointment",
        "modalName": "ScheduleMeetingModal",
        "color": "blue"
      }
    ]
  }
}
```

**Action object fields**: `key`, `icon` (iconify), `mode` ("modal"/"link"), `label`, `url?`, `target?`, `modalName?`, `color?` ("green"/"blue"/"dark"/"light"), `outline?`, `size?` ("sm"/"md"/"lg"), `tooltip?`

**Minimal working example**:
```json
{
  "widget_type_id": "media-actionPanel",
  "attributes": {
    "actionPanel": {
      "title": "Actions",
      "actions": [
        { "key": "help", "icon": "tabler:help", "mode": "modal", "label": "Get Help", "modalName": "HelpModal" }
      ]
    }
  },
  "params": { "settings": { "toolbar": {} } }
}
```

---

## 18. businessCard

| Field | Value |
|-------|-------|
| **widget_type_id** | `api-businesscard` (or legacy `business-card`) |
| **DB classbase** | `businessCard` |
| **Base loader** | Api |
| **Data source** | API (`query_slug.slug`) -- expects `data[0]` |

**What it does**: Displays a user profile card with avatar, name, subtitle, personal info, points, and badges.

**params**:
```json
{
  "information": {
    "avatar": "profile_image_url",
    "title": "display_name",
    "subTitle": "job_title_description",
    "personalInfo": ["store_name", "warp_id"]
  },
  "settings": { "toolbar": {} }
}
```

**Minimal working example**:
```json
{
  "widget_type_id": "api-businesscard",
  "query_slug": { "slug": "user_profile" },
  "params": {
    "information": {
      "avatar": "profile_image",
      "title": "display_name",
      "subTitle": "job_title",
      "personalInfo": ["email", "phone"]
    },
    "settings": { "toolbar": {} }
  }
}
```

---

## 19. profile-card

| Field | Value |
|-------|-------|
| **widget_type_id** | `profile-card` |
| **DB classbase** | `profileCard` -> resolves to `profile-card` |
| **Base loader** | Api (or Media) |
| **Data source** | API data or direct |

**What it does**: Detailed profile card with sectioned display. Groups fields into titled sections with icons, labels, and boolean status chips.

**params**:
```json
{
  "display_data": [
    {
      "title": "Contact Info",
      "childs": [
        { "label": "Full Name", "value": "first_name", "icon": "users" },
        { "label": "Email", "value": "email", "icon": "envelope" },
        { "label": "Active", "value": "is_active", "icon": "id-badge", "check": true }
      ]
    }
  ],
  "settings": { "toolbar": {} }
}
```

**Icon mapping**: `users`, `envelope`, `sitemap`, `phone`, `mobile`, `map-marker`, `globe`, `location-arrow`, `compass`, `compress`, `id-card`, `id-badge`, `graduation-cap`, `search`

**Minimal working example**:
```json
{
  "widget_type_id": "profile-card",
  "query_slug": { "slug": "user_details" },
  "params": {
    "display_data": [
      {
        "title": "Basic Info",
        "childs": [
          { "label": "Full Name", "value": "first_name", "icon": "users" },
          { "label": "Email", "value": "email", "icon": "envelope" }
        ]
      }
    ],
    "settings": { "toolbar": {} }
  }
}
```

---

## 20. formBuilder

| Field | Value |
|-------|-------|
| **widget_type_id** | `form-builder` or `media-form-builder` |
| **DB classbase** | `formBuilderWidget` -> resolves to `formBuilder` |
| **Base loader** | Api or Media |
| **Data source** | Fetches form schema from `params.model.meta` endpoint `:meta` |

**What it does**: Dynamic form generator. Fetches a JSON Schema from a `:meta` endpoint, renders a full form with validation, and submits to the endpoint.

**params**:
```json
{
  "model": {
    "meta": "api/v2/forms/my-form-slug",
    "recaptcha": false,
    "oneShot": true,
    "static": {
      "top": "<h2>Welcome</h2>",
      "hideTitle": false
    },
    "responseAlert": {
      "callback": "myResponseCallback"
    },
    "callback": {
      "form": "myFormCallback"
    },
    "extras": {}
  },
  "settings": { "toolbar": {} }
}
```

**Minimal working example**:
```json
{
  "widget_type_id": "media-form-builder",
  "params": {
    "model": { "meta": "api/v2/forms/contact-form" },
    "settings": { "toolbar": {} }
  }
}
```

---

## 21. TicketZammad

| Field | Value |
|-------|-------|
| **widget_type_id** | `media-ticket-zammad` |
| **DB classbase** | `TicketZammad` |
| **Base loader** | Media |
| **Data source** | `widget.ticket` (passed as context) |

**What it does**: Displays a Zammad support ticket with title, number, state, created date, type, and following status.

**Expected `widget.ticket` object**:
```json
{
  "title": "Ticket Subject",
  "number": "12345",
  "state_id": 2,
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-16T08:00:00Z",
  "type": "Incident",
  "following": "Yes",
  "owner_id": 42
}
```
State IDs: 1=New, 2=Open, 3=Pending Reminder, 4=Pending Action, 5=Closed, 6=Merged, 7=Removed

**Minimal working example**:
```json
{
  "widget_type_id": "media-ticket-zammad",
  "params": { "settings": { "toolbar": {} } }
}
```
Note: Ticket data is typically injected via widget instance context, not directly via params.

---

## 22. Alert

| Field | Value |
|-------|-------|
| **widget_type_id** | `media-alert` |
| **DB classbase** | `Alert` |
| **Base loader** | Media |
| **Data source** | Static (`format_definition`) or reactive from API `data.message` |

**What it does**: Displays a colored alert banner with title, body text, and optional action buttons.

**format_definition** (implements `AlertMessage` interface):
```json
{
  "type": "info",
  "title": "Important Notice",
  "text": "This is the alert body with <b>HTML</b> support",
  "message": "Fallback plain message",
  "props": {
    "classes": "text-lg font-medium"
  },
  "callbackBtn": "Learn More",
  "callback": "myCallbackAction"
}
```

**type** values: `"error"` (red), `"success"` (green), `"warning"` (yellow), `"info"` (blue)

**params**:
```json
{
  "settings": {
    "appearance": { "border": true },
    "toolbar": {}
  }
}
```

**Minimal working example**:
```json
{
  "widget_type_id": "media-alert",
  "format_definition": {
    "type": "info",
    "title": "Welcome",
    "text": "This is an informational alert."
  },
  "params": { "settings": { "toolbar": {} } }
}
```

---

## 23. GoalTrackerRewards

| Field | Value |
|-------|-------|
| **widget_type_id** | `media-goal-tracker-rewards` or `media-goaltrackerrewards` |
| **DB classbase** | `GoalTrackerRewards` |
| **Base loader** | Media |
| **Data source** | Static (prop `items`) or `format_definition` |

**What it does**: Displays goal cards with progress bars, status badges (progress/pending/completed), expandable task details.

**Expected items array**:
```json
[
  {
    "goalDate": "10/03/2024",
    "title": "Increase sales",
    "description": "Exceed last month's sales",
    "status": "progress",
    "progressValue": 50,
    "tasks": [
      { "name": "Sales realization", "value": 70 },
      { "name": "Create sales plan", "value": 100 }
    ]
  }
]
```
**status** values: `"progress"`, `"pending"`, `"completed"`

**Minimal working example**:
```json
{
  "widget_type_id": "media-goaltrackerrewards",
  "params": { "settings": { "toolbar": {} } }
}
```

---

## 24. AchievementTimeline

| Field | Value |
|-------|-------|
| **widget_type_id** | `media-achievement-timeline` |
| **DB classbase** | `AchievementTimeline` |
| **Base loader** | Media |
| **Data source** | Static (prop `timelineItems`) |

**What it does**: Alternating left/right timeline with badge images, user initials, messages, and dotted connecting lines.

**Expected timelineItems array**:
```json
[
  {
    "date": "Aug 10, 2024",
    "time": "10:30 AM",
    "firstName": "Jane",
    "lastName": "Doe",
    "message": "Congratulations, received a new badge!",
    "image": "https://example.com/badge.png"
  }
]
```

**Minimal working example**:
```json
{
  "widget_type_id": "media-achievement-timeline",
  "params": { "settings": { "toolbar": {} } }
}
```

---

## 25. ListOfUsers

| Field | Value |
|-------|-------|
| **widget_type_id** | `media-list-of-users` |
| **DB classbase** | `ListOfUsers` |
| **Base loader** | Media |
| **Data source** | Static/hardcoded demo |

**What it does**: Simple list of user avatars with names and activity dates. Currently uses hardcoded demo data.

**Minimal working example**:
```json
{
  "widget_type_id": "media-list-of-users",
  "params": { "settings": { "toolbar": {} } }
}
```

---

## 26. ListOfPinned

| Field | Value |
|-------|-------|
| **widget_type_id** | (no dedicated DB entry -- uses a generic or custom type) |
| **DB classbase** | `ListOfPinned` |
| **Base loader** | Api |
| **Data source** | API data array of widget objects |

**What it does**: Displays pinned widgets in card or table view with like/share actions. Uses widget icons and categories.

**Data format**: Array of widget objects with `widget_id`, `title`, `description`, `attributes.icon`, `like` boolean.

**Minimal working example**:
```json
{
  "widget_type_id": "api-list-pinned",
  "query_slug": { "slug": "pinned_widgets" },
  "params": { "settings": { "toolbar": {} } }
}
```

---

## 27. TaskDetailsPanelWidget

| Field | Value |
|-------|-------|
| **widget_type_id** | `task-detail` or `api-task-detail` |
| **DB classbase** | `TaskDetailsPanelWidgetWidget` -> resolves to `TaskDetailsPanelWidget` |
| **Base loader** | Api |
| **Data source** | Shared dashboard data (`gridItemsData`) |

**What it does**: iOS-style task/event detail panel. Reads selected task from `$dashboard.gridItemsData.fieldsync_selected.event_id`. Shows status, priority, assignment, location, schedule.

**Expected task object fields**: `event_id`, `name`, `description`, `status` (ASSIGNED/IN_PROGRESS/BLOCKED/COMPLETED), `priority` (HIGH/NORMAL/LOW), `category`, `assignee_id`, `program_name`, `client_id`, `store_name`, `store_id`, `event_positions` ({lat, lng}), `start_timestamp`, `end_timestamp`, `updated_at`

**query_slug** (to load shared data):
```json
{ "slug": "fieldsync_events", "dashboard": "fieldsync_events" }
```

**Minimal working example**:
```json
{
  "widget_type_id": "api-task-detail",
  "query_slug": { "slug": "events_list", "dashboard": "fieldsync_events" },
  "params": { "settings": { "toolbar": {} } }
}
```

---

## 28. TaskStatus

| Field | Value |
|-------|-------|
| **widget_type_id** | `task-status` or `api-task-status` |
| **DB classbase** | `TaskStatusWidget` -> resolves to `TaskStatus` |
| **Base loader** | Api |
| **Data source** | Shared dashboard data (`gridItemsData`) |

**What it does**: Similar to TaskDetailsPanelWidget but focused on staffing status. Shows position details, staff assignments, scheduling. Reads selected from `$dashboard.gridItemsData.fieldsync_selected.event_id`.

**Expected fields**: `event_id`, `event_name`, `staffing_status` (Staffed/In Progress/Blocked/Finished/Completed), `staff_position_name`, `staff_position_email`, `assigned_staff_id`, `client_id`, `latitude`, `longitude`, `position_start_time`, `position_end_time`, `position_duration_hours`, `position_created_at`, `position_updated_at`, `event_position_id`

**Minimal working example**:
```json
{
  "widget_type_id": "api-task-status",
  "query_slug": { "slug": "events_list", "dashboard": "fieldsync_events" },
  "params": { "settings": { "toolbar": {} } }
}
```

---

## 29. PriorityBriefing

| Field | Value |
|-------|-------|
| **widget_type_id** | `priority-briefing` or `api-priority-briefing` |
| **DB classbase** | `PriorityBriefing` |
| **Base loader** | Api |
| **Data source** | API (`query_slug.slug`) |

**What it does**: Collapsible retailer groups with prioritized briefing cards (1st/2nd/3rd priority). Each group has an audio podcast player, account manager info, and priority detail cards. Supports local play-state persistence and notification intents.

**Expected data rows**:
```json
[
  {
    "retailer": "Best Buy US",
    "account_manager": "John Smith",
    "submission_date": "2024-12-01T04:45:22Z",
    "priority_type": "1st",
    "category": "Sales",
    "details": "Q4 sales exceeded target by 15%",
    "is_latest": true,
    "podcast_url": "https://cdn.example.com/briefing.mp3"
  }
]
```

**Minimal working example**:
```json
{
  "widget_type_id": "api-priority-briefing",
  "query_slug": { "slug": "priority_briefings" },
  "params": { "settings": { "toolbar": { "reload": true } } }
}
```

---

## 30. MapReps

| Field | Value |
|-------|-------|
| **widget_type_id** | `map-reps` or `api-map-reps` |
| **DB classbase** | `MapRepsWidget` -> resolves to `MapReps` |
| **Base loader** | Api |
| **Data source** | API + GPS live tracking |

**What it does**: Google Maps-based widget showing field representatives. Integrates GPS live location tracking via `/api/v1/gps/sessions`. Shows task markers, rep locations with real-time updates.

**Expected data**: Array of task/event objects with location data.

**params**: Standard API widget params plus GPS polling configuration.

**Minimal working example**:
```json
{
  "widget_type_id": "api-map-reps",
  "query_slug": { "slug": "field_events", "dashboard": "fieldsync_events" },
  "params": { "settings": { "toolbar": { "reload": true } } }
}
```

---

## 31. MapStore

| Field | Value |
|-------|-------|
| **widget_type_id** | `api-maps-track` |
| **DB classbase** | `MapStore` |
| **Base loader** | Api |
| **Data source** | API data (store locations) |

**What it does**: Store location map with selectable stores, detail panel, and linked employee data. Selects stores and fetches nearby employees via `retail360_community_employees_hr`.

**Shares data**: Updates `$dashboard.gridItemsData.employees` when stores are selected.

**Minimal working example**:
```json
{
  "widget_type_id": "api-maps-track",
  "query_slug": { "slug": "store_locations" },
  "params": { "settings": { "toolbar": { "reload": true } } }
}
```

---

## 32. FileManager

| Field | Value |
|-------|-------|
| **widget_type_id** | `api-file-manager` or `file-manager` |
| **DB classbase** | `FileManager` |
| **Base loader** | Api or Media |
| **Data source** | Server filesystem (tenant-scoped) |

**What it does**: Full file manager with sidebar folder tree, file listing, upload, and download capabilities. Supports modal mode for file selection.

**params**:
```json
{
  "path": "/documents",
  "settings": { "toolbar": {} }
}
```

**Minimal working example**:
```json
{
  "widget_type_id": "file-manager",
  "params": {
    "path": "/",
    "settings": { "toolbar": {} }
  }
}
```

---

## 33. StaticCard

| Field | Value |
|-------|-------|
| **widget_type_id** | (no dedicated DB entry -- use a custom type) |
| **DB classbase** | `StaticCard` |
| **Base loader** | Media |
| **Data source** | Static JSON file (`widgetCardData.json`) |

**What it does**: Simple card with image, title, description, and CTA button. Reads from a static JSON file.

**Expected JSON data**:
```json
{
  "src": "https://example.com/image.jpg",
  "title": "Card Title",
  "description": "Card description text",
  "btn": {
    "btnText": "Learn More",
    "to": "https://example.com",
    "external": true,
    "backgroundColor": "red"
  }
}
```

---

## 34. AgGrid

| Field | Value |
|-------|-------|
| **widget_type_id** | `api-table` (or legacy `api-pqtable`, `api-datatable`) |
| **DB classbase** | `ApiTableWidget` -> resolves to `AgGrid` |
| **Base loader** | Api |
| **Data source** | API (`query_slug.slug`) |

**What it does**: Full-featured data grid using AG Grid Community. Supports column definitions via `format_definition`, cell actions, drilldowns, export (Excel), modals, form builders, pagination, and complex cell renderers.

**format_definition** (column definitions):
```json
{
  "column_name": {
    "headerName": "Display Name",
    "type": "text",
    "width": 150,
    "sort": "asc",
    "hide": false,
    "cellRenderer": "customRenderer"
  }
}
```

**params** (key options):
```json
{
  "demo": { "show": false, "data": [] },
  "addFilterConditions": {},
  "addWhereConditions": {},
  "addConditions": {},
  "removeConditions": [],
  "process_data": {},
  "settings": { "toolbar": { "reload": true, "filtering": true, "export": true } }
}
```

**Minimal working example**:
```json
{
  "widget_type_id": "api-table",
  "query_slug": { "slug": "my_data_query" },
  "format_definition": {
    "name": { "headerName": "Name" },
    "email": { "headerName": "Email" }
  },
  "params": { "settings": { "toolbar": { "reload": true, "export": true } } }
}
```

---

## 35. Chat

| Field | Value |
|-------|-------|
| **widget_type_id** | (used as modal component, not standalone widget_type) |
| **DB classbase** | `Chat` |
| **Base loader** | N/A -- invoked via modal |

**What it does**: Chat/conversation component. Displays chronological comments with date separators, user avatars, and input for new messages. Used inside modals opened from AgGrid actions.

**Props**:
```json
{
  "action": "comments",
  "data": [],
  "widget": {},
  "callback": null
}
```

---

## 36. chatai

| Field | Value |
|-------|-------|
| **widget_type_id** | (embedded component) |
| **DB classbase** | `chatai` |
| **Base loader** | Media |
| **Data source** | `data` object with `url`, `token`, `apikey` |

**What it does**: Embeds an external AI chat interface via iframe. Appends auth tokens to the URL.

**Expected data**:
```json
{
  "url": "https://chat.example.com",
  "token": "user-jwt-token",
  "apikey": "api-key"
}
```

---

## 37. QueryExecutor

| Field | Value |
|-------|-------|
| **widget_type_id** | (admin/dev tool, typically custom type) |
| **DB classbase** | `QueryExecutor` |
| **Base loader** | Media |
| **Data source** | User-entered SQL queries |

**What it does**: SQL editor with Monaco editor, database selector, query execution, result display via AgGrid, and CSV/JSON export. Connects to `/api/v1/datasources/drivers/list` for available databases and `/api/v1/queries/run` for execution.

**Minimal working example**:
```json
{
  "widget_type_id": "query-executor",
  "params": { "settings": { "toolbar": {} } }
}
```

---

## 38. Pdf

| Field | Value |
|-------|-------|
| **widget_type_id** | `pdf` (via `PdfWidget` classbase in TypeMedia) |
| **DB classbase** | `Pdf` |
| **Base loader** | Media |
| **Data source** | `data` (URL string) or `widget.url` |

**What it does**: Renders page 1 of a PDF on a canvas using pdfjs-dist.

**Minimal working example**:
```json
{
  "widget_type_id": "pdf",
  "url": "https://example.com/document.pdf",
  "params": { "settings": { "toolbar": {} } }
}
```

---

## 39. PdfViewer

| Field | Value |
|-------|-------|
| **widget_type_id** | `pdf` (shares type with Pdf, but different classbase routing) |
| **DB classbase** | `PdfViewer` |
| **Base loader** | Media |
| **Data source** | `widget.url` |

**What it does**: Full PDF viewer via iframe embed (uses browser's native PDF viewer). More complete than Pdf widget which only shows page 1.

**Minimal working example**:
```json
{
  "widget_type_id": "pdf",
  "url": "https://example.com/document.pdf",
  "classbase": "PdfViewer",
  "params": { "settings": { "toolbar": {} } }
}
```

---

## Universal Widget Fields Reference

Every widget row in the DB supports these fields:

| Field | Type | Description |
|-------|------|-------------|
| `widget_id` | UUID | Auto-generated |
| `widget_type_id` | string | Maps to `navigator.widget_types.widget_type` |
| `title` | string | Display title |
| `description` | string | Optional description |
| `url` | string | Used by media widgets (YouTube, Vimeo, Image, PDF, etc.) |
| `classbase` | string | Override for component resolution (usually auto-derived) |
| `query_slug` | JSON | `{ slug, method?, dashboard?, v3?, conditional_filtering? }` |
| `conditions` | JSON | Query conditions: `{ firstdate, lastdate, where_cond, filter_options }` |
| `params` | JSON | Component-specific parameters + `settings` |
| `format_definition` | JSON | Component-specific display/column/layout configuration |
| `attributes` | JSON | Metadata: `{ icon, title, widget_location, actionPanel, product360, ... }` |
| `master_filtering` | boolean | Whether dashboard filters apply |
| `allow_filtering` | boolean | Whether widget allows filtering |
| `filtering_show` | JSON | Filter visibility config |
| `cond_definition` | JSON | Condition definitions |
| `where_definition` | JSON | Where clause definitions |
| `save_filtering` | boolean | Persist filter state |
| `module_id` | UUID | Parent module |
| `template_id` | UUID | Widget template reference |
| `program_id` | UUID | Parent program |
| `dashboard_id` | UUID | Parent dashboard |

---

## widget_type_id to classbase Quick Reference (Batch 2)

| widget_type_id | classbase | Component Dir |
|----------------|-----------|---------------|
| `media-list-of-links` | `ListOfLinks` | ListOfLinks/ |
| `media-list-of-documents` | `ListOfDocuments` | ListOfDocuments/ |
| `media-list-cards` | `ListOrCard` | ListOrCard/ |
| `api-list-cards` | `ApiListOrCards` | ApiListOrCards/ |
| `media-carousel` | `Carousel` | Carousel/ |
| `media-youtube` | `YouTube` | YouTube/ |
| `youtube` | `youtubeWidget` | YouTube/ |
| `vimeo` | `vimeoWidget` | Vimeo/ |
| `spotify` | `SpotifyWidget` | Spotify/ |
| `soundcloud` | `SoundCloudWidget` | SoundCloud/ |
| `image` | `imageWidget` | Image/ |
| `download-widget` | `DownloadWidget` | Download/ |
| `dropzone` | `Dropzone` | Dropzone/ |
| `api-timeline` | `TimelineWidget` | Timeline/ |
| `media-timelinerewards` | `TimelineRewards` | TimelineRewards/ |
| `media-comments` | `Comments` | Comments/ |
| `media-announcements` | `Announcements` | Announcements/ |
| `media-actionPanel` | `ActionPanel` | ActionPanel/ |
| `api-businesscard` | `businessCard` | businessCard/ |
| `business-card` | `businessCard` | businessCard/ |
| `profile-card` | `profileCard` | profile-card/ |
| `form-builder` | `formBuilderWidget` | formBuilder/ |
| `media-form-builder` | `formBuilderWidget` | formBuilder/ |
| `media-ticket-zammad` | `TicketZammad` | TicketZammad/ |
| `media-alert` | `Alert` | Alert/ |
| `media-goaltrackerrewards` | `GoalTrackerRewards` | GoalTrackerRewards/ |
| `media-achievement-timeline` | `AchievementTimeline` | AchievementTimeline/ |
| `media-list-of-users` | `ListOfUsers` | ListOfUsers/ |
| `task-detail` / `api-task-detail` | `TaskDetailsPanelWidgetWidget` | TaskDetailsPanelWidget/ |
| `task-status` / `api-task-status` | `TaskStatusWidget` | TaskStatus/ |
| `priority-briefing` / `api-priority-briefing` | `PriorityBriefing` | PriorityBriefing/ |
| `map-reps` / `api-map-reps` | `MapRepsWidget` | MapReps/ |
| `api-maps-track` | `MapStore` | MapStore/ |
| `api-file-manager` / `file-manager` | `FileManager` | FileManager/ |
| `api-table` | `ApiTableWidget` -> `AgGrid` | AgGrid/ |
| `pdf` | `PdfWidget` | Pdf/ or PdfViewer/ |
| `media-iframe` | `Iframe` | Iframe/ |
