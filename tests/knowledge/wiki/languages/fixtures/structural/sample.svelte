<script lang="ts">
  import { helper } from '$lib/util'

  /** Component label. */
  export const label = 'x'

  /** Say hello. */
  export function greet(name: string): string {
    return `hi ${name}`
  }
</script>
<div>{label}</div>
