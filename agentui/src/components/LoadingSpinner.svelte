<script>
  /**
   * LoadingSpinner Component
   *
   * A reusable loading spinner with various sizes and customization options.
   * Uses daisyUI's loading component.
   */

  let {
    size = 'md',
    type = 'spinner',
    color = '',
    text = '',
    center = true,
    className = ''
  } = $props();

  // Size mapping
  const sizeClasses = {
    xs: 'loading-xs',
    sm: 'loading-sm',
    md: 'loading-md',
    lg: 'loading-lg'
  };

  // Type mapping
  const typeClasses = {
    spinner: 'loading-spinner',
    dots: 'loading-dots',
    ring: 'loading-ring',
    ball: 'loading-ball',
    bars: 'loading-bars',
    infinity: 'loading-infinity'
  };

  // Color mapping
  const colorClasses = {
    primary: 'text-primary',
    secondary: 'text-secondary',
    accent: 'text-accent',
    neutral: 'text-neutral',
    info: 'text-info',
    success: 'text-success',
    warning: 'text-warning',
    error: 'text-error'
  };

  const loadingClasses = $derived(
    `loading ${typeClasses[type] || typeClasses.spinner} ${sizeClasses[size] || sizeClasses.md} ${
      color ? colorClasses[color] : ''
    } ${className}`
  );

  const wrapperClasses = $derived(
    center ? 'flex flex-col items-center justify-center gap-2' : 'flex items-center gap-2'
  );
</script>

<div class={wrapperClasses}>
  <span class={loadingClasses}></span>
  {#if text}
    <span class="text-sm text-base-content/70">{text}</span>
  {/if}
</div>
