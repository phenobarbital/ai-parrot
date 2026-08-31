import { tv, type VariantProps } from "tailwind-variants";

export const agentChatHeader = tv({
  base:
    "flex items-center px-4 py-2 " +
    "bg-[var(--agent-chat-header-bg)] text-[var(--agent-chat-header-fg)] " +
    "border-b border-border",
});

export const agentChatSidebar = tv({
  base:
    "flex flex-col h-full overflow-y-auto " +
    "bg-[var(--agent-chat-sidebar-bg)] text-[var(--agent-chat-sidebar-fg)]",
});

export const agentChatSidebarItem = tv({
  base:
    "w-full flex items-center justify-start gap-2 px-3 py-2 text-sm font-medium " +
    "rounded-xl transition-colors",
  variants: {
    state: {
      active:
        "bg-[var(--agent-chat-sidebar-item-active-bg)] " +
        "text-[var(--agent-chat-sidebar-item-active-fg)] " +
        "hover:opacity-90",
      idle:
        "text-muted-foreground " +
        "hover:bg-[var(--agent-chat-sidebar-item-hover-bg)] " +
        "hover:text-foreground",
    },
  },
  defaultVariants: { state: "idle" },
});

export const agentChatInput = tv({
  base:
    "w-full px-3 py-2 rounded-md " +
    "bg-[var(--agent-chat-input-bg)] text-[var(--agent-chat-input-fg)] " +
    "border border-[var(--agent-chat-input-border)]",
});

export type AgentChatSidebarItemVariants = VariantProps<
  typeof agentChatSidebarItem
>;
