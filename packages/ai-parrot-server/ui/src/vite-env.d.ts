/// <reference types="vite/client" />

// FEAT-476: build-time AgentChat feature flag constants injected by
// vite.config.ts's `define` (from PUBLIC_AGENTCHAT_*, default true).
// Consumed by src/lib/features.ts; see spec §2 "Feature flags".
declare const __AGENTCHAT_VOICE__: boolean;
declare const __AGENTCHAT_AVATAR__: boolean;
declare const __AGENTCHAT_MAPS__: boolean;
declare const __AGENTCHAT_CHARTS__: boolean;
declare const __AGENTCHAT_CANVAS__: boolean;
declare const __AGENTCHAT_INFOGRAPHIC__: boolean;
declare const __AGENTCHAT_DATASETS__: boolean;
declare const __AGENTCHAT_RICH_EDITOR__: boolean;
