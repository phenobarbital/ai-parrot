<script lang="ts">
  import RefactorTest from "./RefactorTest.svelte";
  import "./lib/dashboard/theme.css";
</script>

<RefactorTest />

<style>
  /* Global styles are now handled by theme.css */
  :global(body) {
    overflow: hidden; /* Prevent body scroll, let dashboard handle it */
  }

  main {
    display: flex;
    flex-direction: column;
    height: 100vh;
    width: 100vw;
    max-width: none;
    margin: 0;
    padding: 0;
  }

  header {
    height: 50px;
    padding: 0 1rem;
    background: #f0f0f0;
    border-bottom: 1px solid #ccc;
    display: flex;
    align-items: center;
    gap: 1rem;
    flex-shrink: 0;
  }

  h1 {
    margin: 0;
    font-size: 1.2rem;
  }

  .dashboard-wrapper {
    flex: 1;
    position: relative;
    overflow: hidden;
    background: #fff;
  }
</style>
