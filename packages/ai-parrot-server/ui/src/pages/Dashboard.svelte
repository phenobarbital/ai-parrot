<!-- Placeholder Dashboard page (TASK-2528) — replaced by TASK-2529. -->
<script lang="ts">
  import { Card, CardContent, CardHeader, CardTitle } from "$lib/ui/internal/shadcn/ui/card/index.js";
</script>

<Card>
  <CardHeader>
    <CardTitle>Dashboard</CardTitle>
  </CardHeader>
  <CardContent>
    <p class="text-muted-foreground text-sm">
      Server status content lands here (TASK-2529, consuming
      GET /api/v1/admin/status).
    </p>
  </CardContent>
</Card>
