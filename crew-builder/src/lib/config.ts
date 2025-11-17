const DEFAULT_ENV_LABEL = import.meta.env?.VITE_CREW_BUILDER_ENV || 'local';
const environmentLabel = DEFAULT_ENV_LABEL.trim() || 'local';
const storageNamespace = `crew-builder.${environmentLabel}`;

export const config = {
  environmentLabel,
  conversationStoragePrefix: `${storageNamespace}.conversation`
};
