# Navigator Widget Types - Quick Reference

## Resolution: widget_type_id → classbase → Svelte component
## Base loaders: api-* (fetch API), media-* (static data), rest-* (fetch URL)

## Charts & Visualization
- `api-echarts` (EchartsWidget): Bar, line, area, barline, donut, gauge, funnel charts. params.graph.type selects sub-type.
- `api-echarts-map` (EchartsMapWidget): Geographic heat maps with ECharts.

## Data Grids & Tables
- `api-pqtable` (pqTableWidget): Advanced grid with freeze cols, grouping, sorting, export. Uses format_definition for column defs.
- `api-selectPqTable` (selectpqtableWidget): Interactive grid with action buttons, refresh, grouping.
- `api-table` (ApiTableWidget): Simple table with roll_up aggregation. Uses format_definition for column formatters.
- `api-datatable` (dtWidget): Legacy datatable.

## KPI Cards
- `api-card` (CardWidget): KPI metric cards with icons, formatters, drilldowns. params.card.cards defines each metric.

## Maps & Location
- `api-maps` (MapsWidget): Google Maps with markers and info windows.
- `api-leaflet` / `media-leaflet` (MapsLeaflet): Leaflet maps with layers, choropleth, custom tiles.
- `api-maps-track` (MapStore): Map with business location tracking.
- `api-route` (RouteWidget): Optimal routing with stop-by-stop directions.
- `api-map-reps` / `map-reps` (MapRepsWidget): Map of field representatives.

## Media & Content
- `media-editor-wysiwyg` (EditorWysiwyg): Rich text HTML editor. Content in format_definition.html.
- `media-iframe` / `iframe` (Iframe): Embedded iframe. URL in format_definition.url or widget url field.
- `media-carousel` (Carousel): Image carousel from format_definition.images array.
- `media-list-of-links` (ListOfLinks): Clickable links list from format_definition.links.
- `media-list-of-documents` (ListOfDocuments): Downloadable files list from format_definition.files.
- `media-list-cards` / `api-list-cards` (ListOrCard/ApiListOrCards): Card grid layout.
- `media-youtube` / `youtube` (YouTube): YouTube video embed.
- `media-announcements` (Announcements): Announcement cards with images and actions.
- `media-comments` (Comments): Comment thread on a widget.
- `image` (imageWidget): Static image from URL.

## Photos & Files
- `api-photo-feed-widget` (photoFeedWidget): Photo gallery with tabs, categories, PPT export.
- `api-file-manager` / `file-manager` (FileManager): File browser with upload/download.
- `dropzone` (Dropzone): Drag-and-drop file upload.
- `download-widget` (DownloadWidget): Download button widget.

## AI & Chatbots
- `media-bot` (ChatbotAI): AI chatbot interface. Reads bot config from API.
- `media-botagent` (ChatbotAgentAI): Agent-mode chatbot with file/drawer support.
- `api-ia` (iaWidget): Widget powered by AI agent.

## Tasks & Workflow
- `api-task-detail` / `task-detail` (TaskDetailsPanelWidgetWidget): Task details panel.
- `api-task-status` / `task-status` (TaskStatusWidget): Task status tracker.
- `api-priority-briefing` / `priority-briefing` (PriorityBriefing): Priority briefing by retailer.
- `media-actionPanel` (ActionPanel): Action buttons panel.

## Social & Engagement
- `api-leaderboard` (LeaderboardWidget): Ranking leaderboard with avatars.
- `api-rewards` (RewardsWidget): Rewards display with redemption.
- `media-timelinerewards` (TimelineRewards): Reward timeline.
- `media-goal-tracker-rewards` (GoalTrackerRewards): Goal progress tracker.
- `media-achievement-timeline` (AchievementTimeline): Achievement milestones.
- `api-timeline` (TimelineWidget): Activity timeline.

## People & Profiles
- `profile-card` (profile-card): User profile card.
- `api-businesscard` / `business-card` (businessCard): Contact business card.
- `media-list-of-users` (ListOfUsers): User list with search.
- `media-ticket-zammad` (TicketZammad): Support ticket interface.

## Other
- `quick-start` (quickStartWidget): Quick navigation panel. No API data needed.
- `form-builder` / `media-form-builder` (formBuilderWidget): Dynamic form builder.
- `expert-system` (systemExpertWidget): Expert system with external API.
- `media-alert` (Alert): Alert/warning banner.
- `embed` (EmbedWidget): Raw HTML embed.
- `base` (TrocWidget): Base widget (development).

## Widget Categories (widgetcat_id)
- 1=walmart, 2=utility, **3=generic (default)**, 4=mso, 5=blank, 6=loreal

## Common Date Tokens for conditions
CURRENT_DATE, FDOM (first day month), LDOM, FDOW (first day week), LDOW, FDOY (first day year)

## Key Rule
99.9% of widgets use a template_id. Override only fields that differ from template.
Use `get_widget_schema` tool for full JSON structure of any specific type.
