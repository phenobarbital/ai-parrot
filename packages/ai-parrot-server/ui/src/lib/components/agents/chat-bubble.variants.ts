import { tv, type VariantProps } from "tailwind-variants";

export const chatBubble = tv({
  base: "block w-fit max-w-[90%] min-h-11 min-w-11 px-4 py-2 rounded-2xl",
  variants: {
    role: {
      user: "bg-[var(--agent-chat-bubble-user-bg)] text-[var(--agent-chat-bubble-user-fg)]",
      assistant:
        "bg-[var(--agent-chat-bubble-assistant-bg)] text-[var(--agent-chat-bubble-assistant-fg)]",
      system:
        "bg-[var(--agent-chat-bubble-system-bg)] text-[var(--agent-chat-bubble-system-fg)]",
    },
    edge: {
      start: "rounded-bl-none",
      end: "rounded-br-none",
      none: "",
    },
  },
  defaultVariants: { role: "assistant", edge: "none" },
});

export type ChatBubbleVariants = VariantProps<typeof chatBubble>;
